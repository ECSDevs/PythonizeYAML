// Copyright (c) 2026 PythonizeYAML contributors
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

use crate::emitter::{emit_documents, emit_single, EmitConfig};
use crate::error::{ErrorKind, YamlError};
use crate::model::{
    NativeDocument as ModelDocument, NodeId, NodeKind, Scalar, ScalarKind, ScalarStyle, Span,
};
use crate::parser;
use base64::Engine;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyBytes, PyDict, PyFloat, PyList, PySet, PyString, PyTuple};
use std::collections::HashMap;
use std::sync::Arc;

#[pyclass(module = "pythonizeyaml._native", frozen)]
pub struct NativeDocument {
    pub inner: Arc<ModelDocument>,
}

pub fn parse_value(
    py: Python<'_>,
    text: &str,
    safe: bool,
) -> PyResult<(Py<PyAny>, Py<NativeDocument>)> {
    let document = parser::parse(text).map_err(native_error)?;
    let handle = Py::new(
        py,
        NativeDocument {
            inner: Arc::new(document),
        },
    )?;
    let count = handle.borrow(py).inner.documents.len();
    if count > 1 {
        return Err(native_error(YamlError::new(
            ErrorKind::Composer,
            "expected a single document",
            Span::default(),
        )));
    }
    let root = handle
        .borrow(py)
        .inner
        .documents
        .first()
        .map(|doc| doc.root)
        .unwrap_or(usize::MAX);
    let mut memo = HashMap::new();
    let value = materialize_node(
        py,
        &handle.borrow(py).inner,
        root,
        handle.bind(py).as_any(),
        safe,
        &mut memo,
    )?;
    Ok((value, handle))
}

pub fn parse_all_values(
    py: Python<'_>,
    text: &str,
    safe: bool,
) -> PyResult<(Py<PyList>, Py<NativeDocument>)> {
    let document = parser::parse(text).map_err(native_error)?;
    let handle = Py::new(
        py,
        NativeDocument {
            inner: Arc::new(document),
        },
    )?;
    let list = PyList::empty(py);
    let roots: Vec<_> = handle
        .borrow(py)
        .inner
        .documents
        .iter()
        .map(|doc| doc.root)
        .collect();
    let mut memo = HashMap::new();
    for root in roots {
        list.append(materialize_node(
            py,
            &handle.borrow(py).inner,
            root,
            handle.bind(py).as_any(),
            safe,
            &mut memo,
        )?)?;
    }
    Ok((list.unbind(), handle))
}

fn materialize_node(
    py: Python<'_>,
    document: &ModelDocument,
    node_id: NodeId,
    handle: &Bound<'_, PyAny>,
    safe: bool,
    memo: &mut HashMap<NodeId, Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    if node_id == usize::MAX {
        return Ok(py.None());
    }
    if let Some(existing) = memo.get(&node_id) {
        return Ok(existing.clone_ref(py));
    }
    let node = document.arena.node(node_id);
    if node.tag.as_deref() == Some("tag:yaml.org,2002:set") {
        return materialize_set(py, document, node_id, handle, safe, memo);
    }
    if node
        .tag
        .as_deref()
        .is_some_and(|tag| tag == "tag:yaml.org,2002:omap" || tag == "tag:yaml.org,2002:pairs")
    {
        let inner = materialize_untagged(py, document, node_id, handle, safe, memo)?;
        return materialize_pairs(py, inner.bind(py));
    }
    if let Some(tag) = &node.tag {
        if !is_standard_tag(tag) {
            if safe {
                return Err(native_error(YamlError::new(
                    ErrorKind::Constructor,
                    format!("unsupported tag '{tag}'"),
                    node.span,
                )));
            }
            let inner = materialize_untagged(py, document, node_id, handle, safe, memo)?;
            let tagged = py
                .import("pythonizeyaml.tagged")?
                .getattr("Tagged")?
                .call1((tag, inner))?;
            return Ok(tagged.unbind());
        }
    }
    materialize_untagged(py, document, node_id, handle, safe, memo)
}

fn is_standard_tag(tag: &str) -> bool {
    matches!(
        tag,
        "tag:yaml.org,2002:null"
            | "tag:yaml.org,2002:bool"
            | "tag:yaml.org,2002:int"
            | "tag:yaml.org,2002:float"
            | "tag:yaml.org,2002:decimal"
            | "tag:yaml.org,2002:str"
            | "tag:yaml.org,2002:binary"
            | "tag:yaml.org,2002:timestamp"
            | "tag:yaml.org,2002:seq"
            | "tag:yaml.org,2002:map"
            | "tag:yaml.org,2002:set"
            | "tag:yaml.org,2002:omap"
            | "tag:yaml.org,2002:pairs"
            | "tag:yaml.org,2002:merge"
    )
}
fn materialize_untagged(
    py: Python<'_>,
    document: &ModelDocument,
    node_id: NodeId,
    handle: &Bound<'_, PyAny>,
    safe: bool,
    memo: &mut HashMap<NodeId, Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    if let Some(existing) = memo.get(&node_id) {
        return Ok(existing.clone_ref(py));
    }
    let node = document.arena.node(node_id);
    match &node.kind {
        NodeKind::Scalar(scalar) => {
            // Quoted scalars always carry `ScalarKind::Str` in the arena with
            // the explicit tag attached to the node itself, so re-apply the
            // tag here; otherwise `!!binary "!!!"` would silently materialize
            // the raw string instead of raising a constructor error.
            let scalar =
                apply_explicit_tag(scalar, node.tag.as_deref(), node.span).map_err(native_error)?;
            let value = materialize_scalar(py, &scalar, node.span)?;
            if safe {
                Ok(value)
            } else {
                wrap_scalar_value(py, value)
            }
        }
        NodeKind::Alias(target) => materialize_node(py, document, *target, handle, safe, memo),
        NodeKind::Tagged { tag, value } => {
            if tag.ends_with(":set") {
                return materialize_set(py, document, node_id, handle, safe, memo);
            }
            let inner = materialize_node(py, document, *value, handle, safe, memo)?;
            let tagged = py
                .import("pythonizeyaml.tagged")?
                .getattr("Tagged")?
                .call1((tag, inner))?;
            Ok(tagged.unbind())
        }
        NodeKind::Sequence(items) => {
            let container: Bound<'_, PyAny> = if safe {
                PyList::empty(py).into_any()
            } else {
                py.import("pythonizeyaml.nodes")?
                    .getattr("RoundTripList")?
                    .call1((handle, node_id))?
            };
            let placeholder = container.clone().unbind();
            memo.insert(node_id, placeholder);
            let list = container.cast::<PyList>()?;
            let mut node_ids = Vec::with_capacity(items.len());
            for item in items {
                list.append(materialize_node(py, document, *item, handle, safe, memo)?)?;
                node_ids.push(*item);
            }
            if !safe {
                let metadata = PyList::new(py, node_ids)?;
                container.setattr("_pyy_node_ids", metadata)?;
            }
            Ok(container.unbind())
        }
        NodeKind::Mapping(entries) => {
            materialize_mapping(py, document, node_id, entries, handle, safe, memo)
        }
        NodeKind::Set(items) => {
            materialize_set_items(py, document, node_id, items, handle, safe, memo)
        }
    }
}

fn materialize_mapping(
    py: Python<'_>,
    document: &ModelDocument,
    node_id: NodeId,
    entries: &[crate::model::MappingEntry],
    handle: &Bound<'_, PyAny>,
    safe: bool,
    memo: &mut HashMap<NodeId, Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    let container: Bound<'_, PyAny> = if safe {
        PyDict::new(py).into_any()
    } else {
        py.import("pythonizeyaml.nodes")?
            .getattr("RoundTripMap")?
            .call1((handle, node_id))?
    };
    memo.insert(node_id, container.clone().unbind());
    let mapping = container.cast::<PyDict>()?;
    let metadata = PyDict::new(py);
    for entry in entries
        .iter()
        .filter(|entry| is_merge_key(document, entry.key))
    {
        let merged = materialize_node(py, document, entry.value, handle, safe, memo)?;
        merge_mapping(py, mapping, merged.bind(py), &metadata)?;
    }
    let mut seen = Vec::<Py<PyAny>>::new();
    for entry in entries
        .iter()
        .filter(|entry| !is_merge_key(document, entry.key))
    {
        let key = materialize_node(py, document, entry.key, handle, safe, memo)?;
        if key.bind(py).hash().is_err() {
            return Err(native_error(YamlError::new(
                ErrorKind::Constructor,
                "found unhashable key",
                entry.key_span,
            )));
        }
        if seen
            .iter()
            .any(|existing| existing.bind(py).eq(key.bind(py)).unwrap_or(false))
        {
            return Err(native_error(YamlError::new(
                ErrorKind::Constructor,
                "duplicate mapping key",
                entry.key_span,
            )));
        }
        seen.push(key.clone_ref(py));
        let value = materialize_node(py, document, entry.value, handle, safe, memo)?;
        mapping.set_item(key.bind(py), value.bind(py))?;
        metadata.set_item(key.bind(py), (entry.key, entry.value))?;
    }
    if !safe {
        container.setattr("_pyy_entry_nodes", metadata)?;
    }
    Ok(container.unbind())
}

fn is_merge_key(document: &ModelDocument, node_id: NodeId) -> bool {
    match &document.arena.node(node_id).kind {
        NodeKind::Scalar(scalar) => scalar.value == "<<",
        _ => false,
    }
}

fn merge_mapping<'py>(
    _py: Python<'py>,
    target: &Bound<'py, PyDict>,
    source: &Bound<'py, PyAny>,
    metadata: &Bound<'py, PyDict>,
) -> PyResult<()> {
    if let Ok(mapping) = source.cast::<PyDict>() {
        for (key, value) in mapping.iter() {
            if !target.contains(&key)? {
                target.set_item(&key, value)?;
                metadata.set_item(&key, (-1isize, -1isize))?;
            }
        }
        return Ok(());
    }
    if let Ok(items) = source.cast::<PyList>() {
        for item in items.iter() {
            merge_mapping(_py, target, &item, metadata)?;
        }
    }
    Ok(())
}

fn materialize_pairs(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let Some(items) = value.cast::<PyList>().ok() else {
        return Ok(value.clone().unbind());
    };
    let output = PyList::empty(py);
    for item in items.iter() {
        if let Ok(mapping) = item.cast::<PyDict>() {
            if mapping.len() == 1 {
                for (key, value) in mapping.iter() {
                    output.append(PyTuple::new(py, [key, value])?)?;
                }
                continue;
            }
        }
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn materialize_set(
    py: Python<'_>,
    document: &ModelDocument,
    node_id: NodeId,
    handle: &Bound<'_, PyAny>,
    safe: bool,
    memo: &mut HashMap<NodeId, Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    let node = document.arena.node(node_id);
    if let NodeKind::Mapping(entries) = &node.kind {
        let keys: Vec<_> = entries.iter().map(|entry| entry.key).collect();
        return materialize_set_items(py, document, node_id, &keys, handle, safe, memo);
    }
    match &node.kind {
        NodeKind::Set(items) => {
            materialize_set_items(py, document, node_id, items, handle, safe, memo)
        }
        NodeKind::Tagged { value, .. } => {
            materialize_node(py, document, *value, handle, safe, memo)
        }
        // A set tag on anything else (e.g. a bare scalar) has no members to
        // iterate; materialize the node itself instead of recursing back into
        // `materialize_set` with the same id.
        _ => materialize_untagged(py, document, node_id, handle, safe, memo),
    }
}

fn materialize_set_items(
    py: Python<'_>,
    document: &ModelDocument,
    node_id: NodeId,
    items: &[NodeId],
    handle: &Bound<'_, PyAny>,
    safe: bool,
    memo: &mut HashMap<NodeId, Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    let container: Bound<'_, PyAny> = if safe {
        PySet::empty(py)?.into_any()
    } else {
        py.import("pythonizeyaml.nodes")?
            .getattr("RoundTripSet")?
            .call1((handle, node_id))?
    };
    memo.insert(node_id, container.clone().unbind());
    let set = container.cast::<PySet>()?;
    let metadata = PyDict::new(py);
    for item in items {
        let value = materialize_node(py, document, *item, handle, safe, memo)?;
        if value.bind(py).hash().is_err() {
            return Err(native_error(YamlError::new(
                ErrorKind::Constructor,
                "found unhashable key",
                document.arena.node(*item).span,
            )));
        }
        set.add(value.bind(py))?;
        metadata.set_item(value.bind(py), *item)?;
    }
    if !safe {
        container.setattr("_pyy_node_ids", metadata)?;
    }
    Ok(container.unbind())
}

/// Re-applies an explicit YAML core tag to a scalar. Plain scalars already
/// carry the tag's kind from the parser's `classify_scalar`, so this is
/// idempotent for them; quoted and block scalars always arrive as `Str` and
/// need the tag's conversion here.
fn apply_explicit_tag(scalar: &Scalar, tag: Option<&str>, span: Span) -> Result<Scalar, YamlError> {
    let Some(suffix) = tag.and_then(|tag| tag.strip_prefix("tag:yaml.org,2002:")) else {
        return Ok(scalar.clone());
    };
    let mut result = scalar.clone();
    result.kind = match suffix {
        "str" => ScalarKind::Str,
        "null" => ScalarKind::Null,
        "int" => {
            // Quoted `!!int` scalars keep their raw spelling; normalize it the
            // same way the parser does for plain integers so materialization
            // and dirty checks see decimal text.
            result.value = crate::number::integer_to_decimal_string(
                &scalar.value,
                crate::number::SchemaVersion::Yaml11,
            )
            .unwrap_or_else(|| scalar.value.clone());
            ScalarKind::Int
        }
        "float" => ScalarKind::Float,
        "decimal" => ScalarKind::Decimal,
        "binary" => ScalarKind::Binary,
        "timestamp" => ScalarKind::Timestamp,
        "bool" => {
            let lower = scalar.value.to_ascii_lowercase();
            match lower.as_str() {
                "true" | "yes" | "on" => ScalarKind::Bool(true),
                "false" | "no" | "off" => ScalarKind::Bool(false),
                _ => {
                    return Err(YamlError::new(
                        ErrorKind::Constructor,
                        format!("could not resolve !!bool value '{}'", scalar.value),
                        span,
                    ));
                }
            }
        }
        // Non-core tags and the merge tag are left to the caller.
        _ => return Ok(scalar.clone()),
    };
    Ok(result)
}

/// Round-trip loads wrap every materialized scalar in the Python subclass
/// from `pythonizeyaml.nodes.wrap_scalar` that carries the styling API;
/// `bool` and `None` have no subclassable type and stay plain.
fn wrap_scalar_value(py: Python<'_>, value: Py<PyAny>) -> PyResult<Py<PyAny>> {
    let nodes = py.import("pythonizeyaml.nodes")?;
    let wrapped = nodes.getattr("wrap_scalar")?.call1((value,))?;
    Ok(wrapped.unbind())
}

fn materialize_scalar(py: Python<'_>, scalar: &Scalar, span: Span) -> PyResult<Py<PyAny>> {
    match &scalar.kind {
        ScalarKind::Null => Ok(py.None()),
        ScalarKind::Bool(value) => Ok(PyBool::new(py, *value).to_owned().unbind().into_any()),
        ScalarKind::Int => {
            let result = py
                .import("builtins")?
                .getattr("int")?
                .call1((scalar.value.as_str(),))?;
            Ok(result.unbind())
        }
        ScalarKind::Float => {
            let value = match scalar.value.as_str() {
                "inf" => f64::INFINITY,
                "-inf" => f64::NEG_INFINITY,
                "nan" => f64::NAN,
                value => value.parse::<f64>().map_err(|_| {
                    native_error(YamlError::new(
                        ErrorKind::Constructor,
                        format!("could not resolve float value '{value}'"),
                        span,
                    ))
                })?,
            };
            Ok(PyFloat::new(py, value).into_any().unbind())
        }
        ScalarKind::Decimal => {
            let result = py
                .import("decimal")?
                .getattr("Decimal")?
                .call1((scalar.value.as_str(),))?;
            Ok(result.unbind())
        }
        ScalarKind::Str => Ok(PyString::new(py, &scalar.value).into_any().unbind()),
        ScalarKind::Binary => {
            let decoded = base64::engine::general_purpose::STANDARD
                .decode(scalar.value.trim())
                .map_err(|_| {
                    native_error(YamlError::new(
                        ErrorKind::Constructor,
                        format!("invalid !!binary value '{}'", scalar.value.trim()),
                        span,
                    ))
                })?;
            Ok(PyBytes::new(py, &decoded).into_any().unbind())
        }
        ScalarKind::Timestamp => materialize_timestamp(py, scalar.value.trim(), span),
    }
}

/// Builds `datetime.date`/`datetime.datetime` from the YAML timestamp
/// components so construction does not depend on `datetime.fromisoformat`,
/// whose accepted formats vary by Python version (`Z` and short fractions
/// are 3.11+ only).
fn materialize_timestamp(py: Python<'_>, text: &str, span: Span) -> PyResult<Py<PyAny>> {
    let Some(parts) = parser::parse_timestamp(text) else {
        return Err(native_error(YamlError::new(
            ErrorKind::Constructor,
            format!("invalid !!timestamp value '{text}'"),
            span,
        )));
    };
    let value = build_timestamp_value(py, &parts).map_err(|err| {
        // Grammar-valid but calendar-invalid text (e.g. `2001-13-45`) makes
        // datetime construction itself fail; funnel it through the normal
        // error translation instead of leaking a raw ValueError.
        if err.is_instance_of::<PyValueError>(py) {
            native_error(YamlError::new(
                ErrorKind::Constructor,
                format!("invalid !!timestamp value '{text}'"),
                span,
            ))
        } else {
            err
        }
    })?;
    Ok(value.unbind())
}

fn build_timestamp_value<'py>(
    py: Python<'py>,
    parts: &parser::TimestampParts,
) -> PyResult<Bound<'py, PyAny>> {
    let module = py.import("datetime")?;
    let Some(time) = parts.time.as_ref() else {
        let value = module
            .getattr("date")?
            .call1((parts.year, parts.month, parts.day))?;
        return Ok(value.into_any());
    };
    let tzinfo = match time.tz_offset_seconds {
        None => py.None(),
        Some(0) => module.getattr("timezone")?.getattr("utc")?.unbind(),
        Some(offset) => {
            let delta = module.getattr("timedelta")?.call1((0, offset, 0))?;
            module.getattr("timezone")?.call1((delta,))?.unbind()
        }
    };
    let value = module.getattr("datetime")?.call1((
        parts.year,
        parts.month,
        parts.day,
        time.hour,
        time.minute,
        time.second,
        time.microsecond,
        tzinfo,
    ))?;
    Ok(value.into_any())
}

pub fn dump_value(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    config: EmitConfig,
    explicit_start: Option<bool>,
) -> PyResult<String> {
    // Only a real document handle counts: the round-trip scalar wrappers
    // carry `_pyy_handle = None` as a class default, and a bare `None`
    // attribute must fall through to the plain dump path.
    let handle = value.getattr("_pyy_handle").ok().and_then(|candidate| {
        candidate
            .cast::<NativeDocument>()
            .ok()
            .cloned()
            .map(|document| document.into_any())
    });
    let node_id = value
        .getattr("_pyy_node_id")
        .ok()
        .and_then(|item| item.extract::<i64>().ok())
        .unwrap_or(-1);
    if let Some(handle) = handle {
        let document = handle.cast::<NativeDocument>()?;
        let native = document.borrow();
        let model = &native.inner;
        let node_id = if node_id >= 0 && (node_id as usize) < model.arena.nodes.len() {
            node_id as usize
        } else {
            usize::MAX
        };
        if !has_dirty(value)? {
            return clean_dump_text(model, node_id, explicit_start);
        }
        return dirty_dump_text(py, value, model, node_id, config, explicit_start);
    }
    emit_single(py, value, config, explicit_start).map_err(native_error)
}

/// The dirty-path text for a value carrying a node id: single-document roots
/// dump the edited whole source, roots inside a multi-document stream dump
/// only their own edited document, and any other node is re-emitted from its
/// own edited source text.
fn dirty_dump_text(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    model: &ModelDocument,
    node_id: NodeId,
    config: EmitConfig,
    explicit_start: Option<bool>,
) -> PyResult<String> {
    let mut edits = Vec::new();
    collect_edits(py, value, model, node_id, config, false, &mut edits)?;
    let is_root = node_id == usize::MAX
        || model
            .documents
            .iter()
            .any(|document| document.root == node_id);
    if is_root {
        if model.documents.len() == 1 {
            let text = apply_edits(&model.text, edits)?;
            return Ok(apply_explicit_start_override(text, explicit_start));
        }
        if let Some(document) = model
            .documents
            .iter()
            .find(|document| document.root == node_id)
        {
            let span = document.span;
            let base = slice_source(model, span)?;
            let shifted: Vec<(Span, String)> = edits
                .into_iter()
                .filter(|(edit_span, _)| edit_span.start >= span.start && edit_span.end <= span.end)
                .map(|(edit_span, replacement)| {
                    (
                        Span::new(edit_span.start - span.start, edit_span.end - span.start),
                        replacement,
                    )
                })
                .collect();
            let mut text = apply_edits(&base, shifted)?;
            if !text.ends_with('\n') {
                text.push('\n');
            }
            return Ok(apply_explicit_start_override(text, explicit_start));
        }
        let text = apply_edits(&model.text, edits)?;
        return Ok(apply_explicit_start_override(text, explicit_start));
    }
    sub_node_dump_text(model, node_id, edits)
}

/// The clean-path text for a value carrying a node id. Document roots dump
/// their document text (the whole source for a single-document stream); any
/// other node dumps exactly its own source text, so `dump(d["a"])` yields
/// `b: 1` instead of the whole document and `dump(stream[0])` yields only
/// the first document of a stream.
fn clean_dump_text(
    model: &ModelDocument,
    node_id: NodeId,
    explicit_start: Option<bool>,
) -> PyResult<String> {
    if node_id == usize::MAX {
        if model.documents.len() == 1 {
            return Ok(apply_explicit_start_override(
                model.text.clone(),
                explicit_start,
            ));
        }
        return Ok(model.text.clone());
    }
    if model.documents.len() == 1 && model.documents[0].root == node_id {
        return Ok(apply_explicit_start_override(
            model.text.clone(),
            explicit_start,
        ));
    }
    if let Some(document) = model
        .documents
        .iter()
        .find(|document| document.root == node_id)
    {
        let mut text = slice_source(model, document.span)?;
        if !text.ends_with('\n') {
            text.push('\n');
        }
        return Ok(apply_explicit_start_override(text, explicit_start));
    }
    let mut text = slice_source(model, model.arena.node(node_id).span)?;
    if !text.ends_with('\n') {
        text.push('\n');
    }
    Ok(text)
}

/// Applies the collected data edits to only the given node's source text.
/// Edits outside the node's own span (an alias resolving to a target
/// elsewhere in the document) cannot be applied to the slice and are skipped.
fn sub_node_dump_text(
    model: &ModelDocument,
    node_id: NodeId,
    edits: Vec<(Span, String)>,
) -> PyResult<String> {
    let span = model.arena.node(node_id).span;
    let base = slice_source(model, span)?;
    let mut shifted: Vec<(Span, String)> = Vec::new();
    for (edit_span, replacement) in edits {
        if edit_span.start >= span.start && edit_span.end <= span.end {
            shifted.push((
                Span::new(edit_span.start - span.start, edit_span.end - span.start),
                replacement,
            ));
        }
    }
    let mut text = apply_edits(&base, shifted)?;
    if !text.ends_with('\n') {
        text.push('\n');
    }
    Ok(text)
}

fn slice_source(model: &ModelDocument, span: Span) -> PyResult<String> {
    model
        .text
        .get(span.range())
        .map(str::to_owned)
        .ok_or_else(|| {
            native_error(YamlError::new(
                ErrorKind::Serializer,
                "internal error: node span out of range",
                span,
            ))
        })
}

/// Expands a node's span to the full source lines it occupies, so a removal
/// edit deletes the whole entry including its indentation, dash/key, and the
/// trailing newline. Spans that already end at a newline (mapping
/// `entry_span`) are kept as-is.
fn entry_line_range(text: &str, span: Span) -> Span {
    let start = text[..span.start]
        .rfind('\n')
        .map(|pos| pos + 1)
        .unwrap_or(0);
    let end = if text[..span.end].ends_with('\n') {
        span.end
    } else {
        text[span.end..]
            .find('\n')
            .map(|pos| span.end + pos + 1)
            .unwrap_or(text.len())
    };
    Span::new(start, end)
}

fn collect_edits(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    document: &ModelDocument,
    node_id: NodeId,
    config: EmitConfig,
    suppress_structural: bool,
    edits: &mut Vec<(Span, String)>,
) -> PyResult<()> {
    if node_id >= document.arena.nodes.len() {
        return Ok(());
    }
    let node = document.arena.node(node_id);
    match &node.kind {
        NodeKind::Scalar(scalar) => {
            if !scalar_matches_py(py, value, scalar)? {
                edits.push((
                    node.value_span,
                    encode_scalar(py, value, scalar, document, node.value_span, config)?,
                ));
            }
        }
        NodeKind::Alias(target) => collect_edits(
            py,
            value,
            document,
            *target,
            config,
            suppress_structural,
            edits,
        )?,
        NodeKind::Tagged { value: inner, .. } => collect_edits(
            py,
            value,
            document,
            *inner,
            config,
            suppress_structural,
            edits,
        )?,
        NodeKind::Sequence(items) => {
            let Some(list) = value.cast::<PyList>().ok() else {
                edits.push((
                    node.span,
                    canonical_edit(py, value, config, node_base_indent(document, node.span))?,
                ));
                return Ok(());
            };
            let ids = value
                .getattr("_pyy_node_ids")
                .ok()
                .and_then(|item| item.extract::<Vec<i64>>().ok());
            let Some(ids) = ids else {
                // A plain (user-assigned) list carries no per-item node
                // identity, so the whole container is re-emitted from the data.
                edits.push((
                    node.span,
                    canonical_edit(py, value, config, node_base_indent(document, node.span))?,
                ));
                return Ok(());
            };
            if ids.len() != items.len() {
                if suppress_structural {
                    // A structural edit (a removal or an insertion) shifted item
                    // positions, so the wrapper's own per-item ids — not the zip
                    // position — map each remaining value to its true source node.
                    let mut surviving: Vec<usize> = Vec::new();
                    for (index, child) in list.iter().enumerate() {
                        let child_id = ids.get(index).copied().unwrap_or(-1);
                        if child_id < 0 {
                            // A Python-created item: it has no source line to
                            // reuse, and the caller re-inserts it through an
                            // external patch, so emit nothing for it here.
                            // Falling back to a whole-container re-emit would
                            // overlap those external patches and get dropped,
                            // silently losing the insertion.
                            continue;
                        }
                        let child_id = child_id as usize;
                        if child_id >= document.arena.nodes.len() {
                            edits.push((
                                node.span,
                                canonical_edit(
                                    py,
                                    value,
                                    config,
                                    node_base_indent(document, node.span),
                                )?,
                            ));
                            return Ok(());
                        }
                        surviving.push(child_id);
                        collect_edits(py, &child, document, child_id, config, true, edits)?;
                    }
                    // Source entries whose node no longer exists in the data
                    // must be deleted; nothing else emits their lines.
                    for child_id in items.iter() {
                        if !surviving.contains(child_id) {
                            let span = document.arena.node(*child_id).span;
                            edits.push((entry_line_range(&document.text, span), String::new()));
                        }
                    }
                    return Ok(());
                }
                edits.push((
                    node.span,
                    canonical_edit(py, value, config, node_base_indent(document, node.span))?,
                ));
                return Ok(());
            }
            for (index, child_id) in items.iter().enumerate() {
                let child = list.get_item(index)?;
                collect_edits(
                    py,
                    &child,
                    document,
                    *child_id,
                    config,
                    suppress_structural,
                    edits,
                )?;
            }
        }
        NodeKind::Mapping(entries) => {
            let Some(mapping) = value.cast::<PyDict>().ok() else {
                edits.push((
                    node.span,
                    canonical_edit(py, value, config, node_base_indent(document, node.span))?,
                ));
                return Ok(());
            };
            if mapping.len() != entries.len() {
                if suppress_structural {
                    for entry in entries {
                        let key_kind = &document.arena.node(entry.key).kind;
                        let Some(key) = find_python_key(py, mapping, key_kind)? else {
                            if is_merge_key(document, entry.key) {
                                // `<<` resolves into real data entries at
                                // load, so its absence from the data is the
                                // resolution, not a removal: keep the source
                                // entry verbatim.
                                continue;
                            }
                            // The entry was removed from the data; delete its
                            // source lines since nothing else emits the removal.
                            // The entry span ends at the key line, so a block
                            // value's lines must come from the union with the
                            // value node's span.
                            let value_span = document.arena.node(entry.value).span;
                            let start = entry.entry_span.start.min(value_span.start);
                            let end = entry.entry_span.end.max(value_span.end);
                            edits.push((
                                entry_line_range(&document.text, Span::new(start, end)),
                                String::new(),
                            ));
                            continue;
                        };
                        let child = mapping.get_item(&key)?.ok_or_else(|| {
                            native_error(YamlError::new(
                                ErrorKind::Constructor,
                                "mapping key disappeared",
                                entry.key_span,
                            ))
                        })?;
                        collect_edits(py, &child, document, entry.value, config, true, edits)?;
                    }
                    return Ok(());
                }
                edits.push((
                    node.span,
                    canonical_edit(py, value, config, node_base_indent(document, node.span))?,
                ));
                return Ok(());
            }
            for entry in entries {
                let key_kind = &document.arena.node(entry.key).kind;
                let Some(key) = find_python_key(py, mapping, key_kind)? else {
                    if is_merge_key(document, entry.key) {
                        // A resolved merge entry survives untouched here too:
                        // the container would otherwise be canonically
                        // re-emitted, materializing the resolved entries and
                        // dropping the source `<<` line.
                        continue;
                    }
                    edits.push((
                        node.span,
                        canonical_edit(py, value, config, node_base_indent(document, node.span))?,
                    ));
                    return Ok(());
                };
                let child = mapping.get_item(&key)?.ok_or_else(|| {
                    native_error(YamlError::new(
                        ErrorKind::Constructor,
                        "mapping key disappeared",
                        entry.key_span,
                    ))
                })?;
                collect_edits(
                    py,
                    &child,
                    document,
                    entry.value,
                    config,
                    suppress_structural,
                    edits,
                )?;
            }
        }
        NodeKind::Set(items) => {
            let Some(set) = value.cast::<PySet>().ok() else {
                edits.push((
                    node.span,
                    canonical_edit(py, value, config, node_base_indent(document, node.span))?,
                ));
                return Ok(());
            };
            if set.len() != items.len() {
                edits.push((
                    node.span,
                    canonical_edit(py, value, config, node_base_indent(document, node.span))?,
                ));
            }
        }
    }
    Ok(())
}

fn canonical_edit(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    config: EmitConfig,
    base_indent: usize,
) -> PyResult<String> {
    let mut rendered = emit_single(py, value, config, Some(false)).map_err(native_error)?;
    while rendered.ends_with('\n') {
        rendered.pop();
    }
    if base_indent > 0 {
        let mut lines = rendered.split('\n');
        if let Some(first) = lines.next() {
            let mut adjusted = first.to_owned();
            for line in lines {
                adjusted.push('\n');
                adjusted.push_str(&" ".repeat(base_indent));
                adjusted.push_str(line);
            }
            rendered = adjusted;
        }
    }
    Ok(rendered)
}

fn scalar_matches_py(py: Python<'_>, value: &Bound<'_, PyAny>, scalar: &Scalar) -> PyResult<bool> {
    match &scalar.kind {
        ScalarKind::Null => Ok(value.is_none()),
        ScalarKind::Bool(expected) => value
            .extract::<bool>()
            .map(|actual| actual == *expected)
            .or(Ok(false)),
        ScalarKind::Int => {
            let actual = value.str()?.to_string_lossy().into_owned();
            Ok(normalize_integer_text(&actual) == normalize_integer_text(&scalar.value))
        }
        ScalarKind::Float => {
            let expected = match scalar.value.as_str() {
                "inf" => f64::INFINITY,
                "-inf" => f64::NEG_INFINITY,
                "nan" => f64::NAN,
                raw => raw.parse::<f64>().unwrap_or(f64::NAN),
            };
            let Some(actual) = value.extract::<f64>().ok() else {
                return Ok(false);
            };
            if expected.is_nan() {
                Ok(actual.is_nan())
            } else {
                Ok(actual.to_bits() == expected.to_bits())
            }
        }
        ScalarKind::Decimal => {
            let expected = value
                .py()
                .import("decimal")?
                .getattr("Decimal")?
                .call1((scalar.value.as_str(),))?;
            Ok(value.eq(expected).unwrap_or(false))
        }
        ScalarKind::Str => Ok(value
            .cast::<PyString>()
            .ok()
            .is_some_and(|text| text.to_string_lossy() == scalar.value)),
        ScalarKind::Binary => {
            let Some(bytes) = value.cast::<PyBytes>().ok() else {
                return Ok(false);
            };
            let expected = base64::engine::general_purpose::STANDARD
                .decode(scalar.value.trim())
                .unwrap_or_default();
            Ok(bytes.as_bytes() == expected)
        }
        ScalarKind::Timestamp => timestamp_scalar_matches(py, value, &scalar.value),
    }
}

/// Timestamps are compared component-wise: the source scalar text is parsed
/// with the parser's timestamp matcher and rebuilt as the datetime the
/// constructor would produce, so `2001-12-15T02:59:43Z` and
/// `2001-12-15 02:59:43+00:00` count as the same value instead of never
/// matching the `str()` spelling (which reformatted untouched timestamps on
/// every unrelated mutation). Naive and aware datetimes compare unequal, and
/// the text comparison remains as the fallback when the source does not
/// parse as a timestamp.
fn timestamp_scalar_matches(py: Python<'_>, value: &Bound<'_, PyAny>, raw: &str) -> PyResult<bool> {
    let text = raw.trim();
    if let Some(parts) = parser::parse_timestamp(text) {
        // Calendar-invalid source text (e.g. `2001-13-45`) cannot be
        // constructed; treat it as changed rather than failing the dump.
        if let Ok(expected) = build_timestamp_value(py, &parts) {
            return Ok(value.eq(&expected).unwrap_or(false));
        }
        return Ok(false);
    }
    Ok(value.str()?.to_string_lossy().starts_with(text))
}

fn find_python_key<'py>(
    py: Python<'py>,
    mapping: &Bound<'py, PyDict>,
    key_kind: &NodeKind,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    if let NodeKind::Scalar(scalar) = key_kind {
        if let Ok(expected) = materialize_scalar(py, scalar, Span::default()) {
            for (key, _) in mapping.iter() {
                if key.eq(expected.bind(py)).unwrap_or(false) {
                    return Ok(Some(key));
                }
            }
        }
    }
    Ok(None)
}

fn wrapper_node_ids(value: &Bound<'_, PyAny>, attribute: &str, fallback_len: usize) -> Vec<i64> {
    value
        .getattr(attribute)
        .ok()
        .and_then(|items| items.extract::<Vec<i64>>().ok())
        .unwrap_or_else(|| vec![-1; fallback_len])
}

fn has_dirty(root: &Bound<'_, PyAny>) -> PyResult<bool> {
    fn visit(
        value: &Bound<'_, PyAny>,
        seen: &mut std::collections::HashSet<usize>,
    ) -> PyResult<bool> {
        let pointer = value.as_ptr() as usize;
        if !seen.insert(pointer) {
            return Ok(false);
        }
        if value
            .getattr("_pyy_dirty")
            .ok()
            .and_then(|item| item.extract::<bool>().ok())
            .unwrap_or(false)
        {
            return Ok(true);
        }
        if let Ok(mapping) = value.cast::<PyDict>() {
            for (_, child) in mapping.iter() {
                if visit(&child, seen)? {
                    return Ok(true);
                }
            }
        } else if let Ok(list) = value.cast::<PyList>() {
            for child in list.iter() {
                if visit(&child, seen)? {
                    return Ok(true);
                }
            }
        } else if let Ok(set) = value.cast::<PySet>() {
            for child in set.iter() {
                if visit(&child, seen)? {
                    return Ok(true);
                }
            }
        } else if let Ok(inner) = value.getattr("value") {
            if value
                .get_type()
                .name()
                .ok()
                .is_some_and(|name| name.to_string_lossy() == "Tagged")
                && visit(&inner, seen)?
            {
                return Ok(true);
            }
        }
        Ok(false)
    }
    visit(root, &mut std::collections::HashSet::new())
}

fn encode_scalar(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    original: &Scalar,
    document: &ModelDocument,
    span: Span,
    config: EmitConfig,
) -> PyResult<String> {
    if let Ok(text) = value.cast::<PyString>() {
        let text = text.to_string_lossy();
        match original.style {
            ScalarStyle::SingleQuoted => return Ok(format!("'{}'", text.replace('\'', "''"))),
            ScalarStyle::DoubleQuoted => return Ok(format!("\"{}\"", escape_double(&text))),
            ScalarStyle::Literal | ScalarStyle::Folded => {
                let line_start = document.text[..span.start]
                    .rfind('\n')
                    .map_or(0, |index| index + 1);
                let indent = document.text[line_start..]
                    .bytes()
                    .take_while(|byte| *byte == b' ')
                    .count();
                return Ok(render_block_string(
                    &text,
                    indent + 2,
                    original.style,
                    original.chomping,
                ));
            }
            ScalarStyle::Plain => {}
        }
    }
    canonical_edit(py, value, config, node_base_indent(document, span))
}

fn render_block_string(
    value: &str,
    indent: usize,
    style: ScalarStyle,
    chomping: Option<char>,
) -> String {
    let marker = if style == ScalarStyle::Folded {
        '>'
    } else {
        '|'
    };
    let mut output = String::new();
    output.push(marker);
    if let Some(chomping) = chomping {
        output.push(chomping);
    } else if value.ends_with('\n') {
        output.push('+');
    }
    output.push('\n');
    for line in value.trim_end_matches('\n').split('\n') {
        output.push_str(&" ".repeat(indent));
        output.push_str(line);
        output.push('\n');
    }
    output.pop();
    output
}

fn escape_double(value: &str) -> String {
    let mut output = String::new();
    for ch in value.chars() {
        match ch {
            '\\' => output.push_str("\\\\"),
            '"' => output.push_str("\\\""),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            _ => output.push(ch),
        }
    }
    output
}

fn node_base_indent(document: &ModelDocument, span: Span) -> usize {
    let line_start = document.text[..span.start]
        .rfind('\n')
        .map_or(0, |index| index + 1);
    document.text[line_start..span.start]
        .bytes()
        .take_while(|byte| *byte == b' ')
        .count()
}
/// Spans are BYTE offsets into the UTF-8 `source`. Every patch is validated
/// here at the FFI boundary, so an inverted, out-of-bounds, or
/// non-char-boundary span (for example a Python character offset coming from
/// an unpatched caller) surfaces as a Serializer-kind native error instead of
/// a `replace_range` panic. Replacement text arrives as a Rust `String`, so
/// its UTF-8 validity is guaranteed by the type system.
fn apply_edits(source: &str, mut edits: Vec<(Span, String)>) -> PyResult<String> {
    for (span, _) in &edits {
        if span.start > span.end
            || span.end > source.len()
            || !source.is_char_boundary(span.start)
            || !source.is_char_boundary(span.end)
        {
            return Err(native_error(YamlError::new(
                ErrorKind::Serializer,
                format!(
                    "invalid patch span {}..{} for a source of {} bytes",
                    span.start,
                    span.end,
                    source.len()
                ),
                *span,
            )));
        }
    }
    edits.sort_by_key(|(span, _)| (span.start, span.end));
    let mut filtered: Vec<(Span, String)> = Vec::new();
    for edit in edits {
        if let Some((last, _)) = filtered.last() {
            if edit.0.start < last.end {
                continue;
            }
        }
        filtered.push(edit);
    }
    let mut output = source.to_owned();
    for (span, replacement) in filtered.into_iter().rev() {
        output.replace_range(span.range(), &replacement);
    }
    Ok(output)
}

/// Content test for a `---` document-start marker line, mirroring the
/// parser's `is_marker`: the line content is exactly `---`, or starts with
/// `--- ` / `---#`. Lookalikes like `---foo` or `---42` are plain scalars.
fn is_marker_line(trimmed: &str) -> bool {
    trimmed.starts_with("---")
        && matches!(trimmed.as_bytes().get(3), None | Some(b' ') | Some(b'#'))
}

/// True when the first significant line (skipping blanks, comments, and
/// `%directive` lines) is a `---` document-start marker.
fn starts_with_document_marker(text: &str) -> bool {
    let (_, rest) = split_bom(text);
    for raw in rest.split_inclusive('\n') {
        let trimmed = raw.strip_suffix('\n').unwrap_or(raw).trim_end();
        if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with('%') {
            continue;
        }
        return is_marker_line(trimmed);
    }
    false
}

/// Prepends a `---` marker after any leading `%directive` lines; inserting
/// before a `%YAML`/`%TAG` directive would be invalid YAML.
fn insert_explicit_start(text: &str) -> String {
    let (bom, rest) = split_bom(text);
    let mut after_directives = 0usize;
    for raw in rest.split_inclusive('\n') {
        let trimmed = raw.strip_suffix('\n').unwrap_or(raw).trim_end();
        if trimmed.starts_with('%') {
            after_directives += raw.len();
        } else {
            break;
        }
    }
    let mut output = String::with_capacity(text.len() + "---\n".len());
    output.push_str(bom);
    output.push_str(&rest[..after_directives]);
    output.push_str("---\n");
    output.push_str(&rest[after_directives..]);
    output
}

/// Removes a leading `---` marker line (skipping blanks, comments, and
/// directives before it) and leaves the text untouched when there is none.
fn remove_explicit_start(source: &str) -> String {
    let (bom, rest) = split_bom(source);
    let mut prefix = String::from(bom);
    let mut consumed = 0usize;
    let mut removed = false;
    for raw in rest.split_inclusive('\n') {
        consumed += raw.len();
        let trimmed = raw.strip_suffix('\n').unwrap_or(raw).trim_end();
        if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with('%') {
            prefix.push_str(raw);
            continue;
        }
        if is_marker_line(trimmed) {
            removed = true;
        } else {
            prefix.push_str(raw);
        }
        break;
    }
    if !removed {
        return source.to_owned();
    }
    prefix.push_str(&rest[consumed..]);
    prefix
}

fn split_bom(text: &str) -> (&str, &str) {
    text.strip_prefix('\u{FEFF}')
        .map_or(("", text), |rest| ("\u{FEFF}", rest))
}

fn apply_explicit_start_override(text: String, explicit_start: Option<bool>) -> String {
    match explicit_start {
        Some(true) => {
            if starts_with_document_marker(&text) {
                text
            } else {
                insert_explicit_start(&text)
            }
        }
        Some(false) => {
            if starts_with_document_marker(&text) {
                remove_explicit_start(&text)
            } else {
                text
            }
        }
        None => text,
    }
}

fn normalize_integer_text(value: &str) -> String {
    let value = value.trim().trim_start_matches('+');
    let mut normalized = value.trim_start_matches('0').to_owned();
    if normalized.is_empty() {
        normalized.push('0');
    }
    if value.starts_with('-') && normalized != "0" {
        normalized.insert(0, '-');
    }
    normalized
}

pub fn dump_values(
    py: Python<'_>,
    values: &Bound<'_, PyList>,
    config: EmitConfig,
    explicit_start: Option<bool>,
) -> PyResult<String> {
    if values.is_empty() {
        return Ok(String::new());
    }
    if values.len() == 1 {
        let value = values.get_item(0)?;
        return dump_value(py, &value, config, explicit_start);
    }
    let mut common_handle: Option<Py<NativeDocument>> = None;
    let mut all_clean = true;
    let mut root_ids = Vec::new();
    for value in values.iter() {
        let handle = value
            .getattr("_pyy_handle")
            .ok()
            .and_then(|handle| handle.extract::<Py<NativeDocument>>().ok());
        let node_id = value
            .getattr("_pyy_node_id")
            .ok()
            .and_then(|item| item.extract::<usize>().ok())
            .unwrap_or(usize::MAX);
        root_ids.push(node_id);
        if !has_dirty(&value)? {
            if let Some(handle) = handle {
                if let Some(existing) = &common_handle {
                    if !existing.bind(py).is(handle.bind(py)) {
                        all_clean = false;
                    }
                } else {
                    common_handle = Some(handle);
                }
            } else {
                all_clean = false;
            }
        } else {
            all_clean = false;
        }
    }
    if all_clean {
        if let Some(handle) = common_handle {
            let document = handle.bind(py).cast::<NativeDocument>()?;
            let native = document.borrow();
            if root_ids
                == native
                    .inner
                    .documents
                    .iter()
                    .map(|doc| doc.root)
                    .collect::<Vec<_>>()
            {
                return Ok(native.inner.text.clone());
            }
        }
    }
    emit_documents(py, values, config, explicit_start).map_err(native_error)
}

pub fn extract_emit_config(config: &Bound<'_, PyAny>) -> PyResult<EmitConfig> {
    // `width` and `preserve_quotes` are carried through but the native
    // emitter currently ignores them: line wrapping would produce folded
    // plain scalars the parser cannot re-read, and fresh dumps carry no
    // per-value source quoting to preserve (see EmitConfig).
    Ok(EmitConfig {
        mapping: config.getattr("mapping").and_then(|v| v.extract())?,
        sequence: config.getattr("sequence").and_then(|v| v.extract())?,
        offset: config.getattr("offset").and_then(|v| v.extract())?,
        width: config.getattr("width").and_then(|v| v.extract())?,
        preserve_quotes: config
            .getattr("preserve_quotes")
            .and_then(|v| v.extract())?,
    })
}

pub fn native_error(error: YamlError) -> PyErr {
    let kind = match error.kind {
        ErrorKind::Scanner => 0,
        ErrorKind::Parser => 1,
        ErrorKind::Composer => 2,
        ErrorKind::Constructor => 3,
        ErrorKind::Emitter => 4,
        ErrorKind::Representer => 5,
        ErrorKind::Serializer => 6,
    };
    PyErr::new::<crate::NativeYamlError, _>((kind, error.problem, error.mark.start, error.mark.end))
}
#[pymethods]
impl NativeDocument {
    fn source(&self) -> String {
        self.inner.text.clone()
    }

    fn root_ids(&self) -> Vec<usize> {
        self.inner
            .documents
            .iter()
            .map(|document| document.root)
            .collect()
    }

    fn document_info(&self, py: Python<'_>, root_id: usize) -> PyResult<Py<PyDict>> {
        let document = self
            .inner
            .documents
            .iter()
            .find(|document| document.root == root_id)
            .ok_or_else(|| {
                native_error(YamlError::new(
                    ErrorKind::Composer,
                    "unknown document root",
                    Span::default(),
                ))
            })?;
        let info = PyDict::new(py);
        info.set_item("root_id", document.root)?;
        info.set_item("span", (document.span.start, document.span.end))?;
        info.set_item("explicit_start", document.explicit_start)?;
        info.set_item("explicit_end", document.explicit_end)?;
        info.set_item("directives", document.directives.clone())?;
        Ok(info.unbind())
    }

    fn describe(&self, py: Python<'_>, node_id: usize) -> PyResult<Py<PyDict>> {
        let node = self.inner.arena.nodes.get(node_id).ok_or_else(|| {
            native_error(YamlError::new(
                ErrorKind::Composer,
                "unknown node id",
                Span::default(),
            ))
        })?;
        let info = PyDict::new(py);
        info.set_item("id", node.id)?;
        info.set_item("span", (node.span.start, node.span.end))?;
        info.set_item("value_span", (node.value_span.start, node.value_span.end))?;
        info.set_item("tag", node.tag.clone())?;
        info.set_item("raw_tag", raw_tag(self.inner.text.as_str(), node))?;
        info.set_item("anchor", node.anchor.clone())?;
        match &node.kind {
            NodeKind::Scalar(scalar) => {
                info.set_item("kind", "scalar")?;
                info.set_item("style", scalar_style_name(scalar.style))?;
                info.set_item(
                    "chomping",
                    scalar
                        .chomping
                        .map(|value| if value == '-' { "strip" } else { "keep" }),
                )?;
                info.set_item("raw", scalar.raw.clone())?;
                info.set_item("value", scalar.value.clone())?;
                info.set_item("collection_style", py.None())?;
            }
            NodeKind::Sequence(items) => {
                info.set_item("kind", "sequence")?;
                info.set_item(
                    "collection_style",
                    collection_style(self.inner.text.as_str(), node),
                )?;
                info.set_item("children", items.clone())?;
                info.set_item("style", py.None())?;
                info.set_item("chomping", py.None())?;
            }
            NodeKind::Mapping(entries) => {
                info.set_item("kind", "mapping")?;
                info.set_item(
                    "collection_style",
                    collection_style(self.inner.text.as_str(), node),
                )?;
                let children = PyList::empty(py);
                for entry in entries {
                    let item = PyDict::new(py);
                    item.set_item("key_id", entry.key)?;
                    item.set_item("value_id", entry.value)?;
                    item.set_item("key_span", (entry.key_span.start, entry.key_span.end))?;
                    item.set_item("value_span", (entry.value_span.start, entry.value_span.end))?;
                    item.set_item("entry_span", (entry.entry_span.start, entry.entry_span.end))?;
                    children.append(item)?;
                }
                info.set_item("children", children)?;
                info.set_item("style", py.None())?;
                info.set_item("chomping", py.None())?;
            }
            NodeKind::Set(items) => {
                info.set_item("kind", "set")?;
                info.set_item(
                    "collection_style",
                    collection_style(self.inner.text.as_str(), node),
                )?;
                info.set_item("children", items.clone())?;
                info.set_item("style", py.None())?;
                info.set_item("chomping", py.None())?;
            }
            NodeKind::Alias(target) => {
                info.set_item("kind", "alias")?;
                info.set_item("alias_target", *target)?;
                info.set_item(
                    "alias_name",
                    self.inner.text[node.value_span.range()].trim_start_matches('*'),
                )?;
                info.set_item("style", py.None())?;
                info.set_item("chomping", py.None())?;
                info.set_item("collection_style", py.None())?;
            }
            NodeKind::Tagged { value, .. } => {
                info.set_item("kind", "tagged")?;
                info.set_item("tagged_value_id", *value)?;
                info.set_item("style", py.None())?;
                info.set_item("chomping", py.None())?;
                info.set_item("collection_style", py.None())?;
            }
        }
        Ok(info.unbind())
    }
}

fn scalar_style_name(style: crate::model::ScalarStyle) -> &'static str {
    match style {
        crate::model::ScalarStyle::Plain => "plain",
        crate::model::ScalarStyle::SingleQuoted => "single",
        crate::model::ScalarStyle::DoubleQuoted => "double",
        crate::model::ScalarStyle::Literal => "literal",
        crate::model::ScalarStyle::Folded => "folded",
    }
}

fn collection_style(source: &str, node: &crate::model::Node) -> &'static str {
    let text = source[node.span.start..node.span.end].trim_start();
    if text.starts_with('[') || text.starts_with('{') {
        "flow"
    } else {
        "block"
    }
}

fn raw_tag(source: &str, node: &crate::model::Node) -> Option<String> {
    node.tag.as_ref()?;
    let line_start = source[..node.span.start]
        .rfind('\n')
        .map_or(0, |index| index + 1);
    let prefix = &source[line_start..node.span.start];
    let mut found = None;
    for token in prefix.split_whitespace() {
        if token.starts_with('!') {
            found = Some(token.to_owned());
        }
    }
    found
}

pub fn dump_value_with_patches(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    config: EmitConfig,
    explicit_start: Option<bool>,
    patches: &Bound<'_, PyList>,
    handle_override: Option<&Bound<'_, NativeDocument>>,
    node_id_override: Option<usize>,
) -> PyResult<String> {
    let external = parse_patch_list(patches)?;
    let inferred_handle = value.getattr("_pyy_handle").ok().and_then(|candidate| {
        candidate
            .cast::<NativeDocument>()
            .ok()
            .cloned()
            .map(|document| document.into_any())
    });
    let handle = handle_override
        .map(|handle| handle.clone().into_any())
        .or(inferred_handle);
    let node_id = node_id_override
        .or_else(|| {
            value
                .getattr("_pyy_node_id")
                .ok()
                .and_then(|item| item.extract::<usize>().ok())
        })
        .unwrap_or(usize::MAX);
    if let Some(handle) = handle {
        let document = handle.cast::<NativeDocument>()?;
        let native = document.borrow();
        let model = &native.inner;
        let node_id = if node_id < model.arena.nodes.len() {
            node_id
        } else {
            usize::MAX
        };
        // Without external patches this is exactly a plain dump, so node
        // identity applies (dumping one document of a stream yields that
        // document's text only).
        if external.is_empty() {
            if !has_dirty(value)? {
                return clean_dump_text(model, node_id, explicit_start);
            }
            return dirty_dump_text(py, value, model, node_id, config, explicit_start);
        }
        let mut data_edits = Vec::new();
        if has_dirty(value)? {
            collect_edits(
                py,
                value,
                &native.inner,
                node_id,
                config,
                !external.is_empty(),
                &mut data_edits,
            )?;
        }
        let mut edits = external.clone();
        for edit in data_edits {
            if !external
                .iter()
                .any(|external_edit| spans_overlap(external_edit.0, edit.0))
            {
                edits.push(edit);
            }
        }
        let mut text = apply_edits(&native.inner.text, edits)?;
        if explicit_start.is_some() {
            text = apply_explicit_start_override(text, explicit_start);
        }
        return Ok(text);
    }
    let base = emit_single(py, value, config, explicit_start).map_err(native_error)?;
    apply_edits(&base, external)
}

/// Patches are `(start, end, replacement)` triples whose offsets are BYTE
/// offsets into the UTF-8 source text, not Python character offsets. Any
/// malformed patch (wrong shape, non-integer or negative offset) becomes a
/// Serializer-kind native error, and range/char-boundary validation in
/// [`apply_edits`] guarantees that a character-offset span from an unpatched
/// caller produces a clean error, never a panic or silent corruption.
fn parse_patch_list(patches: &Bound<'_, PyList>) -> PyResult<Vec<(Span, String)>> {
    let mut result = Vec::with_capacity(patches.len());
    for (index, patch) in patches.iter().enumerate() {
        let parsed = (|| -> PyResult<(usize, usize, String)> {
            Ok((
                patch.get_item(0)?.extract::<usize>()?,
                patch.get_item(1)?.extract::<usize>()?,
                patch.get_item(2)?.extract::<String>()?,
            ))
        })();
        let (start, end, text) = parsed.map_err(|error| {
            native_error(YamlError::new(
                ErrorKind::Serializer,
                format!("invalid patch at index {index}: {error}"),
                Span::default(),
            ))
        })?;
        result.push((Span::new(start, end), text));
    }
    Ok(result)
}

fn spans_overlap(left: Span, right: Span) -> bool {
    left.start < right.end && right.start < left.end
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::exceptions::PyValueError;
    use std::sync::Arc;

    fn with_python<R>(f: impl FnOnce(Python<'_>) -> R) -> R {
        Python::initialize();
        Python::try_attach(f).expect("python interpreter should be available in tests")
    }

    /// A dict subclass so test values can carry the wrapper attributes
    /// (`_pyy_handle`, `_pyy_node_id`, ...) without importing the
    /// `pythonizeyaml` package (whose `__init__` imports the installed
    /// extension, which is not the one under test).
    fn wrapper_class(py: Python<'_>) -> Bound<'_, PyAny> {
        py.eval(c"type('W', (dict,), {})", None, None).unwrap()
    }

    fn handle_for(py: Python<'_>, source: &str) -> (Py<NativeDocument>, Arc<ModelDocument>) {
        let model = Arc::new(parser::parse(source).unwrap());
        let handle = Py::new(
            py,
            NativeDocument {
                inner: model.clone(),
            },
        )
        .unwrap();
        (handle, model)
    }

    fn mapping_node_id(model: &ModelDocument, root: NodeId, key: &str) -> NodeId {
        let NodeKind::Mapping(entries) = &model.arena.node(root).kind else {
            panic!("expected a mapping root");
        };
        entries
            .iter()
            .find(|entry| {
                matches!(&model.arena.node(entry.key).kind,
                NodeKind::Scalar(scalar) if scalar.value == key)
            })
            .map(|entry| entry.value)
            .unwrap_or_else(|| panic!("missing key {key}"))
    }

    fn assert_native_error(error: &PyErr, kind: i64, needle: &str) {
        Python::attach(|py| {
            assert!(
                !error.is_instance_of::<PyValueError>(py),
                "raw ValueError leaked: {error}"
            );
            let args = error.value(py).getattr("args").unwrap();
            let error_kind: i64 = args.get_item(0).unwrap().extract().unwrap();
            let problem: String = args.get_item(1).unwrap().extract().unwrap();
            assert_eq!(error_kind, kind, "problem was {problem:?}");
            assert!(
                problem.contains(needle),
                "problem {problem:?} missing {needle:?}"
            );
        });
    }

    // --- Item 8: dump_value honors node identity. ---

    #[test]
    fn clean_sub_node_dump_returns_only_that_node() {
        with_python(|py| {
            let (handle, model) = handle_for(py, "a:\n  b: 1\n");
            let inner_id = mapping_node_id(&model, model.documents[0].root, "a");
            let class = wrapper_class(py);
            let inner = class.call0().unwrap();
            inner.cast::<PyDict>().unwrap().set_item("b", 1).unwrap();
            inner.setattr("_pyy_handle", handle).unwrap();
            inner.setattr("_pyy_node_id", inner_id).unwrap();
            let text = dump_value(py, inner.as_any(), EmitConfig::default(), None).unwrap();
            assert_eq!(text, "b: 1\n");
        });
    }

    #[test]
    fn clean_document_dump_returns_that_document_of_a_stream() {
        with_python(|py| {
            let (values, handle) = parse_all_values(py, "a: 1\n---\nb: 2\n", true).unwrap();
            let roots: Vec<NodeId> = handle
                .borrow(py)
                .inner
                .documents
                .iter()
                .map(|document| document.root)
                .collect();
            let class = wrapper_class(py);
            let mut wrappers = Vec::new();
            for (index, root) in roots.iter().enumerate() {
                let wrapper = class.call0().unwrap();
                let source = values.bind(py).get_item(index).unwrap();
                for (key, value) in source.cast::<PyDict>().unwrap().iter() {
                    wrapper
                        .cast::<PyDict>()
                        .unwrap()
                        .set_item(key, value)
                        .unwrap();
                }
                wrapper
                    .setattr("_pyy_handle", handle.clone_ref(py))
                    .unwrap();
                wrapper.setattr("_pyy_node_id", *root).unwrap();
                wrappers.push(wrapper);
            }
            let first = dump_value(py, wrappers[0].as_any(), EmitConfig::default(), None).unwrap();
            assert_eq!(first, "a: 1\n");
            let second = dump_value(py, wrappers[1].as_any(), EmitConfig::default(), None).unwrap();
            assert_eq!(second, "---\nb: 2\n");
            // explicit_start=False strips only that document's marker.
            let stripped =
                dump_value(py, wrappers[1].as_any(), EmitConfig::default(), Some(false)).unwrap();
            assert_eq!(stripped, "b: 2\n");
        });
    }

    #[test]
    fn dirty_sub_node_dump_re_emits_only_that_node() {
        with_python(|py| {
            let (handle, model) = handle_for(py, "a:\n  b: 1\n");
            let inner_id = mapping_node_id(&model, model.documents[0].root, "a");
            let class = wrapper_class(py);
            let inner = class.call0().unwrap();
            let dict = inner.cast::<PyDict>().unwrap();
            dict.set_item("b", 2).unwrap();
            inner.setattr("_pyy_handle", handle).unwrap();
            inner.setattr("_pyy_node_id", inner_id).unwrap();
            inner.setattr("_pyy_dirty", true).unwrap();
            let text = dump_value(py, inner.as_any(), EmitConfig::default(), None).unwrap();
            assert_eq!(text, "b: 2\n");
        });
    }

    #[test]
    fn root_dump_keeps_the_whole_document() {
        with_python(|py| {
            let source = "a:\n  b: 1\n";
            let (handle, model) = handle_for(py, source);
            let class = wrapper_class(py);
            let root_wrapper = class.call0().unwrap();
            let inner = class.call0().unwrap();
            inner.cast::<PyDict>().unwrap().set_item("b", 1).unwrap();
            root_wrapper
                .cast::<PyDict>()
                .unwrap()
                .set_item("a", inner)
                .unwrap();
            root_wrapper.setattr("_pyy_handle", handle).unwrap();
            root_wrapper
                .setattr("_pyy_node_id", model.documents[0].root)
                .unwrap();
            let text = dump_value(py, root_wrapper.as_any(), EmitConfig::default(), None).unwrap();
            assert_eq!(text, source);
        });
    }

    // --- Item 9: document-marker semantics. ---

    #[test]
    fn marker_lookalikes_are_not_explicit_starts() {
        assert_eq!(remove_explicit_start("---foo\n"), "---foo\n");
        assert_eq!(remove_explicit_start("---42\n"), "---42\n");
        assert!(!starts_with_document_marker("---foo\n"));
        assert!(starts_with_document_marker("---\na: 1\n"));
        assert!(starts_with_document_marker("--- # c\na: 1\n"));
        assert!(starts_with_document_marker("%YAML 1.2\n---\na: 1\n"));
        assert!(!starts_with_document_marker("a: 1\n"));
    }

    #[test]
    fn explicit_start_removal_keeps_directives_and_content() {
        assert_eq!(remove_explicit_start("---\na: 1\n"), "a: 1\n");
        assert_eq!(
            remove_explicit_start("%YAML 1.2\n---\na: 1\n"),
            "%YAML 1.2\na: 1\n"
        );
        assert_eq!(remove_explicit_start("--- # c\na: 1\n"), "a: 1\n");
        assert_eq!(remove_explicit_start("a: 1\n"), "a: 1\n");
    }

    #[test]
    fn explicit_start_insertion_goes_after_directives() {
        assert_eq!(
            insert_explicit_start("%YAML 1.2\na: 1\n"),
            "%YAML 1.2\n---\na: 1\n"
        );
        assert_eq!(insert_explicit_start("a: 1\n"), "---\na: 1\n");
        assert_eq!(
            apply_explicit_start_override("---\na: 1\n".to_owned(), Some(true)),
            "---\na: 1\n"
        );
    }

    #[test]
    fn explicit_start_override_round_trips() {
        with_python(|py| {
            let (handle, model) = handle_for(py, "%YAML 1.2\n---\na: 1\n");
            let class = wrapper_class(py);
            let wrapper = class.call0().unwrap();
            wrapper.cast::<PyDict>().unwrap().set_item("a", 1).unwrap();
            wrapper.setattr("_pyy_handle", handle).unwrap();
            wrapper
                .setattr("_pyy_node_id", model.documents[0].root)
                .unwrap();
            let text = dump_value(py, wrapper.as_any(), EmitConfig::default(), Some(true)).unwrap();
            assert_eq!(text, "%YAML 1.2\n---\na: 1\n");
        });
    }

    // --- Item 10: alias to the enclosing anchor. ---

    #[test]
    fn alias_to_enclosing_anchor_is_self_referential() {
        with_python(|py| {
            let (value, _handle) = parse_value(py, "a: &x\n  b: *x\n", true).unwrap();
            let root = value.bind(py).cast::<PyDict>().unwrap();
            let inner = root.get_item("a").unwrap().unwrap();
            let inner_dict = inner.cast::<PyDict>().unwrap();
            let b = inner_dict.get_item("b").unwrap().unwrap();
            assert!(!b.is_none(), "alias to enclosing anchor materialized None");
            assert_eq!(
                b.as_ptr(),
                inner.as_ptr(),
                "alias did not share the anchor object"
            );
        });
    }

    #[test]
    fn regular_block_and_flow_aliases_still_resolve() {
        with_python(|py| {
            let (value, _handle) = parse_value(py, "a: &x 1\nb: *x\n", true).unwrap();
            let root = value.bind(py).cast::<PyDict>().unwrap();
            assert_eq!(
                root.get_item("b")
                    .unwrap()
                    .unwrap()
                    .extract::<i64>()
                    .unwrap(),
                1
            );
            let (value, _handle) = parse_value(py, "items: [&x {k: 1}, *x]\n", true).unwrap();
            let root = value.bind(py).cast::<PyDict>().unwrap();
            let items_value = root.get_item("items").unwrap().unwrap();
            let items = items_value.cast::<PyList>().unwrap();
            let first = items.get_item(0).unwrap();
            let second = items.get_item(1).unwrap();
            assert!(second.is(&first));
        });
    }

    // --- Item 11: untouched timestamps stay byte-identical. ---

    #[test]
    fn unrelated_mutation_keeps_timestamp_text() {
        with_python(|py| {
            let source = "ts: 2001-12-15T02:59:43Z\nother: 1\n";
            let (handle, model) = handle_for(py, source);
            let class = wrapper_class(py);
            let wrapper = class.call0().unwrap();
            let dict = wrapper.cast::<PyDict>().unwrap();
            let datetime = py
                .import("datetime")
                .unwrap()
                .getattr("datetime")
                .unwrap()
                .getattr("fromisoformat")
                .unwrap()
                .call1(("2001-12-15T02:59:43+00:00",))
                .unwrap();
            dict.set_item("ts", datetime).unwrap();
            dict.set_item("other", 2).unwrap();
            wrapper.setattr("_pyy_handle", handle).unwrap();
            wrapper
                .setattr("_pyy_node_id", model.documents[0].root)
                .unwrap();
            wrapper.setattr("_pyy_dirty", true).unwrap();
            let text = dump_value(py, wrapper.as_any(), EmitConfig::default(), None).unwrap();
            assert_eq!(text, "ts: 2001-12-15T02:59:43Z\nother: 2\n");
        });
    }

    #[test]
    fn changed_timestamp_values_are_updated() {
        with_python(|py| {
            let source = "ts: 2001-12-15T02:59:43Z\n";
            let (handle, model) = handle_for(py, source);
            let class = wrapper_class(py);
            let wrapper = class.call0().unwrap();
            let dict = wrapper.cast::<PyDict>().unwrap();
            let datetime = py
                .import("datetime")
                .unwrap()
                .getattr("datetime")
                .unwrap()
                .getattr("fromisoformat")
                .unwrap()
                .call1(("2001-12-15T02:59:44+00:00",))
                .unwrap();
            dict.set_item("ts", datetime).unwrap();
            wrapper.setattr("_pyy_handle", handle).unwrap();
            wrapper
                .setattr("_pyy_node_id", model.documents[0].root)
                .unwrap();
            wrapper.setattr("_pyy_dirty", true).unwrap();
            let text = dump_value(py, wrapper.as_any(), EmitConfig::default(), None).unwrap();
            assert!(text.contains("02:59:44"), "got {text:?}");
        });
    }

    // --- Item 12: unhashable keys are Constructor errors. ---

    #[test]
    fn unhashable_mapping_key_is_a_constructor_error() {
        with_python(|py| {
            let error = parse_value(py, "{[a]: b}\n", true).unwrap_err();
            assert_native_error(&error, 3, "unhashable key");
        });
    }

    #[test]
    fn unhashable_set_member_is_a_constructor_error() {
        with_python(|py| {
            let error = parse_value(py, "!!set {[a]: null}\n", true).unwrap_err();
            assert_native_error(&error, 3, "unhashable key");
        });
    }

    // --- Item 13: constructor errors go through the native funnel. ---

    #[test]
    fn invalid_timestamp_is_a_constructor_error() {
        with_python(|py| {
            let error = parse_value(py, "!!timestamp not-a-date\n", true).unwrap_err();
            assert_native_error(&error, 3, "timestamp");
        });
    }

    #[test]
    fn invalid_binary_is_a_constructor_error() {
        with_python(|py| {
            let error = parse_value(py, "!!binary \"!!!\"\n", true).unwrap_err();
            assert_native_error(&error, 3, "binary");
        });
    }

    #[test]
    fn invalid_float_is_a_constructor_error() {
        with_python(|py| {
            let error = parse_value(py, "!!float not-a-float\n", true).unwrap_err();
            assert_native_error(&error, 3, "float");
        });
    }

    // --- Item 6: patch spans are validated, never panicking. ---

    #[test]
    fn mid_character_patch_span_is_a_serializer_error() {
        with_python(|py| {
            let (handle, model) = handle_for(py, "héllo\n");
            let patches = PyList::new(py, [py.eval(c"[1, 2, 'X']", None, None).unwrap()]).unwrap();
            let none = py.None().into_bound(py);
            let error = dump_value_with_patches(
                py,
                &none,
                EmitConfig::default(),
                None,
                &patches,
                Some(handle.bind(py)),
                Some(model.documents[0].root),
            )
            .unwrap_err();
            assert_native_error(&error, 6, "invalid patch span");
        });
    }

    #[test]
    fn out_of_bounds_and_inverted_patch_spans_are_errors() {
        with_python(|py| {
            let (handle, model) = handle_for(py, "abc\n");
            for patch in [(0usize, 999usize, "X"), (3usize, 1usize, "X")] {
                let triple = format!("[{}, {}, 'X']", patch.0, patch.1);
                let patch_expr = std::ffi::CString::new(triple).unwrap();
                let patches =
                    PyList::new(py, [py.eval(patch_expr.as_c_str(), None, None).unwrap()]).unwrap();
                let none = py.None().into_bound(py);
                let result = dump_value_with_patches(
                    py,
                    &none,
                    EmitConfig::default(),
                    None,
                    &patches,
                    Some(handle.bind(py)),
                    Some(model.documents[0].root),
                );
                let error = result.unwrap_err();
                assert_native_error(&error, 6, "invalid patch span");
            }
        });
    }

    #[test]
    fn negative_patch_offset_is_a_serializer_error() {
        with_python(|py| {
            let (handle, model) = handle_for(py, "abc\n");
            let patch = py.eval(c"[-1, 1, 'X']", None, None).unwrap();
            let patches = PyList::new(py, [patch]).unwrap();
            let none = py.None().into_bound(py);
            let error = dump_value_with_patches(
                py,
                &none,
                EmitConfig::default(),
                None,
                &patches,
                Some(handle.bind(py)),
                Some(model.documents[0].root),
            )
            .unwrap_err();
            assert_native_error(&error, 6, "invalid patch");
        });
    }

    #[test]
    fn valid_patches_still_apply() {
        with_python(|py| {
            let (handle, model) = handle_for(py, "héllo\n");
            let patches = PyList::new(py, [py.eval(c"[0, 1, 'H']", None, None).unwrap()]).unwrap();
            let none = py.None().into_bound(py);
            let text = dump_value_with_patches(
                py,
                &none,
                EmitConfig::default(),
                None,
                &patches,
                Some(handle.bind(py)),
                Some(model.documents[0].root),
            )
            .unwrap();
            assert_eq!(text, "Héllo\n");
        });
    }

    #[test]
    fn python_created_items_are_skipped_instead_of_wholesale_rewrites() {
        with_python(|py| {
            let (handle, model) = handle_for(py, "items:\n  - one\n  - two\nother: x\n");
            let root_id = model.documents[0].root;
            let items_id = mapping_node_id(&model, root_id, "items");
            let item_ids: Vec<i64> = match &model.arena.node(items_id).kind {
                NodeKind::Sequence(items) => items.iter().map(|id| *id as i64).collect(),
                _ => panic!("expected a sequence"),
            };
            // The edited data: the two source items keep their node ids and a
            // third item was appended in Python (id -1). The external patch
            // styles `other`, outside the list.
            let list_class = py.eval(c"type('L', (list,), {})", None, None).unwrap();
            let items = list_class.call0().unwrap();
            for name in ["one", "two", "three"] {
                items.call_method1("append", (name,)).unwrap();
            }
            let mut ids = item_ids.clone();
            ids.push(-1);
            items
                .setattr("_pyy_node_ids", PyList::new(py, ids).unwrap())
                .unwrap();
            items.setattr("_pyy_dirty", true).unwrap();
            let root = wrapper_class(py).call0().unwrap();
            root.set_item("items", &items).unwrap();
            root.set_item("other", "x").unwrap();
            root.setattr("_pyy_dirty", true).unwrap();
            let other_id = mapping_node_id(&model, root_id, "other");
            let span = model.arena.node(other_id).value_span;
            let patch = format!("[{}, {}, '\"x\"']", span.start, span.end);
            let patch_c = std::ffi::CString::new(patch).unwrap();
            let patches =
                PyList::new(py, [py.eval(patch_c.as_c_str(), None, None).unwrap()]).unwrap();
            let text = dump_value_with_patches(
                py,
                &root,
                EmitConfig::default(),
                None,
                &patches,
                Some(handle.bind(py)),
                Some(root_id),
            )
            .unwrap();
            // The appended item is re-inserted by the caller's external patch,
            // so the native side must skip it; a whole-container rewrite here
            // would overlap nothing and duplicate the item.
            assert_eq!(text, "items:\n  - one\n  - two\nother: \"x\"\n");
        });
    }

    #[test]
    fn unknown_node_ids_are_composer_errors() {
        with_python(|py| {
            let (handle, _model) = handle_for(py, "a: 1\n");
            let bound = handle.bind(py);
            let error = bound.borrow().describe(py, 9999).unwrap_err();
            assert_native_error(&error, 2, "unknown node id");
            let error = bound.borrow().document_info(py, 9999).unwrap_err();
            assert_native_error(&error, 2, "unknown document root");
        });
    }
}
