"""Python-facing engine wrappers around the native Rust implementation."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional

from . import _native
from .config import DEFAULT_CONFIG, IndentConfig
from .errors import RepresenterError, YAMLError, translate_native_error

__all__ = ["YAML", "SafeYAML"]

Stream = Any


def _read_text(stream: Stream) -> str:
    if hasattr(stream, "read"):
        stream = stream.read()
    if isinstance(stream, bytes):
        return stream.decode("utf-8")
    if isinstance(stream, str):
        return stream
    raise TypeError(
        "expected a str, bytes or a stream with a .read() method, got "
        f"{type(stream).__name__}"
    )


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
        text = _read_text(stream)
        try:
            value, _handle = _native.parse(text, safe=self._is_safe)
        except _native.NativeYamlError as exc:
            raise translate_native_error(exc, text) from None
        return value

    def load_all(self, stream: Stream) -> List[Any]:
        text = _read_text(stream)
        try:
            values, _handle = _native.parse_all(text, safe=self._is_safe)
        except _native.NativeYamlError as exc:
            raise translate_native_error(exc, text) from None
        return list(values)

    def dump(
        self,
        data: Any,
        stream: Optional[Any] = None,
        *,
        config: Optional[IndentConfig] = None,
        explicit_start: Optional[bool] = None,
    ) -> Optional[str]:
        _reject_safe_tagged(data, self._is_safe)
        selected = config if config is not None else self.config
        try:
            text = _native.dump(data, config=selected, explicit_start=explicit_start)
        except _native.NativeYamlError as exc:
            raise translate_native_error(exc) from None
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
    ) -> Optional[str]:
        documents = list(documents)
        for document in documents:
            _reject_safe_tagged(document, self._is_safe)
        selected = config if config is not None else self.config
        try:
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


