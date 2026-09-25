"""Emitter configuration for :mod:`pythonizeyaml`.

A document that was loaded keeps the indentation of its source; the values here
are the fallback used for data that was created in Python and therefore has no
original layout to preserve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["IndentConfig", "DEFAULT_CONFIG"]


@dataclass(frozen=True)
class IndentConfig:
    """Indentation, line width and quote-retention settings.

    Attributes:
        mapping: Indent width used for nested mappings.
        sequence: Indent width used for nested sequences.
        offset: How far the sequence dash sits relative to its parent indent.
        width: Preferred maximum line width before the emitter wraps.
        preserve_quotes: Keep redundant scalar quotes (``'x'`` vs ``"x"``) on a
            round trip.
    """

    mapping: int = 2
    sequence: int = 2
    offset: int = 0
    width: int = 80
    preserve_quotes: bool = True

    def __post_init__(self) -> None:
        if self.mapping < 1:
            raise ValueError("mapping indent must be >= 1")
        if self.sequence < 1:
            raise ValueError("sequence indent must be >= 1")
        if self.offset < 0:
            raise ValueError("sequence offset must be >= 0")
        if self.offset >= self.sequence:
            raise ValueError("sequence offset must be smaller than the sequence indent")
        if self.width < 1:
            raise ValueError("width must be >= 1")

    def apply_to(self, backend: Any) -> None:
        """Apply these settings to a backend ``YAML`` emitter instance."""
        backend.indent(mapping=self.mapping, sequence=self.sequence, offset=self.offset)
        backend.width = self.width
        backend.preserve_quotes = self.preserve_quotes


DEFAULT_CONFIG = IndentConfig()