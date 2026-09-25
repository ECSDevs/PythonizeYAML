"""Requirement 6: multi-document streams keep document order and layout."""

from __future__ import annotations

import pytest

import pythonizeyaml as py

# Three documents, each with its own comments and indentation, written inline so
# the expectations are visible next to the assertions.
THREE_DOCS = (
    "---\n"
    "name: first\n"
    "values:\n"
    "  - a\n"
    "  - b\n"
    "---\n"
    "# second document\n"
    "name: second\n"
    "nested:\n"
    "    key: value\n"
    "---\n"
    "name: third\n"
)


@pytest.fixture
def multi_source(read_fixture):
    return read_fixture("multi_document.yaml")


def test_load_all_returns_documents_in_order(multi_source):
    documents = py.load_all(multi_source)
    assert len(documents) == 3
    assert [doc["name"] for doc in documents] == ["first", "second", "third"]


def test_load_refuses_a_multi_document_stream(multi_source):
    """``load`` is single-document only, matching PyYAML; use ``load_all``."""
    with pytest.raises(py.ComposerError):
        py.load(multi_source)


def test_dump_all_reproduces_the_stream_byte_for_byte(multi_source):
    documents = py.load_all(multi_source)
    assert py.dump_all(documents) == multi_source


def test_each_document_keeps_its_own_layout(multi_source):
    out = py.dump_all(py.load_all(multi_source))
    # The first document is 2-space indented, the second one 4-space.
    assert "values:\n  - a\n  - b\n" in out
    assert "nested:\n    key: value\n" in out


def test_comment_between_documents_survives(multi_source):
    out = py.dump_all(py.load_all(multi_source))
    assert "# comment before the second document\n---\n" in out


def test_inline_three_document_stream_round_trips():
    assert py.dump_all(py.load_all(THREE_DOCS)) == THREE_DOCS


def test_inline_three_document_stream_order():
    documents = py.load_all(THREE_DOCS)
    assert [doc["name"] for doc in documents] == ["first", "second", "third"]
    assert documents[1]["nested"] == {"key": "value"}


def test_dump_all_to_a_stream_writes_and_returns_none(multi_source):
    import io

    stream = io.StringIO()
    assert py.dump_all(py.load_all(multi_source), stream=stream) is None
    assert stream.getvalue() == multi_source


def test_explicit_document_start_is_not_lost(multi_source):
    """A stream that starts with ``---`` must not have it silently dropped."""
    assert multi_source.startswith("---\n")
    out = py.dump(py.load("---\nname: solo\n"))
    assert out.startswith("---\n")