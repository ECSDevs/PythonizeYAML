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

"""Differential tests against PyYAML: ``safe_load`` resolver parity.

The goal of this module is parity: ``pythonizeyaml.safe_load`` must return
exactly what ``yaml.safe_load`` (PyYAML, YAML 1.1 rules) returns for the same
input. Every expected value below was verified against PyYAML 6.0.3's actual
behavior, and the test re-checks each expectation against the installed PyYAML
at runtime, so the table cannot silently drift from PyYAML.

Any new case added here must reflect PyYAML's ACTUAL behavior (run both
libraries and confirm before committing the expectation). If a case currently
fails, fix pythonizeyaml's resolver -- never weaken the expectation to match
our output. Known YAML 1.1 quirks preserved by PyYAML:

- ``yes``/``no``/``on``/``off`` resolve to booleans (any case).
- ``052`` is octal (42); ``0o52`` is NOT an int and stays a string.
- ``1:30`` is sexagesimal (90); ``1:30.5`` is a sexagesimal float (90.5).
- Float exponents need an explicit sign: ``1.5e3`` stays a string,
  ``1.5e+3`` is a float.
- ``.inf``/``.nan`` (any case) are floats; bare ``INF`` stays a string.
"""

from __future__ import annotations

import datetime
import math

import pytest

yaml = pytest.importorskip("yaml")

import pythonizeyaml  # noqa: E402

# (label, yaml source, PyYAML-verified expected value)
CASES = [
    # Booleans.
    ("bool-true", "true\n", True),
    ("bool-false-upper", "FALSE\n", False),
    ("bool-title-case", "True\n", True),
    ("bool-yes", "yes\n", True),
    ("bool-no", "no\n", False),
    ("bool-on", "on\n", True),
    ("bool-off", "OFF\n", False),
    # Nulls.
    ("null-tilde", "~\n", None),
    ("null-word", "null\n", None),
    ("null-capitalized", "Null\n", None),
    ("null-empty-document", "", None),
    # Integers.
    ("int-plain", "42\n", 42),
    ("int-negative", "-17\n", -17),
    ("int-plus", "+7\n", 7),
    ("int-hex", "0x2A\n", 42),
    ("int-hex-negative", "-0x1f\n", -31),
    ("int-octal-zero-prefix", "052\n", 42),
    ("int-octal-0o-is-string", "0o52\n", "0o52"),
    ("int-underscore", "1_000\n", 1000),
    ("int-sexagesimal", "1:30\n", 90),
    ("int-sexagesimal-three-part", "1:30:00\n", 5400),
    # Floats.
    ("float-plain", "1.5\n", 1.5),
    ("float-negative", "-2.25\n", -2.25),
    ("float-exponent-signed", "1.5e+3\n", 1500.0),
    ("float-exponent-unsigned-is-string", "1.5e3\n", "1.5e3"),
    ("float-leading-dot", ".5\n", 0.5),
    ("float-trailing-dot", "1.\n", 1.0),
    ("float-sexagesimal", "1:30.5\n", 90.5),
    ("float-inf", ".inf\n", float("inf")),
    ("float-inf-negative", "-.inf\n", float("-inf")),
    ("float-inf-capitalized", ".Inf\n", float("inf")),
    ("float-nan", ".nan\n", float("nan")),
    ("float-nan-capitalized", ".NaN\n", float("nan")),
    ("float-inf-bare-word-is-string", "INF\n", "INF"),
    # Strings and quoting.
    ("string-plain", "hello world\n", "hello world"),
    ("string-single-quoted-number", "'123'\n", "123"),
    ("string-double-quoted-bool-word", '"yes"\n', "yes"),
    ("string-quoted-colon", "'a: b'\n", "a: b"),
    ("string-single-quote-escape", "'it''s'\n", "it's"),
    ("string-double-quote-escape", '"a\\tb"\n', "a\tb"),
    # Timestamps.
    (
        "timestamp-date",
        "2001-12-14\n",
        datetime.date(2001, 12, 14),
    ),
    (
        "timestamp-datetime-tz",
        "2001-12-14t21:59:43.10-05:00\n",
        datetime.datetime(
            2001,
            12,
            14,
            21,
            59,
            43,
            100000,
            tzinfo=datetime.timezone(datetime.timedelta(hours=-5)),
        ),
    ),
    # Collections.
    ("map-block", "a: 1\nb: two\nc: [3, 4]\n", {"a": 1, "b": "two", "c": [3, 4]}),
    ("map-flow", "{a: 1, b: [2, 3]}\n", {"a": 1, "b": [2, 3]}),
    ("seq-block", "- 1\n- two\n- key: value\n", [1, "two", {"key": "value"}]),
    ("seq-flow", "[1, 'two', {k: v}]\n", [1, "two", {"k": "v"}]),
    (
        "seq-of-maps",
        "- name: a\n  v: 1\n- name: b\n  v: 2\n",
        [{"name": "a", "v": 1}, {"name": "b", "v": 2}],
    ),
    (
        "map-nested",
        "outer:\n  inner:\n    - 1\n    - x: 2\n",
        {"outer": {"inner": [1, {"x": 2}]}},
    ),
    (
        "map-typed-keys",
        "true: 1\n1.5: two\n~: three\n",
        {True: 1, 1.5: "two", None: "three"},
    ),
    (
        "block-literal-clip",
        "text: |\n  line one\n  line two\n",
        {"text": "line one\nline two\n"},
    ),
    (
        "block-folded-clip",
        "text: >\n  fold one\n  fold two\n",
        {"text": "fold one fold two\n"},
    ),
    ("block-literal-keep", "text: |+\n  keep\n\n\n", {"text": "keep\n\n\n"}),
    # Anchors, aliases, and merge keys.
    (
        "anchor-alias",
        "x: &a 41\ny: *a\nz: [0, *a]\n",
        {"x": 41, "y": 41, "z": [0, 41]},
    ),
    (
        "merge-key",
        "base: &b\n  a: 1\n  shared: s\nderived:\n  <<: *b\n  b: 2\n",
        {"base": {"a": 1, "shared": "s"}, "derived": {"a": 1, "shared": "s", "b": 2}},
    ),
    (
        "merge-key-list",
        "a: &x {p: 1}\nb: &y {q: 2}\nc:\n  <<: [*x, *y]\n  r: 3\n",
        {"a": {"p": 1}, "b": {"q": 2}, "c": {"p": 1, "q": 2, "r": 3}},
    ),
    # Multi-line plain scalars: one break folds to a space, blank lines fold
    # to that many newlines, more-indented lines keep folding with their
    # leading whitespace stripped, and a comment line ends the scalar.
    ("multiline-plain-fold", "key: multi\n  line\n", {"key": "multi line"}),
    (
        "multiline-plain-continue",
        "a: multi\n  line\n  again\nb: 2\n",
        {"a": "multi line again", "b": 2},
    ),
    (
        "multiline-plain-blank",
        "a: multi\n\n  line\nb: 2\n",
        {"a": "multi\nline", "b": 2},
    ),
    (
        "multiline-plain-two-blanks",
        "a: x\n\n  y\n\n\n  z\nb: 2\n",
        {"a": "x\ny\n\nz", "b": 2},
    ),
    (
        "multiline-plain-deeper",
        "a: multi\n  more\n    deeper\n  line\nb: 2\n",
        {"a": "multi more deeper line", "b": 2},
    ),
    (
        "multiline-plain-value-on-next-lines",
        "a:\n  multi\n  line\nb: 2\n",
        {"a": "multi line", "b": 2},
    ),
    (
        "multiline-plain-dash-like",
        "a: x\n  - y\n",
        {"a": "x - y"},
    ),
    (
        "multiline-plain-comment-ends",
        "a: multi\n# comment\nb: 2\n",
        {"a": "multi", "b": 2},
    ),
    (
        "multiline-plain-comment-then-value",
        "a: x\n  y # c\nb: 2\n",
        {"a": "x y", "b": 2},
    ),
    ("multiline-seq-item-fold", "- multi\n  line\n- two\n", ["multi line", "two"]),
    ("multiline-seq-item-blank", "- x\n\n  y\n- z\n", ["x\ny", "z"]),
    ("multiline-root-scalar", "42\nmore\n", "42 more"),
    ("multiline-root-scalar-marker", "--- 42\nmore\n", "42 more"),
    # Multi-line flow collections.
    ("multiline-flow-seq", "a: [1,\n  2,\n  3]\n", {"a": [1, 2, 3]}),
    ("multiline-flow-map", "{a: 1,\n b: 2}\n", {"a": 1, "b": 2}),
    ("multiline-flow-nested", "a: [1, [2,\n  3], {k: v}]\n", {"a": [1, [2, 3], {"k": "v"}]}),
    ("multiline-flow-blank", "a: [1,\n\n  2]\n", {"a": [1, 2]}),
    ("multiline-flow-comment", "a: [1,\n  2\n# c\n, 3]\n", {"a": [1, 2, 3]}),
    ("multiline-flow-next-key", "a: [1,\n  2]\nb: 3\n", {"a": [1, 2], "b": 3}),
    ("multiline-flow-in-seq", "- 1\n- [x,\n  y]\n- z\n", [1, ["x", "y"], "z"]),
    ("multiline-root-flow", "[1,\n  2]\n", [1, 2]),
    # Multi-line quoted scalars: a break folds to a space after stripping the
    # break's surrounding whitespace, and blank lines fold to newlines.
    ("multiline-quoted-double", 'key: "multi\n  line"\n', {"key": "multi line"}),
    ("multiline-quoted-single", "key: 'multi\n  line'\n", {"key": "multi line"}),
    ("multiline-quoted-blank", 'key: "x\n\n  y"\n', {"key": "x\ny"}),
    ("multiline-quoted-hash", 'key: "multi\n  # line"\n', {"key": "multi # line"}),
    ("multiline-quoted-in-flow", 'a: ["x\n  y"]\n', {"a": ["x y"]}),
    ("multiline-quoted-on-next-lines", 'a:\n  "multi\n  line"\n', {"a": "multi line"}),
    # Compact nested sequences.
    ("compact-nested-seq", "- - a\n- - b\n", [["a"], ["b"]]),
    ("compact-nested-seq-shared", "- - a\n  - b\n", [["a", "b"]]),
    ("compact-nested-three-deep", "- - - a\n", [[["a"]]]),
    ("compact-nested-with-maps", "- - a: 1\n- - b: 2\n", [[{"a": 1}], [{"b": 2}]]),
    ("plain-item-folds-dash-like", "- a\n  - b\n- c\n", ["a - b", "c"]),
    # Explicit keys.
    ("explicit-key-basic", "? key\n: value\n", {"key": "value"}),
    ("explicit-key-null", "? key\n", {"key": None}),
    ("explicit-key-mixed", "? k\n: v\nb: 2\n", {"k": "v", "b": 2}),
    ("explicit-key-after-implicit", "a: 1\n? k\n: v\nb: 2\n", {"a": 1, "k": "v", "b": 2}),
    (
        "explicit-key-multiline-key",
        "? multi\n  line key\n: v\n",
        {"multi line key": "v"},
    ),
    (
        "explicit-key-multiline-value",
        "? k\n: multi\n  line\n",
        {"k": "multi line"},
    ),
    ("explicit-key-block-seq-value", "? k\n:\n- a\n", {"k": ["a"]}),
    ("explicit-key-block-map-value", "? k\n:\n  a: 1\n", {"k": {"a": 1}}),
    ("explicit-key-nested-in-map", "a:\n  ? k\n  : v\n", {"a": {"k": "v"}}),
    ("explicit-key-in-sequence", "- ? k\n  : v\n", [{"k": "v"}]),
    ("explicit-key-bare-question", "?\n: v\n", {None: "v"}),
    ("explicit-key-flow-key-scalar", "? k\n: [1,\n  2]\n", {"k": [1, 2]}),
    # Document handling around multi-line constructs.
    ("multiline-scalar-explicit-end", "42\nmore\n...\n", "42 more"),
]


def _values_equal(actual, expected) -> bool:
    """Compare parsed values, treating NaN as equal to itself."""
    if isinstance(actual, float) and isinstance(expected, float):
        return (math.isnan(actual) and math.isnan(expected)) or actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _values_equal(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _values_equal(item, other) for item, other in zip(actual, expected)
        )
    return type(actual) is type(expected) and actual == expected


@pytest.mark.parametrize("label,source,expected", CASES, ids=[case[0] for case in CASES])
def test_safe_load_matches_pyyaml(label, source, expected):
    # Guard the table itself: the expectation must still be what PyYAML does.
    pyyaml_value = yaml.safe_load(source)
    assert _values_equal(pyyaml_value, expected), (
        f"table expectation for {label!r} no longer matches "
        f"PyYAML {yaml.__version__}: {pyyaml_value!r} != {expected!r}"
    )
    actual = pythonizeyaml.safe_load(source)
    assert _values_equal(actual, expected), (
        f"safe_load({source!r}) returned {actual!r}, "
        f"PyYAML {yaml.__version__} returns {expected!r}"
    )


def test_safe_mode_rejects_object_tags_like_pyyaml():
    """Both libraries refuse !!python/object tags in safe mode."""
    source = '!!python/object/apply:os.system ["echo hi"]\n'
    with pytest.raises(Exception) as pyyaml_error:
        yaml.safe_load(source)
    with pytest.raises(Exception) as pythonizeyaml_error:
        pythonizeyaml.safe_load(source)
    assert type(pyyaml_error.value).__name__ == "ConstructorError"
    assert type(pythonizeyaml_error.value).__name__ == "ConstructorError"
