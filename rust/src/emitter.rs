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

use crate::error::{ErrorKind, Result, YamlError};
use crate::model::{NodeKind, ScalarKind, Span};
use crate::parser;
use base64::Engine;
use pyo3::prelude::*;
use pyo3::types::{
    PyAny, PyBool, PyBytes, PyDict, PyFloat, PyInt, PyList, PySet, PyString, PyTuple,
};

#[derive(Clone, Copy, Debug)]
pub struct EmitConfig {
    pub mapping: usize,
    pub sequence: usize,
    pub offset: usize,
    /// Preferred maximum line width. Intentionally unimplemented: wrapping a
    /// long plain scalar would produce folded continuation lines that the
    /// current line-based parser cannot re-read, so the value is accepted
    /// from the Python configuration but ignored until folding support
    /// exists in the parser.
    #[allow(dead_code)]
    pub width: usize,
    /// Request to keep redundant scalar quoting. Unimplemented on this path:
    /// fresh dumps carry no per-value source quoting information, so there is
    /// nothing to preserve; the patch-based path in `py.rs` keeps each
    /// unchanged scalar's original style regardless.
    #[allow(dead_code)]
    pub preserve_quotes: bool,
}

impl Default for EmitConfig {
    fn default() -> Self {
        Self {
            mapping: 2,
            sequence: 2,
            offset: 0,
            width: 80,
            preserve_quotes: true,
        }
    }
}

pub fn emit_documents<'py>(
    py: Python<'py>,
    values: &Bound<'py, PyList>,
    config: EmitConfig,
    explicit_start: Option<bool>,
) -> Result<String> {
    let mut output = String::new();
    for index in 0..values.len() {
        let value = values.get_item(index).map_err(py_error)?;
        if index > 0 || explicit_start == Some(true) {
            output.push_str("---\n");
        }
        output.push_str(&emit_value(py, &value, 0, config)?);
        if !output.ends_with('\n') {
            output.push('\n');
        }
    }
    Ok(output)
}

pub fn emit_single<'py>(
    py: Python<'py>,
    value: &Bound<'py, PyAny>,
    config: EmitConfig,
    explicit_start: Option<bool>,
) -> Result<String> {
    let mut output = String::new();
    if explicit_start == Some(true) {
        output.push_str("---\n");
    }
    output.push_str(&emit_value(py, value, 0, config)?);
    if !output.ends_with('\n') {
        output.push('\n');
    }
    Ok(output)
}

fn emit_value<'py>(
    py: Python<'py>,
    value: &Bound<'py, PyAny>,
    indent: usize,
    config: EmitConfig,
) -> Result<String> {
    if value.is_none() {
        return Ok("null".to_owned());
    }
    if let Ok(boolean) = value.cast::<PyBool>() {
        return Ok(if boolean.is_true() { "true" } else { "false" }.to_owned());
    }
    if let Ok(integer) = value.cast::<PyInt>() {
        return Ok(integer
            .str()
            .map_err(py_error)?
            .to_string_lossy()
            .into_owned());
    }
    if let Ok(float) = value.cast::<PyFloat>() {
        return emit_float(float.value());
    }
    if let Ok(string) = value.cast::<PyString>() {
        return emit_string_scalar(&string.to_string_lossy(), indent + config.mapping, config);
    }
    if let Ok(bytes) = value.cast::<PyBytes>() {
        let encoded = base64::engine::general_purpose::STANDARD.encode(bytes.as_bytes());
        return Ok(format!("!!binary {encoded}"));
    }
    if let Ok(mapping) = value.cast::<PyDict>() {
        return emit_mapping(py, mapping, indent, config);
    }
    if let Ok(list) = value.cast::<PyList>() {
        return emit_sequence(py, list, indent, config);
    }
    if let Ok(tuple) = value.cast::<PyTuple>() {
        return emit_tuple(py, tuple, indent, config);
    }
    if let Ok(set) = value.cast::<PySet>() {
        return emit_set(py, set, indent, config);
    }
    if let Some(decimal) = decimal_text(value) {
        return Ok(decimal);
    }
    if let Some(timestamp) = datetime_value_text(value) {
        return Ok(timestamp);
    }
    if is_tagged(value) {
        let tag = value
            .getattr("tag")
            .map_err(py_error)?
            .extract::<String>()
            .map_err(py_error)?;
        let inner = value.getattr("value").map_err(py_error)?;
        let rendered = emit_value(py, &inner, indent + config.mapping, config)?;
        if rendered.contains('\n') {
            // Multi-line content (block scalars, collections) must continue
            // on its own indented lines; a space join would leave the body at
            // the wrong indentation for anything but top-level nodes.
            return Ok(format!("!<{tag}>\n{rendered}"));
        }
        return Ok(format!("!<{tag}> {rendered}"));
    }
    Err(YamlError::new(
        ErrorKind::Representer,
        format!(
            "cannot represent Python type '{}'",
            value.get_type().name().map_err(py_error)?
        ),
        Span::default(),
    ))
}

fn emit_mapping<'py>(
    py: Python<'py>,
    mapping: &Bound<'py, PyDict>,
    indent: usize,
    config: EmitConfig,
) -> Result<String> {
    if mapping.is_empty() {
        return Ok("{}".to_owned());
    }
    let mut output = String::new();
    for (key, value) in mapping.iter() {
        output.push_str(&" ".repeat(indent));
        output.push_str(&emit_mapping_key(py, &key, config)?);
        output.push(':');
        if value.is_none() {
            output.push('\n');
        } else if let Ok(child) = value.cast::<PyDict>() {
            if child.is_empty() {
                output.push_str(" {}\n");
            } else {
                output.push('\n');
                output.push_str(&emit_mapping(py, child, indent + config.mapping, config)?);
            }
        } else if let Ok(list) = value.cast::<PyList>() {
            if list.is_empty() {
                output.push_str(" []\n");
            } else {
                output.push('\n');
                output.push_str(&emit_sequence(py, list, indent + config.offset, config)?);
            }
        } else {
            let rendered = emit_scalar_inline(py, &value, indent, indent + config.mapping, config)?;
            output.push(' ');
            output.push_str(&rendered);
            // Block scalars with clip/keep chomping end with their own line
            // break; anything else needs the structural break appended.
            if !rendered.ends_with('\n') {
                output.push('\n');
            }
        }
    }
    Ok(output)
}

fn emit_sequence<'py>(
    py: Python<'py>,
    sequence: &Bound<'py, PyList>,
    indent: usize,
    config: EmitConfig,
) -> Result<String> {
    if sequence.is_empty() {
        return Ok("[]".to_owned());
    }
    let mut output = String::new();
    for item in sequence.iter() {
        if let Ok(mapping) = item.cast::<PyDict>() {
            if mapping.is_empty() {
                output.push_str(&" ".repeat(indent));
                output.push_str("- {}\n");
            } else {
                output.push_str(&emit_mapping_in_sequence(py, mapping, indent, config)?);
            }
        } else if let Ok(list) = item.cast::<PyList>() {
            if list.is_empty() {
                output.push_str(&" ".repeat(indent));
                output.push_str("- []\n");
            } else {
                output.push_str(&" ".repeat(indent));
                output.push_str("-\n");
                output.push_str(&emit_sequence(py, list, indent + config.sequence, config)?);
            }
        } else {
            output.push_str(&" ".repeat(indent));
            output.push_str("- ");
            let rendered = emit_scalar_inline(py, &item, indent, indent + config.sequence, config)?;
            output.push_str(&rendered);
            if !rendered.ends_with('\n') {
                output.push('\n');
            }
        }
    }
    Ok(output)
}

fn emit_mapping_in_sequence<'py>(
    py: Python<'py>,
    mapping: &Bound<'py, PyDict>,
    dash_indent: usize,
    config: EmitConfig,
) -> Result<String> {
    let mapping_indent = dash_indent + 2;
    let mut output = String::new();
    let mut first = true;
    for (key, value) in mapping.iter() {
        if first {
            output.push_str(&" ".repeat(dash_indent));
            output.push_str("- ");
            first = false;
        } else {
            output.push_str(&" ".repeat(mapping_indent));
        }
        output.push_str(&emit_mapping_key(py, &key, config)?);
        output.push(':');
        if value.is_none() {
            output.push('\n');
        } else if let Ok(child) = value.cast::<PyDict>() {
            if child.is_empty() {
                output.push_str(" {}\n");
            } else {
                output.push('\n');
                output.push_str(&emit_mapping(
                    py,
                    child,
                    mapping_indent + config.mapping,
                    config,
                )?);
            }
        } else if let Ok(list) = value.cast::<PyList>() {
            if list.is_empty() {
                output.push_str(" []\n");
            } else {
                output.push('\n');
                output.push_str(&emit_sequence(
                    py,
                    list,
                    mapping_indent + config.offset,
                    config,
                )?);
            }
        } else {
            let rendered = emit_scalar_inline(
                py,
                &value,
                mapping_indent,
                mapping_indent + config.mapping,
                config,
            )?;
            output.push(' ');
            output.push_str(&rendered);
            if !rendered.ends_with('\n') {
                output.push('\n');
            }
        }
    }
    Ok(output)
}

fn emit_tuple<'py>(
    py: Python<'py>,
    value: &Bound<'py, PyTuple>,
    indent: usize,
    config: EmitConfig,
) -> Result<String> {
    let list = PyList::new(py, value.iter()).map_err(py_error)?;
    emit_sequence(py, &list, indent, config)
}

fn emit_set<'py>(
    py: Python<'py>,
    value: &Bound<'py, PySet>,
    indent: usize,
    config: EmitConfig,
) -> Result<String> {
    if value.is_empty() {
        return Ok("!!set {}".to_owned());
    }
    let member_indent = indent + config.mapping;
    let mut output = String::from("!!set\n");
    for item in value.iter() {
        output.push_str(&" ".repeat(member_indent));
        if let Ok(string) = item.cast::<PyString>() {
            let text = string.to_string_lossy();
            // A block scalar body cannot share its line with ": null", so
            // multi-line set members are double-quoted instead.
            if text.contains('\n') {
                output.push_str(&format!("\"{}\"", escape_double_quotes(&text)));
            } else {
                output.push_str(&quote_string(&text));
            }
        } else {
            output.push_str(&emit_scalar_inline(
                py,
                &item,
                member_indent,
                member_indent + config.mapping,
                config,
            )?);
        }
        output.push_str(": null\n");
    }
    Ok(output)
}

/// Renders a value in a `key: value` / `- value` position. `indent` is the
/// structural column of the parent key or dash (used by nested collections
/// such as sets) and `continuation` is the column any block-scalar body must
/// use so it stays deeper than the parent.
fn emit_scalar_inline<'py>(
    py: Python<'py>,
    value: &Bound<'py, PyAny>,
    indent: usize,
    continuation: usize,
    config: EmitConfig,
) -> Result<String> {
    if value.is_none() {
        return Ok("null".to_owned());
    }
    if let Ok(boolean) = value.cast::<PyBool>() {
        return Ok(if boolean.is_true() { "true" } else { "false" }.to_owned());
    }
    if let Ok(integer) = value.cast::<PyInt>() {
        return Ok(integer
            .str()
            .map_err(py_error)?
            .to_string_lossy()
            .into_owned());
    }
    if let Ok(float) = value.cast::<PyFloat>() {
        return emit_float(float.value());
    }
    if let Ok(string) = value.cast::<PyString>() {
        return emit_string_scalar(&string.to_string_lossy(), continuation, config);
    }
    if let Ok(bytes) = value.cast::<PyBytes>() {
        let encoded = base64::engine::general_purpose::STANDARD.encode(bytes.as_bytes());
        return Ok(format!("!!binary {encoded}"));
    }
    if let Some(decimal) = decimal_text(value) {
        return Ok(decimal);
    }
    if let Ok(set) = value.cast::<PySet>() {
        // `emit_set` output is complete (each member line ends with its own
        // break), so callers must not append another structural break.
        return emit_set(py, set, indent, config);
    }
    if let Some(timestamp) = datetime_value_text(value) {
        return Ok(timestamp);
    }
    // Tagged and other collection-like values continue from the structural
    // indent as well.
    emit_value(py, value, indent, config)
}

fn emit_string_scalar(value: &str, indent: usize, _config: EmitConfig) -> Result<String> {
    if value.contains('\n')
        && !value
            .chars()
            .any(|ch| ch != '\n' && ((ch as u32) < 0x20 || ch as u32 == 0x7f))
    {
        return Ok(render_literal_block(value, indent));
    }
    Ok(quote_string(value))
}

/// Renders a literal (`|`) block scalar whose chomping indicator is derived
/// from the value's trailing newlines: none -> strip (`|-`), exactly one ->
/// clip (`|`), more than one -> keep (`|+`). The returned text is complete:
/// every line (including the blank lines keep chomping needs) ends with its
/// own line break, so callers append a structural break only when the text
/// does not already end with one.
fn render_literal_block(value: &str, indent: usize) -> String {
    let content = value.trim_end_matches('\n');
    let trailing = value.len() - content.len();
    let mut body_lines: Vec<&str> = content.split('\n').collect();
    if trailing > 1 {
        // Keep chomping must reproduce every trailing break beyond the one
        // that terminates the last content line.
        body_lines.extend(std::iter::repeat_n("", trailing - 1));
    }
    let mut output = String::from("|");
    match trailing {
        0 => output.push('-'),
        1 => {}
        _ => output.push('+'),
    }
    output.push('\n');
    for line in body_lines {
        if !line.is_empty() {
            output.push_str(&" ".repeat(indent));
            output.push_str(line);
        }
        output.push('\n');
    }
    if trailing == 0 {
        // Strip chomping removes the break that would terminate the last
        // line; clip/keep keep every break.
        output.pop();
    }
    output
}

fn emit_mapping_key<'py>(
    py: Python<'py>,
    value: &Bound<'py, PyAny>,
    config: EmitConfig,
) -> Result<String> {
    let _ = py;
    if value.is_none() {
        return Ok("null".to_owned());
    }
    if let Ok(string) = value.cast::<PyString>() {
        return Ok(quote_string(&string.to_string_lossy()));
    }
    if let Ok(boolean) = value.cast::<PyBool>() {
        return Ok(if boolean.is_true() { "true" } else { "false" }.to_owned());
    }
    if let Ok(integer) = value.cast::<PyInt>() {
        return Ok(integer
            .str()
            .map_err(py_error)?
            .to_string_lossy()
            .into_owned());
    }
    if let Ok(float) = value.cast::<PyFloat>() {
        return emit_float(float.value());
    }
    if let Some(decimal) = decimal_text(value) {
        return Ok(decimal);
    }
    if let Some(timestamp) = datetime_key_text(value) {
        return Ok(timestamp);
    }
    let _ = config;
    Err(YamlError::new(
        ErrorKind::Serializer,
        format!(
            "mapping keys of type '{}' are not supported",
            value.get_type().name().map_err(py_error)?.to_string_lossy()
        ),
        Span::default(),
    ))
}

/// A `datetime.datetime` / `datetime.date` value emits like PyYAML: the
/// `str()` spelling, which is a valid YAML timestamp that reloads as an equal
/// value.
fn datetime_value_text(value: &Bound<'_, PyAny>) -> Option<String> {
    datetime_module_text(value, false)
}

/// A `datetime.datetime` / `datetime.date` mapping key emits as a plain YAML
/// timestamp so it reloads as an equal key.
fn datetime_key_text(value: &Bound<'_, PyAny>) -> Option<String> {
    datetime_module_text(value, true)
}

fn datetime_module_text(value: &Bound<'_, PyAny>, isoformat: bool) -> Option<String> {
    // Accept subclasses too (the round-trip scalar wrappers): a datetime is
    // also an instance of date, so the datetime check must come first.
    let is_datetime = is_instance_of_module_class(value, "datetime", "datetime");
    let is_date = !is_datetime && is_instance_of_module_class(value, "datetime", "date");
    if !is_datetime && !is_date {
        return None;
    }
    let text = if isoformat {
        value
            .getattr("isoformat")
            .ok()?
            .call0()
            .ok()?
            .extract::<String>()
            .ok()?
    } else {
        value.str().ok()?.to_string_lossy().into_owned()
    };
    // Only emit unquoted when the parser reads the text back as a timestamp;
    // otherwise fall through to the ordinary (error/quoted) handling.
    parser::parse_timestamp(&text).map(|_| text)
}

/// Whether ``value`` is an instance of ``module.class`` (subclasses count).
fn is_instance_of_module_class(value: &Bound<'_, PyAny>, module: &str, class: &str) -> bool {
    let Ok(module_object) = value.py().import(module) else {
        return false;
    };
    let Ok(class_object) = module_object.getattr(class) else {
        return false;
    };
    value.is_instance(&class_object).unwrap_or(false)
}

fn quote_string(value: &str) -> String {
    if can_plain(value) {
        value.to_owned()
    } else if value
        .chars()
        .any(|ch| (ch as u32) < 0x20 || ch as u32 == 0x7f)
    {
        // Control characters (tabs, newlines, C0) cannot live in a
        // single-quoted scalar; PyYAML switches to double-quoted style.
        format!("\"{}\"", escape_double_quotes(value))
    } else {
        format!("'{}'", value.replace('\'', "''"))
    }
}

/// True when `value` can be emitted as a plain (unquoted) scalar and re-read
/// as the same string: the character rules below plus a resolution check that
/// runs the parser's own plain-scalar resolver on the candidate text, so any
/// spelling that would come back as bool/int/float/null/timestamp is quoted.
fn can_plain(value: &str) -> bool {
    if value.is_empty() || value.trim() != value {
        return false;
    }
    if value
        .chars()
        .any(|ch| ch == '\n' || ch == '\r' || (ch as u32) < 0x20 || ch as u32 == 0x7f)
    {
        return false;
    }
    if value.contains(": ") || value.contains(" #") || value.ends_with(':') {
        return false;
    }
    if value.starts_with([
        '-', '?', ':', ',', '[', ']', '{', '}', '#', '&', '*', '!', '|', '>', '\'', '"', '%', '@',
        '`',
    ]) {
        return false;
    }
    !plain_scalar_resolves_away(value)
}

/// Re-parses the candidate as a standalone document so the decision reuses
/// the parser's plain-scalar resolver verbatim instead of duplicating it.
/// Anything that does not come back as a plain string scalar (or that the
/// parser would reject, fold into a collection, or treat as a document
/// marker) must be quoted.
fn plain_scalar_resolves_away(value: &str) -> bool {
    let Ok(document) = parser::parse(&format!("{value}\n")) else {
        return true;
    };
    let Some(doc) = document.documents.first() else {
        return true;
    };
    match &document.arena.node(doc.root).kind {
        NodeKind::Scalar(scalar) => scalar.kind != ScalarKind::Str,
        _ => true,
    }
}

fn escape_double_quotes(value: &str) -> String {
    let mut output = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            '\\' => output.push_str("\\\\"),
            '"' => output.push_str("\\\""),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            '\0' => output.push_str("\\0"),
            '\x07' => output.push_str("\\a"),
            '\x08' => output.push_str("\\b"),
            '\x0b' => output.push_str("\\v"),
            '\x0c' => output.push_str("\\f"),
            '\x1b' => output.push_str("\\e"),
            ch if (ch as u32) < 0x20 || ch as u32 == 0x7f => {
                output.push_str(&format!("\\x{:02X}", ch as u32));
            }
            ch => output.push(ch),
        }
    }
    output
}

fn emit_float(value: f64) -> Result<String> {
    if value.is_nan() {
        return Ok(".nan".to_owned());
    }
    if value == f64::INFINITY {
        return Ok(".inf".to_owned());
    }
    if value == f64::NEG_INFINITY {
        return Ok("-.inf".to_owned());
    }
    Ok(format_float(value))
}

/// PyYAML's float representer: the shortest round-trip digits, always with a
/// "." or an exponent so the scalar reloads as a float. Exponent form is used
/// when the decimal exponent is < -4 or >= 16, exactly like Python's `repr`,
/// with a sign and at least two exponent digits (`1.0e+300`, `1.5e-05`).
fn format_float(value: f64) -> String {
    let scientific = format!("{value:e}");
    let Some((mantissa, exponent)) = scientific.split_once('e') else {
        return scientific;
    };
    let exponent: i32 = exponent.parse().unwrap_or(0);
    if !(-4..16).contains(&exponent) {
        let mantissa = if mantissa.contains('.') {
            mantissa.to_owned()
        } else {
            format!("{mantissa}.0")
        };
        let sign = if exponent < 0 { '-' } else { '+' };
        format!("{mantissa}e{sign}{:02}", exponent.abs())
    } else {
        let mut fixed = value.to_string();
        if !fixed.contains('.') {
            fixed.push_str(".0");
        }
        fixed
    }
}

fn decimal_text(value: &Bound<'_, PyAny>) -> Option<String> {
    if !is_instance_of_module_class(value, "decimal", "Decimal") {
        return None;
    }
    value
        .str()
        .ok()
        .map(|value| value.to_string_lossy().into_owned())
}

fn is_tagged(value: &Bound<'_, PyAny>) -> bool {
    let Ok(module) = value.get_type().module() else {
        return false;
    };
    let Ok(name) = value.get_type().name() else {
        return false;
    };
    module.to_string_lossy() == "pythonizeyaml.tagged" && name.to_string_lossy() == "Tagged"
}

fn py_error(error: PyErr) -> YamlError {
    YamlError::new(ErrorKind::Emitter, error.to_string(), Span::default())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn with_python<R>(f: impl FnOnce(Python<'_>) -> R) -> R {
        Python::initialize();
        Python::try_attach(f).expect("python interpreter should be available in tests")
    }

    // --- Item 1: PyYAML float repr rules. ---

    #[test]
    fn floats_use_the_pyyaml_repr_rules() {
        let cases: &[(f64, &str)] = &[
            (1.0, "1.0"),
            (0.0, "0.0"),
            (-0.0, "-0.0"),
            (-1.5, "-1.5"),
            (0.1, "0.1"),
            (0.5, "0.5"),
            (1e-4, "0.0001"),
            (1e-5, "1.0e-05"),
            (5e-5, "5.0e-05"),
            (1.5e-5, "1.5e-05"),
            (1.5e-300, "1.5e-300"),
            (5e-324, "5.0e-324"),
            (1e15, "1000000000000000.0"),
            (9999999999999998.0, "9999999999999998.0"),
            (123456789012345.0, "123456789012345.0"),
            (1e16, "1.0e+16"),
            (1.2345678901234568e18, "1.2345678901234568e+18"),
            (1e300, "1.0e+300"),
            (f64::MAX, "1.7976931348623157e+308"),
        ];
        for (value, expected) in cases {
            assert_eq!(&format_float(*value), expected, "for {value}");
        }
    }

    #[test]
    fn nonfinite_floats_use_yaml_spellings() {
        assert_eq!(emit_float(f64::NAN).unwrap(), ".nan");
        assert_eq!(emit_float(f64::INFINITY).unwrap(), ".inf");
        assert_eq!(emit_float(f64::NEG_INFINITY).unwrap(), "-.inf");
    }

    #[test]
    fn dumped_floats_reload_as_floats_with_equal_value() {
        with_python(|py| {
            // Exactly-representable values so the parser's exact resolver
            // keeps them in the float type (inexact spellings widen to
            // Decimal by design).
            for value in [1.0, 0.5, 12345.0, 1e16, -3.75, 9007199254740992.0] {
                let text = emit_value(
                    py,
                    PyFloat::new(py, value).as_any(),
                    0,
                    EmitConfig::default(),
                )
                .unwrap();
                let document = parser::parse(&format!("{text}\n")).unwrap();
                let root = document.documents[0].root;
                let NodeKind::Scalar(scalar) = &document.arena.node(root).kind else {
                    panic!("expected a scalar for {text}");
                };
                assert_eq!(scalar.kind, ScalarKind::Float, "for {text}");
                let reloaded: f64 = scalar.value.parse().unwrap();
                assert_eq!(reloaded, value, "for {text}");
            }
        });
    }

    // --- Item 2: plain-scalar safety. ---

    #[test]
    fn resolver_ambiguous_strings_are_not_plain() {
        for value in [
            "yes",
            "123",
            "0x1F",
            "1_000",
            "abc:",
            "+.inf",
            "2001-12-15",
            "1:30",
            "null",
            "~",
            "TRUE",
            "off",
            "052",
            "1.5",
            "1.0e+400",
            "2001-12-15T02:59:43",
            "...",
            "---",
        ] {
            assert!(!can_plain(value), "{value} must be quoted");
        }
    }

    #[test]
    fn ordinary_strings_stay_plain() {
        for value in [
            "hello world",
            "x:y",
            "hello#world",
            "a-b",
            "y",
            "n",
            "1e5",
            "09:00",
            "a:b:c",
            "value_1",
            "École",
        ] {
            assert!(can_plain(value), "{value} should stay plain");
        }
    }

    #[test]
    fn character_rules_force_quoting() {
        for value in [
            "", " lead", "trail ", "a: b", "a #c", "- x", "?", ":x", ",x", "[x", "]x", "{x", "}x",
            "#x", "&x", "*x", "!x", "|x", ">x", "'x", "\"x", "%x", "@x", "`x", "a\tb",
        ] {
            assert!(!can_plain(value), "{value:?} must be quoted");
        }
    }

    #[test]
    fn ambiguous_strings_use_pyyaml_single_quote_style() {
        assert_eq!(quote_string("yes"), "'yes'");
        // A leading quote character triggers the doubled-quote escape.
        assert_eq!(quote_string("'x"), "'''x'");
        assert_eq!(quote_string("hello world"), "hello world");
        // Control characters switch to double-quoted style with escapes.
        assert_eq!(quote_string("a\tb"), "\"a\\tb\"");
        assert_eq!(quote_string("a\nb"), "\"a\\nb\"");
    }

    // --- Item 3: literal block chomping. ---

    #[test]
    fn literal_block_chomping_is_derived_from_the_value() {
        let cases: &[(&str, &str)] = &[
            ("a", "|-\n  a"),
            ("a\n", "|\n  a\n"),
            ("a\n\n\n", "|+\n  a\n\n\n"),
            ("a\nb", "|-\n  a\n  b"),
            ("a\nb\n", "|\n  a\n  b\n"),
            ("a\nb\n\n", "|+\n  a\n  b\n\n"),
            ("\n\n", "|+\n\n\n"),
            ("a\n\n", "|+\n  a\n\n"),
        ];
        for (value, expected) in cases {
            assert_eq!(&render_literal_block(value, 2), expected, "for {value:?}");
        }
    }

    #[test]
    fn literal_blocks_leave_no_trailing_space_lines() {
        for value in ["a\nb", "a\nb\n", "a\nb\n\n", "\n\n", "a\n\nb"] {
            let rendered = render_literal_block(value, 4);
            for line in rendered.lines() {
                assert!(
                    !line.ends_with(' '),
                    "trailing space in {rendered:?} for {value:?}"
                );
            }
        }
    }

    #[test]
    fn block_scalars_round_trips_through_the_parser() {
        for value in ["a\n", "a", "a\n\n\n", "a\nb", "a\nb\n", "a\nb\n\n", "\n\n"] {
            let rendered = emit_string_scalar(value, 2, EmitConfig::default()).unwrap();
            // Mirror the emitter's conditional structural break.
            let mut source = format!("k: {rendered}");
            if !rendered.ends_with('\n') {
                source.push('\n');
            }
            let document = parser::parse(&source).unwrap();
            let root = document.documents[0].root;
            let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
                panic!("expected a mapping for {source:?}");
            };
            let NodeKind::Scalar(scalar) = &document.arena.node(entries[0].value).kind else {
                panic!("expected a scalar for {source:?}");
            };
            assert_eq!(scalar.value, value, "round trip failed for {value:?}");
        }
    }

    // --- Item 4: nested block scalars and sets are indent-aware. ---

    #[test]
    fn nested_block_scalar_bodies_are_indented() {
        with_python(|py| {
            let outer = PyDict::new(py);
            let inner = PyDict::new(py);
            inner.set_item("key", "a\nb").unwrap();
            outer.set_item("outer", inner).unwrap();
            let text = emit_value(py, outer.as_any(), 0, EmitConfig::default()).unwrap();
            assert_eq!(text, "outer:\n  key: |-\n    a\n    b\n");
            let document = parser::parse(&text).unwrap();
            let root = document.documents[0].root;
            let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
                panic!("expected a mapping");
            };
            let NodeKind::Mapping(inner_entries) = &document.arena.node(entries[0].value).kind
            else {
                panic!("expected a nested mapping");
            };
            let NodeKind::Scalar(scalar) = &document.arena.node(inner_entries[0].value).kind else {
                panic!("expected a scalar");
            };
            assert_eq!(scalar.value, "a\nb");
        });
    }

    #[test]
    fn block_scalar_in_sequence_mapping_is_indented() {
        with_python(|py| {
            let inner = PyDict::new(py);
            inner.set_item("k", "a\nb").unwrap();
            let list = PyList::new(py, [inner]).unwrap();
            let text = emit_value(py, list.as_any(), 0, EmitConfig::default()).unwrap();
            assert_eq!(text, "- k: |-\n    a\n    b\n");
            let document = parser::parse(&text).unwrap();
            let root = document.documents[0].root;
            let NodeKind::Sequence(items) = &document.arena.node(root).kind else {
                panic!("expected a sequence");
            };
            let NodeKind::Mapping(entries) = &document.arena.node(items[0]).kind else {
                panic!("expected a mapping item");
            };
            let NodeKind::Scalar(scalar) = &document.arena.node(entries[0].value).kind else {
                panic!("expected a scalar");
            };
            assert_eq!(scalar.value, "a\nb");
        });
    }

    #[test]
    fn block_scalar_in_a_nested_sequence_is_indented() {
        with_python(|py| {
            let inner_list = PyList::new(py, ["a\nb"]).unwrap();
            let outer_list = PyList::new(py, [inner_list]).unwrap();
            let text = emit_value(py, outer_list.as_any(), 0, EmitConfig::default()).unwrap();
            assert_eq!(text, "-\n  - |-\n    a\n    b\n");
            let document = parser::parse(&text).unwrap();
            let root = document.documents[0].root;
            let NodeKind::Sequence(items) = &document.arena.node(root).kind else {
                panic!("expected a sequence");
            };
            let NodeKind::Sequence(inner) = &document.arena.node(items[0]).kind else {
                panic!("expected a nested sequence");
            };
            let NodeKind::Scalar(scalar) = &document.arena.node(inner[0]).kind else {
                panic!("expected a scalar");
            };
            assert_eq!(scalar.value, "a\nb");
        });
    }

    #[test]
    fn sets_are_indent_aware() {
        with_python(|py| {
            let set = PySet::empty(py).unwrap();
            set.add(1).unwrap();
            set.add(2).unwrap();
            let text = emit_set(py, &set, 4, EmitConfig::default()).unwrap();
            assert!(text.starts_with("!!set\n    "), "got {text:?}");
            assert!(text.contains("    1: null\n"));
            assert!(text.contains("    2: null\n"));
        });
    }

    #[test]
    fn nested_sets_stay_indented_under_their_key() {
        with_python(|py| {
            let set = PySet::empty(py).unwrap();
            set.add(1).unwrap();
            let outer = PyDict::new(py);
            outer.set_item("s", set).unwrap();
            let text = emit_value(py, outer.as_any(), 2, EmitConfig::default()).unwrap();
            assert_eq!(text, "  s: !!set\n    1: null\n");
            // Embedded under a root key the fragment must re-parse.
            let document = format!("outer:\n{text}");
            assert!(parser::parse(&document).is_ok());
        });
    }

    // --- Item 5: mapping key types. ---

    #[test]
    fn mapping_keys_support_float_none_and_datetime() {
        with_python(|py| {
            let config = EmitConfig::default();
            assert_eq!(
                emit_mapping_key(py, PyFloat::new(py, 1.5).as_any(), config).unwrap(),
                "1.5"
            );
            let none = py.None().into_bound(py);
            assert_eq!(emit_mapping_key(py, &none, config).unwrap(), "null");
            let datetime = py
                .import("datetime")
                .unwrap()
                .getattr("datetime")
                .unwrap()
                .call1((2001, 12, 15, 2, 59, 43))
                .unwrap();
            assert_eq!(
                emit_mapping_key(py, datetime.as_any(), config).unwrap(),
                "2001-12-15T02:59:43"
            );
            // A float key round-trips as a float, not a string.
            let text = emit_mapping_key(py, PyFloat::new(py, 1.5).as_any(), config).unwrap();
            let document = parser::parse(&format!("{text}: v\n")).unwrap();
            let root = document.documents[0].root;
            let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
                panic!("expected a mapping");
            };
            let NodeKind::Scalar(scalar) = &document.arena.node(entries[0].key).kind else {
                panic!("expected a scalar key");
            };
            assert_eq!(scalar.kind, ScalarKind::Float);
        });
    }

    #[test]
    fn unsupported_mapping_keys_raise_a_serializer_error() {
        with_python(|py| {
            let config = EmitConfig::default();
            let list_key = PyList::empty(py);
            let error = emit_mapping_key(py, list_key.as_any(), config).unwrap_err();
            assert_eq!(error.kind, ErrorKind::Serializer);
            assert!(error.problem.contains("mapping keys of type 'list'"));
            let dict_key = PyDict::new(py);
            let error = emit_mapping_key(py, dict_key.as_any(), config).unwrap_err();
            assert_eq!(error.kind, ErrorKind::Serializer);
        });
    }

    #[test]
    fn float_keys_reload_as_float_keys() {
        with_python(|py| {
            let mapping = PyDict::new(py);
            mapping.set_item(1.5, "v").unwrap();
            let text = emit_value(py, mapping.as_any(), 0, EmitConfig::default()).unwrap();
            assert_eq!(text, "1.5: v\n");
        });
    }
}
