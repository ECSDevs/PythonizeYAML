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

"""Requirement 5: scalar quoting styles are retained, not normalized."""

from __future__ import annotations

import pytest

import pythonizeyaml as py


@pytest.fixture
def style_source(read_fixture):
    return read_fixture("scalar_styles.yaml")


@pytest.fixture
def style_output(style_source):
    return py.dump(py.load(style_source))


def test_whole_document_is_byte_identical(style_source, style_output):
    assert style_output == style_source


def test_plain_scalar_stays_plain(style_output):
    assert "plain: bare value\n" in style_output


def test_single_quoted_scalar_stays_single_quoted(style_output):
    assert "single: 'single quoted'\n" in style_output


def test_double_quoted_scalar_stays_double_quoted(style_output):
    assert 'double: "double quoted"\n' in style_output


def test_redundant_single_quotes_are_retained(style_output):
    assert "single_plain: 'plain'\n" in style_output


def test_redundant_double_quotes_are_retained(style_output):
    assert 'double_plain: "plain"\n' in style_output


def test_redundant_quotes_are_not_normalized_away(style_output):
    # Both spellings mean the same thing, so a normalizing round trip would drop
    # one of the quote styles; the pair proves each is preserved independently.
    assert "single_plain: plain\n" not in style_output
    assert "double_plain: plain\n" not in style_output


def test_a_quoted_number_stays_quoted(style_output):
    assert "numeric_string: '123'\n" in style_output


def test_quote_style_is_independent_per_scalar(style_source):
    data = py.load(style_source)
    # All three plain-valued keys decode to the same string...
    assert data["single_plain"] == data["double_plain"] == "plain"
    assert data["plain"] == "bare value"
    # ...yet each keeps its own style on the way back out.
    out = py.dump(data)
    assert "single_plain: 'plain'\n" in out
    assert 'double_plain: "plain"\n' in out