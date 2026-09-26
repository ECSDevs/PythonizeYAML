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

"""Aliasing to brand-new paths and alias-aware data views."""

from __future__ import annotations

from pythonizeyaml import load_document


def test_alias_to_a_new_path_appears_in_the_data_and_dumps():
    document = load_document("a: &anc 1\nb: 2\n")
    document.alias("copy", target=document.node("a"))
    assert "copy" in document.keys()
    assert document.at("copy") == 1
    assert document.data["copy"] == 1
    assert ("copy", 1) in list(document.items())
    assert document.dump() == "a: &anc 1\nb: 2\ncopy: *anc\n"


def test_alias_to_a_new_path_anchors_the_target_when_needed():
    document = load_document("a: 1\nb: 2\n")
    document.alias("copy", target=document.node("a"))
    assert document.dump() == "a: &id001 1\nb: 2\ncopy: *id001\n"


def test_alias_to_a_new_nested_path_is_created_and_dumped():
    document = load_document("a: &anc 1\nb: 2\n")
    document.alias(("x", "y"), target=document.node("a"))
    assert document.data["x"]["y"] == 1
    assert document.at("x", "y") == 1
    assert document.dump() == "a: &anc 1\nb: 2\nx:\n  y: *anc\n"


def test_alias_to_a_new_path_survives_a_reload():
    document = load_document("a: &anc 1\nb: 2\n")
    document.alias("copy", target=document.node("a"))
    reloaded = load_document(document.dump())
    assert reloaded.data["copy"] == 1


def test_alias_to_an_existing_path_resolves_in_the_data_views():
    document = load_document("a: 1\nb: 2\n")
    document.alias("b", target=document.node("a"))
    assert document.at("b") == 1
    assert document.data["b"] == 1
    assert list(document.items()) == [("a", 1), ("b", 1)]
    assert list(document.values()) == [1, 1]
    assert document.dump() == "a: &id001 1\nb: *id001\n"


def test_the_resolved_data_view_tracks_later_target_changes():
    document = load_document("a: 1\nb: 2\n")
    document.alias("b", target=document.node("a"))
    document.node("a").value = 99
    assert document.at("b") == 99
    assert document.data["b"] == 99
    assert list(document.values()) == [99, 99]


def test_the_data_view_is_unchanged_without_aliases():
    document = load_document("a: 1\nb: 2\n")
    assert document.data is document.value
    assert list(document.items()) == [("a", 1), ("b", 2)]
