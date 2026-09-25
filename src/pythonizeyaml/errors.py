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

"""Public exception hierarchy for :mod:`pythonizeyaml`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

__all__ = [
    "YAMLError",
    "MarkedYAMLError",
    "ScannerError",
    "ParserError",
    "ComposerError",
    "ConstructorError",
    "EmitterError",
    "RepresenterError",
    "SerializerError",
    "PathError",
    "StyleError",
    "AliasError",
]


@dataclass(frozen=True, slots=True)
class Mark:
    """A source position reported by the Rust parser."""

    name: str
    index: int
    line: int
    column: int

    def __str__(self) -> str:
        return f'  in "{self.name}", line {self.line + 1}, column {self.column + 1}'


class YAMLError(Exception):
    """Base class for every error raised by :mod:`pythonizeyaml`."""


class MarkedYAMLError(YAMLError):
    """Base class for parser errors carrying a source position."""

    def __init__(
        self,
        context: Optional[str] = None,
        context_mark: Any = None,
        problem: Optional[str] = None,
        problem_mark: Any = None,
        note: Optional[str] = None,
    ) -> None:
        self.context = context
        self.context_mark = context_mark
        self.problem = problem
        self.problem_mark = problem_mark
        self.note = note
        super().__init__(self._compose_message())

    def _compose_message(self) -> str:
        lines = []
        if self.context is not None:
            lines.append(str(self.context))
        if self.context_mark is not None:
            lines.append(str(self.context_mark))
        if self.problem is not None:
            lines.append(str(self.problem))
        if self.problem_mark is not None:
            lines.append(str(self.problem_mark))
        if self.note is not None:
            lines.append(str(self.note))
        return "\n".join(lines)


class ScannerError(MarkedYAMLError):
    pass


class ParserError(MarkedYAMLError):
    pass


class ComposerError(MarkedYAMLError):
    pass


class ConstructorError(MarkedYAMLError):
    pass


class EmitterError(YAMLError):
    pass


class RepresenterError(YAMLError):
    pass


class SerializerError(YAMLError):
    pass


class PathError(YAMLError):
    pass

class StyleError(YAMLError):
    pass

class AliasError(YAMLError):
    pass

_ERROR_TYPES = {
    0: ScannerError,
    1: ParserError,
    2: ComposerError,
    3: ConstructorError,
    4: EmitterError,
    5: RepresenterError,
    6: SerializerError,
}


def translate_native_error(exc: BaseException, source: str = "<unicode string>") -> YAMLError:
    """Translate the extension's compact error payload into the public hierarchy."""

    args = getattr(exc, "args", ())
    if len(args) == 1 and isinstance(args[0], tuple):
        args = args[0]
    kind, problem, start, _end = (list(args) + [1, str(exc), 0, 0])[:4]
    mark = _mark_from_byte_offset(source, int(start), "unicode string")
    error_type = _ERROR_TYPES.get(int(kind), ParserError)
    if issubclass(error_type, MarkedYAMLError):
        return error_type(problem=str(problem), problem_mark=mark)
    return error_type(str(problem))


def translate_representer_error(exc: BaseException) -> YAMLError:
    return RepresenterError(str(exc))


def _mark_from_byte_offset(source: str, offset: int, name: str) -> Mark:
    encoded = source.encode("utf-8")
    prefix = encoded[: max(0, offset)].decode("utf-8", errors="ignore")
    line = prefix.count("\n")
    column = len(prefix.rsplit("\n", 1)[-1])
    return Mark(name=name, index=offset, line=line, column=column)


