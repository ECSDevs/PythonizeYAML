"""Values for YAML tags without a native Python representation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["Tagged"]


@dataclass(frozen=True, slots=True)
class Tagged:
    """An immutable tag/value pair used for application-specific YAML tags."""

    tag: str
    value: Any
