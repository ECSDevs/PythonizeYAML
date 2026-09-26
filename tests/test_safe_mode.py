# Copyright (c) 2026 PythonizeYAML contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Requirement 10: safe mode rejects arbitrary object tags and stays plain."""

from __future__ import annotations

import pytest

import pythonizeyaml as py
from pythonizeyaml import (
    ConstructorError,
    MarkedYAMLError,
    RepresenterError,
    SafeYAML,
    Tagged,
    YAMLError,
)

OBJECT_TAG = "!!python/object/apply:os.system ['echo hi']\n"


def test_safe_load_rejects_arbitrary_object_tags():
    with pytest.raises(ConstructorError):
        py.safe_load(OBJECT_TAG)


def test_safe_load_all_rejects_arbitrary_object_tags():
    with pytest.raises(ConstructorError):
        list(py.safe_load_all("---\na: 1\n---\n" + OBJECT_TAG))


def test_constructor_error_is_part_of_the_library_hierarchy():
    with pytest.raises(ConstructorError) as caught:
        py.safe_load(OBJECT_TAG)
    error = caught.value
    assert isinstance(error, YAMLError)
    assert isinstance(error, MarkedYAMLError)
    assert type(error).__module__ == "pythonizeyaml.errors"


def test_safe_load_rejects_the_tag_inside_a_mapping():
    with pytest.raises(ConstructorError):
        py.safe_load("payload: " + OBJECT_TAG)


def test_a_nested_object_tag_is_also_rejected():
    with pytest.raises(ConstructorError):
        py.safe_load("outer:\n  inner: !!python/name:os.system\n")


def test_safe_engine_rejects_object_tags_directly():
    with pytest.raises(ConstructorError):
        SafeYAML().load(OBJECT_TAG)


def test_safe_load_returns_plain_python_types(read_fixture):
    data = py.safe_load(read_fixture("plain_types.yaml"))
    assert type(data) is dict
    assert type(data["nested"]) is dict
    assert type(data["items"]) is list
    assert data == {
        "name": "plain",
        "count": 3,
        "enabled": True,
        "ratio": 1.5,
        "nested": {"key": "value"},
        "items": ["one", "two"],
    }


def test_safe_load_all_returns_plain_python_types():
    documents = list(py.safe_load_all("---\na: 1\n---\nb: 2\n"))
    assert len(documents) == 2
    assert all(type(doc) is dict for doc in documents)
    assert documents == [{"a": 1}, {"b": 2}]


def test_safe_load_handles_scalars():
    assert py.safe_load("42\n") == 42
    assert py.safe_load("hello\n") == "hello"


def test_plain_round_trip_load_still_returns_mappings_and_lists(read_fixture):
    """The default (round-trip) loader is the one that keeps styles; plain
    ``dict``/``list`` subclasses are still what callers get."""
    data = py.load(read_fixture("plain_types.yaml"))
    assert isinstance(data, dict)
    assert isinstance(data["items"], list)


def test_safe_dump_round_trips_a_plain_dict():
    data = {"a": 1, "b": "two", "items": [1, 2]}
    text = py.safe_dump(data)
    assert isinstance(text, str)
    assert py.safe_load(text) == data


def test_safe_dump_all_round_trips_plain_dicts():
    documents = [{"a": 1}, {"b": 2}]
    text = py.safe_dump_all(documents)
    assert list(py.safe_load_all(text)) == documents


def test_safe_dump_does_not_emit_python_object_tags():
    class Custom:
        pass

    with pytest.raises(YAMLError):
        py.safe_dump({"obj": Custom()})


# -- safe dumps of Document objects ---------------------------------------


def test_safe_dump_rejects_a_document_with_a_native_custom_tag():
    document = py.load_document("a: !foo 1\nb: 2\n")
    with pytest.raises(RepresenterError):
        py.safe_dump(document)


def test_safe_dump_rejects_a_document_with_tagged_values_in_its_data():
    document = py.load_document("a: 1\n")
    document["custom"] = Tagged("!custom", "x")
    with pytest.raises(RepresenterError):
        py.safe_dump(document)


def test_safe_dump_rejects_a_document_with_a_registry_set_custom_tag():
    document = py.load_document("a: 1\n")
    document["a"].tag = "!app/custom"
    with pytest.raises(RepresenterError):
        py.safe_dump(document)


def test_safe_dump_all_rejects_documents_with_custom_tags():
    document = py.load_document("a: !foo 1\n")
    with pytest.raises(RepresenterError):
        py.safe_dump_all([document])


def test_round_trip_dump_still_allows_custom_tags():
    document = py.load_document("a: !foo 1\nb: 2\n")
    assert py.dump(document) == "a: !foo 1\nb: 2\n"