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
    documents = py.load_all("---\na: 1\n---\nb: 2\n", Loader=None)
    assert documents == [{"a": 1}, {"b": 2}]


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
    assert py.round_trip_load_all(source) == py.load_all(source)
    assert py.round_trip_dump(py.load(source)) == py.dump(py.load(source))
    assert py.round_trip_dump_all(py.load_all(source)) == py.dump_all(py.load_all(source))


def test_round_trip_load_is_the_same_callable_as_load():
    assert py.round_trip_load is py.load
    assert py.round_trip_load_all is py.load_all