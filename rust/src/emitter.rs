use crate::error::{ErrorKind, Result, YamlError};
use crate::model::Span;
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
    pub width: usize,
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
        return emit_string_scalar(&string.to_string_lossy(), indent, config);
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
    if is_tagged(value) {
        let tag = value
            .getattr("tag")
            .map_err(py_error)?
            .extract::<String>()
            .map_err(py_error)?;
        let inner = value.getattr("value").map_err(py_error)?;
        let rendered = emit_value(py, &inner, indent, config)?;
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
            output.push(' ');
            output.push_str(&emit_scalar_inline(py, &value, config)?);
            output.push('\n');
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
            output.push_str(&emit_scalar_inline(py, &item, config)?);
            output.push('\n');
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
            output.push(' ');
            output.push_str(&emit_scalar_inline(py, &value, config)?);
            output.push('\n');
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
    let mut output = String::from("!!set\n");
    for item in value.iter() {
        output.push_str(&" ".repeat(indent + config.mapping));
        output.push_str(&emit_scalar_inline(py, &item, config)?);
        output.push_str(": null\n");
    }
    Ok(output)
}

fn emit_scalar_inline<'py>(
    py: Python<'py>,
    value: &Bound<'py, PyAny>,
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
        return emit_string_scalar(&string.to_string_lossy(), 0, config);
    }
    if let Some(decimal) = decimal_text(value) {
        return Ok(decimal);
    }
    if is_tagged(value) {
        return emit_value(py, value, 0, config);
    }
    emit_value(py, value, 0, config)
}

fn emit_string_scalar(value: &str, indent: usize, _config: EmitConfig) -> Result<String> {
    if value.contains('\n') {
        let mut out = String::from("|-\n");
        for line in value.split('\n') {
            out.push_str(&" ".repeat(indent + 2));
            out.push_str(line);
            out.push('\n');
        }
        while out.ends_with('\n') {
            out.pop();
        }
        return Ok(out);
    }
    Ok(quote_string(value))
}

fn emit_mapping_key<'py>(
    py: Python<'py>,
    value: &Bound<'py, PyAny>,
    config: EmitConfig,
) -> Result<String> {
    let _ = (py, config);
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
    Ok(format!(
        "'{}'",
        value
            .str()
            .map_err(py_error)?
            .to_string_lossy()
            .replace('\'', "''")
    ))
}

fn quote_string(value: &str) -> String {
    if can_plain(value) {
        value.to_owned()
    } else {
        format!("'{}'", value.replace('\'', "''"))
    }
}

fn can_plain(value: &str) -> bool {
    if value.is_empty() || value.trim() != value {
        return false;
    }
    if value
        .chars()
        .any(|ch| ch == '\n' || ch == '\r' || ch == '\t')
    {
        return false;
    }
    if value.contains(": ") || value.contains(" #") {
        return false;
    }
    if value.starts_with([
        '-', '?', ':', ',', '[', ']', '{', '}', '#', '&', '*', '!', '|', '>', '\'', '"', '%', '@',
    ]) {
        return false;
    }
    let lower = value.to_ascii_lowercase();
    if matches!(
        lower.as_str(),
        "null" | "true" | "false" | "~" | ".inf" | ".nan"
    ) {
        return false;
    }
    if lower.parse::<i64>().is_ok() || lower.parse::<f64>().is_ok() {
        return false;
    }
    true
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
    Ok(value.to_string())
}

fn decimal_text(value: &Bound<'_, PyAny>) -> Option<String> {
    let module = value
        .get_type()
        .module()
        .ok()?
        .to_string_lossy()
        .into_owned();
    let name = value.get_type().name().ok()?.to_string_lossy().into_owned();
    if module == "decimal" && name == "Decimal" {
        value
            .str()
            .ok()
            .map(|value| value.to_string_lossy().into_owned())
    } else {
        None
    }
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
