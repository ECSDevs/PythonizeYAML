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

"""Round-trip container types used by the native PythonizeYAML engine."""

from __future__ import annotations

from typing import Any


class _RoundTripMixin:
    _pyy_handle: Any
    _pyy_node_id: int
    _pyy_dirty: bool

    def _pyy_mark_dirty(self) -> None:
        self._pyy_dirty = True


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
        dict.__setitem__(self, key, value)
        self._pyy_entry_nodes.setdefault(key, (-1, -1))
        self._pyy_mark_dirty()

    def __delitem__(self, key: Any) -> None:
        dict.__delitem__(self, key)
        self._pyy_entry_nodes.pop(key, None)
        self._pyy_mark_dirty()

    def clear(self) -> None:
        dict.clear(self)
        self._pyy_entry_nodes.clear()
        self._pyy_mark_dirty()

    def pop(self, key: Any, *default: Any) -> Any:
        value = dict.pop(self, key, *default)
        self._pyy_entry_nodes.pop(key, None)
        self._pyy_mark_dirty()
        return value

    def popitem(self) -> tuple[Any, Any]:
        item = dict.popitem(self)
        self._pyy_entry_nodes.pop(item[0], None)
        self._pyy_mark_dirty()
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
        list.__setitem__(self, index, value)
        if isinstance(index, slice):
            self._pyy_node_ids[index] = [-1] * len(value)
        else:
            try:
                if index >= len(self._pyy_node_ids):
                    self._pyy_node_ids[index] = -1
            except IndexError:
                pass
        self._pyy_mark_dirty()

    def __delitem__(self, index: Any) -> None:
        list.__delitem__(self, index)
        del self._pyy_node_ids[index]
        self._pyy_mark_dirty()

    def append(self, value: Any) -> None:
        list.append(self, value)
        self._pyy_node_ids.append(-1)
        self._pyy_mark_dirty()

    def extend(self, values: Any) -> None:
        values = list(values)
        list.extend(self, values)
        self._pyy_node_ids.extend([-1] * len(values))
        self._pyy_mark_dirty()

    def insert(self, index: int, value: Any) -> None:
        list.insert(self, index, value)
        self._pyy_node_ids.insert(index, -1)
        self._pyy_mark_dirty()

    def pop(self, index: int = -1) -> Any:
        value = list.pop(self, index)
        self._pyy_node_ids.pop(index)
        self._pyy_mark_dirty()
        return value

    def clear(self) -> None:
        list.clear(self)
        self._pyy_node_ids.clear()
        self._pyy_mark_dirty()

    def remove(self, value: Any) -> None:
        index = self.index(value)
        self.__delitem__(index)

    def reverse(self) -> None:
        list.reverse(self)
        self._pyy_node_ids.reverse()
        self._pyy_mark_dirty()

    def sort(self, *args: Any, **kwargs: Any) -> None:
        list.sort(self, *args, **kwargs)
        self._pyy_node_ids.sort(key=lambda _: 0)
        self._pyy_mark_dirty()

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

