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
    value = py.load("value: 1e400\n")["value"]
    assert value == Decimal("1e400")
    assert type(value) is Decimal


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
