"""Requirement 8: indentation of freshly built data follows the engine config."""

from __future__ import annotations

import pytest

import pythonizeyaml as py
from pythonizeyaml import DEFAULT_CONFIG, IndentConfig, YAML

# Built in Python, so there is no source layout to preserve: the config decides.
FRESH = {"a": {"b": 1}, "items": [1, 2, 3]}
FRESH_NESTED = {"items": [{"a": 1}, {"b": 2}]}


def test_default_config_values():
    assert DEFAULT_CONFIG.mapping == 2
    assert DEFAULT_CONFIG.sequence == 2
    assert DEFAULT_CONFIG.offset == 0
    assert DEFAULT_CONFIG.width == 80
    assert DEFAULT_CONFIG.preserve_quotes is True


def test_default_config_applies_to_fresh_data():
    assert py.dump(FRESH) == "a:\n  b: 1\nitems:\n- 1\n- 2\n- 3\n"


def test_custom_indent_config_applies_to_fresh_data():
    engine = YAML(IndentConfig(mapping=4, sequence=4, offset=2))
    assert engine.dump(FRESH) == "a:\n    b: 1\nitems:\n  - 1\n  - 2\n  - 3\n"


def test_custom_config_applies_to_a_fresh_list_of_mappings():
    engine = YAML(IndentConfig(mapping=4, sequence=4, offset=2))
    assert engine.dump(FRESH_NESTED) == "items:\n  - a: 1\n  - b: 2\n"


def test_custom_config_changes_only_the_layout_not_the_data():
    engine = YAML(IndentConfig(mapping=4, sequence=4, offset=2))
    assert py.load(engine.dump(FRESH)) == FRESH


def test_indent_kwarg_uses_pyyaml_mapping_width():
    out = py.dump(FRESH, indent=4)
    assert "a:\n    b: 1\n" in out
    assert "\n  b: 1\n" not in out
    # PyYAML's ``indent`` keeps the sequence dash flush with its parent key.
    assert out.startswith("a:\n")
    assert "items:\n- " in out


@pytest.mark.parametrize("width", [3, 4, 6])
def test_indent_kwarg_width_is_honoured(width):
    out = py.dump(FRESH, indent=width)
    assert "a:\n" + (" " * width) + "b: 1\n" in out


def test_fresh_data_is_unaffected_by_an_earlier_loaded_dump(read_fixture):
    """A preserved source layout must not leak into the engine's own config."""
    engine = YAML()
    four_space = read_fixture("simple_4space.yaml")
    assert engine.dump(engine.load(four_space)) == four_space
    assert engine.dump(FRESH) == "a:\n  b: 1\nitems:\n- 1\n- 2\n- 3\n"
    assert py.dump(FRESH) == "a:\n  b: 1\nitems:\n- 1\n- 2\n- 3\n"