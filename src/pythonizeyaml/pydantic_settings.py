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

"""Optional pydantic-settings integration: :class:`YAMLSettings`.

This module requires ``pydantic-settings`` (``pip install
pythonizeyaml[pydantic-settings]``). The public names are also exported lazily
from the package root when pydantic-settings is importable.

:class:`YAMLSettings` adds a YAML settings source to
:class:`pydantic_settings.BaseSettings`, read with pythonizeyaml's own parser.
Source priority follows BaseSettings conventions: init values, environment
variables, dotenv, the YAML file(s), then the secrets directory.
"""

from __future__ import annotations

import os
from typing import Any, Optional, Sequence, Union

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from .api import safe_load
from .document import Document, _plain_value
from .pydantic import (
    _ANCHOR_ATTR,
    YAMLSerializationMixin,
    _load_single_document,
    _sync_plain_mapping,
)

__all__ = ["YAMLSettings", "YAMLSettingsSource", "YAMLSettingsConfigDict"]

#: One path, or an ordered sequence of paths (later files override earlier keys).
YamlFile = Union[str, "os.PathLike[str]"]


class YAMLSettingsConfigDict(SettingsConfigDict, total=False):
    """A :class:`pydantic_settings.SettingsConfigDict` with a ``yaml_file`` key.

    >>> model_config = YAMLSettingsConfigDict(yaml_file="app.yaml")
    """

    yaml_file: Union[YamlFile, Sequence[YamlFile]]


def _yaml_files(value: Any) -> list[str]:
    """Normalize a ``yaml_file`` config value into a list of path strings."""
    if value is None:
        return []
    if isinstance(value, (str, os.PathLike)):
        return [os.fspath(value)]
    return [os.fspath(path) for path in value]


class YAMLSettingsSource(YamlConfigSettingsSource):
    """A YAML settings source parsed with pythonizeyaml instead of PyYAML.

    Accepts everything the built-in ``YamlConfigSettingsSource`` accepts
    (``yaml_file``, ``yaml_file_encoding``, ``yaml_config_section``,
    ``deep_merge``) and reads the same ``model_config["yaml_file"]`` key; only
    the parser differs. Files are read with pythonizeyaml's safe engine, so
    unknown application tags are rejected with
    :class:`~pythonizeyaml.errors.ConstructorError` instead of being loaded,
    and missing files are silently skipped (BaseSettings file-source
    convention). PyYAML is never imported.
    """

    def _read_file(self, file_path):
        with file_path.open(encoding=self.yaml_file_encoding or "utf-8") as handle:
            loaded = safe_load(handle)
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(
                f"YAML settings file {file_path} must contain a mapping, "
                f"found {type(loaded).__name__}"
            )
        return loaded


def _load_anchor(yaml_file: Any) -> Optional[Document]:
    """Re-parse the configured YAML files with the round-trip engine.

    The first existing mapping-root document becomes the style anchor; later
    files are merged into it without deleting keys. Returns ``None`` when no
    usable file is configured — the instance then dumps without source styles.
    """
    anchor: Optional[Document] = None
    for path in _yaml_files(yaml_file):
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            document = _load_single_document(handle)
        if document is None:
            continue
        if anchor is None:
            if isinstance(document, dict):
                anchor = document
            continue
        plain = _plain_value(document)
        if isinstance(plain, dict):
            _sync_plain_mapping(anchor, plain, delete_missing=False)
    return anchor


class YAMLSettings(YAMLSerializationMixin, BaseSettings):
    """A :class:`pydantic_settings.BaseSettings` subclass with a YAML source.

    >>> class Settings(YAMLSettings):
    ...     model_config = YAMLSettingsConfigDict(yaml_file="app.yaml")
    ...     host: str
    ...     port: int = 8080

    Source priority: init values, environment variables, dotenv, the YAML
    file(s), secrets directory. The instance keeps the parsed YAML document as
    a style anchor, so ``model_dump_yaml()`` reproduces the file byte-for-byte
    except for values provided by higher-priority sources (or changed after
    construction), which are re-emitted with default styling.
    """

    model_config = YAMLSettingsConfigDict()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YAMLSettingsSource(settings_cls),
            file_secret_settings,
        )

    def __init__(self, *args: Any, **values: Any) -> None:
        super().__init__(*args, **values)
        anchor = _load_anchor(type(self).model_config.get("yaml_file"))
        if anchor is not None:
            object.__setattr__(self, _ANCHOR_ATTR, anchor)
