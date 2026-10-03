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

"""The ``yaml <file> <get|set|del> <path> [value]`` command-line tool."""

from __future__ import annotations

import pytest

from pythonizeyaml.cli import main

CONF = """\
# top comment
foo:
  bar: 1   # keep me
  baz: hello
list:
  - a
  - b
servers:
  - host: h1
    port: 80
"""


@pytest.fixture
def conf(tmp_path):
    path = tmp_path / "conf.yaml"
    path.write_text(CONF, encoding="utf-8")
    return path


def read(path) -> str:
    return path.read_text(encoding="utf-8")


# -- get -------------------------------------------------------------------


def test_get_returns_scalars_and_collections(conf, capsys):
    assert main([str(conf), "get", "foo.bar"]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main([str(conf), "get", "list"]) == 0
    assert capsys.readouterr().out == "- a\n- b\n"
    assert main([str(conf), "get", "servers.0.host"]) == 0
    assert capsys.readouterr().out == "h1\n"


def test_get_missing_path_fails(conf, capsys):
    assert main([str(conf), "get", "nope.deep"]) == 1
    # The message names the deepest segment that could be resolved.
    assert "no YAML node at path nope" in capsys.readouterr().err


def test_get_into_a_scalar_fails(conf, capsys):
    assert main([str(conf), "get", "foo.bar.deep"]) == 1
    assert capsys.readouterr().err


# -- set -------------------------------------------------------------------


def test_set_existing_value_keeps_the_rest_byte_identical(conf):
    assert main([str(conf), "set", "servers.0.port", "8080"]) == 0
    assert read(conf) == CONF.replace("port: 80", "port: 8080")


def test_set_creates_the_missing_chain(conf):
    assert main([str(conf), "set", "a.b.c.d", "hello"]) == 0
    assert read(conf) == CONF + "a:\n  b:\n    c:\n      d: hello\n"


def test_set_on_an_empty_file(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    assert main([str(path), "set", "a.b", "1"]) == 0
    assert read(path) == "a:\n  b: 1\n"


def test_set_writes_into_sequence_items(conf):
    assert main([str(conf), "set", "servers.0.host", "h2"]) == 0
    assert read(conf) == CONF.replace("host: h1", "host: h2")


def test_set_missing_sequence_item_fails(conf, capsys):
    assert main([str(conf), "set", "list.5", "x"]) == 1
    assert "no sequence item at path list.5" in capsys.readouterr().err


def test_set_interprets_yaml_values(conf, capsys):
    for path, raw, expected in [
        ("t.int", "123", 123),
        ("t.bool", "true", True),
        ("t.float", "1.5", 1.5),
        ("t.null", "null", None),
        ("t.list", "[1, 2]", [1, 2]),
        ("t.str", "hello world", "hello world"),
        ("t.quoted", "'123'", "123"),
    ]:
        assert main([str(conf), "set", path, raw]) == 0
        assert main([str(conf), "get", path]) == 0
        assert capsys.readouterr().out.strip()
    import pythonizeyaml

    data = pythonizeyaml.safe_load(read(conf))
    assert data["t"] == {
        "int": 123,
        "bool": True,
        "float": 1.5,
        "null": None,
        "list": [1, 2],
        "str": "hello world",
        "quoted": "123",
    }


def test_set_on_a_root_scalar_replaces_it(tmp_path, capsys):
    path = tmp_path / "scalar.yaml"
    path.write_text("old\n", encoding="utf-8")
    assert main([str(path), "set", "a", "1"]) == 1
    assert "the document root is not a mapping" in capsys.readouterr().err


# -- del -------------------------------------------------------------------


def test_del_removes_a_nested_leaf(conf):
    assert main([str(conf), "del", "foo.bar"]) == 0
    assert read(conf) == CONF.replace("  bar: 1   # keep me\n", "")


def test_del_removes_a_block_valued_root_entry_without_losing_comments(conf):
    assert main([str(conf), "del", "servers"]) == 0
    assert read(conf) == CONF.replace("servers:\n  - host: h1\n    port: 80\n", "")


def test_del_removes_a_sequence_item(conf):
    assert main([str(conf), "del", "list.0"]) == 0
    assert read(conf) == CONF.replace("  - a\n", "")


def test_del_missing_path_fails(conf, capsys):
    assert main([str(conf), "del", "nope.x"]) == 1
    assert "no YAML node at path nope" in capsys.readouterr().err


# -- usage errors ----------------------------------------------------------


def test_usage_errors_exit_with_code_2(conf, capsys):
    for argv in (
        [],
        [str(conf)],
        [str(conf), "get"],
        [str(conf), "upsert", "a"],
        [str(conf), "get", "a..b"],
        [str(conf), "set", "a"],
        [str(conf), "set", "a", "1", "2"],
        [str(conf), "get", "a", "b"],
    ):
        assert main(argv) == 2, argv
        assert "usage:" in capsys.readouterr().err


def test_missing_file_fails(conf, capsys):
    missing = conf.with_name("nope.yaml")
    assert main([str(missing), "get", "a"]) == 1
    assert "no such file" in capsys.readouterr().err


def test_multi_document_files_are_rejected(tmp_path, capsys):
    path = tmp_path / "multi.yaml"
    path.write_text("a: 1\n---\nb: 2\n", encoding="utf-8")
    assert main([str(path), "get", "a"]) == 1
    assert "2 YAML documents" in capsys.readouterr().err


def test_help_flag(conf, capsys):
    assert main(["--help"]) == 0
    assert "usage:" in capsys.readouterr().out
