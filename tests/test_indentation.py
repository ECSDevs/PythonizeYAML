"""Requirement 3: source indentation (mapping width and dash offset) survives."""

from __future__ import annotations

from dataclasses import replace

import pytest

import pythonizeyaml as py


def round_trip(source: str) -> str:
    return py.dump(py.load(source))


@pytest.fixture
def two_space_source(read_fixture):
    return read_fixture("simple_2space.yaml")


@pytest.fixture
def four_space_source(read_fixture):
    return read_fixture("simple_4space.yaml")


def test_two_space_indent_survives(two_space_source):
    out = round_trip(two_space_source)
    assert out == two_space_source
    assert "server:\n  host: localhost\n" in out
    assert "\n    debug: true\n" in out
    # Not normalized to the 4-space layout.
    assert "\n    host: localhost\n" not in out


def test_four_space_indent_survives(four_space_source):
    out = round_trip(four_space_source)
    assert out == four_space_source
    assert "server:\n    host: localhost\n" in out
    assert "\n        debug: true\n" in out
    # Not normalized to the 2-space layout.
    assert "\n  host: localhost\n" not in out


def test_two_and_four_space_layouts_are_distinct(two_space_source, four_space_source):
    assert round_trip(two_space_source) != round_trip(four_space_source)


def test_loaded_data_does_not_force_the_engine_default(two_space_source, four_space_source):
    """The layout travels with the data, not with the engine's own config."""
    engine = py.YAML(replace(py.DEFAULT_CONFIG, mapping=8, sequence=8))
    assert engine.dump(engine.load(two_space_source)) == two_space_source
    assert engine.dump(engine.load(four_space_source)) == four_space_source


@pytest.fixture
def offset_source(read_fixture):
    return read_fixture("sequence_offset.yaml")


@pytest.fixture
def flush_source(read_fixture):
    return read_fixture("sequence_flush.yaml")


def test_non_default_dash_offset_survives(offset_source):
    out = round_trip(offset_source)
    assert out == offset_source
    assert "items:\n    - one\n    - two\n    - three\n" in out
    # The dash was indented deeper than its parent key, so it must not be
    # emitted flush with the key.
    assert "items:\n- one" not in out


def test_flush_dash_offset_survives(flush_source):
    out = round_trip(flush_source)
    assert out == flush_source
    assert "items:\n- one\n- two\n- three\n" in out
    assert "items:\n    - one" not in out


def test_the_two_dash_offsets_round_trip_differently(offset_source, flush_source):
    assert round_trip(offset_source) == offset_source
    assert round_trip(flush_source) == flush_source
    assert round_trip(offset_source) != round_trip(flush_source)


def test_mapping_body_under_an_indented_dash_survives(offset_source):
    out = round_trip(offset_source)
    assert "\n    - name: a\n      value: 1\n" in out