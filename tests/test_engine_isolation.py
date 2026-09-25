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

"""Requirement 12: engine instances are isolated from each other."""

from __future__ import annotations

import pythonizeyaml as py
from pythonizeyaml import DEFAULT_CONFIG, IndentConfig, SafeYAML, YAML

FRESH = {"a": {"b": 1}, "items": [1, 2, 3]}


def test_each_engine_keeps_its_own_config():
    four = YAML(IndentConfig(mapping=4))
    two = YAML(IndentConfig(mapping=2))
    assert four.config.mapping == 4
    assert two.config.mapping == 2
    assert four.config is not two.config


def test_engines_emit_according_to_their_own_config():
    four = YAML(IndentConfig(mapping=4))
    two = YAML(IndentConfig(mapping=2))
    assert four.dump(FRESH) == "a:\n    b: 1\nitems:\n- 1\n- 2\n- 3\n"
    assert two.dump(FRESH) == "a:\n  b: 1\nitems:\n- 1\n- 2\n- 3\n"


def test_dumping_with_one_engine_does_not_change_another():
    four = YAML(IndentConfig(mapping=4, sequence=4, offset=2))
    two = YAML(IndentConfig(mapping=2))
    first_four = four.dump(FRESH)
    two.dump(FRESH)
    assert four.dump(FRESH) == first_four


def test_alternating_dumps_stay_stable():
    four = YAML(IndentConfig(mapping=4, sequence=4, offset=2))
    two = YAML(IndentConfig(mapping=2))
    for _ in range(3):
        assert four.dump(FRESH) == four.dump(FRESH)
        assert two.dump(FRESH) == two.dump(FRESH)
    assert four.dump(FRESH) != two.dump(FRESH)


def test_the_module_functions_do_not_use_a_custom_engine():
    custom = YAML(IndentConfig(mapping=8, sequence=8))
    custom.dump(FRESH)
    assert py.dump(FRESH) == "a:\n  b: 1\nitems:\n- 1\n- 2\n- 3\n"


def test_a_default_engine_uses_the_default_config():
    assert YAML().config is DEFAULT_CONFIG


def test_the_safe_engine_is_separate_from_the_round_trip_engine():
    safe = SafeYAML()
    round_trip = YAML()
    assert safe is not round_trip
    assert safe._backend is not round_trip._backend
    assert safe._backend_typ == "safe"
    assert round_trip._backend_typ == "rt"


def test_safe_mode_does_not_preserve_round_trip_styles():
    """Only the round-trip engine retains redundant quotes."""
    assert py.dump(py.load("a: 'x'\n")) == "a: 'x'\n"
    assert "'x'" not in py.safe_dump(py.safe_load("a: 'x'\n"))


def test_a_layout_hint_travels_with_the_data_between_engines(read_fixture):
    source = read_fixture("simple_4space.yaml")
    first = YAML().load(source)
    second = YAML(IndentConfig(mapping=2))
    # Both engines reproduce the source layout because the hint lives on the data.
    assert YAML().dump(first) == source
    assert second.dump(first) == source
    assert YAML(IndentConfig(mapping=2)).dump(second.load(source)) == source


def test_one_engine_failing_does_not_disable_another():
    broken = YAML(IndentConfig(mapping=4))
    try:
        broken.load("items: [1, 2, 3\n")
    except py.YAMLError:
        pass
    healthy = YAML()
    assert healthy.dump(FRESH) == "a:\n  b: 1\nitems:\n- 1\n- 2\n- 3\n"