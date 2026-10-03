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

"""Container-protocol mutations, root replacement, bounds and node refs."""

from __future__ import annotations

import pytest

from pythonizeyaml import (
    AliasError,
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
    assert document["x"] == 9
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


# -- reads ---------------------------------------------------------------------


def test_chained_subscripts_read_nested_values():
    document = load_document("service:\n  ports: [8080, 8081]\n")
    assert document["service"]["ports"][0] == 8080


def test_get_reads_nested_paths_with_a_default():
    document = load_document("a:\n  b: 1\n")
    assert document.get("a") == {"b": 1}
    assert document.get(("a", "b")) == 1
    assert document.get("missing", "fallback") == "fallback"
    assert document.get(("a", "missing")) is None


def test_a_missing_path_raises_path_error_and_get_falls_back():
    document = load_document("a: 1\n")
    with pytest.raises(PathError):
        document["b"]
    with pytest.raises(PathError):
        document["b"]
    assert document.get("b") is None
    assert dict(document.data) == {"a": 1}


# -- failed mutations leave the document untouched ---------------------------


def test_failed_node_update_leaves_the_data_unchanged():
    document = load_document("a: 1\n")
    with pytest.raises(StyleError):
        document["a"].set(value=42, inline="not a comment")
    assert dict(document.data) == {"a": 1}
    assert document.dump() == "a: 1\n"


def test_failed_style_assignment_leaves_the_value_unchanged():
    document = load_document("a: 1\n")
    with pytest.raises(StyleError):
        document["a"].set(value=2, style="literal")
    assert dict(document.data) == {"a": 1}
    assert document.dump() == "a: 1\n"


def test_failed_node_update_leaves_a_sequence_unchanged():
    document = load_document("items:\n  - 1\n")
    node = document["items"][0]
    with pytest.raises(StyleError):
        node.set(value=9, style=ScalarStyle.LITERAL)
    assert list(document.data["items"]) == [1]


# -- sequence edits through the container -------------------------------------


def test_container_append_dumps_the_new_item():
    document = load_document("items:\n  - 1\n  - 2\n")
    document["items"].append(3)
    assert list(document.data["items"]) == [1, 2, 3]
    assert document.dump() == "items:\n  - 1\n  - 2\n  - 3\n"


def test_styling_a_container_appended_item():
    document = load_document("items:\n  - 1\n  - 2\n")
    document["items"].append("note")
    document["items"][2].style = "double"
    assert document.dump() == 'items:\n  - 1\n  - 2\n  - "note"\n'


def test_insert_follows_list_index_semantics():
    document = load_document("items:\n  - 1\n  - 2\n")
    document["items"].insert(99, "end")
    document["items"].insert(-5, "start")
    assert list(document.data["items"]) == ["start", 1, 2, "end"]


def test_insert_at_the_end_position_appends():
    document = load_document("items:\n  - 1\n  - 2\n")
    document["items"].insert(2, 3)
    assert list(document.data["items"]) == [1, 2, 3]


def test_insert_with_a_negative_index_follows_list_semantics():
    document = load_document("items:\n  - 1\n  - 2\n")
    document["items"].insert(-1, "x")
    assert list(document.data["items"]) == [1, "x", 2]


def test_sequence_root_supports_list_operations():
    document = load_document("- one\n- two\n")
    document.append("three")
    document.insert(0, "zero")
    assert document.dump() == "- zero\n- one\n- two\n- three\n"
    del document[0]
    assert list(document.data) == ["one", "two", "three"]


# -- removal reindexes sibling overrides ---------------------------------------


def test_del_shifts_sibling_style_overrides_in_the_registries():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document["items"][2].style = "single"
    del document["items"][0]
    assert document._styles == {("items", 1): ScalarStyle.SINGLE}
    assert document["items"][1].style is ScalarStyle.SINGLE
    assert document["items"][1].value == "three"


def test_del_drops_overrides_of_the_removed_item():
    document = load_document("items:\n  - one\n  - two\n")
    document["items"][0].style = "single"
    del document["items"][0]
    assert document._styles == {}


def test_del_shifts_sibling_comment_overrides():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document["items"][2].comments.inline = "# third"
    del document["items"][0]
    assert document._comments == {("items", 1): {"before": [], "inline": "# third", "after": []}}


def test_del_on_a_mapping_root_discards_overrides_below_the_key():
    document = load_document("a:\n  b: one\nx: two\n")
    document["a"]["b"].style = "single"
    del document["a"]
    assert document._styles == {}
    assert document.dump() == "x: two\n"


def test_nested_del_discards_overrides_below_the_removed_node():
    document = load_document("a:\n  b: one\n  c: two\n")
    document["a"]["b"].style = "single"
    del document["a"]["b"]
    assert document._styles == {}
    assert document.dump() == "a:\n  c: two\n"


def test_dump_after_del_with_sibling_overrides_does_not_raise():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document["items"][2].style = "single"
    del document["items"][0]
    # The style override must survive the removal; the exact emitted text for a
    # list that shrank *and* carries a style patch needs the native patcher to
    # reconcile structural edits with overrides (Gate 2 native work).
    assert isinstance(document.dump(), str)


def test_removed_style_override_patch_targets_the_shifted_item():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document["items"][2].style = "single"
    del document["items"][0]
    patches = document._build_patches(document._config)
    assert len(patches) == 1
    start, end, text = patches[0]
    # The single-quote replacement is positioned exactly on "three", which
    # moved from index 2 to index 1.
    assert document.source[start:end] == "three"
    assert text == "'three'"


def test_removed_style_override_is_applied_to_the_shifted_item():
    document = load_document("items:\n  - one\n  - two\n  - three\n")
    document["items"][2].style = "single"
    del document["items"][0]
    assert document.dump() == "items:\n  - two\n  - 'three'\n"


# -- aliases and removal ---------------------------------------------------------


def test_del_refuses_to_remove_a_node_that_still_has_aliases():
    document = load_document("a: &anc 1\nb: 2\n")
    document.alias("copy", target=document["a"])
    with pytest.raises(AliasError):
        del document["a"]
    assert document.dump() == "a: &anc 1\nb: 2\ncopy: *anc\n"


def test_del_removes_an_alias_entry():
    document = load_document("a: &anc 1\nb: 2\n")
    document.alias("copy", target=document["a"])
    del document["copy"]
    assert document.dump() == "a: &anc 1\nb: 2\n"


# -- structural additions survive external style patches ------------------------
#
# With external patches the native patcher skips Python-created items instead
# of rewriting their containers, and dump() re-inserts the additions itself.


def test_append_survives_a_sibling_style_override():
    document = load_document("items:\n  - one\n  - two\n")
    document["items"][0].style = "single"
    document["items"].append("three")
    assert document.dump() == "items:\n  - 'one'\n  - two\n  - three\n"


def test_insert_at_the_front_survives_a_sibling_style_override():
    document = load_document("items:\n  - one\n  - two\n")
    document["items"][1].style = "double"
    document["items"].insert(0, "zero")
    assert document.dump() == 'items:\n  - zero\n  - one\n  - "two"\n'


def test_new_mapping_key_survives_a_sibling_style_override():
    document = load_document("a: one\nb: two\n")
    document["a"].style = "single"
    document["c"] = "three"
    assert document.dump() == "a: 'one'\nb: two\nc: three\n"


def test_new_nested_mapping_value_survives_a_sibling_style_override():
    document = load_document("a: one\n")
    document["a"].style = "single"
    document["build"] = {"command": "python -m build", "jobs": 2}
    assert document.dump() == (
        "a: 'one'\nbuild:\n  command: python -m build\n  jobs: 2\n"
    )


def test_consecutive_appends_survive_a_style_override_outside_the_list():
    document = load_document("items:\n  - one\nother: x\n")
    document["other"].style = "double"
    document["items"].append("two")
    document["items"].append("three")
    assert document.dump() == 'items:\n  - one\n  - two\n  - three\nother: "x"\n'


def test_plain_list_replacement_survives_a_style_override_outside_the_list():
    document = load_document("items:\n  - one\n  - two\nother: x\n")
    document["other"].style = "double"
    document["items"] = ["y", "z"]
    assert document.dump() == 'items:\n  - y\n  - z\nother: "x"\n'


def test_shorter_plain_list_replacement_survives_a_style_override():
    document = load_document("items:\n  - one\n  - two\nother: x\n")
    document["other"].style = "double"
    document["items"] = ["y"]
    assert document.dump() == 'items:\n  - y\nother: "x"\n'


def test_nested_sequence_additions_survive_a_style_override_outside():
    document = load_document("matrix:\n  - - 1\n    - 2\nother: x\n")
    document["other"].style = "double"
    document["matrix"][0].append(3)
    document["matrix"].append([9])
    assert document.dump() == (
        "matrix:\n  - - 1\n    - 2\n    - 3\n  -\n    - 9\nother: \"x\"\n"
    )


def test_styling_an_inner_item_and_appending_to_its_list():
    document = load_document("matrix:\n  - - a\n    - b\nother: x\n")
    document["matrix"][0][0].style = "single"
    document["matrix"][0].append("c")
    assert document.dump() == (
        "matrix:\n  - - 'a'\n    - b\n    - c\nother: x\n"
    )


def test_an_alias_entry_addition_survives_a_style_override():
    document = load_document("base: &anc 1\nitems:\n  - one\nother: x\n")
    document["other"].style = "double"
    document.alias("copy", target=document["base"])
    assert document.dump() == 'base: &anc 1\nitems:\n  - one\nother: "x"\ncopy: *anc\n'


def test_sequence_root_append_survives_an_item_style_override():
    document = load_document("- one\n- two\n")
    document[0].style = "single"
    document.append("three")
    assert document.dump() == "- 'one'\n- two\n- three\n"


# -- inline comment validation -------------------------------------------------


def test_inline_comment_validation_rejects_newlines():
    document = load_document("a: 1\n")
    with pytest.raises(StyleError):
        document["a"].comments.inline = "x\ny"
    assert dict(document.data) == {"a": 1}
    assert document.dump() == "a: 1\n"


# -- value identity -----------------------------------------------------------


def test_node_ref_follows_its_node_after_an_insert():
    document = load_document("items:\n  - one\n  - two\n")
    ref = document["items"][1]
    document["items"].insert(0, "zero")
    assert ref.path == ("items", 2)
    assert ref.value == "two"


def test_node_ref_can_update_its_node_after_an_insert():
    document = load_document("items:\n  - one\n  - two\n")
    ref = document["items"][1]
    document["items"].insert(0, "zero")
    ref.value = "TWO"
    assert list(document.data["items"]) == ["zero", "one", "TWO"]


def test_node_ref_raises_after_its_node_is_removed():
    document = load_document("items:\n  - one\n  - two\n")
    ref = document["items"][1]
    del document["items"][1]
    with pytest.raises(PathError):
        ref.value


def test_value_resolves_by_identity_even_without_a_handle():
    document = Document.new({"items": ["one", "two"]})
    ref = document["items"][1]
    document["items"].insert(0, "zero")
    # Identity resolution needs no native node ids: the wrapper follows its
    # own value through the shift.
    assert ref.path == ("items", 2)
    assert ref.value == "two"


# -- surgical insertions and removals (no canonical re-render) -----------------


def test_new_root_key_after_a_block_valued_sibling_keeps_the_source():
    source = "# top\nfoo:\n  bar: 1   # keep me\nlist:\n  - a\n  - b\nservers:\n  - host: h1\n"
    document = load_document(source)
    document["alpha"] = 1
    assert document.dump() == source + "alpha: 1\n"


def test_a_new_chain_keeps_sibling_comments_and_indentation():
    source = "# top\nfoo:\n  bar: 1   # keep me\nlist:\n  - a\n  - b\n"
    document = load_document(source)
    document["a"] = {"b": {"c": "hello"}}
    assert document.dump() == source + "a:\n  b:\n    c: hello\n"


def test_consecutive_new_keys_keep_their_order():
    source = "a: 1\nlist:\n  - x\n"
    document = load_document(source)
    document["alpha"] = 1
    document["zzz"] = 2
    assert document.dump() == source + "alpha: 1\nzzz: 2\n"


def test_appending_to_a_sequence_of_mappings_keeps_the_compact_form():
    source = "servers:\n  - host: h1\n    port: 80\n"
    document = load_document(source)
    document["servers"].append({"host": "h2", "port": 81})
    assert document.dump() == "servers:\n  - host: h1\n    port: 80\n  - host: h2\n    port: 81\n"


def test_removing_a_block_valued_entry_keeps_nested_comments():
    source = "# top\nfoo:\n  bar: 1   # keep me\n  baz: hello\nlist:\n  - a\nservers:\n  - host: h1\n"
    document = load_document(source)
    del document["servers"]
    assert document.dump() == "# top\nfoo:\n  bar: 1   # keep me\n  baz: hello\nlist:\n  - a\n"


def test_removal_and_addition_in_one_dump():
    source = "keep: 1\ndrop:\n  deep: true\n"
    document = load_document(source)
    del document["drop"]
    document["added"] = 2
    assert document.dump() == "keep: 1\nadded: 2\n"


def test_merge_key_resolved_entries_are_not_patched_in():
    # ``<<`` resolves into real data entries at load; a dump of an untouched
    # document must stay verbatim, and the resolved entries must never be
    # patched into the text as if the user had added them. Editing one of the
    # mapping's own entries keeps the source ``<<`` line and patches only the
    # edited value.
    source = "base: &base {x: 1}\nmerged:\n  <<: *base\n  y: 2\n"
    document = load_document(source)
    assert document.dump() == source
    document["merged"]["y"] = 3
    assert document.dump() == "base: &base {x: 1}\nmerged:\n  <<: *base\n  y: 3\n"


# -- inline comments on non-scalar entries -------------------------------------


def test_inline_comment_on_a_block_valued_entry_keeps_the_block():
    document = load_document("foo:\n  bar: 1\n  baz: 2\nlist:\n  - a\n")
    document["foo"].comments.inline = "# group"
    assert document.dump() == "foo:  # group\n  bar: 1\n  baz: 2\nlist:\n  - a\n"


def test_inline_comment_replaces_an_existing_key_line_comment():
    document = load_document("foo:  # old\n  bar: 1\n")
    document["foo"].comments.inline = "# new"
    assert document.dump() == "foo:  # new\n  bar: 1\n"


def test_inline_comment_on_a_scalar_entry_is_unchanged():
    document = load_document("a: 1   # keep me\nb: 2\n")
    document["a"].comments.inline = "# changed"
    assert document.dump() == "a: 1  # changed\nb: 2\n"


def test_inline_comment_on_a_block_scalar_lands_on_the_header():
    document = load_document("desc: |\n  text\n")
    document["desc"].comments.inline = "# note"
    dumped = document.dump()
    assert dumped == "desc: |  # note\n  text\n"
    assert document.data["desc"] == "text\n"


def test_inline_comment_on_a_sequence_item_keeps_the_item():
    document = load_document("list:\n  - a\n  - b\n")
    document["list"][0].comments.inline = "# first"
    assert document.dump() == "list:\n  - a  # first\n  - b\n"


def test_removing_the_last_child_of_an_entry_renders_an_empty_collection():
    document = load_document("a:\n  b:\n    c: 1\n")
    del document["a"]["b"]["c"]
    assert document.dump() == "a:\n  b: {}\n"
    assert document.data == {"a": {"b": {}}}


def test_removing_the_last_item_of_a_sequence_renders_an_empty_sequence():
    document = load_document("list:\n  - only\n")
    del document["list"][0]
    assert document.dump() == "list: []\n"
    assert document.data == {"list": []}


def test_removing_entries_from_a_non_empty_parent_adds_no_empty_render():
    document = load_document("a:\n  b: 1\n  c: 2\n")
    del document["a"]["c"]
    assert document.dump() == "a:\n  b: 1\n"


def test_inline_comment_on_an_anchored_block_entry_keeps_the_anchor():
    document = load_document("foo: &f\n  bar: 1\n")
    document["foo"].comments.inline = "# group"
    dumped = document.dump()
    assert dumped == "foo: &f  # group\n  bar: 1\n"
    assert document.data["foo"] == {"bar": 1}


def test_clearing_an_inline_comment_wipes_it():
    document = load_document("a: 1   # old\nb: 2\n")
    document["a"].comments.inline = None
    assert document.dump() == "a: 1\nb: 2\n"


def test_clearing_an_inline_comment_on_a_block_entry_wipes_it():
    document = load_document("foo:  # old\n  bar: 1\n")
    document["foo"].comments.inline = None
    assert document.dump() == "foo:\n  bar: 1\n"


def test_after_comments_on_a_block_valued_entry_land_past_the_block():
    document = load_document("foo:\n  bar: 1\nnext: 2\n")
    document["foo"].comments.after = "# end of foo"
    assert document.dump() == "foo:\n  bar: 1\n# end of foo\nnext: 2\n"
