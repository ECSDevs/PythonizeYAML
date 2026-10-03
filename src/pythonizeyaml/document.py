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

"""Mutable, style-aware YAML documents layered over the native engine."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from . import _native
from .config import DEFAULT_CONFIG, IndentConfig
from .errors import AliasError, PathError, StyleError, translate_native_error
from .styles import Chomping, CollectionStyle, ScalarStyle, SourceSpan
from .nodes import (
    Comments,
    RoundTripBytes,
    RoundTripDate,
    RoundTripDatetime,
    RoundTripDecimal,
    RoundTripFloat,
    RoundTripInt,
    RoundTripList,
    RoundTripMap,
    RoundTripStr,
    RoundTripTime,
    _ANCHOR_RE,
    _RoundTripMixin,
    prepare_value,
    unwrap_scalar,
)

_SCALAR_WRAPPERS = (
    RoundTripStr,
    RoundTripInt,
    RoundTripFloat,
    RoundTripBytes,
    RoundTripDecimal,
    RoundTripDatetime,
    RoundTripDate,
    RoundTripTime,
)


def _path_tuple(path: tuple[Any, ...]) -> tuple[Any, ...]:
    if len(path) == 1 and isinstance(path[0], (tuple, list)):
        return tuple(path[0])
    return tuple(path)


def _raw_get(container: Any, key: Any) -> Any:
    """Read one item from a container's raw storage.

    Document instances store their data in themselves and override
    ``__getitem__`` to resolve paths, so reads that are already walking a
    resolved path must bypass the override to avoid re-entering it.
    """
    if isinstance(container, dict):
        return dict.__getitem__(container, key)
    if isinstance(container, list):
        return list.__getitem__(container, key)
    return container[key]


def _plain_value(value: Any) -> Any:
    """Convert loaded document data into plain Python data.

    Round-trip containers become plain ``dict``/``list`` values, scalar
    wrappers unwrap to their built-in type, scalar-root documents unwrap to
    their value, and everything else (including inert
    :class:`~pythonizeyaml.tagged.Tagged` values) is passed through as is.
    """
    if isinstance(value, _SCALAR_WRAPPERS):
        return unwrap_scalar(value)
    if isinstance(value, dict):
        return {_plain_value(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, Document):
        return _plain_value(value.value)
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, set):
        return {_plain_value(item) for item in value}
    return value


class _OffsetMap:
    """Converts between native byte offsets and Python character offsets.

    Native spans and patch positions are byte offsets into the UTF-8 source,
    while the document layer does all of its string math on ``str`` indices;
    every offset crossing the boundary goes through this map.
    """

    def __init__(self, source: str) -> None:
        self._byte_of_char = [0]
        char_of_byte: list[int] = []
        total = 0
        for index, char in enumerate(source):
            width = len(char.encode("utf-8"))
            total += width
            char_of_byte.extend([index] * width)
            self._byte_of_char.append(total)
        char_of_byte.append(len(source))
        self._char_of_byte = char_of_byte

    def to_char(self, offset: int) -> int:
        if offset <= 0:
            return 0
        return self._char_of_byte[min(offset, len(self._char_of_byte) - 1)]

    def to_byte(self, offset: int) -> int:
        if offset <= 0:
            return 0
        return self._byte_of_char[min(offset, len(self._byte_of_char) - 1)]


def _description_in_chars(raw: dict[str, Any], offsets: _OffsetMap) -> dict[str, Any]:
    """Rewrites a native node description's byte spans as character offsets."""

    def _convert_span(span: Any) -> Any:
        if isinstance(span, (tuple, list)) and len(span) == 2:
            return (offsets.to_char(int(span[0])), offsets.to_char(int(span[1])))
        return span

    described = dict(raw)
    described["span"] = _convert_span(described.get("span"))
    described["value_span"] = _convert_span(described.get("value_span"))
    children = described.get("children")
    if isinstance(children, list):
        rewritten = []
        for child in children:
            if isinstance(child, dict):
                child = dict(child)
                for field in ("key_span", "value_span", "entry_span"):
                    child[field] = _convert_span(child.get(field))
            rewritten.append(child)
        described["children"] = rewritten
    return described


class Document:
    """A mutable style-aware YAML document."""

    def __init__(
        self,
        data: Any,
        *,
        handle: Any = None,
        root_id: int = -1,
        source: str = "",
        config: Optional[IndentConfig] = None,
    ) -> None:
        self._data = data
        self._handle = handle
        self._root_id = root_id
        self._source = source
        self._offsets = _OffsetMap(source) if handle is not None else None
        self._config = config or DEFAULT_CONFIG
        self._styles: dict[tuple[Any, ...], ScalarStyle] = {}
        self._collection_styles: dict[tuple[Any, ...], CollectionStyle] = {}
        self._chomping: dict[tuple[Any, ...], Chomping] = {}
        self._block_indent: dict[tuple[Any, ...], int] = {}
        self._tags: dict[tuple[Any, ...], Optional[str]] = {}
        self._anchors: dict[tuple[Any, ...], Optional[str]] = {}
        self._comments: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._aliases: dict[tuple[Any, ...], str] = {}
        self._directives_override: Optional[list[str]] = None
        self._explicit_start_override: Optional[bool] = None
        self._explicit_end_override: Optional[bool] = None
        self._root_replaced = False
        # Source entries removed through the container protocol, as
        # (parent node id, removed value node id) pairs. They become deletion
        # patches so a dump drops their lines instead of canonically re-emitting
        # the parent (which loses nested comments). The pending map stages
        # pre-removal lookups so a failed removal (missing key) records nothing.
        self._removals: list[tuple[int, int]] = []
        self._pending_removals: dict[tuple[int, Any], tuple[int, int]] = {}
        self._prepare_tree()
        self._snapshot_virtual_entries()

    def _snapshot_virtual_entries(self) -> None:
        """Record data entries that exist only in the resolved view.

        Merge keys (``<<: *base``) resolve into real entries at load; those
        entries carry no source node and must never be patched into the text
        as if the user had added them.
        """
        virtual: set[tuple[Any, ...]] = set()
        if self._handle is not None:
            stack = [((), self._data)]
            while stack:
                path, value = stack.pop()
                if isinstance(value, dict):
                    entry_nodes = getattr(value, "_pyy_entry_nodes", None)
                    if entry_nodes is None:
                        continue
                    for key, child in dict.items(value):
                        pair = entry_nodes.get(key)
                        if pair is None or int(pair[1]) < 0:
                            virtual.add(path + (key,))
                        else:
                            stack.append((path + (key,), child))
                elif isinstance(value, list):
                    node_ids = getattr(value, "_pyy_node_ids", None)
                    if node_ids is None:
                        continue
                    for index, child in enumerate(value):
                        child_id = int(node_ids[index]) if index < len(node_ids) else -1
                        if child_id < 0:
                            virtual.add(path + (index,))
                        else:
                            stack.append((path + (index,), child))
        self._virtual_entries: set[tuple[Any, ...]] = virtual

    def _prepare_tree(self) -> None:
        """Bind every round-trip value in the data tree to this document.

        Loaded documents arrive from the native engine with round-trip
        containers and wrapped scalars; this walk binds them to ``self``.
        Documents built from plain Python data are converted in place (plain
        ``dict``/``list`` become round-trip containers, scalars are wrapped)
        so every value the container protocol returns carries the styling API.
        """
        stack = [self._data]
        while stack:
            container = stack.pop()
            if isinstance(container, _RoundTripMixin):
                container._pyy_document = self
            if isinstance(container, dict):
                for key in dict.keys(container):
                    child = dict.__getitem__(container, key)
                    prepared = prepare_value(child, self)
                    if prepared is not child:
                        dict.__setitem__(container, key, prepared)
                    if isinstance(prepared, (dict, list)):
                        stack.append(prepared)
            elif isinstance(container, list):
                for index in range(list.__len__(container)):
                    child = list.__getitem__(container, index)
                    prepared = prepare_value(child, self)
                    if prepared is not child:
                        list.__setitem__(container, index, prepared)
                    if isinstance(prepared, (dict, list)):
                        stack.append(prepared)

    @classmethod
    def new(cls, root: Any = None, *, config: Optional[IndentConfig] = None) -> "Document":
        return cls(root, config=config)

    @property
    def data(self) -> Any:
        """The document data with alias entries resolved to their targets.

        This is a resolved *view*, not the aliased identity: a value read
        through an alias entry is the alias target's current value, and when
        any alias is registered the returned mapping/sequence is a shallow
        resolved copy rather than the live container. Without aliases the
        underlying data object is returned unchanged.
        """
        return self._resolved_data()

    @property
    def value(self) -> Any:
        """The document root value, as a Python scalar or round-trip container."""
        return self._data

    @value.setter
    def value(self, value: Any) -> None:
        self._set_value((), value)

    @property
    def directives(self) -> list[str]:
        if self._directives_override is not None:
            return list(self._directives_override)
        if self._handle is not None and self._root_id >= 0:
            return list(self._handle.document_info(self._root_id)["directives"])
        return []

    @directives.setter
    def directives(self, value: Iterable[str]) -> None:
        directives = list(value)
        for directive in directives:
            if not directive.startswith("%"):
                raise StyleError("directives must start with '%'")
        self._directives_override = directives

    @property
    def explicit_start(self) -> bool:
        if self._explicit_start_override is not None:
            return self._explicit_start_override
        if self._handle is not None and self._root_id >= 0:
            return bool(self._handle.document_info(self._root_id)["explicit_start"])
        return False

    @explicit_start.setter
    def explicit_start(self, value: bool) -> None:
        self._explicit_start_override = bool(value)

    @property
    def explicit_end(self) -> bool:
        if self._explicit_end_override is not None:
            return self._explicit_end_override
        if self._handle is not None and self._root_id >= 0:
            return bool(self._handle.document_info(self._root_id)["explicit_end"])
        return False

    @explicit_end.setter
    def explicit_end(self, value: bool) -> None:
        self._explicit_end_override = bool(value)

    @property
    def source(self) -> str:
        if self._handle is not None:
            return self._handle.source()
        return self._source

    def __getitem__(self, key: Any) -> Any:
        return self._at((key,))

    def __setitem__(self, key: Any, value: Any) -> None:
        self._set_value((key,), value)

    def __delitem__(self, key: Any) -> None:
        """Remove a root-level child of a plain-container root.

        Container-root documents (``DocumentMapping``/``DocumentSequence``)
        resolve deletion through their round-trip container hooks instead;
        this covers documents created from plain Python data.
        """
        path = (key,)
        self._check_removal_allowed(path)
        parent = self._data
        try:
            del parent[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise PathError(f"no YAML node at path {path!r}") from exc
        self._discard_overrides(path)
        if isinstance(parent, list) and isinstance(key, int) and not isinstance(key, bool):
            position = key if key >= 0 else len(parent) + 1 + key
            self._reindex_overrides_after_removal((), position)

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the value at *key*, or *default* when there is no node.

        A tuple or list key is treated as a nested path, matching the
        convention of :meth:`node`: ``document.get(("a", "b"))`` reads
        ``a.b``. Alias entries read through to their target's current value.
        """
        try:
            return self._at(_path_tuple((key,)))
        except PathError:
            return default

    def _at(self, path: tuple[Any, ...]) -> Any:
        """Alias-resolved read at a path tuple."""
        if path in self._aliases:
            target = self._target_path_for_alias(path)
            if target is not None:
                return self._at(target)
        current = self._data
        for part in path:
            try:
                current = _raw_get(current, part)
            except (KeyError, IndexError, TypeError) as exc:
                raise PathError(f"no YAML node at path {path!r}") from exc
        if isinstance(current, _RoundTripMixin):
            # Remember where the value was read from: styled access resolves
            # by identity, and this lets an object stored at several paths
            # (assigned to more than one key) resolve to the intended one.
            current._pyy_path_hint = path
        return current

    def __iter__(self) -> Iterator[Any]:
        if isinstance(self._data, (dict, list, tuple, set, str, bytes)):
            return iter(self._data)
        raise TypeError(f"'{type(self._data).__name__}' object is not iterable")

    def __len__(self) -> int:
        return len(self._data)

    def keys(self):
        if not isinstance(self._data, dict):
            raise TypeError("document root is not a mapping")
        return self._data.keys()

    def items(self):
        """Mapping items with alias entries resolved to their target values."""
        if not isinstance(self._data, dict):
            raise TypeError("document root is not a mapping")
        resolved = self._resolved_data()
        if resolved is self._data:
            # Raw base-class iteration: container roots must not re-enter the
            # overridden DocumentMapping.items.
            return dict.items(self._data)
        return resolved.items()

    def values(self):
        """Mapping values with alias entries resolved to their target values."""
        if not isinstance(self._data, dict):
            raise TypeError("document root is not a mapping")
        resolved = self._resolved_data()
        if resolved is self._data:
            return dict.values(self._data)
        return resolved.values()

    def __int__(self) -> int:
        return int(self._data)

    def __float__(self) -> float:
        return float(self._data)

    def __complex__(self) -> complex:
        return complex(self._data)

    def __str__(self) -> str:
        data = self._data
        if isinstance(data, (dict, list, tuple, set)):
            return self.dump()
        return str(data)

    def __bool__(self) -> bool:
        return bool(self._data)

    def __deepcopy__(self, memo: dict[int, Any]) -> "Document":
        """Return an independent deep copy of this document.

        Handle-backed documents are reloaded from their dumped text (which
        keeps the byte-identical formatting of untouched documents); documents
        without a handle deep-copy their data, configuration and override
        registries. Copies are fully independent: mutating one never affects
        the other, and their dumps are separate.
        """
        if self._handle is not None:
            return load_document(self.dump())
        data = self._data
        if data is self:
            if isinstance(self, dict):
                data_copy = copy.deepcopy(dict(self), memo)
            else:
                data_copy = copy.deepcopy(list(self), memo)
            clone = type(self)(data_copy)
        else:
            clone = _make_document(copy.deepcopy(data, memo))
        clone._config = copy.deepcopy(self._config, memo)
        clone._source = self._source
        clone._root_id = self._root_id
        clone._styles = copy.deepcopy(self._styles, memo)
        clone._collection_styles = copy.deepcopy(self._collection_styles, memo)
        clone._chomping = copy.deepcopy(self._chomping, memo)
        clone._block_indent = copy.deepcopy(self._block_indent, memo)
        clone._tags = copy.deepcopy(self._tags, memo)
        clone._anchors = copy.deepcopy(self._anchors, memo)
        clone._comments = copy.deepcopy(self._comments, memo)
        clone._aliases = copy.deepcopy(self._aliases, memo)
        clone._directives_override = (
            None if self._directives_override is None else list(self._directives_override)
        )
        clone._explicit_start_override = self._explicit_start_override
        clone._explicit_end_override = self._explicit_end_override
        clone._root_replaced = self._root_replaced
        clone._removals = list(self._removals)
        return clone

    def _resolved_data(self) -> Any:
        """Shallow read-through of the data with direct alias entries resolved."""
        data = self._data
        if not self._aliases:
            return data
        if isinstance(data, dict):
            return {
                key: self._resolve_entry((key,), value)
                for key, value in dict.items(data)
            }
        if isinstance(data, list):
            return [self._resolve_entry((index,), value) for index, value in enumerate(data)]
        return data

    def _resolve_entry(self, path: tuple[Any, ...], value: Any) -> Any:
        if path in self._aliases:
            return self._at(path)
        return value

    # -- value identity resolution ---------------------------------------------
    #
    # Styled access goes through the value itself (every value reachable via
    # the container protocol is a round-trip wrapper), so paths are resolved
    # by object identity: the value's last-read path is validated first, then
    # a full scan runs. Alias occurrences are excluded — they share the
    # target's object, so styling through an alias entry styles the anchor
    # target.

    def _require_path(self, value: Any) -> tuple[Any, ...]:
        """The path ``value`` lives at, raising when it cannot be located."""
        hint = getattr(value, "_pyy_path_hint", None)
        if hint is not None and self._hint_matches(hint, value):
            return hint
        found = [
            path
            for path, candidate in self._iter_paths()
            if candidate is value and path not in self._aliases
        ]
        if len(found) == 1:
            path = found[0]
            try:
                value._pyy_path_hint = path
            except AttributeError:
                pass
            return path
        if not found:
            raise PathError(
                "this value is not in the document; it was removed, replaced, "
                "or never attached"
            )
        raise PathError(
            "this value is stored at several paths; read it via document[...] "
            "at the intended location before styling it"
        )

    def _locate(self, value: Any) -> Optional[tuple[Any, ...]]:
        """The path of ``value`` inside the document, or ``None``."""
        try:
            return self._require_path(value)
        except PathError:
            return None

    def _hint_matches(self, path: tuple[Any, ...], value: Any) -> bool:
        current = self._data
        for part in path:
            try:
                current = _raw_get(current, part)
            except (KeyError, IndexError, TypeError):
                return False
        return current is value

    def _style_at(self, path: tuple[Any, ...]) -> Optional[ScalarStyle]:
        override = self._styles.get(path)
        if override is not None:
            return override
        description = self._describe(path)
        value = description.get("style") if description else None
        return ScalarStyle(value) if value else None

    def _set_style_at(self, path: tuple[Any, ...], value: ScalarStyle | str) -> None:
        style = ScalarStyle(value)
        self._validate_scalar_style(self._at(path), style)
        self._styles[path] = style

    def _collection_style_at(self, path: tuple[Any, ...]) -> Optional[CollectionStyle]:
        override = self._collection_styles.get(path)
        if override is not None:
            return override
        description = self._describe(path)
        value = description.get("collection_style") if description else None
        return CollectionStyle(value) if value else None

    def _set_collection_style_at(self, path: tuple[Any, ...], value: CollectionStyle | str) -> None:
        style = CollectionStyle(value)
        self._validate_collection_style(self._at(path), style)
        self._collection_styles[path] = style

    def _chomping_at(self, path: tuple[Any, ...]) -> Optional[Chomping]:
        override = self._chomping.get(path)
        if override is not None:
            return override
        description = self._describe(path)
        value = description.get("chomping") if description else None
        return Chomping(value) if value else None

    def _set_chomping_at(self, path: tuple[Any, ...], value: Chomping | str | None) -> None:
        chomping = Chomping(value) if value is not None else None
        style = self._style_at(path)
        if chomping is not None and style not in {ScalarStyle.LITERAL, ScalarStyle.FOLDED}:
            raise StyleError("chomping requires a literal or folded scalar")
        if chomping is None:
            self._chomping.pop(path, None)
        else:
            self._chomping[path] = chomping

    def _set_block_indent_at(self, path: tuple[Any, ...], value: Optional[int]) -> None:
        if value is None:
            self._block_indent.pop(path, None)
            return
        if not 1 <= value <= 9:
            raise StyleError("block indentation indicator must be between 1 and 9")
        if self._style_at(path) not in {ScalarStyle.LITERAL, ScalarStyle.FOLDED}:
            raise StyleError("block indentation requires a literal or folded scalar")
        self._block_indent[path] = value

    def _tag_at(self, path: tuple[Any, ...]) -> Optional[str]:
        if path in self._tags:
            return self._tags[path]
        description = self._describe(path)
        return (description.get("raw_tag") or description.get("tag")) if description else None

    def _set_tag_at(self, path: tuple[Any, ...], value: Optional[str]) -> None:
        if value is not None and not value.startswith("!"):
            raise StyleError("YAML tags must start with '!'")
        self._tags[path] = value

    def _anchor_at(self, path: tuple[Any, ...]) -> Optional[str]:
        if path in self._anchors:
            return self._anchors[path]
        description = self._describe(path)
        return description.get("anchor") if description else None

    def _set_anchor_at(self, path: tuple[Any, ...], value: Optional[str]) -> None:
        if value is not None and not _ANCHOR_RE.match(value):
            raise StyleError(f"invalid YAML anchor name: {value!r}")
        old = self._anchor_at(path)
        native_aliases = self._native_aliases_for_target(path)
        if value is not None and old is not None and old != value:
            for alias_path, alias_anchor in list(self._aliases.items()):
                if alias_anchor == old:
                    self._aliases[alias_path] = value
            for alias_path in native_aliases:
                self._aliases[alias_path] = value
        if value is None and (
            any(anchor == old for anchor in self._aliases.values()) or bool(native_aliases)
        ):
            raise AliasError("cannot remove an anchor that still has aliases")
        self._anchors[path] = value

    def _describe(self, path: tuple[Any, ...]) -> Optional[dict[str, Any]]:
        node_id = self._node_id_for_path(path)
        if self._handle is None or node_id < 0:
            return None
        if self._offsets is None:
            self._offsets = _OffsetMap(self._source)
        return _description_in_chars(self._handle.describe(node_id), self._offsets)

    def _require_offsets(self) -> _OffsetMap:
        if self._offsets is None:
            self._offsets = _OffsetMap(self._source)
        return self._offsets

    def _node_id_for_path(self, path: tuple[Any, ...]) -> int:
        current = self._data
        node_id = self._root_id
        for part in path:
            if isinstance(current, dict):
                metadata = getattr(current, "_pyy_entry_nodes", {})
                pair = metadata.get(part)
                node_id = int(pair[1]) if pair is not None else -1
                try:
                    current = _raw_get(current, part)
                except KeyError as exc:
                    raise PathError(f"no YAML node at path {path!r}") from exc
            elif isinstance(current, list):
                try:
                    index = int(part)
                    metadata = list(getattr(current, "_pyy_node_ids", []))
                    node_id = int(metadata[index]) if index < len(metadata) else -1
                    current = current[index]
                except (ValueError, IndexError, TypeError) as exc:
                    raise PathError(f"no YAML node at path {path!r}") from exc
            else:
                raise PathError(f"no YAML node at path {path!r}")
        return node_id

    def _check_removal_allowed(self, path: tuple[Any, ...]) -> None:
        """Raise when the node at ``path`` still has aliases pointing at it."""
        if not path:
            raise PathError("cannot remove the document root")
        try:
            node_id = self._node_id_for_path(path)
        except PathError:
            node_id = -1
        if self._has_aliases_to(node_id):
            raise AliasError("cannot remove a node that still has aliases")

    # -- round-trip container hooks ---------------------------------------------
    #
    # Containers notify their document before and after structural edits (see
    # _RoundTripMixin) so the path-keyed override registries keep describing
    # the right nodes.

    def _pre_child_removed(self, container: Any, key: Any) -> None:
        prefix = self._locate(container)
        if prefix is not None:
            self._check_removal_allowed(prefix + (key,))
            self._stage_removal(container, key)

    def _stage_removal(self, container: Any, key: Any) -> None:
        """Remember the source identity of a child about to be removed.

        Only scalar keys are tracked: slice deletions and wholesale resets
        change item positions wholesale and fall back to a canonical re-emit.
        """
        if isinstance(key, (slice, list, tuple)):
            return
        container_id = getattr(container, "_pyy_node_id", -1)
        if not isinstance(container_id, int) or container_id < 0:
            return
        if isinstance(container, dict):
            pair = getattr(container, "_pyy_entry_nodes", {}).get(key)
            value_id = int(pair[1]) if pair is not None else -1
        elif isinstance(container, list):
            if not isinstance(key, int) or isinstance(key, bool):
                return
            ids = getattr(container, "_pyy_node_ids", [])
            value_id = int(ids[key]) if 0 <= key < len(ids) else -1
        else:
            return
        if value_id >= 0:
            self._pending_removals[(id(container), key)] = (container_id, value_id)

    def _post_child_removed(self, container: Any, key: Any) -> None:
        record = self._pending_removals.pop((id(container), key), None)
        if record is not None:
            self._removals.append(record)
        prefix = self._locate(container)
        if prefix is None:
            return
        if isinstance(container, list) and isinstance(key, int) and not isinstance(key, bool):
            position = key if key >= 0 else len(container) + 1 + key
            self._reindex_overrides_after_removal(prefix, position)
        elif isinstance(key, slice):
            self._discard_below(prefix)
        else:
            self._discard_overrides(prefix + (key,))

    def _post_child_inserted(self, container: Any, index: Any) -> None:
        prefix = self._locate(container)
        if prefix is None:
            return
        if isinstance(index, int) and not isinstance(index, bool):
            position = max(0, index if index >= 0 else len(container) - 1 + index)
            self._reindex_overrides_after_insert(prefix, position)

    def _post_children_reset(self, container: Any) -> None:
        prefix = self._locate(container)
        if prefix is not None:
            self._discard_below(prefix)

    def _reindex_overrides_after_insert(self, parent_path: tuple[Any, ...], index: int) -> None:
        """Shift sibling override entries at or after an inserted list position."""
        for mapping in (
            self._styles,
            self._collection_styles,
            self._chomping,
            self._block_indent,
            self._tags,
            self._anchors,
            self._comments,
            self._aliases,
        ):
            shifted: list[tuple[tuple[Any, ...], Any]] = []
            for key in list(mapping):
                if len(key) <= len(parent_path) or key[: len(parent_path)] != parent_path:
                    continue
                sibling = key[len(parent_path)]
                if not isinstance(sibling, int) or isinstance(sibling, bool):
                    continue
                if sibling >= index:
                    shifted.append((key, mapping.pop(key)))
            for key, value in shifted:
                position = key[len(parent_path)]
                new_key = key[:len(parent_path)] + (position + 1,) + key[len(parent_path) + 1 :]
                mapping[new_key] = value

    def _discard_below(self, prefix: tuple[Any, ...]) -> None:
        """Drop every override strictly below ``prefix``.

        Used when a container's item order changes wholesale (sort, reverse,
        clear): the container keeps its own overrides, but nothing below it
        describes a stable node anymore.
        """
        for mapping in (
            self._styles,
            self._collection_styles,
            self._chomping,
            self._block_indent,
            self._tags,
            self._anchors,
            self._comments,
            self._aliases,
        ):
            for key in list(mapping):
                if len(key) > len(prefix) and key[: len(prefix)] == prefix:
                    mapping.pop(key, None)

    def _reindex_overrides_after_removal(
        self,
        parent_path: tuple[Any, ...],
        index: int,
    ) -> None:
        """Shift sibling override entries after an item left a list.

        Overrides for items after the removed index move down one position so
        they keep describing the same nodes; overrides for the removed item
        (and anything below it) are dropped.
        """
        for mapping in (
            self._styles,
            self._collection_styles,
            self._chomping,
            self._block_indent,
            self._tags,
            self._anchors,
            self._comments,
            self._aliases,
        ):
            shifted: list[tuple[tuple[Any, ...], Any]] = []
            for key in list(mapping):
                if len(key) <= len(parent_path) or key[: len(parent_path)] != parent_path:
                    continue
                sibling = key[len(parent_path)]
                if not isinstance(sibling, int) or isinstance(sibling, bool):
                    continue
                if sibling == index:
                    del mapping[key]
                elif sibling > index:
                    shifted.append((key, mapping.pop(key)))
            for key, value in shifted:
                position = key[len(parent_path)]
                new_key = key[:len(parent_path)] + (position - 1,) + key[len(parent_path) + 1 :]
                mapping[new_key] = value

    def alias(
        self,
        *path: Any,
        target: Any,
        anchor: str | None = None,
    ) -> Any:
        """Point ``path`` at the value of another node through an alias.

        ``target`` is the value to alias — the wrapper read from the document
        (``document.alias("copy", target=document["base"])``) — or a path
        tuple pointing at it. When the target has no anchor yet one is
        created (or taken from *anchor*).
        """
        normalized = _path_tuple(path)
        if isinstance(target, _RoundTripMixin):
            if target._pyy_document is not self:
                raise AliasError("alias target belongs to a different document")
            target_path = target._pyy_path()
        elif isinstance(target, (tuple, list)):
            target_path = tuple(target)
        else:
            target_path = (target,)
        target_value = self._at(target_path)
        anchor_name = self._anchor_at(target_path)
        if anchor_name is None:
            anchor_name = anchor or self._unique_anchor()
            self._set_anchor_at(target_path, anchor_name)
        elif anchor is not None and anchor != anchor_name:
            self._set_anchor_at(target_path, anchor)
            anchor_name = anchor
        # Resolve existence against the real data tree *before* registering the
        # alias: the alias registry must not influence the existence check.
        existed = self._path_exists(normalized)
        self._aliases[normalized] = anchor_name
        if not existed:
            self._set_value(normalized, target_value, create=True)
        return self._at(normalized)

    def _set_value(self, path: tuple[Any, ...], value: Any, *, create: bool = False) -> None:
        if not path:
            self._replace_root(value)
            return
        if self._data is None:
            self._data = RoundTripMap()
            self._data._pyy_document = self
        current = self._data
        for index, part in enumerate(path[:-1]):
            try:
                current = _raw_get(current, part)
            except (KeyError, IndexError, TypeError):
                if not create or not isinstance(part, str):
                    raise PathError(f"no YAML node at path {path!r}") from None
                next_part = path[index + 1]
                if not isinstance(current, dict):
                    raise PathError(f"cannot create mapping below path {path[: index + 1]!r}")
                current[part] = RoundTripMap() if isinstance(next_part, str) else RoundTripList()
                current = current[part]
        key = path[-1]
        if isinstance(current, dict):
            current[key] = value
            return
        if isinstance(current, list):
            try:
                current[int(key)] = value
                return
            except (ValueError, IndexError, TypeError) as exc:
                raise PathError(f"no sequence item at path {path!r}") from exc
        raise PathError(f"cannot assign below scalar node at path {path[:-1]!r}")

    def _replace_root(self, value: Any) -> None:
        """Replace the document root, keeping container-root storage in sync.

        Replacing the root invalidates source preservation, so dumps are routed
        through the full re-emit path afterwards.
        """
        current = self._data
        if current is self and isinstance(current, dict) and hasattr(value, "items"):
            self.clear()
            for key, item in dict(value).items():
                self[key] = item
        elif current is self and isinstance(current, list) and isinstance(value, list):
            self.clear()
            for item in value:
                self.append(item)
        else:
            self._data = prepare_value(value, self)
        self._prepare_tree()
        self._root_replaced = True

    def _path_exists(self, path: tuple[Any, ...]) -> bool:
        """Whether ``path`` exists in the real data tree, ignoring aliases."""
        current = self._data
        for part in path:
            try:
                current = _raw_get(current, part)
            except (KeyError, IndexError, TypeError):
                return False
        return True

    def _unique_anchor(self) -> str:
        used = set(self._anchors.values()) | set(self._aliases.values())
        index = 1
        while f"id{index:03d}" in used:
            index += 1
        return f"id{index:03d}"

    def _has_aliases_to(self, node_id: int) -> bool:
        if node_id < 0:
            return False
        for alias_path in self._aliases:
            target = self._target_path_for_alias(alias_path)
            if target is not None and self._node_id_for_path(target) == node_id:
                return True
        return False

    def _native_aliases_for_target(self, target_path: tuple[Any, ...]) -> dict[tuple[Any, ...], str]:
        target_id = self._node_id_for_path(target_path)
        result: dict[tuple[Any, ...], str] = {}
        if target_id < 0:
            return result
        for path, _ in self._iter_paths():
            description = self._describe(path)
            if (
                description
                and description.get("kind") == "alias"
                and int(description.get("alias_target", -1)) == target_id
            ):
                result[path] = description.get("alias_name", "")
        return result
    def _target_path_for_alias(self, alias_path: tuple[Any, ...]) -> Optional[tuple[Any, ...]]:
        anchor = self._aliases.get(alias_path)
        if anchor is None:
            description = self._describe(alias_path)
            if description and description.get("kind") == "alias":
                target_id = description.get("alias_target")
                return self._path_for_node_id(target_id)
            return None
        for path, node_anchor in self._iter_anchor_paths():
            if node_anchor == anchor:
                return path
        return None

    def _iter_anchor_paths(self) -> Iterator[tuple[tuple[Any, ...], str]]:
        for path, anchor in self._anchors.items():
            if anchor:
                yield path, anchor
        if self._handle is not None:
            for node_id, description in self._walk_descriptions():
                anchor = description.get("anchor")
                if anchor:
                    yield self._path_for_node_id(node_id) or (), anchor

    def _walk_descriptions(self) -> Iterator[tuple[int, dict[str, Any]]]:
        if self._handle is None:
            return
        for root_id in self._handle.root_ids():
            stack = [root_id]
            seen = set()
            while stack:
                node_id = stack.pop()
                if node_id in seen:
                    continue
                seen.add(node_id)
                description = _description_in_chars(
                    self._handle.describe(node_id), self._require_offsets()
                )
                yield node_id, description
                for child in description.get("children", []):
                    if isinstance(child, dict):
                        stack.append(child["key_id"])
                        stack.append(child["value_id"])
                    else:
                        stack.append(child)

    def _path_for_node_id(self, node_id: int) -> Optional[tuple[Any, ...]]:
        if node_id == self._root_id:
            return ()
        for path, _ in self._iter_paths():
            if self._node_id_for_path(path) == node_id:
                return path
        return None

    def _iter_paths(self) -> Iterator[tuple[tuple[Any, ...], Any]]:
        stack = [((), self._data)]
        while stack:
            path, value = stack.pop()
            yield path, value
            if isinstance(value, dict):
                # Raw base-class iteration: value may be a container-root
                # document whose items() resolves aliases.
                for key, child in reversed(list(dict.items(value))):
                    stack.append((path + (key,), child))
            elif isinstance(value, list):
                for index in range(len(value) - 1, -1, -1):
                    stack.append((path + (index,), value[index]))

    def _has_style_changes(self) -> bool:
        return (
            any(
                (
                    self._styles,
                    self._collection_styles,
                    self._chomping,
                    self._block_indent,
                    self._tags,
                    self._anchors,
                    self._comments,
                    self._aliases,
                )
            )
            or self._directives_override is not None
            or self._explicit_start_override is not None
            or self._explicit_end_override is not None
        )

    def _has_dirty_data(self) -> bool:
        """Whether any round-trip container in the tree was mutated.

        Mirrors the native ``has_dirty`` check. A document that was never
        mutated dumps verbatim even when its data carries resolved entries the
        source does not show (merge keys resolve ``<<`` into real entries at
        load), so virtual additions like those must not be patched in.
        """
        stack = [self._data]
        while stack:
            value = stack.pop()
            if getattr(value, "_pyy_dirty", False):
                return True
            if isinstance(value, dict):
                stack.extend(dict.values(value))
            elif isinstance(value, list):
                stack.extend(value)
        return False

    def _validate_value_style(self, value: Any, style: Optional[ScalarStyle]) -> None:
        if style is None:
            return
        self._validate_scalar_style(value, style)

    def _validate_scalar_style(self, value: Any, style: ScalarStyle) -> None:
        if style in {ScalarStyle.LITERAL, ScalarStyle.FOLDED, ScalarStyle.SINGLE, ScalarStyle.DOUBLE}:
            if not isinstance(value, str):
                raise StyleError(f"{style.value} style requires a string value")
        if style is ScalarStyle.PLAIN and isinstance(value, str) and _plain_would_change_type(value):
            raise StyleError("plain style would change the resolved YAML type")

    def _validate_collection_style(self, value: Any, style: CollectionStyle) -> None:
        if not isinstance(value, (dict, list)):
            raise StyleError("collection_style requires a mapping or sequence")
        if style is CollectionStyle.FLOW:
            self._validate_flow_value(value)

    def _validate_flow_value(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                self._validate_flow_value(key)
                self._validate_flow_value(child)
        elif isinstance(value, list):
            for child in value:
                self._validate_flow_value(child)
        elif isinstance(value, str) and "\n" in value:
            raise StyleError("multiline strings cannot be emitted safely in flow style")

    def _span(self, path: tuple[Any, ...]) -> Optional[SourceSpan]:
        description = self._describe(path)
        if description is None:
            return None
        start, end = description["span"]
        return self._make_span(start, end)

    def _entry_span(self, path: tuple[Any, ...]) -> Optional[tuple[int, int]]:
        if not path:
            return None
        parent = self._describe(path[:-1])
        if parent is None or parent.get("kind") != "mapping":
            return None
        node_id = self._node_id_for_path(path)
        for child in parent.get("children", []):
            if int(child["value_id"]) == node_id:
                return tuple(child["entry_span"])
        return None

    def _new_node_patch(
        self,
        path: tuple[Any, ...],
        config: IndentConfig,
    ) -> Optional[tuple[int, int, str]]:
        if not path:
            return None
        parent_path = path[:-1]
        parent_description = self._describe(parent_path)
        if parent_description is None or parent_description.get("kind") != "mapping":
            return None
        if parent_description.get("collection_style") == "flow":
            return None
        parent = self._at(parent_path) if parent_path else self.data
        if not isinstance(parent, dict) or path[-1] not in parent:
            return None
        parent_indent = 0
        if parent_path:
            parent_indent = _base_indent(self.source, int(parent_description["span"][0]))
        key = path[-1]
        # A block value is rendered at its own indent (one level below the
        # key's line), matching what _render_mapping/_emit_new produce.
        rendered = _render_node(self, path, parent[key], config, parent_indent + config.mapping)
        comments = self._get_comments(path)
        before_lines = list(comments.get("before", []))
        after_lines = list(comments.get("after", []))
        rendered_lines = rendered.split("\n")
        if before_lines:
            rendered_lines = rendered_lines[len(before_lines) :]
        if after_lines:
            rendered_lines = rendered_lines[: -len(after_lines)]
        rendered = "\n".join(rendered_lines)
        key_text = _render_scalar(key, _default_scalar_style(key))
        if _rendered_is_inline(self, path, parent[key], rendered):
            entry_line = " " * parent_indent + f"{key_text}: {rendered}"
        else:
            indented = _shift_after_first_line(rendered, 0)
            entry_line = " " * parent_indent + f"{key_text}:\n" + indented
        entry_lines = before_lines + [entry_line] + after_lines
        entry = "\n".join(entry_lines)
        keys = list(parent)
        index = keys.index(key)
        position: Optional[int] = None
        while index > 0:
            previous = path[:-1] + (keys[index - 1],)
            previous_description = self._describe(previous)
            if previous_description is None:
                # The previous sibling is itself a Python-created insertion;
                # keep walking back so chained additions share one position.
                index -= 1
                continue
            # The entry span ends at the key line (through its inline comment)
            # while the value span carries block children; insertion goes after
            # both, extended to the end of that line.
            end = int(previous_description["span"][1])
            entry_end = self._entry_span(previous)
            if entry_end is not None:
                end = max(end, int(entry_end[1]))
            current_line_start = self.source.rfind("\n", 0, end) + 1
            if end > current_line_start:
                line_end = self.source.find("\n", end)
                position = len(self.source) if line_end < 0 else line_end + 1
            else:
                position = end
            break
        if position is None:
            position = self.source.rfind("\n", 0, int(parent_description["span"][0])) + 1
        prefix = ""
        if position >= len(self.source) and self.source and not self.source.endswith("\n"):
            # The source's last line has no newline of its own; the inserted
            # entry still starts on a fresh line.
            prefix = "\n"
        return position, position, prefix + entry + "\n"

    def _new_sequence_item_patch(
        self,
        path: tuple[Any, ...],
        config: IndentConfig,
    ) -> Optional[tuple[int, int, str]]:
        """Patch inserting a Python-created item into a block sequence.

        The native patcher skips Python-created items when external patches
        are present (their whole-container rewrite would overlap and be
        dropped), so insertions are rendered and positioned here instead —
        after the nearest preceding item that exists in the source, or at the
        sequence's first item line.
        """
        if not path:
            return None
        parent_path = path[:-1]
        parent_description = self._describe(parent_path)
        if parent_description is None or parent_description.get("kind") != "sequence":
            return None
        if parent_description.get("collection_style") == "flow":
            return None
        parent = self._at(parent_path)
        if not isinstance(parent, list):
            return None
        index = path[-1]
        # ``index == len(parent)`` is an append: the new item goes after the
        # last existing one, whose dash column and end position anchor it.
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= len(parent):
            return None
        child = parent[index]
        dash_indent = self._sequence_dash_indent(parent_path, index)
        if dash_indent is None:
            return None
        child_indent = dash_indent - config.offset + config.sequence
        rendered = _render_node(self, path, child, config, child_indent)
        comments = self._get_comments(path)
        before_lines = list(comments.get("before", []))
        after_lines = list(comments.get("after", []))
        rendered_lines = rendered.split("\n")
        if before_lines:
            rendered_lines = rendered_lines[len(before_lines) :]
        if after_lines:
            rendered_lines = rendered_lines[: -len(after_lines)]
        rendered = "\n".join(rendered_lines)
        if _rendered_is_inline(self, path, child, rendered):
            entry_line = " " * dash_indent + f"- {rendered}"
        elif (
            isinstance(child, dict)
            and rendered.startswith(" " * child_indent)
            and not rendered.startswith(" " * (child_indent + 1))
        ):
            # The sibling that anchored the dash column carries its value on
            # the dash's line, so match that compact form: the first mapping
            # entry sits where the "- " ends, the rest keep their indent.
            entry_line = " " * dash_indent + "- " + rendered[child_indent:]
        else:
            indented = _shift_after_first_line(rendered, 0)
            entry_line = " " * dash_indent + "-\n" + indented
        entry_lines = before_lines + [entry_line] + after_lines
        entry = "\n".join(entry_lines)
        position = self._sequence_insertion_position(parent_path, parent_description, index)
        if position is None:
            return None
        prefix = ""
        if position >= len(self.source) and self.source and not self.source.endswith("\n"):
            prefix = "\n"
        return position, position, prefix + entry + "\n"

    def _sequence_dash_indent(
        self,
        parent_path: tuple[Any, ...],
        index: int,
    ) -> Optional[int]:
        """Column of the dashes introducing the parent sequence's items.

        Derived from an existing sibling item: the item's introducing dash is
        the last ``-`` before its value on the value's line. Returns ``None``
        when the sibling's dash does not start its own line (a sequence that
        is itself an item shares its first line with the outer dash), which
        cannot host a line-boundary insertion and falls back to a re-emit.
        """
        while index > 0:
            previous_description = self._describe(parent_path + (index - 1,))
            if previous_description is not None:
                return self._item_dash_column(previous_description["span"][0])
            # The previous item is itself a Python-created insertion.
            index -= 1
        first_description = self._describe(parent_path + (0,))
        if first_description is None:
            return None
        column = self._item_dash_column(first_description["span"][0])
        if column is None:
            return None
        line_start = self.source.rfind("\n", 0, int(first_description["span"][0])) + 1
        if self.source[line_start:int(first_description["span"][0])].strip():
            # The first item shares its line with the outer dash.
            return None
        return column

    def _item_dash_column(self, value_start: int) -> Optional[int]:
        line_start = self.source.rfind("\n", 0, int(value_start)) + 1
        dash = self.source.rfind("-", line_start, int(value_start))
        if dash < 0:
            return None
        return dash - line_start

    def _sequence_insertion_position(
        self,
        parent_path: tuple[Any, ...],
        parent_description: dict[str, Any],
        index: int,
    ) -> Optional[int]:
        while index > 0:
            previous_description = self._describe(parent_path + (index - 1,))
            if previous_description is not None:
                position = int(previous_description["span"][1])
                current_line_start = self.source.rfind("\n", 0, position) + 1
                if position > current_line_start:
                    line_end = self.source.find("\n", position)
                    position = len(self.source) if line_end < 0 else line_end + 1
                return position
            # The previous item is itself a Python-created insertion; keep
            # walking back so consecutive appends chain onto one position.
            index -= 1
        return self.source.rfind("\n", 0, int(parent_description["span"][0])) + 1

    def _new_node_insertion_patch(
        self,
        path: tuple[Any, ...],
        config: IndentConfig,
    ) -> Optional[tuple[int, int, str]]:
        return self._new_node_patch(path, config) or self._new_sequence_item_patch(path, config)

    def _new_node_removal_patch(self, parent_id: int, value_id: int) -> list[tuple[int, int, str]]:
        """Deletion patches for a removed source entry.

        The entry's full source lines are deleted; when that empties the parent
        collection it is rendered inline (``key: {}`` / ``key: []``) so the
        text keeps reading back as an empty collection instead of null.
        Mirrors the native patcher's own deletion edits (``entry_line_range``
        over a mapping entry's span, or an item's span in a sequence) so the
        two dedupe to a single deletion when both are present.
        """
        patches: list[tuple[int, int, str]] = []
        if self._handle is None or not self.source:
            return patches
        offsets = self._require_offsets()
        start: Optional[int] = None
        end: Optional[int] = None
        try:
            parent = _description_in_chars(self._handle.describe(parent_id), offsets)
        except _native.NativeYamlError:
            return patches
        if parent.get("kind") == "mapping":
            for child in parent.get("children") or ():
                if int(child.get("value_id", -1)) == value_id:
                    # The entry span ends at the key line; a block value's
                    # lines only end with its value span, so delete the union.
                    spans = [
                        child.get(name)
                        for name in ("entry_span", "value_span")
                        if child.get(name) is not None
                    ]
                    if spans:
                        start = min(int(span[0]) for span in spans)
                        end = max(int(span[1]) for span in spans)
                    break
        else:
            try:
                node = _description_in_chars(self._handle.describe(value_id), offsets)
            except _native.NativeYamlError:
                return patches
            start, end = int(node["span"][0]), int(node["span"][1])
        if start is None or end is None:
            return patches
        source = self.source
        line_start = source.rfind("\n", 0, start) + 1
        if source[:end].endswith("\n"):
            line_end = end
        else:
            newline = source.find("\n", end)
            line_end = len(source) if newline < 0 else newline + 1
        patches.append((line_start, line_end, ""))
        empty = self._emptied_parent_patch(parent_id)
        if empty is not None:
            patches.append(empty)
        return patches

    def _emptied_parent_patch(self, parent_id: int) -> Optional[tuple[int, int, str]]:
        """An inline ``{}``/``[]`` render for a collection a removal emptied."""
        parent_path = self._path_for_node_id(parent_id)
        if not parent_path:
            return None  # the document root staying empty reads as null
        parent = self._at(parent_path)
        if not isinstance(parent, (dict, list)) or len(parent):
            return None
        entry_span = self._entry_span(parent_path)
        description = self._describe(parent_path)
        if entry_span is None or description is None:
            return None
        key_line_start = self.source.rfind("\n", 0, int(entry_span[0])) + 1
        key_line_end = self.source.find("\n", int(entry_span[0]))
        if key_line_end < 0:
            key_line_end = len(self.source)
        # Insert before a trailing comment on the key line when there is one.
        point = key_line_end
        key_end = self._key_text_end(parent_path, description)
        if key_end is not None:
            colon = self.source.find(":", key_end, key_line_end)
            if colon >= 0:
                comment = self.source.find(" #", colon + 1, key_line_end)
                if comment >= 0:
                    point = comment
        token = " []" if isinstance(parent, list) else " {}"
        return (point, point, token)

    def _iter_addition_paths(self) -> Iterator[tuple[Any, ...]]:
        """Yield the top-most paths of Python-created nodes.

        A child whose native node id is missing (``-1``) exists only in the
        data, so when external patches are present it must be re-inserted
        through an explicit patch; the walk stops at additions because a
        patch renders the whole added subtree.
        """
        stack = [((), self._data)]
        while stack:
            path, value = stack.pop()
            if isinstance(value, dict):
                entry_nodes = getattr(value, "_pyy_entry_nodes", None)
                if entry_nodes is None:
                    # A plain (user-assigned) container carries no node ids;
                    # the native patcher owns its content via per-value edits
                    # or a whole-container rewrite.
                    continue
                for key, child in dict.items(value):
                    if key == "<<":
                        continue
                    pair = entry_nodes.get(key)
                    child_id = int(pair[1]) if pair is not None else -1
                    if child_id < 0:
                        if path + (key,) not in self._virtual_entries:
                            yield path + (key,)
                    else:
                        stack.append((path + (key,), child))
            elif isinstance(value, list):
                node_ids = getattr(value, "_pyy_node_ids", None)
                if node_ids is None:
                    continue
                for index, child in enumerate(value):
                    child_id = int(node_ids[index]) if index < len(node_ids) else -1
                    if child_id < 0:
                        if path + (index,) not in self._virtual_entries:
                            yield path + (index,)
                    else:
                        stack.append((path + (index,), child))

    def _inline_patch_range(
        self,
        path: tuple[Any, ...],
        description: dict[str, Any],
    ) -> tuple[int, int]:
        value_start, value_end = (int(description["value_span"][0]), int(description["value_span"][1]))
        entry = self._entry_span(path)
        if entry is not None:
            entry_start, _ = entry
            entry_line_start = self.source.rfind("\n", 0, entry_start) + 1
            entry_line_end = self.source.find("\n", entry_start)
            if entry_line_end < 0:
                entry_line_end = len(self.source)
            node_line_start = self.source.rfind("\n", 0, int(description["span"][0])) + 1
            if node_line_start > entry_line_start:
                colon = self.source.find(":", entry_line_start, entry_line_end)
                if colon >= 0:
                    start = colon + 1
                    while start < entry_line_end and self.source[start] == " ":
                        start += 1
                    return start, int(description["span"][1])
        return value_start, value_end
    def _make_span(self, start: int, end: int) -> SourceSpan:
        source = self.source
        prefix = source[:start]
        line = prefix.count("\n") + 1
        column = len(prefix.rsplit("\n", 1)[-1]) + 1
        return SourceSpan(start, end, line, column)

    def _get_comments(self, path: tuple[Any, ...]) -> dict[str, Any]:
        if path in self._comments:
            value = self._comments[path]
            return {
                "before": list(value.get("before", [])),
                "inline": value.get("inline"),
                "after": list(value.get("after", [])),
            }
        description = self._describe(path)
        if description is None or not self.source:
            return {"before": [], "inline": None, "after": []}
        entry = self._entry_span(path) or tuple(description.get("span", (0, 0)))
        value_span = tuple(description.get("value_span", entry))
        # Block-valued entries carry their inline comment on the key line and
        # their after-comments past the value's last line, so both regions are
        # anchored outside the value span (matching _comment_patches).
        line_start = self.source.rfind("\n", 0, int(entry[0])) + 1
        inline_start = self._inline_anchor(path, description, line_start)
        entry_end = max(int(entry[1]), int(value_span[1]))
        current_line_start = self.source.rfind("\n", 0, entry_end) + 1
        if entry_end <= current_line_start:
            after_start: Optional[int] = entry_end
        else:
            line_end = self.source.find("\n", entry_end)
            after_start = len(self.source) if line_end < 0 else line_end + 1
        return _comments_from_source(
            self.source, entry, value_span, inline_start, after_start
        )

    def _set_comment(self, path: tuple[Any, ...], position: str, value: Any) -> None:
        current = self._get_comments(path)
        if position == "inline":
            if value is not None and "\n" in value:
                raise StyleError("inline comments must be a single line")
            if value is not None and not value.startswith("#"):
                raise StyleError("comments must include the leading '#'")
            current["inline"] = value
        else:
            lines = _normalize_comment_lines(value)
            current[position] = lines
        self._comments[path] = current

    def _snapshot(self) -> tuple[Any, ...]:
        """Capture a fully restorable snapshot of the document state.

        The data tree is deep-copied (the native handle is shared, never
        copied), so restoring after a failed mutation also undoes any value
        changes, not just the override registries.
        """
        return (
            self._snapshot_data(),
            dict(self._styles),
            dict(self._collection_styles),
            dict(self._chomping),
            dict(self._block_indent),
            dict(self._tags),
            dict(self._anchors),
            {key: dict(value) for key, value in self._comments.items()},
            dict(self._aliases),
            self._directives_override,
            self._explicit_start_override,
            self._explicit_end_override,
        )

    def _snapshot_data(self) -> tuple[str, Any]:
        memo: dict[int, Any] = {}
        if self._handle is not None:
            # The native handle describes the original source and cannot be
            # deep-copied; share it so restored data keeps its node hints.
            memo[id(self._handle)] = self._handle
        data = self._data
        if data is self:
            # Container-root documents store their data in themselves; copy
            # the underlying storage instead of the document object.
            if isinstance(self, dict):
                return "dict-root", {key: copy.deepcopy(value, memo) for key, value in dict.items(self)}
            return "list-root", [copy.deepcopy(value, memo) for value in list(self)]
        return "value", copy.deepcopy(data, memo)

    def _restore(self, snapshot: tuple[Any, ...]) -> None:
        (
            data_state,
            styles,
            collection_styles,
            chomping,
            block_indent,
            tags,
            anchors,
            comments,
            aliases,
            directives,
            explicit_start,
            explicit_end,
        ) = snapshot
        kind, data = data_state
        if kind == "dict-root":
            # Raw base-class calls keep the round-trip metadata untouched.
            dict.clear(self)
            for key, value in data.items():
                dict.__setitem__(self, key, value)
        elif kind == "list-root":
            list.clear(self)
            for value in data:
                list.append(self, value)
        else:
            self._data = data
        self._styles = styles
        self._collection_styles = collection_styles
        self._chomping = chomping
        self._block_indent = block_indent
        self._tags = tags
        self._anchors = anchors
        self._comments = comments
        self._aliases = aliases
        self._directives_override = directives
        self._explicit_start_override = explicit_start
        self._explicit_end_override = explicit_end

    def _discard_overrides(self, path: tuple[Any, ...]) -> None:
        for mapping in (
            self._styles,
            self._collection_styles,
            self._chomping,
            self._block_indent,
            self._tags,
            self._anchors,
            self._comments,
            self._aliases,
        ):
            for key in list(mapping):
                if key == path or key[: len(path)] == path:
                    mapping.pop(key, None)

    def dump(
        self,
        stream: Any = None,
        *,
        config: Optional[IndentConfig] = None,
        explicit_start: Optional[bool] = None,
        explicit_end: Optional[bool] = None,
    ) -> Optional[str]:
        selected = config or self._config
        start = self.explicit_start if explicit_start is None else explicit_start
        end = self.explicit_end if explicit_end is None else explicit_end
        if self._root_replaced:
            # The root was swapped out, so the original source no longer
            # describes the document: re-emit everything from the data.
            text = self._emit_new(selected, start=start, end=end)
        else:
            patches = self._build_patches(selected)
            override_paths = (
                set(self._styles)
                | set(self._collection_styles)
                | set(self._chomping)
                | set(self._block_indent)
                | set(self._tags)
                | set(self._anchors)
                | set(self._comments)
                | set(self._aliases)
            )
            unsupported_new_paths = any(
                self._describe(path) is None
                and self._new_node_insertion_patch(path, selected) is None
                for path in override_paths
            )
            additions_unpatchable = False
            # Removals: the native patcher deletes source entries missing from
            # the data only when external patches exist. Seed the list with the
            # deletion ranges so a pure removal avoids the canonical re-emit of
            # the parent (which loses nested comments); the native deletion
            # edits dedupe against these.
            if self._removals and self._handle is not None:
                removal_patches: list[tuple[int, int, str]] = []
                for parent_id, value_id in self._removals:
                    removal_patches.extend(self._new_node_removal_patch(parent_id, value_id))
                # One emptied-container render per insertion point: two
                # removals emptying the same parent would otherwise insert
                # `{}` twice.
                seen: set[tuple[int, int, str]] = set()
                for patch in removal_patches:
                    if patch not in seen:
                        seen.add(patch)
                        patches.append(patch)
            if not unsupported_new_paths and (patches or self._has_dirty_data()):
                # With external patches the native patcher skips Python-created
                # items instead of rewriting their containers, so every addition
                # needs an explicit insertion patch here — including the case
                # where these are the only changes (otherwise the whole dirty
                # container is re-emitted canonically, losing sibling comments
                # and source-specific indentation). A document with no dirty
                # container and no overrides dumps verbatim, so additions that
                # only exist in its resolved view (merge keys) are left alone.
                # Deeper insertions come first: at a shared position an inner
                # item must land inside the outer item's block. When any
                # addition cannot be positioned, no patches are sent at all and
                # the native dirty path handles the additions with a localized
                # canonical re-emit instead of a full fresh render.
                addition_patches = []
                for path in self._iter_addition_paths():
                    if path in override_paths:
                        continue
                    patch = self._new_node_insertion_patch(path, selected)
                    if patch is None:
                        additions_unpatchable = True
                        break
                    addition_patches.append((len(path), patch))
                if not additions_unpatchable:
                    addition_patches.sort(key=lambda item: (item[1][0], -item[0]))
                    patches.extend(patch for _, patch in addition_patches)
            # Without any other patches the native dirty path re-emits only the
            # containers that changed, additions included, so an unpositionable
            # addition there is safe. With other patches present the native
            # patcher would skip Python-created items entirely (dropping the
            # addition), which forces the full fresh render.
            needs_new_emitter = (
                self._handle is None
                or unsupported_new_paths
                or (additions_unpatchable and bool(patches))
            )
            if needs_new_emitter:
                text = self._emit_new(selected, start=start, end=end)
            else:
                try:
                    offsets = self._require_offsets()
                    native_patches = [
                        (offsets.to_byte(int(span_start)), offsets.to_byte(int(span_end)), replacement)
                        for span_start, span_end, replacement in patches
                    ]
                    text = _native.dump_with_patches(
                        self._data,
                        native_patches,
                        config=selected,
                        explicit_start=start,
                        handle=self._handle,
                        node_id=self._root_id,
                    )
                except _native.NativeYamlError as exc:
                    raise translate_native_error(exc, self.source) from None
                if self._directives_override is not None:
                    text = _replace_directives(text, self._directives_override)
                if end and not _has_explicit_end(text):
                    if text and not text.endswith("\n"):
                        text += "\n"
                    text += "...\n"
        if stream is None:
            return text
        stream.write(text)
        return None

    def _build_patches(self, config: IndentConfig) -> list[tuple[int, int, str]]:
        patches: list[tuple[int, int, str]] = []
        override_paths = (
            set(self._styles)
            | set(self._collection_styles)
            | set(self._chomping)
            | set(self._block_indent)
            | set(self._tags)
            | set(self._anchors)
            | set(self._comments)
            | set(self._aliases)
        )
        for path in override_paths:
            if self._describe(path) is None:
                patch = self._new_node_insertion_patch(path, config)
                if patch is not None:
                    patches.append(patch)
        for path, style in self._styles.items():
            description = self._describe(path)
            if description is None:
                continue
            value = self._at(path)
            chomping = self._chomping.get(path)
            indent = self._block_indent.get(path)
            replacement = _render_scalar(value, style, chomping=chomping, block_indent=indent)
            start, end = description["value_span"]
            patches.append((int(start), int(end), replacement))
        for path, style in self._collection_styles.items():
            description = self._describe(path)
            if description is None:
                continue
            value = self._at(path)
            replacement = _render_document_node(self, path, config)
            start, end = self._inline_patch_range(path, description)
            patches.append((start, end, " " + replacement))
        for path in set(self._chomping) | set(self._block_indent):
            if path in self._styles:
                continue
            description = self._describe(path)
            if description is None:
                continue
            style = self._style_at(path)
            if style is None:
                continue
            value = self._at(path)
            replacement = _render_scalar(
                value,
                style,
                chomping=self._chomping.get(path),
                block_indent=self._block_indent.get(path),
            )
            start, end = description["value_span"]
            patches.append((int(start), int(end), replacement))
        for path, tag in self._tags.items():
            description = self._describe(path)
            if description is None:
                continue
            anchor = self._anchors.get(path, description.get("anchor"))
            patches.extend(self._property_patches(path, description, tag, anchor))
        for path, anchor in self._anchors.items():
            if path in self._tags:
                continue
            description = self._describe(path)
            if description is None:
                continue
            patches.extend(self._property_patches(path, description, description.get("raw_tag"), anchor))
        for path, comments in self._comments.items():
            patches.extend(self._comment_patches(path, comments))
        for path, anchor in self._aliases.items():
            description = self._describe(path)
            if description is None:
                continue
            start, end = self._inline_patch_range(path, description)
            lead = "" if start == int(description["value_span"][0]) else " "
            patches.append((start, end, lead + f"*{anchor}"))
        return _merge_patches(patches)

    def _property_patches(
        self,
        path: tuple[Any, ...],
        description: dict[str, Any],
        tag: Any,
        anchor: Any,
    ) -> list[tuple[int, int, str]]:
        value_start = int(description["value_span"][0])
        entry = self._entry_span(path)
        properties = ""
        if tag:
            properties += f"{tag} "
        if anchor:
            properties += f"&{anchor} "
        if not properties:
            return []
        if entry is not None:
            entry_start, _ = entry
            entry_line_start = self.source.rfind("\n", 0, entry_start) + 1
            node_line_start = self.source.rfind("\n", 0, int(description["span"][0])) + 1
            if node_line_start > entry_line_start:
                entry_line_end = self.source.find("\n", entry_start)
                if entry_line_end < 0:
                    entry_line_end = len(self.source)
                colon = self.source.find(":", entry_line_start, entry_line_end)
                if colon >= 0:
                    start = colon + 1
                    while start < entry_line_end and self.source[start] == " ":
                        start += 1
                    child_indent = int(description["span"][0]) - node_line_start
                    return [(start, node_line_start, " " + properties.strip() + "\n")]
        line_start = self.source.rfind("\n", 0, value_start) + 1
        prefix = self.source[line_start:value_start]
        cleaned = re.sub(r"\s*(?:![^\s]+|&[^\s]+)\s*", " ", prefix).rstrip() + " "
        return [(line_start, value_start, cleaned + properties)]

    def _comment_patches(
        self,
        path: tuple[Any, ...],
        comments: dict[str, Any],
    ) -> list[tuple[int, int, str]]:
        description = self._describe(path)
        if description is None:
            return []
        entry_span = self._entry_span(path) or tuple(description["span"])
        patches: list[tuple[int, int, str]] = []
        entry_start, entry_end = (int(entry_span[0]), int(entry_span[1]))
        line_start = self.source.rfind("\n", 0, entry_start) + 1
        before = comments.get("before")
        if before is not None:
            start = self._comment_prefix_start(line_start)
            text = "".join(f"{line}\n" for line in before)
            patches.append((start, line_start, text))
        inline = comments.get("inline")
        # The patch is emitted even for a cleared comment (``inline is None``):
        # the anchor replaces the whole tail after the value/colon, so an empty
        # replacement wipes a source comment the user cleared.
        anchor = self._inline_anchor(path, description, line_start)
        line_end = self.source.find("\n", anchor)
        if line_end < 0:
            line_end = len(self.source)
        replacement = f"  {inline}" if inline else ""
        patches.append((anchor, line_end, replacement))
        after = comments.get("after")
        if after is not None:
            next_start = self._next_sibling_start(path)
            if next_start is None:
                next_start = len(self.source)
            # The entry extends through its block value, so after-comments
            # belong past the value's last line — anchoring at the key line
            # would place (or empty-patch) inside the block.
            entry_end = max(entry_end, int(description["value_span"][1]))
            current_line_start = self.source.rfind("\n", 0, entry_end) + 1
            if entry_end <= current_line_start:
                start = entry_end
            else:
                line_end = self.source.find("\n", entry_end)
                start = len(self.source) if line_end < 0 else line_end + 1
            text = "".join(f"{line}\n" for line in after)
            patches.append((start, next_start, text))
        return patches

    def _inline_anchor(
        self,
        path: tuple[Any, ...],
        description: dict[str, Any],
        line_start: int,
    ) -> int:
        """Where an inline-comment replacement starts for the entry at ``path``.

        The comment replaces the tail of the line that carries the entry. For
        scalars and flow values that is the value's own line; for block
        scalars the header line; for block collections the key line right
        after the colon — anchoring at a block value's span end would land
        inside or past the block and wipe its content instead of the comment.
        """
        value_span = description["value_span"]
        value_start, value_end = int(value_span[0]), int(value_span[1])
        value_start_line = self.source.rfind("\n", 0, value_start) + 1
        if value_start_line == line_start:
            if self._style_at(path) in (ScalarStyle.LITERAL, ScalarStyle.FOLDED):
                # Block scalar: the comment rides on the header line after the
                # indicator, never inside the scalar's content.
                header_end = self.source.find("\n", line_start)
                if header_end < 0:
                    header_end = len(self.source)
                return _comment_tail_anchor(
                    self.source[value_start:header_end], value_start, header_end
                )
            return value_end
        key_end = self._key_text_end(path, description)
        if key_end is not None:
            search_end = self.source.find("\n", key_end)
            if search_end < 0:
                search_end = len(self.source)
            colon = self.source.find(":", key_end, search_end)
            if colon >= 0:
                # Replace only the comment tail: key-line properties (anchors,
                # tags) between the colon and the comment must survive.
                return _comment_tail_anchor(
                    self.source[colon + 1 : search_end], colon + 1, search_end
                )
        # Sequence items (and anything without a key span): append at the end
        # of the entry's first line instead of wiping its tail.
        entry_line_end = self.source.find("\n", line_start)
        return len(self.source) if entry_line_end < 0 else entry_line_end

    def _key_text_end(self, path: tuple[Any, ...], description: dict[str, Any]) -> Optional[int]:
        """The character offset just past the entry's key text, if known."""
        if not path or self._handle is None:
            return None
        node_id = description.get("id")
        parent_description = self._describe(path[:-1])
        if node_id is None or parent_description is None:
            return None
        for child in parent_description.get("children") or ():
            if child.get("value_id") == node_id and child.get("key_span") is not None:
                return int(child["key_span"][1])
        return None

    def _comment_prefix_start(self, line_start: int) -> int:
        cursor = line_start
        while cursor > 0:
            previous_end = cursor - 1
            previous_start = self.source.rfind("\n", 0, previous_end) + 1
            line = self.source[previous_start:previous_end]
            if line.strip() and not line.lstrip().startswith("#"):
                break
            cursor = previous_start
        return cursor
    def _next_sibling_start(self, path: tuple[Any, ...]) -> Optional[int]:
        if not path:
            return None
        parent = self._at(path[:-1])
        key = path[-1]
        if isinstance(parent, dict):
            keys = list(parent)
            index = keys.index(key)
            if index + 1 < len(keys):
                next_path = path[:-1] + (keys[index + 1],)
                span = self._entry_span(next_path)
                return span[0] if span else None
        elif isinstance(parent, list):
            index = int(key)
            if index + 1 < len(parent):
                description = self._describe(path[:-1] + (index + 1,))
                if description is not None:
                    # A sequence item's region starts at its dash line, not at
                    # the value span, so the after-comment insertion keeps the
                    # next item's dash and indentation intact.
                    value_start = int(description["span"][0])
                    return self.source.rfind("\n", 0, value_start) + 1
        return None

    def _emit_new(self, config: IndentConfig, *, start: bool, end: bool) -> str:
        lines = list(self._directives_override or [])
        if start and not any(line.strip() == "---" for line in lines):
            lines.append("---")
        body = _render_document_node(self, (), config) if self._data is not None else "null"
        if lines:
            prefix = "\n".join(lines) + "\n"
        else:
            prefix = ""
        text = prefix + body
        if not text.endswith("\n"):
            text += "\n"
        if end:
            text += "...\n"
        return text


class DocumentMapping(RoundTripMap, Document):
    """A mapping-root document that can replace a normal ``dict`` directly."""

    def __eq__(self, other: Any) -> bool:
        return dict.__eq__(self, other._data if isinstance(other, Document) else other)

    def __init__(self, data: dict, **kwargs: Any) -> None:
        dict.__init__(self, data)
        for name in ("_pyy_handle", "_pyy_node_id", "_pyy_dirty", "_pyy_entry_nodes"):
            if hasattr(data, name):
                setattr(self, name, getattr(data, name))
        Document.__init__(self, self, **kwargs)
        self._data = self

    # dict.__getitem__/dict.get/dict.items/dict.values shadow the resolved
    # Document views in the MRO; re-expose them so reads go through the
    # document (alias entries read through to their targets) instead of the
    # raw storage.
    def __getitem__(self, key: Any) -> Any:
        return Document.__getitem__(self, key)

    def get(self, key: Any, default: Any = None) -> Any:
        return Document.get(self, key, default)

    def items(self):
        return Document.items(self)

    def values(self):
        return Document.values(self)

    def __bool__(self) -> bool:
        return dict.__len__(self) != 0


class DocumentSequence(RoundTripList, Document):
    """A sequence-root document that can replace a normal ``list`` directly."""

    def __eq__(self, other: Any) -> bool:
        return list.__eq__(self, other._data if isinstance(other, Document) else other)

    def __init__(self, data: list, **kwargs: Any) -> None:
        list.__init__(self, data)
        for name in ("_pyy_handle", "_pyy_node_id", "_pyy_dirty", "_pyy_node_ids"):
            if hasattr(data, name):
                setattr(self, name, getattr(data, name))
        Document.__init__(self, self, **kwargs)
        self._data = self

    # list.__getitem__ shadows the alias-resolving Document read in the MRO.
    def __getitem__(self, key: Any) -> Any:
        return Document.__getitem__(self, key)

    def __bool__(self) -> bool:
        return list.__len__(self) != 0


class DocumentScalar(Document):
    """A scalar-root document with normal numeric and string coercions."""

    def __eq__(self, other: Any) -> bool:
        return self._data == (other._data if isinstance(other, Document) else other)

    def __hash__(self) -> int:
        # Consistent with __eq__: a scalar document hashes like its value.
        return hash(self._data)


def _document_type(value: Any) -> type[Document]:
    if isinstance(value, dict):
        return DocumentMapping
    if isinstance(value, list):
        return DocumentSequence
    return DocumentScalar


def _make_document(value: Any, **kwargs: Any) -> Document:
    return _document_type(value)(value, **kwargs)


class DocumentStream:
    """A mutable ordered collection of styled YAML documents."""

    def __init__(self, documents: Iterable[Document] = (), *, source: str = "", handle: Any = None) -> None:
        self._documents = list(documents)
        self._source = source
        self._handle = handle

    def __len__(self) -> int:
        return len(self._documents)

    def __iter__(self) -> Iterator[Document]:
        return iter(self._documents)

    def __getitem__(self, index: int) -> Document:
        return self._documents[index]

    def append(self, document: Document) -> None:
        if not isinstance(document, Document):
            raise TypeError("DocumentStream items must be Document objects")
        self._documents.append(document)

    def insert(self, index: int, document: Document) -> None:
        if not isinstance(document, Document):
            raise TypeError("DocumentStream items must be Document objects")
        self._documents.insert(index, document)

    def remove(self, index: int) -> Document:
        return self._documents.pop(index)

    def dump(
        self,
        stream: Any = None,
        *,
        config: Optional[IndentConfig] = None,
        explicit_start: Optional[bool] = None,
        explicit_end: Optional[bool] = None,
    ) -> Optional[str]:
        """Dump the stream, honoring explicit document start/end markers.

        ``explicit_start``/``explicit_end`` default to ``None``, which keeps
        each document's own markers (unchanged sources are returned verbatim);
        ``True`` adds any missing marker and ``False`` removes the stream's
        leading start marker (and a trailing end marker). The first document
        follows the requested start marker; later documents always get their
        required ``---`` separator.
        """
        unchanged = self._handle is not None and not any(
            doc._has_style_changes() for doc in self._documents
        )
        if unchanged:
            text = self._source
            if explicit_start is True and not _has_start_marker(text):
                text = "---\n" + text if text else "---\n"
            elif explicit_start is False:
                text = _strip_start_marker(text)
            if explicit_end is True:
                text = _add_stream_end_markers(text)
            elif explicit_end is False:
                text = _strip_end_marker(text)
            if stream is None:
                return text
            stream.write(text)
            return None
        selected = config or DEFAULT_CONFIG
        first_start = True if explicit_start is None else explicit_start
        parts = []
        for position, doc in enumerate(self._documents):
            start = first_start if position == 0 else True
            end = doc.explicit_end if explicit_end is None else explicit_end
            parts.append(doc._emit_new(selected, start=start, end=end))
        text = "".join(part if part.endswith("\n") else part + "\n" for part in parts)
        if stream is None:
            return text
        stream.write(text)
        return None


def load_document(stream: Any) -> Document:
    text = _read_stream(stream)
    try:
        value, handle = _native.parse(text, safe=False)
    except _native.NativeYamlError as exc:
        raise translate_native_error(exc, text) from None
    root_ids = handle.root_ids()
    root_id = int(root_ids[0]) if root_ids else -1
    return _make_document(value, handle=handle, root_id=root_id, source=text)


def load_documents(stream: Any) -> DocumentStream:
    text = _read_stream(stream)
    try:
        values, handle = _native.parse_all(text, safe=False)
    except _native.NativeYamlError as exc:
        raise translate_native_error(exc, text) from None
    root_ids = handle.root_ids()
    documents = [
        _make_document(value, handle=handle, root_id=int(root_id), source=text)
        for value, root_id in zip(values, root_ids)
    ]
    return DocumentStream(documents, source=text, handle=handle)


def read_document(path: str | Path) -> Document:
    return load_document(Path(path).read_text(encoding="utf-8"))


def read_documents(path: str | Path) -> DocumentStream:
    return load_documents(Path(path).read_text(encoding="utf-8"))


def _read_stream(stream: Any) -> str:
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


def _normalize_comment_lines(value: Any) -> list[str]:
    if value is None:
        return []
    lines = value.split("\n") if isinstance(value, str) else list(value)
    for line in lines:
        if line and not line.lstrip().startswith("#"):
            raise StyleError("comments must include the leading '#'")
    return lines


def _comment_tail_anchor(tail: str, tail_start: int, line_end: int) -> int:
    """The offset where an inline-comment region starts within a line tail.

    Points at an existing `` #`` comment so it gets replaced — including the
    pure whitespace between the colon and it, so the replacement controls the
    spacing — or past the non-comment content, so a new comment is appended
    without touching anchors or tags that share the line.
    """
    comment = tail.find(" #")
    if comment >= 0:
        if not tail[:comment].strip():
            return tail_start
        return tail_start + comment
    return tail_start + len(tail.rstrip())


def _comments_from_source(
    source: str,
    entry_span: tuple[int, int],
    value_span: tuple[int, int],
    inline_start: Optional[int] = None,
    after_start: Optional[int] = None,
) -> dict[str, Any]:
    """Extract an entry's comments from the source text.

    ``inline_start`` and ``after_start`` let block-valued entries anchor the
    inline and after regions outside their value's span (the value of a block
    collection ends far below the key line where its comment lives).
    """
    start, end = entry_span
    before_start = source.rfind("\n", 0, start) + 1
    before: list[str] = []
    cursor = before_start
    while cursor > 0:
        previous_end = cursor - 1
        previous_start = source.rfind("\n", 0, previous_end) + 1
        line = source[previous_start:previous_end]
        if line.strip() and not line.lstrip().startswith("#"):
            break
        before.append(line)
        cursor = previous_start
    before.reverse()
    value_end = min(max(value_span[1], value_span[0]), len(source))
    inline_from = value_end if inline_start is None else max(0, inline_start)
    inline_end = source.find("\n", inline_from)
    if inline_end < 0:
        inline_end = len(source)
    inline_text = source[inline_from:inline_end].strip()
    inline = inline_text if inline_text.startswith("#") else None
    after: list[str] = []
    after_from = end if after_start is None else after_start
    current_line_start = source.rfind("\n", 0, after_from) + 1
    if after_from <= current_line_start:
        cursor = after_from
    else:
        line_end = source.find("\n", after_from)
        cursor = len(source) if line_end < 0 else line_end + 1
    while cursor < len(source):
        next_end = source.find("\n", cursor)
        if next_end < 0:
            line = source[cursor:]
            cursor = len(source)
        else:
            line = source[cursor:next_end]
            cursor = next_end + 1
        if line.strip() and not line.lstrip().startswith("#"):
            break
        after.append(line)
    return {"before": before, "inline": inline, "after": after}


def _render_document_node(document: Document, path: tuple[Any, ...], config: IndentConfig) -> str:
    return _render_node(document, path, document._at(path), config, 0)


def _render_node(
    document: Document,
    path: tuple[Any, ...],
    value: Any,
    config: IndentConfig,
    indent: int,
    flow: bool = False,
    *,
    hoist_comments: bool = False,
) -> str:
    pad = " " * indent
    comments = document._get_comments(path)
    if hoist_comments:
        # The parent renders entry-level before/after comments aligned with
        # the key line; only the inline comment belongs to the value itself.
        comments = {**comments, "before": [], "after": []}
    before = [f"{pad}{line}" if line else "" for line in comments.get("before", [])]
    if path in document._aliases:
        core = f"*{document._aliases[path]}"
    elif isinstance(value, dict):
        node_flow = flow or document._collection_styles.get(path) is CollectionStyle.FLOW
        core = _render_mapping(document, path, value, config, indent, node_flow)
    elif isinstance(value, list):
        node_flow = flow or document._collection_styles.get(path) is CollectionStyle.FLOW
        core = _render_sequence(document, path, value, config, indent, node_flow)
    else:
        style = document._styles.get(path) or _default_scalar_style(value)
        core = _render_scalar(
            value,
            style,
            chomping=document._chomping.get(path),
            block_indent=document._block_indent.get(path),
            indent=indent,
        )
    tag = document._tags.get(path)
    anchor = document._anchors.get(path)
    if path not in document._tags:
        description = document._describe(path)
        tag = (description.get("raw_tag") or description.get("tag")) if description else None
    if path not in document._anchors:
        description = document._describe(path)
        anchor = description.get("anchor") if description else None
    properties = " ".join(part for part in (tag, f"&{anchor}" if anchor else None) if part)
    if properties:
        core = f"{properties} {core}"
    inline = comments.get("inline")
    if inline:
        core += f"  {inline}"
    if before:
        core = "\n".join(before) + "\n" + core
    after = [f"{pad}{line}" if line else "" for line in comments.get("after", [])]
    if after:
        core += "\n" + "\n".join(after)
    return core



def _rendered_is_inline(
    document: Document,
    path: tuple[Any, ...],
    value: Any,
    rendered: str,
) -> bool:
    if isinstance(value, (dict, list)):
        return document._collection_styles.get(path) is CollectionStyle.FLOW or rendered.startswith(("{", "["))
    if rendered.startswith(("|", ">")):
        return True
    return "\n" not in rendered
def _render_mapping(
    document: Document,
    path: tuple[Any, ...],
    value: dict[Any, Any],
    config: IndentConfig,
    indent: int,
    flow: bool,
) -> str:
    if flow:
        entries = []
        for key, child in value.items():
            child_path = path + (key,)
            entries.append(
                f"{_render_scalar(key, ScalarStyle.PLAIN)}: "
                f"{_render_node(document, child_path, child, config, 0, flow=True)}"
            )
        return "{" + ", ".join(entries) + "}"
    if not value:
        return "{}"
    lines: list[str] = []
    child_indent = indent + config.mapping
    for key, child in value.items():
        child_path = path + (key,)
        child_comments = document._get_comments(child_path)
        for line in child_comments.get("before", []):
            lines.append(f"{' ' * indent}{line}" if line else "")
        rendered = _render_node(
            document, child_path, child, config, child_indent, hoist_comments=True
        )
        key_text = _render_scalar(key, _default_scalar_style(key))
        if not _rendered_is_inline(document, child_path, child, rendered):
            lines.append(" " * indent + f"{key_text}:")
            lines.append(rendered)
        else:
            lines.append(" " * indent + f"{key_text}: {rendered}")
        for line in child_comments.get("after", []):
            lines.append(f"{' ' * indent}{line}" if line else "")
    return "\n".join(lines)


def _render_sequence(
    document: Document,
    path: tuple[Any, ...],
    value: list[Any],
    config: IndentConfig,
    indent: int,
    flow: bool,
) -> str:
    if flow:
        items = []
        for index, child in enumerate(value):
            items.append(_render_node(document, path + (index,), child, config, 0, flow=True))
        return "[" + ", ".join(items) + "]"
    if not value:
        return "[]"
    dash_indent = indent + config.offset
    child_indent = indent + config.sequence
    lines: list[str] = []
    for index, child in enumerate(value):
        child_path = path + (index,)
        child_comments = document._get_comments(child_path)
        for line in child_comments.get("before", []):
            lines.append(f"{' ' * dash_indent}{line}" if line else "")
        rendered = _render_node(
            document, child_path, child, config, child_indent, hoist_comments=True
        )
        if not _rendered_is_inline(document, child_path, child, rendered):
            lines.append(" " * dash_indent + "-")
            lines.append(rendered)
        else:
            lines.append(" " * dash_indent + f"- {rendered}")
        for line in child_comments.get("after", []):
            lines.append(f"{' ' * dash_indent}{line}" if line else "")
    return "\n".join(lines)


def _render_scalar(
    value: Any,
    style: ScalarStyle | str,
    *,
    chomping: Chomping | str | None = None,
    block_indent: int | None = None,
    indent: int = 0,
) -> str:
    style = ScalarStyle(style)
    if style is ScalarStyle.LITERAL or style is ScalarStyle.FOLDED:
        if not isinstance(value, str):
            raise StyleError(f"{style.value} style requires a string value")
        marker = "|" if style is ScalarStyle.LITERAL else ">"
        chomp = None
        if chomping is not None:
            chomping = Chomping(chomping)
            chomp = {Chomping.STRIP: "-", Chomping.KEEP: "+"}.get(chomping)
        if block_indent is not None:
            marker += str(block_indent)
        if chomp:
            marker += chomp
        lines = value.rstrip("\n").split("\n")
        body = "\n".join(" " * (indent + 2) + line for line in lines)
        return marker + "\n" + body
    if style is ScalarStyle.SINGLE:
        return "'" + str(value).replace("'", "''") + "'"
    if style is ScalarStyle.DOUBLE:
        return '"' + _escape_double(str(value)) + '"'
    return _plain_scalar(value)


def _plain_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        if value != value:
            return ".nan"
        if value == float("inf"):
            return ".inf"
        if value == float("-inf"):
            return "-.inf"
    text = str(value)
    if isinstance(value, str) and _plain_would_change_type(text):
        return "'" + text.replace("'", "''") + "'"
    return text


def _default_scalar_style(value: Any) -> ScalarStyle:
    if isinstance(value, str) and "\n" in value:
        return ScalarStyle.LITERAL
    return ScalarStyle.PLAIN


def _escape_double(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _plain_would_change_type(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"", "~", "null", "true", "false", ".inf", ".nan"}:
        return True
    if re.fullmatch(r"[-+]?(?:0|[1-9][0-9_]*)", value):
        return True
    if re.fullmatch(r"[-+]?(?:[0-9][0-9_]*\.[0-9_]*|[0-9][0-9_]*[eE][-+]?[0-9]+)", value):
        return True
    return value.startswith(("#", "-", "?", ":", ",", "[", "]", "{", "}", "&", "*", "!", "|", ">", "@", "`"))


def _base_indent(source: str, position: int) -> int:
    line_start = source.rfind("\n", 0, position) + 1
    return len(source[line_start:position]) - len(source[line_start:position].lstrip(" "))


def _shift_after_first_line(value: str, indent: int) -> str:
    if indent <= 0 or "\n" not in value:
        return value
    lines = value.split("\n")
    return lines[0] + "\n" + "\n".join(" " * indent + line for line in lines[1:])


def _merge_patches(patches: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    ordered = sorted(patches, key=lambda patch: (patch[0], patch[1]))
    merged: list[tuple[int, int, str]] = []
    for patch in ordered:
        if merged and patch[0] < merged[-1][1] and patch[0] >= merged[-1][0]:
            previous = merged[-1]
            if patch[1] >= previous[1]:
                merged[-1] = patch
            continue
        merged.append(patch)
    return merged


def _replace_directives(text: str, directives: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    had_start = False
    while lines and (lines[0].lstrip().startswith("%") or lines[0].strip() == "---"):
        if lines[0].strip() == "---":
            had_start = True
        lines.pop(0)
    prefix = "".join(f"{directive}\n" for directive in directives)
    if had_start:
        prefix += "---\n"
    return prefix + "".join(lines)


def _has_explicit_end(text: str) -> bool:
    return any(
        line.strip() == "..." and not line.startswith((" ", "\t"))
        for line in text.splitlines()[-3:]
    )


def _has_start_marker(text: str) -> bool:
    """Whether ``text`` opens with a ``---`` document start marker.

    Blank lines, comments and directives before the marker are skipped.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("%"):
            continue
        return stripped == "---"
    return False


def _strip_start_marker(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        return "".join(lines[1:])
    return text


def _strip_end_marker(text: str) -> str:
    lines = text.splitlines(keepends=True)
    index = len(lines) - 1
    while index >= 0 and not lines[index].strip():
        index -= 1
    if index >= 0 and lines[index].strip() == "..." and not lines[index].startswith((" ", "\t")):
        del lines[index:]
    return "".join(lines)


def _add_stream_end_markers(text: str) -> str:
    """Terminate every document in ``text`` with an unindented ``...``."""
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    for line in lines:
        if (
            output
            and line.strip() == "---"
            and not line.startswith((" ", "\t"))
            and output[-1].strip() != "..."
        ):
            output.append("...\n")
        output.append(line)
    if not output:
        return "...\n"
    if output[-1].strip() != "...":
        if not output[-1].endswith("\n"):
            output[-1] += "\n"
        output.append("...\n")
    return "".join(output)
















