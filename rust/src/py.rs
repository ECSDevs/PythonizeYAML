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
        &handle.bind(py).as_any(),
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
            &handle.bind(py).as_any(),
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
        NodeKind::Scalar(scalar) => materialize_scalar(py, scalar),
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
        if seen
            .iter()
            .any(|existing| existing.bind(py).eq(&key.bind(py)).unwrap_or(false))
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
    py: Python<'py>,
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
            merge_mapping(py, target, &item, metadata)?;
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
        if let Some(mapping) = item.cast::<PyDict>().ok() {
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
    let inner = match &node.kind {
        NodeKind::Tagged { value, .. } => *value,
        _ => node_id,
    };
    materialize_node(py, document, inner, handle, safe, memo)
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
        set.add(value.bind(py))?;
        metadata.set_item(value.bind(py), *item)?;
    }
    if !safe {
        container.setattr("_pyy_node_ids", metadata)?;
    }
    Ok(container.unbind())
}

fn materialize_scalar(py: Python<'_>, scalar: &Scalar) -> PyResult<Py<PyAny>> {
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
                value => value
                    .parse::<f64>()
                    .map_err(|_| PyValueError::new_err("invalid float"))?,
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
                .map_err(|_| PyValueError::new_err("invalid !!binary value"))?;
            Ok(PyBytes::new(py, &decoded).into_any().unbind())
        }
        ScalarKind::Timestamp => {
            let text = scalar.value.trim();
            let module = py.import("datetime")?;
            let value = if text.contains(' ') || text.contains('T') {
                module
                    .getattr("datetime")?
                    .call_method1("fromisoformat", (text,))?
            } else {
                module
                    .getattr("date")?
                    .call_method1("fromisoformat", (text,))?
            };
            Ok(value.unbind())
        }
    }
}

pub fn dump_value(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    config: EmitConfig,
    explicit_start: Option<bool>,
) -> PyResult<String> {
    let handle = value.getattr("_pyy_handle").ok();
    let node_id = value
        .getattr("_pyy_node_id")
        .ok()
        .and_then(|item| item.extract::<i64>().ok())
        .unwrap_or(-1);
    if let Some(handle) = handle {
        let document = handle.cast::<NativeDocument>()?;
        let native = document.borrow();
        if !has_dirty(value)? && native.inner.documents.len() == 1 {
            let mut text = native.inner.text.clone();
            if explicit_start == Some(true) && !text.trim_start().starts_with("---") {
                text.insert_str(0, "---\n");
            } else if explicit_start == Some(false) && text.trim_start().starts_with("---") {
                text = remove_explicit_start(&text);
            }
            return Ok(text);
        }
        if !has_dirty(value)? {
            return Ok(native.inner.text.clone());
        }
        let mut edits = Vec::new();
        collect_edits(
            py,
            value,
            &native.inner,
            node_id as usize,
            config,
            false,
            &mut edits,
        )?;
        return apply_edits(&native.inner.text, edits);
    }
    emit_single(py, value, config, explicit_start).map_err(native_error)
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
            if !scalar_matches_py(value, scalar)? {
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
            let ids = wrapper_node_ids(value, "_pyy_node_ids", list.len());
            if ids.len() != items.len() {
                if suppress_structural {
                    for (index, child_id) in items.iter().enumerate().take(list.len()) {
                        let child = list.get_item(index)?;
                        collect_edits(py, &child, document, *child_id, config, true, edits)?;
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
                        let Some(key) =
                            find_python_key(py, mapping, &document.arena.node(entry.key).kind)?
                        else {
                            continue;
                        };
                        let child = mapping
                            .get_item(&key)?
                            .ok_or_else(|| PyValueError::new_err("mapping key disappeared"))?;
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
                let Some(key) = find_python_key(py, mapping, &document.arena.node(entry.key).kind)?
                else {
                    edits.push((
                        node.span,
                        canonical_edit(py, value, config, node_base_indent(document, node.span))?,
                    ));
                    return Ok(());
                };
                let child = mapping
                    .get_item(&key)?
                    .ok_or_else(|| PyValueError::new_err("mapping key disappeared"))?;
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

fn scalar_matches_py(value: &Bound<'_, PyAny>, scalar: &Scalar) -> PyResult<bool> {
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
        ScalarKind::Timestamp => Ok(value
            .str()?
            .to_string_lossy()
            .starts_with(scalar.value.trim())),
    }
}

fn find_python_key<'py>(
    py: Python<'py>,
    mapping: &Bound<'py, PyDict>,
    key_kind: &NodeKind,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    if let NodeKind::Scalar(scalar) = key_kind {
        if let Ok(expected) = materialize_scalar(py, scalar) {
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
fn apply_edits(source: &str, mut edits: Vec<(Span, String)>) -> PyResult<String> {
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

fn remove_explicit_start(source: &str) -> String {
    let mut lines = source.split_inclusive('\n');
    let Some(first) = lines.next() else {
        return source.to_owned();
    };
    if first.trim_end().starts_with("---") {
        lines.collect()
    } else {
        source.to_owned()
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
    let mut result = EmitConfig::default();
    result.mapping = config.getattr("mapping").and_then(|v| v.extract())?;
    result.sequence = config.getattr("sequence").and_then(|v| v.extract())?;
    result.offset = config.getattr("offset").and_then(|v| v.extract())?;
    result.width = config.getattr("width").and_then(|v| v.extract())?;
    result.preserve_quotes = config
        .getattr("preserve_quotes")
        .and_then(|v| v.extract())?;
    Ok(result)
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
            .ok_or_else(|| PyValueError::new_err("unknown document root"))?;
        let info = PyDict::new(py);
        info.set_item("root_id", document.root)?;
        info.set_item("span", (document.span.start, document.span.end))?;
        info.set_item("explicit_start", document.explicit_start)?;
        info.set_item("explicit_end", document.explicit_end)?;
        info.set_item("directives", document.directives.clone())?;
        Ok(info.unbind())
    }

    fn describe(&self, py: Python<'_>, node_id: usize) -> PyResult<Py<PyDict>> {
        let node = self
            .inner
            .arena
            .nodes
            .get(node_id)
            .ok_or_else(|| PyValueError::new_err("unknown node id"))?;
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
                    &self.inner.text[node.value_span.range()].trim_start_matches('*'),
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
    if node.tag.is_none() {
        return None;
    }
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
    let inferred_handle = value.getattr("_pyy_handle").ok();
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
        let mut data_edits = Vec::new();
        if has_dirty(value)? {
            collect_edits(
                py,
                value,
                &native.inner,
                node_id as usize,
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
        if explicit_start == Some(true) && !text.trim_start().starts_with("---") {
            text.insert_str(0, "---\n");
        } else if explicit_start == Some(false) && text.trim_start().starts_with("---") {
            text = remove_explicit_start(&text);
        }
        return Ok(text);
    }
    let base = emit_single(py, value, config, explicit_start).map_err(native_error)?;
    apply_edits(&base, external)
}

fn parse_patch_list(patches: &Bound<'_, PyList>) -> PyResult<Vec<(Span, String)>> {
    let mut result = Vec::with_capacity(patches.len());
    for patch in patches.iter() {
        let start = patch.get_item(0)?.extract::<usize>()?;
        let end = patch.get_item(1)?.extract::<usize>()?;
        let text = patch.get_item(2)?.extract::<String>()?;
        result.push((Span::new(start, end), text));
    }
    Ok(result)
}

fn spans_overlap(left: Span, right: Span) -> bool {
    left.start < right.end && right.start < left.end
}
