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

"""Round-trip container and scalar types used by the native PythonizeYAML engine.

Every value reachable through a :class:`~pythonizeyaml.document.Document` is an
instance of one of these classes: mappings and sequences are ``dict``/``list``
subclasses, and scalars are subclasses of their natural Python type. All of
them carry the styling API (``style``, ``tag``, ``anchor``, ``comments``, ...)
so values are styled directly instead of through a separate node handle.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Iterable, Optional

from .errors import PathError, StyleError
from .styles import Chomping, CollectionStyle, ScalarStyle, SourceSpan

_ANCHOR_RE = re.compile(r"^[^\s\[\]{},*&!|>@`]+$")


class _RoundTripMixin:
    _pyy_handle: Any = None
    _pyy_node_id: int = -1
    _pyy_dirty: bool = False
    # Owning Document, set when the value lives inside a document. The hooks
    # below route structural edits to it so path-keyed style overrides stay
    # attached to the right nodes; standalone values skip them.
    _pyy_document: Any = None
    # The path the value was last read through. Styled access validates it
    # (cheap) before falling back to a full identity scan of the document.
    _pyy_path_hint: Any = None

    def _pyy_mark_dirty(self) -> None:
        self._pyy_dirty = True

    def _pyy_before_removal(self, key: Any) -> None:
        if self._pyy_document is not None:
            self._pyy_document._pre_child_removed(self, key)

    def _pyy_after_removal(self, key: Any) -> None:
        if self._pyy_document is not None:
            self._pyy_document._post_child_removed(self, key)

    def _pyy_after_insert(self, index: Any) -> None:
        if self._pyy_document is not None:
            self._pyy_document._post_child_inserted(self, index)

    def _pyy_after_reset(self) -> None:
        if self._pyy_document is not None:
            self._pyy_document._post_children_reset(self)

    # -- path resolution ------------------------------------------------------

    def _pyy_path(self) -> tuple[Any, ...]:
        """The value's current path in its document, resolved by identity."""
        document = self._pyy_document
        if document is None:
            raise PathError(
                "this value is not attached to a document; it was removed, "
                "replaced, or never added"
            )
        return document._require_path(self)

    # -- styling API ----------------------------------------------------------
    #
    # These members used to live on NodeRef views; they now hang directly off
    # the values, which resolve their own path by identity when accessed.

    @property
    def path(self) -> tuple[Any, ...]:
        """The node's current path, resolved by value identity."""
        return self._pyy_path()

    @property
    def span(self) -> Optional[SourceSpan]:
        return self._pyy_document._span(self._pyy_path())

    @property
    def value(self) -> Any:
        return self._pyy_document._at(self._pyy_path())

    @value.setter
    def value(self, value: Any) -> None:
        document = self._pyy_document
        path = self._pyy_path()
        document._validate_value_style(value, document._style_at(path))
        document._set_value(path, value)

    @property
    def style(self) -> Optional[ScalarStyle]:
        return self._pyy_document._style_at(self._pyy_path())

    @style.setter
    def style(self, value: ScalarStyle | str) -> None:
        document = self._pyy_document
        document._set_style_at(self._pyy_path(), value)

    @property
    def collection_style(self) -> Optional[CollectionStyle]:
        return self._pyy_document._collection_style_at(self._pyy_path())

    @collection_style.setter
    def collection_style(self, value: CollectionStyle | str) -> None:
        document = self._pyy_document
        document._set_collection_style_at(self._pyy_path(), value)

    @property
    def chomping(self) -> Optional[Chomping]:
        return self._pyy_document._chomping_at(self._pyy_path())

    @chomping.setter
    def chomping(self, value: Chomping | str | None) -> None:
        document = self._pyy_document
        document._set_chomping_at(self._pyy_path(), value)

    @property
    def block_indent_indicator(self) -> Optional[int]:
        return self._pyy_document._block_indent.get(self._pyy_path())

    @block_indent_indicator.setter
    def block_indent_indicator(self, value: Optional[int]) -> None:
        document = self._pyy_document
        document._set_block_indent_at(self._pyy_path(), value)

    @property
    def tag(self) -> Optional[str]:
        return self._pyy_document._tag_at(self._pyy_path())

    @tag.setter
    def tag(self, value: Optional[str]) -> None:
        document = self._pyy_document
        document._set_tag_at(self._pyy_path(), value)

    @property
    def anchor(self) -> Optional[str]:
        return self._pyy_document._anchor_at(self._pyy_path())

    @anchor.setter
    def anchor(self, value: Optional[str]) -> None:
        self._pyy_document._set_anchor_at(self._pyy_path(), value)

    @property
    def comments(self) -> Comments:
        return Comments(self)

    def set(self, **values: Any) -> "_RoundTripMixin":
        """Apply several style fields in one atomic step and return the value.

        The path is resolved once up front, so the fields stay pinned to this
        node even when ``value`` swaps the stored wrapper. Fails as a whole:
        when any field is invalid nothing is applied.
        """
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
        document = self._pyy_document
        path = self._pyy_path()
        candidate = values.get("value", document._at(path))
        if "style" in values:
            document._validate_scalar_style(candidate, ScalarStyle(values["style"]))
        if "collection_style" in values:
            document._validate_collection_style(
                candidate, CollectionStyle(values["collection_style"])
            )
        snapshot = document._snapshot()
        try:
            if "value" in values:
                document._validate_value_style(values["value"], document._style_at(path))
                document._set_value(path, values["value"])
            if "style" in values:
                document._set_style_at(path, values["style"])
            if "collection_style" in values:
                document._set_collection_style_at(path, values["collection_style"])
            if "chomping" in values:
                document._set_chomping_at(path, values["chomping"])
            if "block_indent_indicator" in values:
                document._set_block_indent_at(path, values["block_indent_indicator"])
            if "tag" in values:
                document._set_tag_at(path, values["tag"])
            if "anchor" in values:
                document._set_anchor_at(path, values["anchor"])
            if "before" in values:
                document._set_comment(path, "before", values["before"])
            if "inline" in values:
                document._set_comment(path, "inline", values["inline"])
            if "after" in values:
                document._set_comment(path, "after", values["after"])
        except Exception:
            document._restore(snapshot)
            raise
        return document._at(path)


class Comments:
    """Positioned raw comments for one YAML node or entry."""

    def __init__(self, node: _RoundTripMixin) -> None:
        self._node = node

    @property
    def before(self) -> list[str]:
        return self._node._pyy_document._get_comments(self._node._pyy_path())["before"]

    @before.setter
    def before(self, value: str | Iterable[str] | None) -> None:
        self._node._pyy_document._set_comment(self._node._pyy_path(), "before", value)

    @property
    def inline(self) -> Optional[str]:
        return self._node._pyy_document._get_comments(self._node._pyy_path())["inline"]

    @inline.setter
    def inline(self, value: Optional[str]) -> None:
        self._node._pyy_document._set_comment(self._node._pyy_path(), "inline", value)

    @property
    def after(self) -> list[str]:
        return self._node._pyy_document._get_comments(self._node._pyy_path())["after"]

    @after.setter
    def after(self, value: str | Iterable[str] | None) -> None:
        self._node._pyy_document._set_comment(self._node._pyy_path(), "after", value)


class RoundTripMap(dict, _RoundTripMixin):
    """A dict that retains its source-node identity for lossless updates."""

    def __init__(self, handle: Any = None, node_id: int = -1, *args: Any, **kwargs: Any) -> None:
        dict.__init__(self, *args, **kwargs)
        self._pyy_handle = handle
        self._pyy_node_id = node_id
        self._pyy_dirty = False
        self._pyy_entry_nodes: dict[Any, tuple[int, int]] = {}

    def __call__(self, *path: Any) -> Any:
        current: Any = self
        for part in path:
            current = current[part]
        return current
    def __setitem__(self, key: Any, value: Any) -> None:
        dict.__setitem__(self, key, prepare_value(value, self._pyy_document))
        self._pyy_entry_nodes.setdefault(key, (-1, -1))
        self._pyy_mark_dirty()

    def __delitem__(self, key: Any) -> None:
        self._pyy_before_removal(key)
        dict.__delitem__(self, key)
        self._pyy_entry_nodes.pop(key, None)
        self._pyy_mark_dirty()
        self._pyy_after_removal(key)

    def clear(self) -> None:
        dict.clear(self)
        self._pyy_entry_nodes.clear()
        self._pyy_mark_dirty()
        self._pyy_after_reset()

    def pop(self, key: Any, *default: Any) -> Any:
        self._pyy_before_removal(key)
        existed = dict.__contains__(self, key)
        value = dict.pop(self, key, *default)
        if existed:
            self._pyy_entry_nodes.pop(key, None)
            self._pyy_mark_dirty()
            self._pyy_after_removal(key)
        return value

    def popitem(self) -> tuple[Any, Any]:
        self._pyy_before_removal(next(reversed(self)))
        item = dict.popitem(self)
        self._pyy_entry_nodes.pop(item[0], None)
        self._pyy_mark_dirty()
        self._pyy_after_removal(item[0])
        return item

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key not in self:
            return self.__setitem__(key, default) or self[key]
        return self[key]

    def update(self, *args: Any, **kwargs: Any) -> None:
        values = dict(*args, **kwargs)
        for key, value in values.items():
            self[key] = value

    def __ior__(self, other: Any):
        self.update(other)
        return self


class RoundTripList(list, _RoundTripMixin):
    """A list that retains source-node identities for each item."""

    def __init__(self, handle: Any = None, node_id: int = -1, *args: Any) -> None:
        list.__init__(self, *args)
        self._pyy_handle = handle
        self._pyy_node_id = node_id
        self._pyy_dirty = False
        self._pyy_node_ids: list[int] = []

    def __call__(self, *path: Any) -> Any:
        current: Any = self
        for part in path:
            current = current[part]
        return current

    def __setitem__(self, index: Any, value: Any) -> None:
        if isinstance(index, slice):
            prepared = [prepare_value(item, self._pyy_document) for item in value]
            list.__setitem__(self, index, prepared)
            self._pyy_node_ids[index] = [-1] * len(prepared)
        else:
            list.__setitem__(self, index, prepare_value(value, self._pyy_document))
            try:
                if index >= len(self._pyy_node_ids):
                    self._pyy_node_ids[index] = -1
            except IndexError:
                pass
        self._pyy_mark_dirty()

    def __delitem__(self, index: Any) -> None:
        self._pyy_before_removal(index)
        list.__delitem__(self, index)
        del self._pyy_node_ids[index]
        self._pyy_mark_dirty()
        self._pyy_after_removal(index)

    def append(self, value: Any) -> None:
        list.append(self, prepare_value(value, self._pyy_document))
        self._pyy_node_ids.append(-1)
        self._pyy_mark_dirty()

    def extend(self, values: Any) -> None:
        prepared = [prepare_value(item, self._pyy_document) for item in values]
        list.extend(self, prepared)
        self._pyy_node_ids.extend([-1] * len(prepared))
        self._pyy_mark_dirty()

    def insert(self, index: int, value: Any) -> None:
        list.insert(self, index, prepare_value(value, self._pyy_document))
        self._pyy_node_ids.insert(index, -1)
        self._pyy_mark_dirty()
        self._pyy_after_insert(index)

    def pop(self, index: int = -1) -> Any:
        self._pyy_before_removal(index)
        value = list.pop(self, index)
        self._pyy_node_ids.pop(index)
        self._pyy_mark_dirty()
        self._pyy_after_removal(index)
        return value

    def clear(self) -> None:
        list.clear(self)
        self._pyy_node_ids.clear()
        self._pyy_mark_dirty()
        self._pyy_after_reset()

    def remove(self, value: Any) -> None:
        index = self.index(value)
        self.__delitem__(index)

    def reverse(self) -> None:
        list.reverse(self)
        self._pyy_node_ids.reverse()
        self._pyy_mark_dirty()
        self._pyy_after_reset()

    def sort(self, *args: Any, **kwargs: Any) -> None:
        list.sort(self, *args, **kwargs)
        self._pyy_node_ids.sort(key=lambda _: 0)
        self._pyy_mark_dirty()
        self._pyy_after_reset()

    def __iadd__(self, values: Any):
        self.extend(values)
        return self


class RoundTripSet(set, _RoundTripMixin):
    """A set carrying source metadata for lossless top-level mutations."""

    def __init__(self, handle: Any = None, node_id: int = -1, *args: Any) -> None:
        set.__init__(self, *args)
        self._pyy_handle = handle
        self._pyy_node_id = node_id
        self._pyy_dirty = False
        self._pyy_node_ids: dict[Any, int] = {}

    def add(self, value: Any) -> None:
        set.add(self, value)
        self._pyy_node_ids.setdefault(value, -1)
        self._pyy_mark_dirty()

    def discard(self, value: Any) -> None:
        set.discard(self, value)
        self._pyy_node_ids.pop(value, None)
        self._pyy_mark_dirty()

    def remove(self, value: Any) -> None:
        set.remove(self, value)
        self._pyy_node_ids.pop(value, None)
        self._pyy_mark_dirty()

    def pop(self) -> Any:
        value = set.pop(self)
        self._pyy_node_ids.pop(value, None)
        self._pyy_mark_dirty()
        return value

    def clear(self) -> None:
        set.clear(self)
        self._pyy_node_ids.clear()
        self._pyy_mark_dirty()


class RoundTripStr(str, _RoundTripMixin):
    """A loaded string value carrying its document position."""


class RoundTripInt(int, _RoundTripMixin):
    """A loaded integer value carrying its document position."""


class RoundTripFloat(float, _RoundTripMixin):
    """A loaded float value carrying its document position."""


class RoundTripBytes(bytes, _RoundTripMixin):
    """A loaded ``!!binary`` value carrying its document position."""


class RoundTripDecimal(Decimal, _RoundTripMixin):
    """A loaded ``Decimal`` value carrying its document position."""


class RoundTripDatetime(datetime, _RoundTripMixin):
    """A loaded ``!!timestamp`` datetime carrying its document position."""


class RoundTripDate(date, _RoundTripMixin):
    """A loaded ``!!timestamp`` date carrying its document position."""


class RoundTripTime(time, _RoundTripMixin):
    """A loaded ``!!timestamp`` time carrying its document position."""


_SCALAR_WRAPPER_CLASSES: dict[type, type] = {
    str: RoundTripStr,
    int: RoundTripInt,
    float: RoundTripFloat,
    bytes: RoundTripBytes,
    Decimal: RoundTripDecimal,
    datetime: RoundTripDatetime,
    date: RoundTripDate,
    time: RoundTripTime,
}

_PLAIN_CONSTRUCTORS: dict[type, Any] = {
    wrapper: base for base, wrapper in _SCALAR_WRAPPER_CLASSES.items()
}


def _construct_wrapper(wrapper: type, value: Any) -> Any:
    """Build a fresh wrapper instance copying ``value``'s content.

    ``datetime``/``date``/``time`` have no copy constructor, so they are
    rebuilt field by field (including ``tzinfo`` and ``fold``).
    """
    if wrapper is RoundTripDatetime:
        return datetime.__new__(
            RoundTripDatetime,
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            fold=value.fold,
        )
    if wrapper is RoundTripDate:
        return date.__new__(RoundTripDate, value.year, value.month, value.day)
    if wrapper is RoundTripTime:
        return time.__new__(
            RoundTripTime,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            fold=value.fold,
        )
    return wrapper.__new__(wrapper, value)


def wrap_scalar(value: Any) -> Any:
    """Wrap a materialized scalar in its round-trip subclass.

    Called by the native constructor for every scalar occurrence in a
    round-trip load. ``bool`` and ``None`` have no subclassable Python type
    and stay plain; they are the only loaded scalars without the styling API.
    """
    wrapper = _SCALAR_WRAPPER_CLASSES.get(type(value))
    if wrapper is None:
        return value
    return _construct_wrapper(wrapper, value)


def prepare_value(value: Any, document: Any) -> Any:
    """Prepare a value being stored inside a document.

    Scalars are wrapped and bound to the document, already-wrapped values are
    re-bound (a value moving between documents re-resolves against the new
    one), and plain ``dict``/``list`` values are converted to round-trip
    containers so the styling API reaches newly added subtrees. Anything else
    is stored as given.
    """
    if isinstance(value, _RoundTripMixin):
        if value._pyy_document is not document:
            value._pyy_document = document
            value._pyy_path_hint = None
        return value
    wrapper = _SCALAR_WRAPPER_CLASSES.get(type(value))
    if wrapper is not None:
        wrapped = _construct_wrapper(wrapper, value)
        wrapped._pyy_document = document
        return wrapped
    if isinstance(value, dict):
        converted = RoundTripMap()
        converted._pyy_document = document
        for key, item in value.items():
            converted[key] = item
        return converted
    if isinstance(value, list):
        converted = RoundTripList()
        converted._pyy_document = document
        for item in value:
            converted.append(item)
        return converted
    return value


def unwrap_scalar(value: Any) -> Any:
    """Return the plain built-in value for a round-trip scalar wrapper."""
    base = _PLAIN_CONSTRUCTORS.get(type(value))
    if base is None:
        return value
    if base is datetime:
        return datetime(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            fold=value.fold,
        )
    if base is date:
        return date(value.year, value.month, value.day)
    if base is time:
        return time(
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            fold=value.fold,
        )
    return base(value)
