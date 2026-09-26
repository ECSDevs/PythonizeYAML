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

"""Python-facing engine wrappers around the native Rust implementation."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional

from . import _native
from .config import DEFAULT_CONFIG, IndentConfig
from .document import _has_explicit_end, _read_stream
from .errors import RepresenterError, YAMLError, translate_native_error

__all__ = ["YAML", "SafeYAML"]

Stream = Any


class _NativeBackend:
    """Per-engine native backend marker used to preserve engine isolation."""

    def __init__(self, typ: str) -> None:
        self.typ = typ

    def __repr__(self) -> str:
        return f"<pythonizeyaml native backend {self.typ}>"


class YAML:
    """A YAML engine whose default behavior is lossless round-trip preservation."""

    _backend_typ = "rt"

    def __init__(self, config: Optional[IndentConfig] = None) -> None:
        self.config = config if config is not None else DEFAULT_CONFIG
        self._backend = _NativeBackend(self._backend_typ)

    def load(self, stream: Stream) -> Any:
        from .document import _make_document

        text = _read_stream(stream)
        try:
            value, _handle = _native.parse(text, safe=self._is_safe)
        except _native.NativeYamlError as exc:
            raise translate_native_error(exc, text) from None
        if self._is_safe:
            return value
        roots = _handle.root_ids()
        return _make_document(value, handle=_handle, root_id=int(roots[0]) if roots else -1, source=text)

    def load_all(self, stream: Stream) -> List[Any]:
        from .document import _make_document

        text = _read_stream(stream)
        try:
            values, _handle = _native.parse_all(text, safe=self._is_safe)
        except _native.NativeYamlError as exc:
            raise translate_native_error(exc, text) from None
        if self._is_safe:
            return list(values)
        roots = _handle.root_ids()
        return [
            _make_document(value, handle=_handle, root_id=int(root), source=text)
            for value, root in zip(values, roots)
        ]

    def dump(
        self,
        data: Any,
        stream: Optional[Any] = None,
        *,
        config: Optional[IndentConfig] = None,
        explicit_start: Optional[bool] = None,
        explicit_end: Optional[bool] = None,
    ) -> Optional[str]:
        from .document import Document

        if isinstance(data, Document):
            _reject_safe_tagged(data._data, self._is_safe)
            _reject_safe_document_tags(data, self._is_safe)
            return data.dump(
                stream,
                config=config,
                explicit_start=explicit_start,
                explicit_end=explicit_end,
            )
        _reject_safe_tagged(data, self._is_safe)
        selected = config if config is not None else self.config
        try:
            text = _native.dump(data, config=selected, explicit_start=explicit_start)
        except _native.NativeYamlError as exc:
            raise translate_native_error(exc) from None
        if explicit_end and not _has_explicit_end(text):
            if text and not text.endswith("\n"):
                text += "\n"
            text += "...\n"
        if stream is None:
            return text
        stream.write(text)
        return None

    def dump_all(
        self,
        documents: Iterable[Any],
        stream: Optional[Any] = None,
        *,
        config: Optional[IndentConfig] = None,
        explicit_start: Optional[bool] = None,
        explicit_end: Optional[bool] = None,
    ) -> Optional[str]:
        from .document import Document

        documents = list(documents)
        for document in documents:
            _reject_safe_tagged(document, self._is_safe)
            if isinstance(document, Document):
                _reject_safe_document_tags(document, self._is_safe)
        selected = config if config is not None else self.config
        try:
            if explicit_end:
                # Emit per document so every one can be terminated with "...".
                parts = []
                for index, document in enumerate(documents):
                    start = True if index else explicit_start
                    parts.append(_native.dump(document, config=selected, explicit_start=start))
                text = ""
                for index, part in enumerate(parts):
                    if index:
                        text += "...\n"
                    text += part
                if text and not text.endswith("\n"):
                    text += "\n"
                text += "...\n"
            else:
                text = _native.dump_all(
                    documents, config=selected, explicit_start=explicit_start
                )
        except _native.NativeYamlError as exc:
            raise translate_native_error(exc) from None
        if stream is None:
            return text
        stream.write(text)
        return None

    @property
    def _is_safe(self) -> bool:
        return self._backend_typ == "safe"


class SafeYAML(YAML):
    """A safe engine that rejects non-standard application tags."""

    _backend_typ = "safe"


def _reject_safe_tagged(value: Any, safe: bool, seen: Optional[set[int]] = None) -> None:
    if not safe:
        return
    from .tagged import Tagged

    if isinstance(value, Tagged):
        raise RepresenterError("safe_dump does not support Tagged values")
    if seen is None:
        seen = set()
    pointer = id(value)
    if pointer in seen:
        return
    seen.add(pointer)
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_safe_tagged(key, safe, seen)
            _reject_safe_tagged(child, safe, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for child in value:
            _reject_safe_tagged(child, safe, seen)


def _reject_safe_document_tags(document: Any, safe: bool) -> None:
    """Reject local (application) tags anywhere in a ``Document`` for safe dumps.

    Standard ``!!``-prefixed tags resolve to plain values and stay allowed;
    local tags such as ``!foo`` are rejected exactly like the plain-data path
    rejects :class:`~pythonizeyaml.tagged.Tagged` instances.
    """
    if not safe:
        return

    for path, _value in document._iter_paths():
        tag = document._tag_at(path)
        if tag is not None and not tag.startswith("!!"):
            raise RepresenterError(
                f"safe_dump does not support custom tags (found {tag!r})"
            )


