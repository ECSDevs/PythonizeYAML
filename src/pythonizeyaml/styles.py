"""Public style metadata types for the advanced document API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScalarStyle(str, Enum):
    PLAIN = "plain"
    SINGLE = "single"
    DOUBLE = "double"
    LITERAL = "literal"
    FOLDED = "folded"


class CollectionStyle(str, Enum):
    BLOCK = "block"
    FLOW = "flow"


class Chomping(str, Enum):
    CLIP = "clip"
    STRIP = "strip"
    KEEP = "keep"


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start: int
    end: int
    line: int
    column: int


__all__ = ["Chomping", "CollectionStyle", "ScalarStyle", "SourceSpan"]
