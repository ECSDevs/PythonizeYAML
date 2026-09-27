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

"""Tests for the optional pydantic integration: :class:`YAMLModel`."""

from __future__ import annotations

import io
import subprocess
import sys

import pytest

pydantic = pytest.importorskip("pydantic")

import pythonizeyaml as py  # noqa: E402
from pythonizeyaml import YAMLModel  # noqa: E402
from pydantic import Field, ValidationError  # noqa: E402

SOURCE = (
    "# app configuration\n"
    "host: db.example.com\n"
    "port: 5432        # backend port\n"
    "debug: false\n"
    "limits:\n"
    "  upload: '10MB'\n"
    "  retries: 3\n"
    "hosts:\n"
    "  - one\n"
    "  - two\n"
    "banner: |\n"
    "  hello\n"
    "  world\n"
)


class Limits(YAMLModel):
    upload: str
    retries: int = 3


class AppConfig(YAMLModel):
    host: str
    port: int = 8080
    debug: bool = False
    limits: Limits
    hosts: list[str] = []
    banner: str = ""


class AllDefaults(YAMLModel):
    a: int = 1
    b: str = "x"


class Minimal(YAMLModel):
    host: str
    port: int = 8080
    debug: bool = False


def test_model_validate_yaml_round_trips_exactly():
    assert AppConfig.model_validate_yaml(SOURCE).model_dump_yaml() == SOURCE


def test_model_validate_document_round_trips_exactly():
    document = py.load(SOURCE)
    assert AppConfig.model_validate(document).model_dump_yaml() == SOURCE


def test_model_validate_yaml_accepts_bytes():
    cfg = AppConfig.model_validate_yaml(SOURCE.encode("utf-8"))
    assert cfg.model_dump_yaml() == SOURCE


def test_model_validate_yaml_accepts_stream():
    cfg = AppConfig.model_validate_yaml(io.StringIO(SOURCE))
    assert cfg.model_dump_yaml() == SOURCE


def test_model_validate_yaml_accepts_file_stream(tmp_path):
    path = tmp_path / "app.yaml"
    path.write_text(SOURCE, encoding="utf-8")
    with path.open("r", encoding="utf-8") as handle:
        cfg = AppConfig.model_validate_yaml(handle)
    assert cfg.model_dump_yaml() == SOURCE


def test_model_dump_returns_a_document():
    cfg = AppConfig.model_validate_yaml(SOURCE)
    document = cfg.model_dump()
    assert isinstance(document, py.Document)
    assert isinstance(document, dict)
    assert document["host"] == "db.example.com"
    assert document["limits"]["retries"] == 3


def test_returned_document_is_editable():
    document = AppConfig.model_validate_yaml(SOURCE).model_dump()
    document["host"] = "edited.example.com"
    assert "host: edited.example.com" in document.dump()


def test_model_dump_yaml_writes_to_stream():
    buffer = io.StringIO()
    assert AppConfig.model_validate_yaml(SOURCE).model_dump_yaml(stream=buffer) is None
    assert buffer.getvalue() == SOURCE


def test_model_dump_yaml_with_encoding_returns_bytes():
    data = AppConfig.model_validate_yaml(SOURCE).model_dump_yaml(encoding="utf-8")
    assert isinstance(data, bytes)
    assert data == SOURCE.encode("utf-8")


def test_mutation_preserves_the_other_bytes():
    cfg = AppConfig.model_validate_yaml(SOURCE)
    cfg.port = 6000
    assert cfg.model_dump_yaml() == SOURCE.replace("5432", "6000")


def test_list_item_mutation_rewrites_only_that_item():
    cfg = AppConfig.model_validate_yaml(SOURCE)
    cfg.hosts[0] = "ONE"
    assert cfg.model_dump_yaml() == SOURCE.replace("  - one", "  - ONE")


def test_nested_field_mutation_rewrites_only_that_leaf():
    cfg = AppConfig.model_validate_yaml(SOURCE)
    cfg.limits.retries = 9
    assert cfg.model_dump_yaml() == SOURCE.replace("retries: 3", "retries: 9")


def test_defaults_absent_in_source_stay_absent():
    source = "# only host\nhost: h\n"
    cfg = Minimal.model_validate_yaml(source)
    assert cfg.model_dump_yaml() == source


def test_runtime_non_default_field_is_appended():
    source = "# only host\nhost: h\n"
    cfg = Minimal.model_validate_yaml(source)
    cfg.debug = True
    assert cfg.model_dump_yaml() == source + "debug: true\n"


def test_runtime_default_value_field_is_not_appended():
    source = "# only host\nhost: h\n"
    cfg = Minimal.model_validate_yaml(source)
    cfg.debug = False
    assert cfg.model_dump_yaml() == source


def test_ignored_extra_keys_are_preserved():
    source = "host: h\nlegacy: removed soon\n"
    assert Minimal.model_validate_yaml(source).model_dump_yaml() == source


def test_tagged_extra_values_are_preserved():
    source = "host: h\nextra: !app secret\n"
    assert Minimal.model_validate_yaml(source).model_dump_yaml() == source


def test_unknown_tag_on_declared_field_is_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate_yaml("host: !app secret\n")


def test_multi_document_stream_is_rejected():
    with pytest.raises(py.ComposerError):
        AppConfig.model_validate_yaml("host: a\n---\nhost: b\n")


def test_malformed_yaml_raises_a_yaml_error():
    with pytest.raises(py.YAMLError):
        AppConfig.model_validate_yaml("host: [unclosed\n")


def test_scalar_root_is_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate_yaml("just a string\n")


def test_empty_source_behaves_like_an_empty_mapping():
    assert AllDefaults.model_validate_yaml("").a == 1


def test_type_coercion_rewrites_only_that_value():
    source = "host: h\nport: '5432'\n"
    dumped = Minimal.model_validate_yaml(source).model_dump_yaml()
    assert dumped != source
    assert "port: 5432\n" in dumped
    assert "host: h\n" in dumped


def test_model_dump_without_anchor_emits_declaration_order():
    assert AllDefaults(a=2).model_dump_yaml() == "a: 2\nb: x\n"


def test_model_validate_plain_dict_has_no_anchor():
    cfg = AllDefaults.model_validate({"a": 3})
    assert cfg.model_dump_yaml() == "a: 3\nb: x\n"


def test_model_dump_kwargs_build_a_fresh_document():
    cfg = AppConfig.model_validate_yaml(SOURCE)
    fresh = cfg.model_dump(include={"host"})
    assert isinstance(fresh, py.Document)
    assert dict(fresh) == {"host": "db.example.com"}
    assert "limits" not in fresh


def test_exported_names_are_lazy():
    assert py.YAMLModel is YAMLModel
    assert "YAMLModel" in py.__all__


def test_pydantic_is_not_imported_eagerly():
    code = "import sys, pythonizeyaml; sys.exit(1 if 'pydantic' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_star_import_works_without_pydantic():
    code = (
        "import sys\n"
        "sys.modules['pydantic'] = None\n"
        "from pythonizeyaml import *\n"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_helpful_error_when_pydantic_is_missing():
    code = (
        "import sys\n"
        "sys.modules['pydantic'] = None\n"
        "import pythonizeyaml\n"
        "try:\n"
        "    pythonizeyaml.YAMLModel\n"
        "except ImportError as exc:\n"
        "    assert 'pythonizeyaml[pydantic]' in str(exc), str(exc)\n"
        "    print('ok')\n"
        "else:\n"
        "    raise SystemExit('expected ImportError')\n"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


# --- pretty dumps -----------------------------------------------------------


class PrettySpaced(YAMLModel):
    first: str = "a"
    mapping: dict[str, int] = Field(default_factory=lambda: {"x": 1})
    empty: dict[str, int] = Field(default_factory=dict)
    last: str = "z"


class PrettyNested(YAMLModel):
    host: str = Field("localhost", description="Address to bind")
    ports: list[int] = Field(default_factory=list)


class PrettyConfig(YAMLModel):
    debug: bool = False
    nested: PrettyNested
    name: str = "app"


class PrettyCarried(YAMLModel):
    name: str = "app"
    mode: str = "fast"


class PrettyInner(YAMLModel):
    beta: int = 2
    alpha: str = "a"


class PrettyOuter(YAMLModel):
    keep: str = "k"
    inner: PrettyInner


class PrettyStrict(YAMLModel):
    alpha: str = "a"


def test_pretty_generates_a_complete_ordered_document():
    assert PrettySpaced().model_dump_yaml(pretty=True) == (
        "first: a\n"
        "\n"
        "mapping:\n"
        "  x: 1\n"
        "\n"
        "empty: {}\n"
        "last: z\n"
    )


def test_pretty_fills_reorders_and_comments_from_source():
    source = "name: myapp\nnested:\n  ports: [8080]\n"
    assert PrettyConfig.model_validate_yaml(source).model_dump_yaml(pretty=True) == (
        "debug: false\n"
        "\n"
        "nested:\n"
        "  # Address to bind\n"
        "  host: localhost\n"
        "\n"
        "  ports:\n"
        "    - 8080\n"
        "\n"
        "name: myapp\n"
    )


def test_pretty_is_idempotent_through_revalidation():
    source = "name: myapp\nnested:\n  ports: [8080]\n"
    once = PrettyConfig.model_validate_yaml(source).model_dump_yaml(pretty=True)
    twice = PrettyConfig.model_validate_yaml(once).model_dump_yaml(pretty=True)
    assert twice == once


def test_pretty_carries_comments_with_their_entries():
    source = "# header\nmode: turbo  # inline note\n\n# tail comment\n"
    assert PrettyCarried.model_validate_yaml(source).model_dump_yaml(pretty=True) == (
        "name: app\n"
        "# header\n"
        "mode: turbo  # inline note\n"
        "# tail comment\n"
    )


def test_pretty_orders_nested_models_recursively():
    source = "inner:\n  alpha: x\n  beta: 1\n"
    assert PrettyOuter.model_validate_yaml(source).model_dump_yaml(pretty=True) == (
        "keep: k\n"
        "\n"
        "inner:\n"
        "  beta: 1\n"
        "  alpha: x\n"
    )


def test_pretty_appends_extra_keys_after_model_fields():
    source = "zeta: extra\nalpha: x\n"
    assert PrettyStrict.model_validate_yaml(source).model_dump_yaml(pretty=True) == (
        "alpha: x\nzeta: extra\n"
    )


def test_pretty_returns_a_document():
    document = PrettySpaced().model_dump(pretty=True)
    assert isinstance(document, py.Document)
    assert list(document) == ["first", "mapping", "empty", "last"]


def test_pretty_with_pydantic_keywords_skips_filling():
    cfg = Minimal.model_validate_yaml("host: h\n")
    assert cfg.model_dump(include={"host"}, pretty=True).dump() == "host: h\n"
    assert cfg.model_dump_yaml(pretty=True) == "host: h\nport: 8080\ndebug: false\n"


def test_pretty_multiline_description_renders_one_line_each():
    class Described(YAMLModel):
        host: str = Field("db", description="Database host.\nUse the service name.")

    assert Described().model_dump_yaml(pretty=True) == (
        "# Database host.\n"
        "# Use the service name.\n"
        "host: db\n"
    )


def test_pretty_spaces_sequence_items_with_containers():
    class SeqItem(YAMLModel):
        host: str = "h"
        ports: list[int] = Field(default_factory=lambda: [1])

    class SeqOuter(YAMLModel):
        items: list[SeqItem] = Field(default_factory=list)

    assert SeqOuter(items=[SeqItem()]).model_dump_yaml(pretty=True) == (
        "items:\n"
        "  -\n"
        "    host: h\n"
        "\n"
        "    ports:\n"
        "      - 1\n"
    )
