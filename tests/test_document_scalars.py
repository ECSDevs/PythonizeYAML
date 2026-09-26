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

"""Scalar wrappers: loaded and assigned values carry the styling API."""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

import pythonizeyaml
from pythonizeyaml import Document, PathError, load_document
from pythonizeyaml.nodes import (
    RoundTripBytes,
    RoundTripDate,
    RoundTripDatetime,
    RoundTripDecimal,
    RoundTripFloat,
    RoundTripInt,
    RoundTripList,
    RoundTripMap,
    RoundTripStr,
)


# -- wrapping on load ----------------------------------------------------------


def test_loaded_scalars_are_wrapped():
    document = load_document("name: hello\nport: 8080\nratio: 1.5\n")
    assert type(document["name"]) is RoundTripStr
    assert type(document["port"]) is RoundTripInt
    assert type(document["ratio"]) is RoundTripFloat


def test_wrappers_compare_and_hash_like_plain_values():
    document = load_document("name: hello\nport: 8080\n")
    assert document["name"] == "hello"
    assert hash(document["port"]) == hash(8080)
    assert {"hello": None} == {document["name"]: None}
    assert isinstance(document["name"], str) and isinstance(document["port"], int)


def test_bool_and_none_have_no_wrapper():
    document = load_document("flag: true\nempty: null\n")
    assert type(document["flag"]) is bool
    assert document["empty"] is None


def test_timestamps_binary_and_decimals_get_their_own_wrappers():
    document = load_document(
        "when: 2020-01-02\nstamp: 2020-01-02T03:04:05Z\nratio: 0.1\nblob: !!binary aGk=\n"
    )
    assert type(document["when"]) is RoundTripDate
    assert type(document["stamp"]) is RoundTripDatetime
    assert isinstance(document["stamp"], datetime)
    assert type(document["ratio"]) is RoundTripDecimal
    assert type(document["blob"]) is RoundTripBytes
    assert document["blob"] == b"hi"


def test_mapping_keys_are_wrapped_too():
    document = load_document("8080: port\nname: hello\n")
    assert 8080 in document and document[8080] == "port"
    assert list(document.keys())[1] == "name"


def test_scalar_root_value_carries_the_api():
    document = load_document("hello\n")
    assert type(document.value) is RoundTripStr
    document.value.style = "double"
    assert document.dump() == '"hello"\n'


# -- plain-data APIs stay plain -------------------------------------------------


def test_safe_load_and_full_load_return_plain_data():
    text = "name: hello\nport: 8080\n"
    assert type(pythonizeyaml.safe_load(text)["name"]) is str
    assert type(pythonizeyaml.safe_load(text)["port"]) is int
    assert type(pythonizeyaml.full_load(text)["name"]) is str
    assert type(list(pythonizeyaml.full_load(text))[0]) is str


# -- styling through values -----------------------------------------------------


def test_styling_a_loaded_string():
    document = load_document("name: hello\n")
    document["name"].style = "double"
    assert document.dump() == 'name: "hello"\n'


def test_chained_subscripts_reach_nested_values():
    document = load_document("service:\n  ports:\n    - 8080\n")
    document["service"]["ports"][0].comments.inline = "# http"
    assert document.dump() == "service:\n  ports:\n    - 8080  # http\n"


def test_container_root_document_carries_the_api():
    document = load_document("a: 1\n")
    document.set(before=["# header"])
    assert document.dump() == "# header\na: 1\n"


# -- wrapping on assignment ------------------------------------------------------


def test_assigned_scalars_are_wrapped_and_styleable():
    document = load_document("base: 1\n")
    document["extra"] = "added"
    assert type(document["extra"]) is RoundTripStr
    document["extra"].set(style="single", before=["# added later"])
    assert document.dump() == "base: 1\n# added later\nextra: 'added'\n"


def test_appended_items_are_wrapped_and_styleable():
    document = load_document("items:\n  - one\n")
    document["items"].append("two")
    assert type(document["items"][1]) is RoundTripStr
    document["items"][1].style = "double"
    assert document.dump() == 'items:\n  - one\n  - "two"\n'


def test_assigned_plain_containers_are_converted():
    document = load_document("base: 1\n")
    document["sub"] = {"a": "x", "b": [1, 2]}
    assert type(document["sub"]) is RoundTripMap
    assert type(document["sub"]["b"]) is RoundTripList
    assert type(document["sub"]["a"]) is RoundTripStr
    document["sub"].set(collection_style="flow")
    assert document.dump() == "base: 1\nsub: {a: x, b: [1, 2]}\n"


def test_nested_block_collection_renders_flow_inside_a_flow_parent():
    document = load_document("base: 1\n")
    document.value = {"matrix": [[1, 2], [3]]}
    document["matrix"].set(collection_style="flow")
    assert document.dump() == "matrix: [[1, 2], [3]]\n"


def test_wrapped_timestamps_render_on_the_dirty_path():
    document = load_document("items:\n  - start: 2020-01-02T03:04:05Z\n")
    document["items"].append("x")
    text = document.dump()
    assert type(load_document(text)["items"][0]["start"]) is RoundTripDatetime


def test_document_new_converts_user_data():
    document = Document.new({"outer": {"inner": "x"}})
    assert type(document["outer"]) is RoundTripMap
    assert type(document["outer"]["inner"]) is RoundTripStr
    document["outer"]["inner"].style = "double"
    assert document.dump() == 'outer:\n  inner: "x"\n'


# -- identity resolution ---------------------------------------------------------


def test_value_follows_its_item_through_shifts():
    document = load_document("items:\n  - one\n  - two\n")
    ref = document["items"][1]
    document["items"].insert(0, "zero")
    assert ref.path == ("items", 2)
    assert ref.value == "two"


def test_detached_value_raises_path_error():
    document = load_document("a: x\n")
    value = document["a"]
    del document["a"]
    with pytest.raises(PathError):
        value.style
    with pytest.raises(PathError):
        value.set(style="double")


def test_value_stored_at_several_paths_needs_a_fresh_read():
    document = load_document("a: x\n")
    shared = document["a"]
    document["b"] = shared
    shared._pyy_path_hint = None
    with pytest.raises(PathError):
        shared.style
    # Reading through the intended path re-pins the hint.
    assert document["b"].path == ("b",)
    document["b"].style = "single"
    assert document.dump() == "a: x\nb: 'x'\n"


def test_copied_wrappers_rebind_to_the_clone():
    document = Document.new({"a": "x"})
    clone = copy.deepcopy(document)
    clone["a"].style = "single"
    assert document.dump() == "a: x\n"
    assert clone.dump() == "a: 'x'\n"


# -- aliases through values -------------------------------------------------------


def test_alias_target_can_be_a_value():
    document = load_document("base: v\n")
    document.alias("copy", target=document["base"])
    assert document.dump() == "base: &id001 v\ncopy: *id001\n"
    assert document["copy"] == "v"


def test_alias_target_can_be_a_path():
    document = load_document("base: v\n")
    document.alias("copy", target="base")
    assert "copy: *id001" in document.dump()


def test_alias_target_from_another_document_is_rejected():
    first = load_document("a: 1\n")
    second = load_document("b: 2\n")
    with pytest.raises(Exception, match="different document"):
        second.alias("copy", target=first["a"])


def test_styling_through_an_alias_styles_the_target():
    document = load_document("base: v\n")
    document.alias("copy", target=document["base"])
    document["copy"].style = "single"
    text = document.dump()
    assert "base: &id001 'v'" in text
    assert "copy: *id001" in text


# -- set() semantics ---------------------------------------------------------------


def test_set_pins_the_path_across_a_value_replacement():
    document = load_document("a: 1\n")
    document["a"].set(value=2, inline="# two")
    assert document.dump() == "a: 2  # two\n"


def test_set_is_atomic_and_returns_the_current_value():
    document = load_document("a: 1\n")
    value = document["a"]
    with pytest.raises(Exception):
        value.set(value=2, style="literal")
    assert dict(document.data) == {"a": 1}
    assert document.dump() == "a: 1\n"
