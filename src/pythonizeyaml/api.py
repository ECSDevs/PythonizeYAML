"""Module-level, PyYAML-compatible entry points.

These functions delegate to a lazily created, process-wide default engine. If you
want your own configuration (or your own isolation between threads), instantiate
:class:`pythonizeyaml.engine.YAML` directly instead.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional, Type

from .config import IndentConfig
from .engine import SafeYAML, YAML
from .document import Document, DocumentStream

__all__ = [
    "load",
    "load_all",
    "dump",
    "dump_all",
    "safe_load",
    "safe_load_all",
    "safe_dump",
    "safe_dump_all",
    "round_trip_load",
    "round_trip_load_all",
    "round_trip_dump",
    "round_trip_dump_all",
]

# PyYAML keywords that have no meaning when the emitter's whole job is to keep the
# input byte-identical. They are accepted (so existing call sites keep working) and
# ignored; they never change or drop the data being dumped.
_ACCEPTED_BUT_IGNORED = frozenset(
    {
        "Dumper",
        "allow_unicode",  # the native emitter always emits unicode; there is no ASCII-only mode
        "default_flow_style",  # flow/block style is part of what is preserved
        "encoding",  # dumps always produce str here; the caller owns encoding
        "sort_keys",  # mapping order is part of what is preserved
    }
)

_engines: Dict[Type[YAML], YAML] = {}
_engines_lock = threading.Lock()


def _default_engine(engine_cls: Type[YAML]) -> YAML:
    """Return the shared default engine for ``engine_cls``, creating it on demand."""
    engine = _engines.get(engine_cls)
    if engine is None:
        with _engines_lock:
            engine = _engines.get(engine_cls)
            if engine is None:
                engine = engine_cls()
                _engines[engine_cls] = engine
    return engine


def _round_trip_engine() -> YAML:
    return _default_engine(YAML)


def _safe_engine() -> SafeYAML:
    return _default_engine(SafeYAML)  # type: ignore[return-value]


def _emission_kwargs(engine: YAML, kwargs: Dict[str, Any]):
    """Split PyYAML dump keywords into (config override, explicit_start)."""
    indent = kwargs.pop("indent", None)
    width = kwargs.pop("width", None)
    explicit_start = kwargs.pop("explicit_start", None)
    for name in list(kwargs):
        if name in _ACCEPTED_BUT_IGNORED:
            del kwargs[name]
    if kwargs:
        raise TypeError(
            "unsupported keyword argument(s): " + ", ".join(sorted(kwargs))
        )

    config: Optional[IndentConfig] = None
    if indent is not None or width is not None:
        # PyYAML's ``indent`` sets the width for nested mappings and sequences
        # alike, with the sequence dash flush with its parent key (offset 0).
        config = replace(
            engine.config,
            mapping=indent if indent is not None else engine.config.mapping,
            sequence=indent if indent is not None else engine.config.sequence,
            offset=0 if indent is not None else engine.config.offset,
            width=width if width is not None else engine.config.width,
        )
    return config, explicit_start


# -- round-trip preserving API (the default) -----------------------------


def load(stream: Any, Loader: Any = None) -> Any:
    """Load the first document from ``stream``, preserving comments and styles.

    ``Loader`` is accepted for PyYAML compatibility and ignored: this library
    always loads in round-trip mode. Use :func:`safe_load` to reject arbitrary
    Python object tags.
    """
    return _round_trip_engine().load(stream)


def load_all(stream: Any, Loader: Any = None) -> List[Any]:
    """Load every document from ``stream``, preserving comments and styles.

    ``Loader`` is accepted for PyYAML compatibility and ignored.
    """
    return _round_trip_engine().load_all(stream)


def dump(data: Any, stream: Optional[Any] = None, **kwargs: Any) -> Optional[str]:
    """Serialize ``data`` to YAML, preserving its original layout.

    Returns the emitted text when ``stream`` is ``None``, otherwise writes to
    ``stream`` and returns ``None``.

    Supported PyYAML keywords: ``indent`` (width for nested mappings/sequences),
    ``width`` (preferred line width) and ``explicit_start`` (emit a leading
    ``---``). ``allow_unicode``, ``default_flow_style``, ``sort_keys``,
    ``encoding`` and ``Dumper`` are accepted and ignored, because they conflict
    with byte-level preservation.
    """
    config, explicit_start = _emission_kwargs(_round_trip_engine(), kwargs)
    if isinstance(data, Document):
        return data.dump(stream, config=config, explicit_start=explicit_start)
    return _round_trip_engine().dump(
        data, stream, config=config, explicit_start=explicit_start
    )


def dump_all(
    documents: Iterable[Any], stream: Optional[Any] = None, **kwargs: Any
) -> Optional[str]:
    """Serialize ``documents`` as a multi-document stream, preserving layout.

    Accepts the same keywords as :func:`dump`.
    """
    config, explicit_start = _emission_kwargs(_round_trip_engine(), kwargs)
    if isinstance(documents, DocumentStream):
        return documents.dump(stream, config=config, explicit_start=bool(explicit_start))
    return _round_trip_engine().dump_all(
        documents, stream, config=config, explicit_start=explicit_start
    )


# -- explicit round-trip spellings ---------------------------------------

round_trip_load = load
round_trip_load_all = load_all


def round_trip_dump(
    data: Any, stream: Optional[Any] = None, **kwargs: Any
) -> Optional[str]:
    """Explicit-intent spelling of :func:`dump`."""
    return dump(data, stream, **kwargs)


def round_trip_dump_all(
    documents: Iterable[Any], stream: Optional[Any] = None, **kwargs: Any
) -> Optional[str]:
    """Explicit-intent spelling of :func:`dump_all`."""
    return dump_all(documents, stream, **kwargs)


# -- safe API -------------------------------------------------------------


def safe_load(stream: Any) -> Any:
    """Load the first document using the safe representation.

    Arbitrary Python object tags (``!!python/object/apply:...`` and friends) are
    rejected with :class:`pythonizeyaml.errors.ConstructorError`.
    """
    return _safe_engine().load(stream)


def safe_load_all(stream: Any) -> List[Any]:
    """Load every document using the safe representation.

    See :func:`safe_load` for the tag restrictions.
    """
    return _safe_engine().load_all(stream)


def safe_dump(data: Any, stream: Optional[Any] = None, **kwargs: Any) -> Optional[str]:
    """Serialize ``data`` using the safe representation.

    Accepts the same keywords as :func:`dump`; only plain YAML types are emitted.
    """
    config, explicit_start = _emission_kwargs(_safe_engine(), kwargs)
    return _safe_engine().dump(
        data, stream, config=config, explicit_start=explicit_start
    )


def safe_dump_all(
    documents: Iterable[Any], stream: Optional[Any] = None, **kwargs: Any
) -> Optional[str]:
    """Serialize ``documents`` using the safe representation.

    Accepts the same keywords as :func:`dump`.
    """
    config, explicit_start = _emission_kwargs(_safe_engine(), kwargs)
    return _safe_engine().dump_all(
        documents, stream, config=config, explicit_start=explicit_start
    )


