mod emitter;
mod error;
mod model;
mod number;
mod parser;
mod py;

use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyList, PyModule};

create_exception!(_native, NativeYamlError, PyException);

#[pyfunction]
#[pyo3(signature = (text, safe=false))]
fn parse(text: &str, safe: bool, py: Python<'_>) -> PyResult<(Py<PyAny>, Py<py::NativeDocument>)> {
    py::parse_value(py, text, safe)
}

#[pyfunction]
#[pyo3(signature = (text, safe=false))]
fn parse_all(
    text: &str,
    safe: bool,
    py: Python<'_>,
) -> PyResult<(Py<PyAny>, Py<py::NativeDocument>)> {
    let (values, handle) = py::parse_all_values(py, text, safe)?;
    if safe {
        return Ok((values.bind(py).clone().into_any().unbind(), handle));
    }
    let ids: Vec<usize> = handle
        .borrow(py)
        .inner
        .documents
        .iter()
        .map(|document| document.root)
        .collect();
    let wrapper = py
        .import("pythonizeyaml.nodes")?
        .getattr("RoundTripList")?
        .call1((handle.bind(py), -1isize))?;
    let list = wrapper.cast::<PyList>()?;
    for value in values.bind(py).iter() {
        list.append(value)?;
    }
    wrapper.setattr("_pyy_node_ids", PyList::new(py, ids)?)?;
    Ok((wrapper.unbind(), handle))
}

#[pyfunction]
#[pyo3(signature = (value, config=None, explicit_start=None))]
fn dump(
    value: &Bound<'_, PyAny>,
    config: Option<&Bound<'_, PyAny>>,
    explicit_start: Option<bool>,
    py: Python<'_>,
) -> PyResult<String> {
    let config = match config {
        Some(config) => py::extract_emit_config(config)?,
        None => emitter::EmitConfig::default(),
    };
    py::dump_value(py, value, config, explicit_start)
}

#[pyfunction]
#[pyo3(signature = (values, config=None, explicit_start=None))]
fn dump_all(
    values: &Bound<'_, PyAny>,
    config: Option<&Bound<'_, PyAny>>,
    explicit_start: Option<bool>,
    py: Python<'_>,
) -> PyResult<String> {
    let config = match config {
        Some(config) => py::extract_emit_config(config)?,
        None => emitter::EmitConfig::default(),
    };
    let list = PyList::empty(py);
    for value in values.try_iter()? {
        list.append(value?)?;
    }
    py::dump_values(py, &list, config, explicit_start)
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<py::NativeDocument>()?;
    module.add("NativeYamlError", module.py().get_type::<NativeYamlError>())?;
    module.add_function(wrap_pyfunction!(parse, module)?)?;
    module.add_function(wrap_pyfunction!(parse_all, module)?)?;
    module.add_function(wrap_pyfunction!(dump, module)?)?;
    module.add_function(wrap_pyfunction!(dump_all, module)?)?;
    module.add_function(wrap_pyfunction!(dump_with_patches, module)?)?;
    Ok(())
}

#[pyfunction]
#[pyo3(signature = (value, patches, config=None, explicit_start=None, handle=None, node_id=None))]
fn dump_with_patches(
    value: &Bound<'_, PyAny>,
    patches: &Bound<'_, PyList>,
    config: Option<&Bound<'_, PyAny>>,
    explicit_start: Option<bool>,
    handle: Option<&Bound<'_, py::NativeDocument>>,
    node_id: Option<usize>,
    py: Python<'_>,
) -> PyResult<String> {
    let config = match config {
        Some(config) => py::extract_emit_config(config)?,
        None => emitter::EmitConfig::default(),
    };
    py::dump_value_with_patches(py, value, config, explicit_start, patches, handle, node_id)
}
