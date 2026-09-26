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

"""DocumentStream start/end markers and the explicit-end detection rule."""

from __future__ import annotations

from pythonizeyaml import load_document, load_documents


# -- unchanged sources --------------------------------------------------------


def test_stream_dump_default_keeps_the_source_verbatim():
    stream = load_documents("---\na: 1\n---\nb: 2\n")
    assert stream.dump() == "---\na: 1\n---\nb: 2\n"


def test_stream_dump_with_explicit_start_true_inserts_a_missing_marker():
    stream = load_documents("a: 1\n")
    assert stream.dump(explicit_start=True) == "---\na: 1\n"


def test_stream_dump_with_explicit_start_false_strips_the_marker():
    stream = load_documents("---\na: 1\n---\nb: 2\n")
    assert stream.dump(explicit_start=False) == "a: 1\n---\nb: 2\n"


def test_stream_dump_explicit_end_adds_a_missing_marker():
    stream = load_documents("a: 1\n")
    assert stream.dump(explicit_end=True) == "a: 1\n...\n"


def test_stream_dump_explicit_end_terminates_every_document():
    stream = load_documents("---\na: 1\n---\nb: 2\n")
    assert stream.dump(explicit_end=True) == "---\na: 1\n...\n---\nb: 2\n...\n"


def test_stream_dump_explicit_end_false_strips_the_marker():
    stream = load_documents("a: 1\n...\n")
    assert stream.dump(explicit_end=False) == "a: 1\n"


def test_stream_dump_honors_directives_before_the_marker():
    stream = load_documents("%YAML 1.2\n---\na: 1\n")
    # The start marker exists (after the directive), so True keeps the source
    # verbatim, and False only strips a *leading* marker line.
    assert stream.dump(explicit_start=True) == "%YAML 1.2\n---\na: 1\n"
    assert stream.dump(explicit_start=False) == "%YAML 1.2\n---\na: 1\n"


# -- re-emitted (changed) streams ---------------------------------------------


def test_stream_reemit_uses_the_requested_explicit_start():
    stream = load_documents("---\na: x\n---\nb: y\n")
    stream[0]["a"].style = "double"
    assert stream.dump(explicit_start=False) == 'a: "x"\n---\nb: y\n'
    assert stream.dump(explicit_start=True) == '---\na: "x"\n---\nb: y\n'


def test_stream_reemit_default_keeps_start_markers():
    stream = load_documents("---\na: x\n---\nb: y\n")
    stream[0]["a"].style = "double"
    assert stream.dump() == '---\na: "x"\n---\nb: y\n'


# -- explicit-end detection ----------------------------------------------------


def test_an_indented_end_marker_inside_a_block_scalar_does_not_count():
    document = load_document("text: |\n  foo\n  ...\n")
    document.explicit_end = True
    assert document.dump() == "text: |\n  foo\n  ...\n...\n"


def test_an_unindented_end_marker_still_suppresses_the_added_marker():
    document = load_document("---\na: 1\n...\n")
    document.explicit_end = True
    assert document.dump() == "---\na: 1\n...\n"
