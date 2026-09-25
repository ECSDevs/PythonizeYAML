"""Parsing failures surface through the public library exception hierarchy."""

from __future__ import annotations

import pytest

import pythonizeyaml as py
from pythonizeyaml import MarkedYAMLError, YAMLError

INVALID_INPUTS = {
    "unclosed_flow_sequence": "items: [1, 2, 3\n",
    "unclosed_flow_mapping": "{a: 1\n",
    "tab_indent": "name: x\n\tnested: y\n",
    "unclosed_quote": "key: 'unterminated\n",
    "mapping_value_in_value": "a: b: c\n",
    "reserved_character": "key: @bad\n",
    "bad_block_indent": "a:\n  b: 1\n c: 2\n",
    "duplicate_key": "a: 1\na: 2\n",
}


@pytest.fixture(params=sorted(INVALID_INPUTS), ids=sorted(INVALID_INPUTS))
def malformed_source(request) -> str:
    return INVALID_INPUTS[request.param]


def test_malformed_input_raises_a_library_error(malformed_source):
    with pytest.raises(YAMLError) as caught:
        py.load(malformed_source)
    assert isinstance(caught.value, MarkedYAMLError)


def test_the_error_is_a_public_library_exception(malformed_source):
    with pytest.raises(YAMLError) as caught:
        py.load(malformed_source)
    error = caught.value
    assert type(error).__module__ == "pythonizeyaml.errors"
    assert type(error) is not YAMLError


def test_the_error_carries_a_mark_and_a_problem(malformed_source):
    with pytest.raises(MarkedYAMLError) as caught:
        py.load(malformed_source)
    error = caught.value
    assert error.problem
    assert error.problem_mark is not None
    assert error.problem_mark.line >= 0
    assert str(error)


def test_load_all_raises_the_same_library_error(malformed_source):
    with pytest.raises(YAMLError):
        py.load_all(malformed_source)


def test_unclosed_flow_sequence_reports_a_parser_error():
    with pytest.raises(py.ParserError):
        py.load("items: [1, 2, 3\n")


def test_tab_indentation_reports_a_scanner_error():
    with pytest.raises(py.ScannerError):
        py.load("name: x\n\tnested: y\n")


def test_duplicate_keys_are_rejected_as_a_constructor_error():
    with pytest.raises(py.ConstructorError):
        py.load("a: 1\na: 2\n")


def test_safe_load_reports_the_same_hierarchy_for_malformed_input(invalid_dir):
    source = (invalid_dir / "unclosed_flow.yaml").read_text(encoding="utf-8")
    with pytest.raises(py.YAMLError) as caught:
        py.safe_load(source)
    assert isinstance(caught.value, MarkedYAMLError)


def test_a_multi_document_stream_is_rejected_by_load_like_pyyaml():
    """PyYAML's ``load`` refuses a stream holding more than one document."""
    with pytest.raises(py.ComposerError):
        py.load("---\na: 1\n---\nb: 2\n")


def test_invalid_fixtures_are_rejected(invalid_dir):
    for path in sorted(invalid_dir.glob("*.yaml")):
        with pytest.raises(py.YAMLError):
            py.load(path.read_text(encoding="utf-8"))


def test_a_valid_document_is_not_affected_by_a_previous_failure():
    with pytest.raises(py.YAMLError):
        py.load("items: [1, 2, 3\n")
    assert py.load("items: [1, 2, 3]\n") == {"items": [1, 2, 3]}


