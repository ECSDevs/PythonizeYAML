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

"""Failed mutations, root replacement, bounds, list removal and node refs."""

from __future__ import annotations

import pytest

from pythonizeyaml import (
    Document,
    PathError,
    ScalarStyle,
    StyleError,
    load_document,
)


# -- root value replacement ------------------------------------------------


def test_root_value_replacement_is_emitted():
    document = load_document("old\n")
    document.value = "new"
    assert document.value == "new"
    assert document.dump() == "new\n"


def test_root_value_replacement_works_for_mapping_roots():
    document = load_document("a: 1\nb: 2\n")
    document.value = {"x": 9}
    assert document.at("x") == 9
    assert dict(document.data) == {"x": 9}
    assert document.dump() == "x: 9\n"


def test_root_value_replacement_works_for_sequence_roots():
    document = load_document("- 1\n- 2\n")
    document.value = [7]
    assert list(document.data) == [7]
    assert document.dump() == "- 7\n"


# -- str() coercions ---------------------------------------------------------


def test_str_of_a_mapping_root_returns_the_dump_text():
    assert str(load_document("a: 1\nb: two\n")) == "a: 1\nb: two\n"


def test_str_of_a_sequence_root_returns_the_dump_text():
    assert str(load_document("- 1\n- 2\n")) == "- 1\n- 2\n"


def test_str_of_a_scalar_root_returns_the_scalar_string():
    assert str(load_document("42\n")) == "42"
    assert str(load_document("hello\n")) == "hello"


# -- failed mutations leave the document untouched ---------------------------


def test_failed_set_leaves_the_data_unchanged():
    document = load_document("a: 1\n")
    with pytest.raises(StyleError):
        document.set("a", value=42, inline="not a comment")
    assert dict(document.data) == {"a": 1}
    assert document.dump() == "a: 1\n"


def test_failed_append_leaves_the_sequence_unchanged():
    document = load_document("items:\n  - 1\n  - 2\n")
    with pytest.raises(StyleError):
        document.append("items", value=3, style=ScalarStyle.LITERAL)
    assert list(document.data["items"]) == [1, 2]
    assert document.dump() == "items:\n  - 1\n  - 2\n"


def test_failed_set_does_not_create_the_path():
    document = load_document("a: 1\n")
    with pytest.raises(StyleError):
        document.set("b", value="x", style="double", chomping="keep")
    assert dict(document.data) == {"a": 1}
    assert "b" not in document.keys()


def test_failed_set_below_a_scalar_raises_path_error_without_mutation():
    document = load_document("a: 1\n")
    with pytest.raises(PathError):
        document.set(("a", "b"), value=2)
    assert dict(document.data) == {"a": 1}


def test_failed_node_update_leaves_the_data_unchanged():
    document = load_document("items:\n  - 1\n")
    node = document.node("items", 0)
    with pytest.raises(StyleError):
        node.update(value=9, style=ScalarStyle.LITERAL)
    assert list(document.data["items"]) == [1]


# -- insert bounds ------------------------------------------------------------


def test_insert_with_an_out_of_range_index_raises_path_error():
    document = load_document("items:\n  - 1\n  - 2\n")
    with pytest.raises(PathError):
        document.insert("items", index=99, value="x")
    assert list(document.data["items"]) == [1, 2]


def test_insert_with_an_out_of_range_negative_index_raises_path_error():
    document = load_document("items:\n  - 1\n  - 2\n")
    with pytest.raises(PathError):
        document.insert("items", index=-5, value="x")
    assert list(document.data["items"]) == [1, 2]


def test_insert_at_the_end_position_appends():
    document = load_document("items:\n  - 1\n  - 2\n")
    document.insert("items", index=2, value=3)
    assert list(document.data["items"]) == [1, 2, 3]


def test_insert_with_a_negative_index_follows_list_semantics():
    document = load_document("items:\n  - 1\n  - 2\n")
    document.insert("items", index=-1, value="x")
    assert list(document.data["items"]) == [1, "x", 2]


# -- remove() reindexes sibling overrides -------------------------------------


def test_remove_shifts_sibling_style_overrides_in_the_registries():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document.node("items", 2).style = "single"
    document.remove("items", 0)
    assert document._styles == {("items", 1): ScalarStyle.SINGLE}
    assert document.node("items", 1).style is ScalarStyle.SINGLE
    assert document.node("items", 1).value == "three"


def test_remove_drops_overrides_of_the_removed_item():
    document = load_document("items:\n  - one\n  - two\n")
    document.node("items", 0).style = "single"
    document.remove("items", 0)
    assert document._styles == {}


def test_remove_shifts_sibling_comment_overrides():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document.node("items", 2).comments.inline = "# third"
    document.remove("items", 0)
    assert document._comments == {("items", 1): {"before": [], "inline": "# third", "after": []}}


def test_dump_after_remove_with_sibling_overrides_does_not_raise():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document.node("items", 2).style = "single"
    document.remove("items", 0)
    # The style override must survive the removal; the exact emitted text for a
    # list that shrank *and* carries a style patch needs the native patcher to
    # reconcile structural edits with overrides (Gate 2 native work).
    assert isinstance(document.dump(), str)


def test_removed_style_override_patch_targets_the_shifted_item():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document.node("items", 2).style = "single"
    document.remove("items", 0)
    patches = document._build_patches(document._config)
    assert len(patches) == 1
    start, end, text = patches[0]
    # The single-quote replacement is positioned exactly on "three", which
    # moved from index 2 to index 1.
    assert document.source[start:end] == "three"
    assert text == "'three'"


def test_removed_style_override_is_applied_to_the_shifted_item():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document.node("items", 2).style = "single"
    document.remove("items", 0)
    assert document.dump() == "items:\n  - two\n  - 'three'\n"


# -- inline comment validation -------------------------------------------------


def test_set_rejects_inline_newlines_before_mutating():
    document = load_document("a: 1\n")
    with pytest.raises(StyleError):
        document.set("a", value=2, inline="x\ny")
    assert dict(document.data) == {"a": 1}
    assert document.dump() == "a: 1\n"


# -- NodeRef identity ----------------------------------------------------------


def test_node_ref_follows_its_node_after_an_insert():
    document = load_document("items:\n  - one\n  - two\n")
    ref = document.node("items", 1)
    document.insert("items", index=0, value="zero")
    assert ref.path == ("items", 2)
    assert ref.value == "two"


def test_node_ref_can_update_its_node_after_an_insert():
    document = load_document("items:\n  - one\n  - two\n")
    ref = document.node("items", 1)
    document.insert("items", index=0, value="zero")
    ref.value = "TWO"
    assert list(document.data["items"]) == ["zero", "one", "TWO"]


def test_node_ref_raises_after_its_node_is_removed():
    document = load_document("items:\n  - one\n  - two\n")
    ref = document.node("items", 1)
    document.remove("items", 1)
    with pytest.raises(PathError):
        ref.value


def test_node_ref_falls_back_to_the_cached_path_without_a_handle():
    document = Document.new({"items": ["one", "two"]})
    ref = document.node("items", 1)
    document.insert("items", index=0, value="zero")
    # No native handle, so no node identity: the ref stays bound to its path.
    assert ref.path == ("items", 1)
    assert ref.value == "one"
