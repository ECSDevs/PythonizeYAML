"""Mutable, style-aware YAML documents layered over the native engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from . import _native
from .config import DEFAULT_CONFIG, IndentConfig
from .errors import AliasError, PathError, StyleError, translate_native_error
from .styles import Chomping, CollectionStyle, ScalarStyle, SourceSpan

_ANCHOR_RE = re.compile(r"^[^\s\[\]{},*&!|>@`]+$")


def _path_tuple(path: tuple[Any, ...]) -> tuple[Any, ...]:
    if len(path) == 1 and isinstance(path[0], (tuple, list)):
        return tuple(path[0])
    return tuple(path)


def _plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {_plain_value(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, set):
        return {_plain_value(item) for item in value}
    return value


class Comments:
    """Positioned raw comments for one YAML node or entry."""

    def __init__(self, node: "NodeRef") -> None:
        self._node = node

    @property
    def before(self) -> list[str]:
        return self._node._document._get_comments(self._node._path)["before"]

    @before.setter
    def before(self, value: str | Iterable[str] | None) -> None:
        self._node._document._set_comment(self._node._path, "before", value)

    @property
    def inline(self) -> Optional[str]:
        return self._node._document._get_comments(self._node._path)["inline"]

    @inline.setter
    def inline(self, value: Optional[str]) -> None:
        self._node._document._set_comment(self._node._path, "inline", value)

    @property
    def after(self) -> list[str]:
        return self._node._document._get_comments(self._node._path)["after"]

    @after.setter
    def after(self, value: str | Iterable[str] | None) -> None:
        self._node._document._set_comment(self._node._path, "after", value)


class NodeRef:
    """A stable path-based view over one node in a :class:`Document`."""

    def __init__(self, document: "Document", path: tuple[Any, ...]) -> None:
        self._document = document
        self._path = path

    @property
    def path(self) -> tuple[Any, ...]:
        return self._path

    @property
    def span(self) -> Optional[SourceSpan]:
        return self._document._span(self._path)

    @property
    def value(self) -> Any:
        return self._document.value(*self._path)

    @value.setter
    def value(self, value: Any) -> None:
        current_style = self.style
        self._document._validate_value_style(value, current_style)
        self._document._set_value(self._path, value)

    @property
    def style(self) -> Optional[ScalarStyle]:
        override = self._document._styles.get(self._path)
        if override is not None:
            return override
        description = self._document._describe(self._path)
        value = description.get("style") if description else None
        return ScalarStyle(value) if value else None

    @style.setter
    def style(self, value: ScalarStyle | str) -> None:
        style = ScalarStyle(value)
        self._document._validate_scalar_style(self.value, style)
        self._document._styles[self._path] = style

    @property
    def collection_style(self) -> Optional[CollectionStyle]:
        override = self._document._collection_styles.get(self._path)
        if override is not None:
            return override
        description = self._document._describe(self._path)
        value = description.get("collection_style") if description else None
        return CollectionStyle(value) if value else None

    @collection_style.setter
    def collection_style(self, value: CollectionStyle | str) -> None:
        style = CollectionStyle(value)
        self._document._validate_collection_style(self.value, style)
        self._document._collection_styles[self._path] = style

    @property
    def chomping(self) -> Optional[Chomping]:
        override = self._document._chomping.get(self._path)
        if override is not None:
            return override
        description = self._document._describe(self._path)
        value = description.get("chomping") if description else None
        return Chomping(value) if value else None

    @chomping.setter
    def chomping(self, value: Chomping | str | None) -> None:
        chomping = Chomping(value) if value is not None else None
        style = self.style
        if chomping is not None and style not in {ScalarStyle.LITERAL, ScalarStyle.FOLDED}:
            raise StyleError("chomping requires a literal or folded scalar")
        if chomping is None:
            self._document._chomping.pop(self._path, None)
        else:
            self._document._chomping[self._path] = chomping

    @property
    def block_indent_indicator(self) -> Optional[int]:
        return self._document._block_indent.get(self._path)

    @block_indent_indicator.setter
    def block_indent_indicator(self, value: Optional[int]) -> None:
        if value is None:
            self._document._block_indent.pop(self._path, None)
            return
        if not 1 <= value <= 9:
            raise StyleError("block indentation indicator must be between 1 and 9")
        if self.style not in {ScalarStyle.LITERAL, ScalarStyle.FOLDED}:
            raise StyleError("block indentation requires a literal or folded scalar")
        self._document._block_indent[self._path] = value

    @property
    def tag(self) -> Optional[str]:
        if self._path in self._document._tags:
            return self._document._tags[self._path]
        description = self._document._describe(self._path)
        return (description.get("raw_tag") or description.get("tag")) if description else None

    @tag.setter
    def tag(self, value: Optional[str]) -> None:
        if value is not None and not value.startswith("!"):
            raise StyleError("YAML tags must start with '!'")
        if value is None:
            self._document._tags[self._path] = None
        else:
            self._document._tags[self._path] = value

    @property
    def anchor(self) -> Optional[str]:
        if self._path in self._document._anchors:
            return self._document._anchors[self._path]
        description = self._document._describe(self._path)
        return description.get("anchor") if description else None

    @anchor.setter
    def anchor(self, value: Optional[str]) -> None:
        if value is not None and not _ANCHOR_RE.match(value):
            raise StyleError(f"invalid YAML anchor name: {value!r}")
        old = self.anchor
        native_aliases = self._document._native_aliases_for_target(self._path)
        if old is not None and old != value:
            for alias_path, alias_anchor in list(self._document._aliases.items()):
                if alias_anchor == old:
                    self._document._aliases[alias_path] = value
            for alias_path in native_aliases:
                self._document._aliases[alias_path] = value
        if value is None and (
            any(anchor == old for anchor in self._document._aliases.values())
            or bool(native_aliases)
        ):
            raise AliasError("cannot remove an anchor that still has aliases")
        self._document._anchors[self._path] = value
        self._document._anchors[self._path] = value

    @property
    def is_alias(self) -> bool:
        if self._path in self._document._aliases:
            return True
        description = self._document._describe(self._path)
        return bool(description and description.get("kind") == "alias")

    @property
    def alias_target(self) -> Optional["NodeRef"]:
        path = self._document._target_path_for_alias(self._path)
        return NodeRef(self._document, path) if path is not None else None

    @property
    def comments(self) -> Comments:
        return Comments(self)

    def update(self, **values: Any) -> "NodeRef":
        allowed = {
            "value",
            "style",
            "collection_style",
            "chomping",
            "block_indent_indicator",
            "tag",
            "anchor",
            "before",
            "inline",
            "after",
        }
        unknown = set(values) - allowed
        if unknown:
            raise TypeError(f"unsupported node fields: {', '.join(sorted(unknown))}")
        candidate = values.get("value", self.value)
        if "style" in values:
            self._document._validate_scalar_style(candidate, ScalarStyle(values["style"]))
        if "collection_style" in values:
            self._document._validate_collection_style(candidate, CollectionStyle(values["collection_style"]))
        snapshot = self._document._snapshot()
        try:
            if "value" in values:
                self.value = values["value"]
            if "style" in values:
                self.style = values["style"]
            if "collection_style" in values:
                self.collection_style = values["collection_style"]
            if "chomping" in values:
                self.chomping = values["chomping"]
            if "block_indent_indicator" in values:
                self.block_indent_indicator = values["block_indent_indicator"]
            if "tag" in values:
                self.tag = values["tag"]
            if "anchor" in values:
                self.anchor = values["anchor"]
            if "before" in values:
                self.comments.before = values["before"]
            if "inline" in values:
                self.comments.inline = values["inline"]
            if "after" in values:
                self.comments.after = values["after"]
        except Exception:
            self._document._restore(snapshot)
            raise
        return self

    def __repr__(self) -> str:
        return f"NodeRef(path={self._path!r})"

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

    @classmethod
    def new(cls, root: Any = None, *, config: Optional[IndentConfig] = None) -> "Document":
        return cls(root, config=config)

    @property
    def data(self) -> Any:
        return self._data

    @property
    def root(self) -> "NodeRef":
        return NodeRef(self, ())

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

    def __getitem__(self, path: Any) -> Any:
        return self.value(*_path_tuple((path,)))

    def __setitem__(self, path: Any, value: Any) -> None:
        self._set_value(_path_tuple((path,)), value)

    def value(self, *path: Any) -> Any:
        normalized = _path_tuple(path)
        if normalized in self._aliases:
            target = self._target_path_for_alias(normalized)
            if target is not None:
                return self.value(*target)
        current = self._data
        for part in normalized:
            try:
                current = current[part]
            except (KeyError, IndexError, TypeError) as exc:
                raise PathError(f"no YAML node at path {normalized!r}") from exc
        return current

    def node(self, *path: Any) -> "NodeRef":
        normalized = _path_tuple(path)
        if normalized:
            self.value(*normalized)
        return NodeRef(self, normalized)

    def _describe(self, path: tuple[Any, ...]) -> Optional[dict[str, Any]]:
        node_id = self._node_id_for_path(path)
        if self._handle is None or node_id < 0:
            return None
        return dict(self._handle.describe(node_id))

    def _node_id_for_path(self, path: tuple[Any, ...]) -> int:
        current = self._data
        node_id = self._root_id
        for part in path:
            if isinstance(current, dict):
                metadata = getattr(current, "_pyy_entry_nodes", {})
                pair = metadata.get(part)
                node_id = int(pair[1]) if pair is not None else -1
                try:
                    current = current[part]
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
    def _value_for_parent(self, path: tuple[Any, ...]) -> Any:
        current = self._data
        for part in path:
            current = current[part]
        return current

    def set(
        self,
        *path: Any,
        value: Any,
        style: ScalarStyle | str | None = None,
        collection_style: CollectionStyle | str | None = None,
        chomping: Chomping | str | None = None,
        block_indent_indicator: int | None = None,
        tag: str | None = None,
        anchor: str | None = None,
        before: str | Iterable[str] | None = None,
        inline: str | None = None,
        after: str | Iterable[str] | None = None,
    ) -> "NodeRef":
        normalized = _path_tuple(path)
        snapshot = self._snapshot()
        scalar_style = ScalarStyle(style) if style is not None else None
        collection_style_value = CollectionStyle(collection_style) if collection_style is not None else None
        if scalar_style is not None:
            self._validate_scalar_style(value, scalar_style)
        if collection_style_value is not None:
            self._validate_collection_style(value, collection_style_value)
        if chomping is not None:
            effective = scalar_style or (_default_scalar_style(value) if isinstance(value, str) else None)
            if effective not in {ScalarStyle.LITERAL, ScalarStyle.FOLDED}:
                raise StyleError("chomping requires a literal or folded scalar")
        if block_indent_indicator is not None and not 1 <= block_indent_indicator <= 9:
            raise StyleError("block indentation indicator must be between 1 and 9")
        if inline is not None and "\\n" in inline:
            raise StyleError("inline comments must be a single line")
        if tag is not None and not tag.startswith("!"):
            raise StyleError("YAML tags must start with an exclamation mark")
        if anchor is not None and not _ANCHOR_RE.match(anchor):
            raise StyleError(f"invalid YAML anchor name: {anchor!r}")
        try:
            self._set_value(normalized, value, create=True)
            node = NodeRef(self, normalized)
            if style is not None:
                node.style = style
            if collection_style is not None:
                node.collection_style = collection_style
            if chomping is not None:
                node.chomping = chomping
            if block_indent_indicator is not None:
                node.block_indent_indicator = block_indent_indicator
            if tag is not None:
                node.tag = tag
            if anchor is not None:
                node.anchor = anchor
            if before is not None:
                node.comments.before = before
            if inline is not None:
                node.comments.inline = inline
            if after is not None:
                node.comments.after = after
        except Exception:
            self._restore(snapshot)
            raise
        return NodeRef(self, normalized)

    def append(
        self,
        *path: Any,
        value: Any,
        **style_options: Any,
    ) -> "NodeRef":
        normalized = _path_tuple(path)
        sequence = self.value(*normalized)
        if not isinstance(sequence, list):
            raise StyleError("append requires a sequence path")
        sequence.append(value)
        return self.set(*normalized, len(sequence) - 1, value=self.value(*normalized, len(sequence) - 1), **style_options)

    def insert(
        self,
        *path: Any,
        index: int,
        value: Any,
        **style_options: Any,
    ) -> "NodeRef":
        normalized = _path_tuple(path)
        sequence = self.value(*normalized)
        if not isinstance(sequence, list):
            raise StyleError("insert requires a sequence path")
        sequence.insert(index, value)
        return self.set(*normalized, index, value=sequence[index], **style_options)

    def remove(self, *path: Any) -> Any:
        normalized = _path_tuple(path)
        if not normalized:
            raise PathError("cannot remove the document root")
        node_id = self._node_id_for_path(normalized)
        if self._has_aliases_to(node_id):
            raise AliasError("cannot remove a node that still has aliases")
        parent = self.value(*normalized[:-1])
        key = normalized[-1]
        try:
            value = parent[key]
            del parent[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise PathError(f"no YAML node at path {normalized!r}") from exc
        self._discard_overrides(normalized)
        return value

    def alias(
        self,
        *path: Any,
        target: "NodeRef | tuple[Any, ...]",
        anchor: str | None = None,
    ) -> "NodeRef":
        normalized = _path_tuple(path)
        target_node = target if isinstance(target, NodeRef) else self.node(*target)
        if target_node._document is not self:
            raise AliasError("alias target belongs to a different document")
        anchor_name = target_node.anchor
        if anchor_name is None:
            anchor_name = anchor or self._unique_anchor()
            target_node.anchor = anchor_name
        elif anchor is not None and anchor != anchor_name:
            target_node.anchor = anchor
            anchor_name = anchor
        self._aliases[normalized] = anchor_name
        if not self._path_exists(normalized):
            self._set_value(normalized, target_node.value, create=True)
        return NodeRef(self, normalized)

    def _set_value(self, path: tuple[Any, ...], value: Any, *, create: bool = False) -> None:
        if not path:
            self._data = value
            return
        if self._data is None:
            self._data = {}
        current = self._data
        for index, part in enumerate(path[:-1]):
            try:
                current = current[part]
            except (KeyError, IndexError, TypeError):
                if not create or not isinstance(part, str):
                    raise PathError(f"no YAML node at path {path!r}") from None
                next_part = path[index + 1]
                if not isinstance(current, dict):
                    raise PathError(f"cannot create mapping below path {path[: index + 1]!r}")
                current[part] = {} if isinstance(next_part, str) else []
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

    def _path_exists(self, path: tuple[Any, ...]) -> bool:
        try:
            self.value(*path)
            return True
        except PathError:
            return False

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
                description = dict(self._handle.describe(node_id))
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
                for key, child in reversed(list(value.items())):
                    stack.append((path + (key,), child))
            elif isinstance(value, list):
                for index in range(len(value) - 1, -1, -1):
                    stack.append((path + (index,), value[index]))

    def _has_style_changes(self) -> bool:
        return any(
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
        ) or self._directives_override is not None or self._explicit_start_override is not None or self._explicit_end_override is not None
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
        parent = self.value(*parent_path) if parent_path else self.data
        if not isinstance(parent, dict) or path[-1] not in parent:
            return None
        parent_indent = 0
        if parent_path:
            parent_indent = _base_indent(self.source, int(parent_description["span"][0]))
        key = path[-1]
        rendered = _render_node(self, path, parent[key], config, parent_indent)
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
        if index > 0:
            previous = path[:-1] + (keys[index - 1],)
            previous_span = self._entry_span(previous)
            position = previous_span[1] if previous_span else int(parent_description["span"][1])
            current_line_start = self.source.rfind("\n", 0, position) + 1
            if position > current_line_start:
                line_end = self.source.find("\n", position)
                position = len(self.source) if line_end < 0 else line_end + 1
        else:
            position = self.source.rfind("\n", 0, int(parent_description["span"][0])) + 1
        return position, position, entry + "\n"
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
        return _comments_from_source(self.source, entry, value_span)

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
        return (
            self._data,
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

    def _restore(self, snapshot: tuple[Any, ...]) -> None:
        (
            self._data,
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
            self._describe(path) is None and self._new_node_patch(path, selected) is None
            for path in override_paths
        )
        needs_new_emitter = self._handle is None or unsupported_new_paths
        if needs_new_emitter:
            text = self._emit_new(selected, start=start, end=end)
        else:
            try:
                text = _native.dump_with_patches(
                    self._data,
                    patches,
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
                patch = self._new_node_patch(path, config)
                if patch is not None:
                    patches.append(patch)
        for path, style in self._styles.items():
            description = self._describe(path)
            if description is None:
                continue
            value = self.value(*path)
            chomping = self._chomping.get(path)
            indent = self._block_indent.get(path)
            replacement = _render_scalar(value, style, chomping=chomping, block_indent=indent)
            start, end = description["value_span"]
            patches.append((int(start), int(end), replacement))
        for path, style in self._collection_styles.items():
            description = self._describe(path)
            if description is None:
                continue
            value = self.value(*path)
            replacement = _render_document_node(self, path, config)
            start, end = self._inline_patch_range(path, description)
            patches.append((start, end, " " + replacement))
        for path in set(self._chomping) | set(self._block_indent):
            if path in self._styles:
                continue
            description = self._describe(path)
            if description is None:
                continue
            style = NodeRef(self, path).style
            if style is None:
                continue
            value = self.value(*path)
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
        value_span = tuple(description["value_span"])
        patches: list[tuple[int, int, str]] = []
        entry_start, entry_end = (int(entry_span[0]), int(entry_span[1]))
        line_start = self.source.rfind("\n", 0, entry_start) + 1
        before = comments.get("before")
        if before is not None:
            start = self._comment_prefix_start(line_start)
            text = "".join(f"{line}\n" for line in before)
            patches.append((start, line_start, text))
        inline = comments.get("inline")
        if inline is not None:
            line_end = self.source.find("\n", int(value_span[1]))
            if line_end < 0:
                line_end = len(self.source)
            replacement = f"  {inline}" if inline else ""
            patches.append((int(value_span[1]), line_end, replacement))
        after = comments.get("after")
        if after is not None:
            next_start = self._next_sibling_start(path)
            if next_start is None:
                next_start = len(self.source)
            current_line_start = self.source.rfind("\n", 0, entry_end) + 1
            if entry_end <= current_line_start:
                start = entry_end
            else:
                line_end = self.source.find("\n", entry_end)
                start = len(self.source) if line_end < 0 else line_end + 1
            text = "".join(f"{line}\n" for line in after)
            patches.append((start, next_start, text))
        return patches

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
        parent = self.value(*path[:-1])
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
                span = self._entry_span(path[:-1] + (index + 1,))
                return span[0] if span else None
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
        explicit_start: bool = True,
    ) -> Optional[str]:
        unchanged = self._handle is not None and not any(
            doc._has_style_changes() for doc in self._documents
        )
        if unchanged:
            text = self._source
            if stream is None:
                return text
            stream.write(text)
            return None
        selected = config or DEFAULT_CONFIG
        parts = [
            doc._emit_new(selected, start=True, end=doc.explicit_end)
            for doc in self._documents
        ]
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
    return Document(value, handle=handle, root_id=root_id, source=text)


def load_documents(stream: Any) -> DocumentStream:
    text = _read_stream(stream)
    try:
        values, handle = _native.parse_all(text, safe=False)
    except _native.NativeYamlError as exc:
        raise translate_native_error(exc, text) from None
    root_ids = handle.root_ids()
    documents = [
        Document(value, handle=handle, root_id=int(root_id), source=text)
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


def _comments_from_source(
    source: str,
    entry_span: tuple[int, int],
    value_span: tuple[int, int],
) -> dict[str, Any]:
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
    inline_end = source.find("\n", value_end)
    if inline_end < 0:
        inline_end = len(source)
    inline_text = source[value_end:inline_end].strip()
    inline = inline_text if inline_text.startswith("#") else None
    after: list[str] = []
    current_line_start = source.rfind("\n", 0, end) + 1
    if end <= current_line_start:
        cursor = end
    else:
        line_end = source.find("\n", end)
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
    return _render_node(document, path, document.value(*path), config, 0)


def _render_node(
    document: Document,
    path: tuple[Any, ...],
    value: Any,
    config: IndentConfig,
    indent: int,
) -> str:
    pad = " " * indent
    comments = document._get_comments(path)
    before = [f"{pad}{line}" if line else "" for line in comments.get("before", [])]
    if path in document._aliases:
        core = f"*{document._aliases[path]}"
    elif isinstance(value, dict):
        flow = document._collection_styles.get(path) is CollectionStyle.FLOW
        core = _render_mapping(document, path, value, config, indent, flow)
    elif isinstance(value, list):
        flow = document._collection_styles.get(path) is CollectionStyle.FLOW
        core = _render_sequence(document, path, value, config, indent, flow)
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
                f"{_render_node(document, child_path, child, config, 0)}"
            )
        return "{" + ", ".join(entries) + "}"
    if not value:
        return "{}"
    lines: list[str] = []
    child_indent = indent + config.mapping
    for key, child in value.items():
        child_path = path + (key,)
        rendered = _render_node(document, child_path, child, config, child_indent)
        key_text = _render_scalar(key, _default_scalar_style(key))
        if not _rendered_is_inline(document, child_path, child, rendered):
            lines.append(" " * indent + f"{key_text}:")
            lines.append(rendered)
        else:
            lines.append(" " * indent + f"{key_text}: {rendered}")
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
            items.append(_render_node(document, path + (index,), child, config, 0))
        return "[" + ", ".join(items) + "]"
    if not value:
        return "[]"
    dash_indent = indent + config.offset
    child_indent = indent + config.sequence
    lines: list[str] = []
    for index, child in enumerate(value):
        rendered = _render_node(document, path + (index,), child, config, child_indent)
        if not _rendered_is_inline(document, child_path, child, rendered):
            lines.append(" " * dash_indent + "-")
            lines.append(rendered)
        else:
            lines.append(" " * dash_indent + f"- {rendered}")
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
    return any(line.strip() == "..." for line in text.splitlines()[-3:])
















