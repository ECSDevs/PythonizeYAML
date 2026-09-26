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

"""Deep copies of documents are fully independent."""

from __future__ import annotations

import copy

from pythonizeyaml import CollectionStyle, Document, load_document


def test_deepcopy_of_a_loaded_document_is_independent():
    document = load_document("a: 1\nb: x\n")
    clone = copy.deepcopy(document)
    clone["a"].value = 2
    assert document["a"] == 1
    assert clone["a"] == 2
    assert document.dump() == "a: 1\nb: x\n"
    assert clone.dump() == "a: 2\nb: x\n"


def test_deepcopy_of_an_untouched_loaded_document_keeps_the_dump_text():
    document = load_document("a: 1\nb: x\n")
    assert copy.deepcopy(document).dump() == document.dump()


def test_deepcopy_of_a_new_document_is_independent():
    document = Document.new({"a": {"b": 1}})
    clone = copy.deepcopy(document)
    clone["a"]["b"] = 2
    assert document["a"]["b"] == 1
    assert clone["a"]["b"] == 2
    assert document.dump() == "a:\n  b: 1\n"
    assert clone.dump() == "a:\n  b: 2\n"


def test_deepcopy_copies_the_override_registries():
    document = Document.new({"a": {"b": 1}})
    document["a"].collection_style = CollectionStyle.FLOW
    clone = copy.deepcopy(document)
    clone["a"].collection_style = CollectionStyle.BLOCK
    assert document.dump() == "a: {b: 1}\n"
    assert clone.dump() == "a:\n  b: 1\n"


def test_deepcopy_of_a_scalar_document_is_independent():
    document = load_document("42\n")
    clone = copy.deepcopy(document)
    clone.value = 43
    assert document.value == 42
    assert document.dump() == "42\n"
    assert clone.value == 43
    assert clone.dump() == "43\n"
