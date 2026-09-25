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

"""Requirement 4: block scalars keep their indicators, content and chomping."""

from __future__ import annotations

import pytest

import pythonizeyaml as py


@pytest.fixture
def block_source(read_fixture):
    return read_fixture("block_scalars.yaml")


@pytest.fixture
def block_output(block_source):
    return py.dump(py.load(block_source))


def test_whole_document_is_byte_identical(block_source, block_output):
    assert block_output == block_source


@pytest.mark.parametrize(
    "header",
    [
        "literal: |\n",
        "folded: >\n",
        "stripped: |-\n",
    ],
)
def test_block_indicators_survive(block_output, header):
    assert header in block_output


def test_literal_block_content_survives(block_output):
    assert "literal: |\n  line one\n  line two\n" in block_output


def test_folded_block_content_survives(block_output):
    assert "folded: >\n  folded line one\n  folded line two\n" in block_output


def test_chomping_indicator_content_survives(block_output):
    assert "stripped: |-\n  no trailing newline\n" in block_output


def test_indicators_are_not_normalized_into_each_other(block_output):
    # A folded scalar must not be re-emitted as literal, and vice versa.
    assert "folded: |" not in block_output
    assert "literal: >" not in block_output
    # The chomping indicator must not be dropped.
    assert "stripped: |\n" not in block_output


def test_loaded_block_scalar_values(block_source):
    data = py.load(block_source)
    assert data["literal"] == "line one\nline two\n"
    assert data["folded"] == "folded line one folded line two\n"
    assert data["stripped"] == "no trailing newline"


def test_a_comment_after_a_block_header_does_not_confuse_the_layout_scan():
    """The indent detector must not treat a ``|`` inside a comment as a block header."""
    source = "key: value  # contains a | pipe symbol\nother:\n  nested: 1\n"
    assert py.dump(py.load(source)) == source