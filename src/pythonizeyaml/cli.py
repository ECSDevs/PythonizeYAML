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

"""Command-line path editor: ``yaml <file> <get|set|del> <path> [value]``.

Paths are dot-separated (``foo.bar.jay``); a numeric segment addresses an item
of the sequence at that point (``servers.0.host``). ``set`` creates missing
intermediate mappings, so ``yaml conf.yml set a.b.c 1`` works even when ``a``
does not exist yet. Untouched parts of the file keep their original comments,
indentation and scalar styles; only the edited subtree is re-emitted.

Values are interpreted as YAML: ``123`` is an int, ``true`` a bool, ``null``
is null, ``[1, 2]`` a list — quote them (``"'123'"``) to force a string.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from .api import safe_dump, safe_load
from .document import Document, _plain_value, read_documents
from .errors import PathError, YAMLError

_USAGE = """\
usage:
  yaml <file> get <path>
  yaml <file> set <path> <value>
  yaml <file> del <path>

Path is dot-separated (foo.bar.jay); numeric segments index into sequences
(servers.0.host). `set` creates missing intermediate mappings automatically.
"""

_COMMANDS = ("get", "set", "del")


class _UsageError(Exception):
    """Bad command line; reported without a traceback."""


def _parse_path(text: str) -> Tuple[str, ...]:
    parts = tuple(text.split("."))
    if not text or any(not part for part in parts):
        raise _UsageError(f"invalid path {text!r}: segments are dot-separated and non-empty")
    return parts


def _fmt(path: Tuple[str, ...]) -> str:
    return ".".join(path)


def _as_index(container: Any, part: str, path: Tuple[str, ...]) -> Any:
    """Resolve one path segment against *container*.

    Numeric segments address sequence items; mapping keys stay strings, so a
    key ``"0"`` is only reachable as ``"0"``, never as the integer ``0``.
    """
    if isinstance(container, list) and not part.isdigit():
        raise YAMLError(
            f"no YAML node at path {_fmt(path)}: sequence index expected, got {part!r}"
        )
    return int(part) if isinstance(container, list) else part


def _child(container: Any, part: str, path: Tuple[str, ...]) -> Any:
    try:
        return container[_as_index(container, part, path)]
    except (KeyError, IndexError, TypeError, PathError):
        raise YAMLError(f"no YAML node at path {_fmt(path)}") from None


def _read(container: Any, part: str, path: Tuple[str, ...]) -> Any:
    """Read one level, reporting missing nodes as container errors.

    Unlike :func:`_child` this keeps the low-level exception so ``set`` can
    distinguish "missing" (auto-create) from "wrong kind of node" (report).
    """
    return container[_as_index(container, part, path)]


def _walk_parent(document: Document, path: Tuple[str, ...]) -> Tuple[Any, Any]:
    """Return the container holding *path* together with its final key."""
    current: Any = document.value
    for depth, part in enumerate(path[:-1]):
        current = _child(current, part, path[: depth + 1])
    return current, _as_index(current, path[-1], path)


def _load_document(file: Path) -> Optional[Document]:
    if not file.is_file():
        raise YAMLError(f"no such file: {file}")
    stream = read_documents(file)
    if len(stream) > 1:
        raise YAMLError(
            f"{file} contains {len(stream)} YAML documents; "
            "this tool only edits single-document files"
        )
    return stream[0] if len(stream) else None


def _print_value(value: Any) -> None:
    sys.stdout.write(safe_dump(_plain_value(value)))


def _write_back(file: Path, document: Document) -> None:
    # newline="" keeps the emitted "\n" verbatim instead of the platform's
    # translation to "\r\n" on Windows.
    with open(file, "w", encoding="utf-8", newline="") as handle:
        handle.write(document.dump())


def _set(document: Optional[Document], path: Tuple[str, ...], raw_value: str) -> Document:
    try:
        value = safe_load(raw_value)
    except YAMLError:
        value = raw_value  # not parseable as YAML: store the text as-is
    if document is None:
        document = Document.new({})
    if document.value is None:
        document.value = {}
    current: Any = document.value
    for depth, part in enumerate(path[:-1]):
        walked = path[: depth + 1]
        try:
            current = _read(current, part, walked)
        except (KeyError, IndexError, TypeError, PathError) as exc:
            # A missing mapping key auto-creates the next chain level (a
            # mapping, or a sequence when the next segment is numeric); an
            # out-of-range index or a scalar mid-path is reported instead.
            if not (isinstance(current, dict) and isinstance(exc, (KeyError, PathError))):
                raise YAMLError(
                    f"cannot set {_fmt(path)}: no mapping exists at {_fmt(walked)}"
                ) from None
            current[part] = [] if path[depth + 1].isdigit() else {}
            current = current[part]
    key = _as_index(current, path[-1], path)
    try:
        current[key] = value
    except IndexError:
        raise YAMLError(f"no sequence item at path {_fmt(path)}") from None
    except TypeError:
        parent = _fmt(path[:-1]) or "the document root"
        raise YAMLError(f"cannot set {_fmt(path)}: {parent} is not a mapping") from None
    return document


def _delete(document: Document, path: Tuple[str, ...]) -> None:
    parent, key = _walk_parent(document, path)
    try:
        del parent[key]
    except (KeyError, IndexError, TypeError, PathError):
        raise YAMLError(f"no YAML node at path {_fmt(path)}") from None


def _run(argv: List[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write(_USAGE)
        return 0
    if len(argv) < 3:
        raise _UsageError("expected <file> <command> <path> (and <value> for set)")
    file, command, path_text = argv[0], argv[1].lower(), argv[2]
    if command not in _COMMANDS:
        raise _UsageError(f"unknown command {command!r}; expected one of: {', '.join(_COMMANDS)}")
    if command == "set":
        if len(argv) != 4:
            raise _UsageError("set requires exactly one <value>")
        raw_value = argv[3]
    elif len(argv) != 3:
        raise _UsageError(f"{command} takes no value argument")

    path = _parse_path(path_text)
    if command == "get":
        document = _load_document(Path(file))
        if document is None:
            raise YAMLError(f"no YAML node at path {path!r}: {file} is empty")
        container, key = _walk_parent(document, path)
        _print_value(_child(container, path[-1], path))
        return 0

    document = _load_document(Path(file))
    if command == "set":
        document = _set(document, path, raw_value)
    else:
        if document is None:
            raise YAMLError(f"no YAML node at path {path!r}: {file} is empty")
        _delete(document, path)
    _write_back(Path(file), document)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Console entry point; returns the process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return _run(args)
    except _UsageError as exc:
        sys.stderr.write(f"error: {exc}\n\n{_USAGE}")
        return 2
    except YAMLError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
