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

"""Requirement 2: comments survive a round trip verbatim."""

from __future__ import annotations

import pytest

import pythonizeyaml as py

FULL_LINE_COMMENTS = [
    "# Top of file comment",
    "# comment above server",
    "  # indented comment inside server",
    "  # indented comment right before the end of the nested mapping",
    "# comment between entries, after a blank line",
    "# trailing comment at end of document",
]

INLINE_COMMENTS = [
    "name: example  # inline on a key",
    "host: localhost  # inline inside a nested mapping",
    "blank_after: true  # a comment separated from the next entry by a blank line",
]


@pytest.fixture
def comments_source(read_fixture):
    return read_fixture("comments.yaml")


@pytest.fixture
def comments_output(comments_source):
    return py.dump(py.load(comments_source))


@pytest.mark.parametrize("comment", FULL_LINE_COMMENTS)
def test_full_line_comments_survive(comments_output, comment):
    assert comment in comments_output


@pytest.mark.parametrize("comment", INLINE_COMMENTS)
def test_inline_comments_survive(comments_output, comment):
    assert comment in comments_output


def test_comment_placement_is_exact(comments_source, comments_output):
    assert comments_output == comments_source


def test_comment_above_a_key_stays_above_it(comments_output):
    assert "# comment above server\nserver:\n" in comments_output


def test_comment_between_entries_stays_between_them(comments_output):
    assert (
        "blank_after: true  # a comment separated from the next entry by a blank line\n"
        "\n"
        "# comment between entries, after a blank line\n"
        "enabled: true\n"
    ) in comments_output


def test_trailing_document_comment_stays_last(comments_output):
    assert comments_output.rstrip("\n").endswith("# trailing comment at end of document")


def test_indented_comment_keeps_its_indentation(comments_output):
    assert "\n  # indented comment inside server\n" in comments_output


def test_blank_lines_are_preserved(comments_output):
    assert "\n\n# comment between entries" in comments_output


def test_comments_do_not_leak_into_the_data(comments_source):
    data = py.load(comments_source)
    assert data["name"] == "example"
    assert data["server"]["host"] == "localhost"
    assert data["enabled"] is True