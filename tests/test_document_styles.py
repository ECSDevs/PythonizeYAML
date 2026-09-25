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

"""Tests for the mutable advanced-style document API."""

from __future__ import annotations

import pytest

import pythonizeyaml as py
from pythonizeyaml import (
    AliasError,
    CollectionStyle,
    Document,
    ScalarStyle,
    StyleError,
    load_document,
    load_documents,
)


def test_read_scalar_style_and_location():
    document = load_document("name: 'example'\n")
    node = document.node("name")
    assert node.style is ScalarStyle.SINGLE
    assert node.value == "example"
    assert node.span is not None
    assert node.span.line == 1


def test_edit_scalar_value_and_style_atomically():
    document = load_document("name: example\nport: 8080\n")
    document.node("name").value = "renamed"
    document.node("name").style = "double"
    assert document.dump() == 'name: "renamed"\nport: 8080\n'
    with pytest.raises(StyleError):
        document.node("port").style = "literal"
    assert document.node("port").value == 8080


def test_read_and_edit_positioned_comments():
    document = load_document("# before\nname: example  # inline\n# after\n")
    node = document.node("name")
    assert node.comments.before == ["# before"]
    assert node.comments.inline == "# inline"
    assert node.comments.after == ["# after"]
    node.comments.before = ["# changed"]
    node.comments.inline = "# updated"
    node.comments.after = ["# tail"]
    assert document.dump() == "# changed\nname: example  # updated\n# tail\n"


def test_edit_tags_anchors_and_aliases():
    document = load_document("base:\n  value: 1\ncopy:\n  value: 1\n")
    document.node("base").anchor = "base"
    document.node("base").tag = "!app/config"
    document.alias("copy", target=("base",))
    assert document.dump() == (
        "base: !app/config &base\n  value: 1\ncopy: *base\n"
    )
    document.node("base").anchor = "renamed"
    assert "copy: *renamed" in document.dump()


def test_alias_removal_is_rejected_while_references_exist():
    document = load_document("base: &base 1\ncopy: *base\n")
    with pytest.raises(AliasError):
        document.node("base").anchor = None


def test_flow_style_conversion_and_strict_validation():
    document = load_document("items:\n  - one\n  - two\n")
    document.node("items").collection_style = "flow"
    assert document.dump() == "items: [one, two]\n"
    with pytest.raises(StyleError):
        document.node("items").style = "double"


def test_create_styled_document():
    document = Document.new({"message": "hello\nworld", "items": [1, 2]})
    document.node("message").style = "literal"
    document.node("items").collection_style = CollectionStyle.FLOW
    assert document.dump() == "message: |\n    hello\n    world\nitems: [1, 2]\n"


def test_document_markers_and_directives():
    document = Document.new({"a": 1})
    document.directives = ["%YAML 1.2"]
    document.explicit_start = True
    document.explicit_end = True
    assert document.dump() == "%YAML 1.2\n---\na: 1\n...\n"


def test_multi_document_stream_round_trips():
    stream = load_documents("---\na: 1\n---\nb: 2\n")
    assert len(stream) == 2
    assert stream[0].value("a") == 1
    assert stream[1].value("b") == 2
    assert stream.dump() == "---\na: 1\n---\nb: 2\n"


def test_existing_dump_accepts_document_without_breaking_plain_data():
    document = load_document("a: 1\n")
    assert py.dump(document) == "a: 1\n"
    assert py.dump({"a": 1}) == "a: 1\n"


def test_insert_styled_node_into_loaded_document_preserves_comments():
    document = load_document("# top\na: 1\n# end\n")
    document.set("b", value="x", style="double", before=["# b"])
    assert document.dump() == '# top\na: 1\n# b\nb: "x"\n# end\n'


def test_update_is_atomic_when_style_is_incompatible():
    document = load_document("a: 1\n")
    node = document.node("a")
    with pytest.raises(StyleError):
        node.update(value=2, style="literal")
    assert node.value == 1
    assert node.style is ScalarStyle.PLAIN


def test_document_stream_styles_changed_documents_without_duplication():
    stream = load_documents("---\na: x\n---\nb: y\n")
    stream[0].node("a").style = "double"
    stream[1].node("b").style = "single"
    assert stream.dump() == '---\na: "x"\n---\nb: \'y\'\n'


def test_explicit_end_marker_is_reported_and_preserved():
    document = load_document("---\na: 1\n...\n")
    assert document.explicit_start is True
    assert document.explicit_end is True
    assert document.dump() == "---\na: 1\n...\n"
