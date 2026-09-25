"""Requirement 1: a load/dump round trip preserves the source byte for byte.

The whole fixture corpus is swept here: one test id per fixture file.
"""

from __future__ import annotations

import io

import pythonizeyaml as py

# Fixture names that must be present for the corpus to be meaningful.
EXPECTED_FIXTURES = {
    "simple_2space.yaml",
    "simple_4space.yaml",
    "comments.yaml",
    "scalar_styles.yaml",
    "block_scalars.yaml",
    "sequence_offset.yaml",
    "sequence_flush.yaml",
    "multi_document.yaml",
    "rich.yaml",
    "plain_types.yaml",
    "no_trailing_newline.yaml",
}


def test_corpus_covers_the_expected_fixtures(fixtures_dir):
    names = {path.name for path in fixtures_dir.glob("*.yaml")}
    assert EXPECTED_FIXTURES <= names


def test_the_corpus_is_not_empty(fixtures_dir):
    assert len(list(fixtures_dir.glob("*.yaml"))) == len(EXPECTED_FIXTURES)


def test_a_file_without_a_trailing_newline_keeps_it_that_way(read_fixture):
    source = read_fixture("no_trailing_newline.yaml")
    assert not source.endswith("\n")
    assert py.dump(py.load(source)) == source


def test_a_file_with_a_trailing_newline_keeps_it_that_way(read_fixture):
    source = read_fixture("simple_2space.yaml")
    assert source.endswith("\n")
    assert py.dump(py.load(source)) == source


def test_fixture_text_is_preserved_byte_for_byte(fixture_path, fixture_text):
    documents = py.load_all(fixture_text)
    assert py.dump_all(documents) == fixture_text
    if len(documents) == 1:
        assert py.dump(py.load(fixture_text)) == fixture_text


def test_round_trip_to_a_stream_is_identical(fixture_path, fixture_text):
    documents = py.load_all(fixture_text)
    stream = io.StringIO()
    assert py.dump_all(documents, stream=stream) is None
    assert stream.getvalue() == fixture_text


def test_round_trip_is_stable_across_repeated_loads(fixture_path, fixture_text):
    """A second round trip must not drift (e.g. by re-detecting indentation)."""
    once = py.dump_all(py.load_all(fixture_text))
    twice = py.dump_all(py.load_all(once))
    assert twice == once == fixture_text