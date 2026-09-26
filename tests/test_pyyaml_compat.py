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

"""Requirement 9: the module-level API stays PyYAML-compatible."""

from __future__ import annotations

import io

import pytest

import pythonizeyaml as py

DATA = {"a": 1, "items": [1, 2]}
PLAIN = "a: 1\nb: two\n"


# -- load -----------------------------------------------------------------


def test_load_accepts_loader_none():
    assert py.load(PLAIN, Loader=None) == {"a": 1, "b": "two"}


def test_load_ignores_an_explicit_loader():
    assert py.load(PLAIN, Loader=py.YAML) == {"a": 1, "b": "two"}


def test_load_all_accepts_loader_none():
    documents = list(py.load_all("---\na: 1\n---\nb: 2\n", Loader=None))
    assert documents == [{"a": 1}, {"b": 2}]


def test_load_all_returns_a_lazy_generator():
    class CountingStream:
        def __init__(self, text):
            self.text = text
            self.reads = 0

        def read(self):
            self.reads += 1
            return self.text

    stream = CountingStream("---\na: 1\n---\nb: 2\n")
    documents = py.load_all(stream)
    assert not isinstance(documents, list)
    assert stream.reads == 0  # nothing read until iteration starts
    assert list(documents) == [{"a": 1}, {"b": 2}]
    assert stream.reads == 1


def test_safe_load_all_returns_a_lazy_generator():
    class CountingStream:
        def __init__(self, text):
            self.text = text
            self.reads = 0

        def read(self):
            self.reads += 1
            return self.text

    stream = CountingStream("---\na: 1\n---\nb: 2\n")
    documents = py.safe_load_all(stream)
    assert stream.reads == 0
    assert list(documents) == [{"a": 1}, {"b": 2}]
    assert stream.reads == 1


# -- full_load / unsafe_load ------------------------------------------------


def test_full_load_returns_plain_data():
    data = py.full_load("a: 1\nb:\n  - x\n")
    assert data == {"a": 1, "b": ["x"]}
    assert type(data) is dict
    assert type(data["b"]) is list


def test_full_load_wraps_unknown_tags_as_inert_tagged_values():
    from pythonizeyaml import Tagged

    data = py.full_load("value: !app/example payload\n")
    assert data["value"] == Tagged("!app/example", "payload")


def test_full_load_never_constructs_arbitrary_objects():
    from pythonizeyaml import Tagged

    data = py.full_load("value: !!python/object/apply:os.system ['echo hi']\n")
    assert isinstance(data["value"], Tagged)


def test_full_load_of_a_scalar_stream_returns_the_scalar():
    assert py.full_load("42\n") == 42
    assert type(py.full_load("42\n")) is int


def test_full_load_all_yields_plain_documents():
    documents = list(py.full_load_all("---\na: 1\n---\nb: 2\n"))
    assert documents == [{"a": 1}, {"b": 2}]
    assert all(type(document) is dict for document in documents)


def test_unsafe_load_matches_full_load():
    source = "a: 1\nvalue: !app/example payload\n"
    assert py.unsafe_load(source) == py.full_load(source)
    assert list(py.unsafe_load_all("---\na: 1\n---\nb: 2\n")) == list(
        py.full_load_all("---\na: 1\n---\nb: 2\n")
    )


def test_unsafe_load_documents_that_it_never_constructs_objects():
    for function in (py.unsafe_load, py.unsafe_load_all):
        assert "arbitrary" in function.__doc__.lower()
        assert "intentionally" in function.__doc__.lower()


# -- dump signature parity ---------------------------------------------------


def test_dump_accepts_the_dumper_positional_slot():
    assert py.dump(DATA, None, None) == py.dump(DATA)
    assert py.dump(DATA, Dumper=int) == py.dump(DATA)
    assert py.dump_all([DATA], None, None) == py.dump_all([DATA])
    assert py.safe_dump(DATA, None, None) == py.safe_dump(DATA)
    assert py.safe_dump_all([DATA], None, None) == py.safe_dump_all([DATA])


def test_dump_accepts_explicit_end():
    assert py.dump(DATA, explicit_end=True) == py.dump(DATA) + "...\n"


def test_dump_accepts_explicit_start_and_end_together():
    assert py.dump(DATA, explicit_start=True, explicit_end=True) == (
        "---\n" + py.dump(DATA) + "...\n"
    )


def test_dump_all_accepts_explicit_end():
    text = py.dump_all([{"a": 1}, {"b": 2}], explicit_end=True)
    assert text == "a: 1\n...\n---\nb: 2\n...\n"


def test_dump_all_accepts_explicit_start_and_end_together():
    text = py.dump_all([{"a": 1}, {"b": 2}], explicit_start=True, explicit_end=True)
    assert text == "---\na: 1\n...\n---\nb: 2\n...\n"


def test_safe_dump_accepts_explicit_end():
    assert py.safe_dump(DATA, explicit_end=True) == py.safe_dump(DATA) + "...\n"


def test_dump_accepts_explicit_end_for_documents():
    document = py.load_document("a: 1\n")
    assert py.dump(document, explicit_end=True) == "a: 1\n...\n"
    assert py.dump(document, explicit_end=False) == "a: 1\n"


# -- scalar documents behave like their values -------------------------------


def test_loaded_scalar_documents_are_hashable():
    number = py.load_document("42\n")
    text = py.load_document("hello\n")
    assert hash(number) == hash(42)
    assert hash(text) == hash("hello")
    mapping = {number: "from document", 42: "plain"}
    assert len(mapping) == 1  # equal keys collapse
    assert mapping[number] == "plain"


def test_load_accepts_bytes():
    assert py.load(b"a: 1\n") == {"a": 1}


def test_load_accepts_a_file_like_stream(fixtures_dir):
    with (fixtures_dir / "simple_2space.yaml").open(encoding="utf-8") as handle:
        data = py.load(handle)
    assert data["server"]["host"] == "localhost"


# -- dump -----------------------------------------------------------------


def test_dump_returns_str_when_no_stream_is_given():
    result = py.dump(DATA)
    assert isinstance(result, str)
    assert result.endswith("\n")


def test_dump_writes_to_the_stream_and_returns_none():
    stream = io.StringIO()
    assert py.dump(DATA, stream=stream) is None
    assert stream.getvalue() == py.dump(DATA)


def test_dump_all_writes_to_the_stream_and_returns_none():
    stream = io.StringIO()
    assert py.dump_all([DATA, DATA], stream=stream) is None
    assert stream.getvalue() == py.dump_all([DATA, DATA])


def test_dump_accepts_width():
    assert py.dump(DATA, width=1000) == py.dump(DATA)


def test_dump_accepts_explicit_start():
    out = py.dump(DATA, explicit_start=True)
    assert out.startswith("---\n")
    assert py.load(out) == DATA


def test_dump_accepts_explicit_start_false():
    assert not py.dump(DATA, explicit_start=False).startswith("---")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sort_keys": True},
        {"default_flow_style": False},
        {"allow_unicode": True},
        {"sort_keys": True, "default_flow_style": False, "allow_unicode": True},
    ],
)
def test_dump_accepts_and_ignores_pyyaml_keywords(kwargs):
    assert py.dump(DATA, **kwargs) == py.dump(DATA)


def test_dump_all_accepts_and_ignores_pyyaml_keywords():
    assert py.dump_all([DATA], sort_keys=True, allow_unicode=True) == py.dump_all([DATA])


def test_safe_dump_accepts_pyyaml_keywords():
    assert py.safe_dump(DATA, sort_keys=False, explicit_start=True).startswith("---\n")


@pytest.mark.parametrize("func", [py.dump, py.dump_all])
def test_unknown_keyword_raises_type_error(func):
    with pytest.raises(TypeError, match="not_a_real_keyword"):
        func(DATA, not_a_real_keyword=1)


def test_unknown_keyword_is_still_rejected_alongside_valid_ones():
    with pytest.raises(TypeError, match="also_fake"):
        py.dump(DATA, width=40, also_fake=True)


# -- aliases ---------------------------------------------------------------


def test_round_trip_spellings_exist_and_agree(fixtures_dir):
    source = (fixtures_dir / "rich.yaml").read_text(encoding="utf-8")
    assert py.round_trip_load(source) == py.load(source)
    assert list(py.round_trip_load_all(source)) == list(py.load_all(source))
    assert py.round_trip_dump(py.load(source)) == py.dump(py.load(source))
    assert py.round_trip_dump_all(list(py.load_all(source))) == py.dump_all(list(py.load_all(source)))


def test_round_trip_load_is_the_same_callable_as_load():
    assert py.round_trip_load is py.load
    assert py.round_trip_load_all is py.load_all