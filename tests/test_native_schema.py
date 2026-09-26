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

"""Tests for the Rust engine's extended schema and mutation behavior."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

import pythonizeyaml as py
from pythonizeyaml import ConstructorError, Tagged


def test_exactly_representable_decimal_stays_float():
    assert py.load("value: 1.5\n")["value"] == 1.5
    assert type(py.load("value: 1.5\n")["value"]) is float


def test_inexact_decimal_becomes_arbitrary_precision_decimal():
    value = py.load("value: 0.1\n")["value"]
    assert value == Decimal("0.1")
    assert type(value) is Decimal


def test_out_of_range_decimal_does_not_become_infinity():
    # `1.0e+400` is a PyYAML float that overflows to ``inf``; the engine's
    # extended schema keeps it as an exact Decimal instead. (Bare ``1e400``
    # is a string under PyYAML's YAML 1.1 float grammar, which needs a
    # decimal point and a signed exponent.)
    value = py.load("value: 1.0e+400\n")["value"]
    assert value == Decimal("1.0e+400")
    assert type(value) is Decimal
    assert py.safe_load("1e400\n") == "1e400"


def test_explicit_float_and_decimal_tags_override_implicit_resolution():
    assert type(py.load("value: !!float 0.1\n")["value"]) is float
    assert type(py.load("value: !!decimal 1.5\n")["value"]) is Decimal


def test_unknown_tags_are_exposed_and_round_trip():
    source = "value: !app/example payload\n"
    value = py.load(source)["value"]
    assert value == Tagged("!app/example", "payload")
    assert py.dump(py.load(source)) == source
    with pytest.raises(ConstructorError):
        py.safe_load(source)


def test_aliases_preserve_python_identity_in_block_and_flow_forms():
    block = py.load("base: &base {value: 1}\ncopy: *base\n")
    assert block["base"] is block["copy"]

    flow = py.load("items: [&item {value: 1}, *item]\n")
    assert flow["items"][0] is flow["items"][1]

    flow["items"][0]["value"] = 2
    assert py.dump(flow) == "items: [&item {value: 2}, *item]\n"


def test_standard_collection_and_scalar_tags():
    source = "!!set {a: null, b: null}\n"
    assert py.load(source) == {"a", "b"}
    assert py.dump(py.load(source)) == source

    assert py.load("value: !!binary aGVsbG8=\n")["value"] == b"hello"
    timestamp = py.load("value: 2001-12-15T02:59:43Z\n")["value"]
    assert timestamp == dt.datetime(2001, 12, 15, 2, 59, 43, tzinfo=dt.timezone.utc)


def test_yaml_timestamp_grammar_matches_pyyaml():
    utc = dt.timezone.utc
    # Z suffix, the form datetime.fromisoformat rejects before Python 3.11.
    assert py.load("value: 2001-12-15T02:59:43Z\n")["value"] == dt.datetime(
        2001, 12, 15, 2, 59, 43, tzinfo=utc
    )
    # Lowercase separator, single-digit hour, and short fraction.
    assert py.load("value: 2001-12-15t2:59:43.1Z\n")["value"] == dt.datetime(
        2001, 12, 15, 2, 59, 43, 100000, tzinfo=utc
    )
    # Space separator with an hour-only negative offset.
    assert py.load("value: 2001-12-14 21:59:43.10 -5\n")["value"] == dt.datetime(
        2001, 12, 14, 21, 59, 43, 100000, tzinfo=dt.timezone(dt.timedelta(hours=-5))
    )
    naive = py.load("value: 2001-12-14 21:59:43\n")["value"]
    assert naive == dt.datetime(2001, 12, 14, 21, 59, 43)
    assert naive.tzinfo is None
    assert py.load("value: 2001-12-15\n")["value"] == dt.date(2001, 12, 15)


def test_timestamp_lookalikes_stay_strings_and_bad_explicit_tags_raise():
    assert py.load("value: 2001-12-15xx\n")["value"] == "2001-12-15xx"
    assert py.load("value: 2001-12-15 21:59\n")["value"] == "2001-12-15 21:59"
    # Invalid timestamp payloads surface through the library's constructor
    # error, not a bare ValueError.
    with pytest.raises(ConstructorError):
        py.load("value: !!timestamp 2001-12-15xx\n")
    with pytest.raises(ConstructorError):
        py.load("value: 2001-13-45\n")


def test_invalid_binary_payloads_raise_constructor_error():
    with pytest.raises(ConstructorError):
        py.load("value: !!binary not-base64!!\n")


def test_unhashable_mapping_keys_raise_constructor_error():
    with pytest.raises(ConstructorError):
        py.load("{[a, b]: v}\n")


def test_dump_with_patches_rejects_spans_outside_the_source():
    from pythonizeyaml import SerializerError, _native
    from pythonizeyaml.errors import translate_native_error

    document = py.load_document("a: 1\n")
    # The native layer reports bad spans as NativeYamlError (kind 6); the
    # public SerializerError comes from the engine's translation.
    with pytest.raises(_native.NativeYamlError) as excinfo:
        _native.dump_with_patches(
            document._data,
            [(len(document.source) + 10, len(document.source) + 20, "x")],
            handle=document._handle,
            node_id=document._root_id,
        )
    assert isinstance(translate_native_error(excinfo.value, document.source), SerializerError)


def test_comment_patches_align_on_non_ascii_sources():
    document = py.load_document("ключ: значение\nдругой: два\n")
    document.node("другой").comments.inline = "# y"
    assert document.dump() == "ключ: значение\nдругой: два  # y\n"
    document.node("ключ").comments.inline = "# x"
    assert document.dump() == "ключ: значение  # x\nдругой: два  # y\n"


def test_merge_keys_resolve_but_round_trip_the_original_source():
    source = "base: &base {x: 1}\nmerged:\n  <<: *base\n  y: 2\n"
    data = py.load(source)
    assert data["merged"] == {"x": 1, "y": 2}
    assert py.dump(data) == source


def test_structural_edits_keep_surrounding_comments_and_indentation():
    source = "# top\na:\n  b: 1\nitems:\n  - one\n# end\n"
    data = py.load(source)
    data["a"]["c"] = 2
    data["items"].append("two")
    assert py.dump(data) == (
        "# top\na:\n  b: 1\n  c: 2\nitems:\n  - one\n  - two\n# end\n"
    )


def test_scalar_root_documents_use_canonical_output():
    assert py.dump(py.load("'1'\n")) == "'1'\n"
    assert py.dump(py.load("plain text\n")) == "plain text\n"


def test_yaml_11_directive_enables_legacy_boolean_resolution():
    assert py.load("%YAML 1.1\n---\nflag: yes\n")["flag"] is True
    assert py.load("%YAML 1.2\n---\nflag: yes\n")["flag"] == "yes"


def test_block_collection_anchors_share_identity():
    source = "base: &base\n  value: 1\ncopy: *base\n"
    data = py.load(source)
    assert data["base"] is data["copy"]
    assert py.dump(data) == source


def test_ordered_map_and_pairs_tags_resolve_to_tuple_sequences():
    ordered = py.load("!!omap\n- a: 1\n- b: 2\n")
    pairs = py.load("!!pairs\n- a: 1\n- b: 2\n")
    assert ordered == [("a", 1), ("b", 2)]
    assert pairs == [("a", 1), ("b", 2)]


def test_safe_dump_rejects_tagged_values():
    with pytest.raises(py.RepresenterError):
        py.safe_dump(Tagged("!custom", "value"))
