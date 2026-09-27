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

"""Tests for the optional pydantic-settings integration: :class:`YAMLSettings`."""

from __future__ import annotations

import subprocess
import sys

import pytest

pydantic = pytest.importorskip("pydantic")
pydantic_settings = pytest.importorskip("pydantic_settings")

import pythonizeyaml as py  # noqa: E402
from pythonizeyaml import YAMLSettings, YAMLSettingsConfigDict  # noqa: E402
from pythonizeyaml.pydantic_settings import YAMLSettingsSource  # noqa: E402
from pydantic import Field, ValidationError  # noqa: E402

SOURCE = (
    "# settings\n"
    "host: db.example.com\n"
    "port: 5432        # backend port\n"
    "debug: false\n"
)


def _settings_class(tmp_path, content=SOURCE, **config):
    path = tmp_path / "app.yaml"
    path.write_text(content, encoding="utf-8")

    class Settings(YAMLSettings):
        model_config = YAMLSettingsConfigDict(yaml_file=str(path), **config)
        host: str
        port: int = 8080
        debug: bool = False

    return Settings, path


def test_yaml_file_round_trips_exactly(tmp_path, monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    Settings, _path = _settings_class(tmp_path)
    settings = Settings()
    assert settings.host == "db.example.com"
    assert settings.port == 5432
    assert settings.model_dump_yaml() == SOURCE


def test_env_overrides_file_and_dump_rewrites_only_that_value(tmp_path, monkeypatch):
    monkeypatch.setenv("HOST", "env-host")
    Settings, _path = _settings_class(tmp_path)
    settings = Settings()
    assert settings.host == "env-host"
    assert settings.model_dump_yaml() == SOURCE.replace("db.example.com", "env-host")


def test_init_values_override_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    Settings, _path = _settings_class(tmp_path)
    settings = Settings(port=9999)
    assert settings.port == 9999
    assert settings.model_dump_yaml() == SOURCE.replace("5432", "9999")


def test_missing_file_is_silently_skipped(tmp_path):
    class Settings(YAMLSettings):
        model_config = YAMLSettingsConfigDict(yaml_file=str(tmp_path / "nope.yaml"))
        debug: bool = False

    assert Settings().debug is False


def test_missing_file_with_required_fields_reports_validation(tmp_path):
    class Settings(YAMLSettings):
        model_config = YAMLSettingsConfigDict(yaml_file=str(tmp_path / "nope.yaml"))
        host: str

    with pytest.raises(ValidationError):
        Settings()


def test_multiple_files_are_merged_in_order(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text("host: base\nport: 1\n", encoding="utf-8")
    override = tmp_path / "override.yaml"
    override.write_text("port: 2\n", encoding="utf-8")

    class Settings(YAMLSettings):
        model_config = YAMLSettingsConfigDict(yaml_file=[str(base), str(override)])
        host: str
        port: int

    settings = Settings()
    assert settings.host == "base"
    assert settings.port == 2
    assert settings.model_dump_yaml() == "host: base\nport: 2\n"


def test_malformed_file_raises_a_yaml_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("host: [unclosed\n", encoding="utf-8")

    class Settings(YAMLSettings):
        model_config = YAMLSettingsConfigDict(yaml_file=str(bad))
        host: str = "x"

    with pytest.raises(py.YAMLError):
        Settings()


def test_non_mapping_root_is_rejected(tmp_path):
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("just a string\n", encoding="utf-8")

    class Settings(YAMLSettings):
        model_config = YAMLSettingsConfigDict(yaml_file=str(scalar))
        debug: bool = False

    with pytest.raises(ValueError, match="must contain a mapping"):
        Settings()


def test_inherited_model_validate_yaml_round_trips(tmp_path):
    Settings, _path = _settings_class(tmp_path)
    settings = Settings.model_validate_yaml(SOURCE)
    assert settings.host == "db.example.com"
    assert settings.model_dump_yaml() == SOURCE


def test_yaml_settings_source_reads_the_config_key(tmp_path):
    Settings, path = _settings_class(tmp_path)
    data = YAMLSettingsSource(Settings)()
    assert data["host"] == "db.example.com"
    assert "yaml_file" in Settings.model_config
    assert str(path) == Settings.model_config["yaml_file"]


def test_exported_names_are_lazy():
    assert py.YAMLSettings is YAMLSettings
    assert "YAMLSettings" in py.__all__
    assert "YAMLSettingsConfigDict" in py.__all__


def test_star_import_works_without_pydantic_settings():
    code = (
        "import sys\n"
        "sys.modules['pydantic_settings'] = None\n"
        "from pythonizeyaml import *\n"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_helpful_error_when_pydantic_settings_is_missing():
    code = (
        "import sys\n"
        "sys.modules['pydantic_settings'] = None\n"
        "import pythonizeyaml\n"
        "try:\n"
        "    pythonizeyaml.YAMLSettings\n"
        "except ImportError as exc:\n"
        "    assert 'pythonizeyaml[pydantic-settings]' in str(exc), str(exc)\n"
        "    print('ok')\n"
        "else:\n"
        "    raise SystemExit('expected ImportError')\n"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def _pretty_settings_class(tmp_path, content="retries: 5\n"):
    path = tmp_path / "app.yaml"
    path.write_text(content, encoding="utf-8")

    class PrettySettings(YAMLSettings):
        model_config = YAMLSettingsConfigDict(yaml_file=str(path))
        host: str = "localhost"
        retries: int = Field(3, description="Retry count")

    return PrettySettings


def test_pretty_settings_reformat_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("RETRIES", raising=False)
    settings = _pretty_settings_class(tmp_path)()
    assert settings.model_dump_yaml(pretty=True) == (
        "host: localhost\n"
        "# Retry count\n"
        "retries: 5\n"
    )


def test_pretty_settings_reflect_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRIES", "9")
    settings = _pretty_settings_class(tmp_path)()
    assert settings.retries == 9
    assert settings.model_dump_yaml(pretty=True) == (
        "host: localhost\n"
        "# Retry count\n"
        "retries: 9\n"
    )
