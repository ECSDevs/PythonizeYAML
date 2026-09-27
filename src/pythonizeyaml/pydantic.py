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

"""Optional Pydantic integration: :class:`YAMLModel` with round-trip fidelity.

This module requires ``pydantic`` (``pip install pythonizeyaml[pydantic]``).
The public entry point is also exported lazily from the package root as
:data:`pythonizeyaml.YAMLModel` when pydantic is importable.

:class:`YAMLModel` keeps the whole original :class:`~pythonizeyaml.document.Document`
on every instance parsed from YAML, so that::

    assert Model.model_validate_yaml(original).model_dump_yaml() == original

holds byte-for-byte for documents whose validated values did not change.
``model_dump(pretty=True)`` instead regenerates the document: fields are
ordered by declaration, missing defaulted fields are filled in,
``Field(description=...)`` becomes a comment block, and non-empty containers
are separated from their neighbours by blank lines.
"""

from __future__ import annotations

import sys
from types import UnionType
from typing import Any, Optional, Union, get_args, get_origin

from pydantic import BaseModel

from .api import load_all
from .document import Document, _plain_value
from .errors import ComposerError, PathError
from .nodes import _RoundTripMixin

if sys.version_info >= (3, 11):  # pragma: no cover - version dependent import
    from typing import Self
else:  # pragma: no cover - version dependent import
    from typing_extensions import Self

__all__ = ["YAMLModel"]

#: Instance attribute holding the adopted round-trip :class:`Document`.
#: Stored via ``object.__setattr__`` so it works across pydantic versions
#: without declaring a private attribute.
_ANCHOR_ATTR = "_yaml_document"

_MISSING = object()


def _load_single_document(source: Any) -> Optional[Document]:
    """Parse ``source`` (str/bytes/stream) with the round-trip engine.

    Returns the parsed :class:`Document`, or ``None`` when the source holds no
    document at all. Raises :class:`~pythonizeyaml.errors.ComposerError` for
    multi-document streams: a model maps to exactly one document.
    """
    documents = list(load_all(source))
    if len(documents) > 1:
        raise ComposerError(
            problem=f"expected a single YAML document, found {len(documents)}"
        )
    return documents[0] if documents else None


def _plain(value: Any) -> Any:
    """Normalize round-trip wrappers to plain data for equality checks."""
    if isinstance(value, (Document, _RoundTripMixin)):
        return _plain_value(value)
    return value


def _storable(value: Any) -> Any:
    """Convert a model value into something document containers can hold."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    return value


def _field_default(field: Any) -> Any:
    """Return the field's default, or ``_MISSING`` when the field is required."""
    if field.is_required():
        return _MISSING
    return field.get_default(call_default_factory=True)


def _sync_mapping(node: Any, instance: Any, cls: type) -> None:
    """Sync the declared fields of ``instance`` into mapping ``node``.

    Unchanged subtrees are left completely untouched so their source bytes
    survive; changed values are written through the container's own
    ``__setitem__`` (which preserves the entry's style and comments). Keys
    that exist in ``node`` but not in the model (ignored extras) are kept.
    """
    for name, field in cls.model_fields.items():
        value = getattr(instance, name)
        if name not in node:
            default = _field_default(field)
            if default is _MISSING or value != default:
                node[name] = _storable(value)
            continue
        current = node[name]
        if isinstance(value, BaseModel) and isinstance(current, dict):
            _sync_mapping(current, value, type(value))
            continue
        if isinstance(value, dict) and isinstance(current, dict):
            _sync_plain_mapping(current, value)
            continue
        if isinstance(value, (list, tuple)) and isinstance(current, list):
            _sync_sequence(current, value)
            continue
        if _plain(current) != _plain(value):
            node[name] = _storable(value)


def _sync_plain_mapping(node: Any, values: Any, *, delete_missing: bool = True) -> None:
    """Sync a plain mapping of values into mapping ``node`` recursively.

    Used for raw ``dict`` fields (state is the full value, so removed keys are
    deleted) and, with ``delete_missing=False``, for merging several settings
    files into one anchor document.
    """
    for key, item in values.items():
        if key not in node:
            node[key] = _storable(item)
            continue
        current = node[key]
        if isinstance(item, BaseModel) and isinstance(current, dict):
            _sync_mapping(current, item, type(item))
            continue
        if isinstance(item, dict) and isinstance(current, dict):
            _sync_plain_mapping(current, item, delete_missing=delete_missing)
            continue
        if isinstance(item, (list, tuple)) and isinstance(current, list):
            _sync_sequence(current, item)
            continue
        if _plain(current) != _plain(item):
            node[key] = _storable(item)
    if delete_missing:
        for key in list(node.keys()):
            if key not in values:
                del node[key]


def _sync_sequence(node: Any, values: Any) -> None:
    """Sync a sequence of model values into list ``node`` item by item."""
    count = min(len(node), len(values))
    for index in range(count):
        current = node[index]
        item = values[index]
        if isinstance(item, BaseModel) and isinstance(current, dict):
            _sync_mapping(current, item, type(item))
            continue
        if isinstance(item, dict) and isinstance(current, dict):
            _sync_plain_mapping(current, item)
            continue
        if isinstance(item, (list, tuple)) and isinstance(current, list):
            _sync_sequence(current, item)
            continue
        if _plain(current) != _plain(item):
            node[index] = _storable(item)
    if len(values) > len(node):
        node.extend([_storable(item) for item in values[len(node):]])
    while len(node) > len(values):
        del node[len(node) - 1]


# --- pretty dumps -----------------------------------------------------------
#
# ``model_dump(pretty=True)`` regenerates the document instead of patching the
# anchor: mapping keys are reordered, which the patch emitter cannot express,
# so the whole tree is rebuilt and re-emitted. The rebuild walks the instance
# (or an already-dumped values mapping) and records a comment *plan* — one
# entry per mapping level, each holding ``(key, value, FieldInfo)`` triples —
# which :func:`_build_pretty_document` applies to the fresh document.

def _is_nonempty_container(value: Any) -> bool:
    """True for a mapping/sequence that spans several lines when emitted."""
    return isinstance(value, (dict, list)) and len(value) > 0


def _model_class_of(annotation: Any) -> Optional[type]:
    """Resolve a field annotation to a single BaseModel subclass, or None."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        models = [
            arg for arg in args
            if isinstance(arg, type) and issubclass(arg, BaseModel)
        ]
        if len(args) == 1 and len(models) == 1:
            return models[0]
    return None


def _strip_blank_edges(lines: list) -> list:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _dedent_lines(lines: list) -> list:
    """Drop the block's common indentation; the renderer re-indents it.

    Comment lines read from a source document keep their original leading
    whitespace, while the fresh-document renderer prepends the node's own
    indent — carrying them over verbatim would double it.
    """
    indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    if not indents:
        return list(lines)
    cut = min(indents)
    return [line[cut:] if line.strip() else "" for line in lines]


def _description_lines(description: Any) -> list:
    """Render a ``Field(description=...)`` as one comment line per source line."""
    if not description:
        return []
    return [
        f"# {line.rstrip()}" if line.strip() else "#"
        for line in str(description).splitlines()
    ]


def _pretty_instance_mapping(
    instance: Any,
    cls: type,
    prefix: tuple,
    plan: list,
    extras: Any = (),
) -> dict:
    """Rebuild a mapping in the model's declared field order.

    Every declared field appears — absent-from-source defaulted fields get
    their current value, which implements default filling. ``extras`` are
    undeclared anchor keys, appended after the model fields in source order.
    """
    ordered: dict = {}
    entries: list = []
    for name, field in cls.model_fields.items():
        value = _pretty_instance_value(getattr(instance, name), prefix + (name,), plan)
        ordered[name] = value
        entries.append((name, value, field))
    for key, value in extras:
        if key in ordered:
            continue
        value = _pretty_plain_value(value, prefix + (key,), plan)
        ordered[key] = value
        entries.append((key, value, None))
    plan.append((prefix, entries))
    return ordered


def _pretty_instance_value(value: Any, path: tuple, plan: list) -> Any:
    """Rebuild one value tree node, recursing into models and containers."""
    if isinstance(value, BaseModel):
        return _pretty_instance_mapping(value, type(value), path, plan)
    if isinstance(value, dict):
        ordered: dict = {}
        entries: list = []
        for key, item in value.items():
            child = _pretty_instance_value(item, path + (key,), plan)
            ordered[key] = child
            entries.append((key, child, None))
        plan.append((path, entries))
        return ordered
    if isinstance(value, (list, tuple)):
        return [
            _pretty_instance_value(item, path + (index,), plan)
            for index, item in enumerate(value)
        ]
    return value


def _pretty_plain_value(value: Any, path: tuple, plan: list) -> Any:
    """Rebuild an already-dumped value tree, keeping mapping order."""
    if isinstance(value, dict):
        ordered: dict = {}
        entries: list = []
        for key, item in value.items():
            child = _pretty_plain_value(item, path + (key,), plan)
            ordered[key] = child
            entries.append((key, child, None))
        plan.append((path, entries))
        return ordered
    if isinstance(value, (list, tuple)):
        return [
            _pretty_plain_value(item, path + (index,), plan)
            for index, item in enumerate(value)
        ]
    return value


def _pretty_plain_mapping(values: dict, cls: type, prefix: tuple, plan: list) -> dict:
    """Order an already-dumped values mapping by the model's fields.

    Used when ``pretty`` is combined with other pydantic keywords: the values
    are plain data, so nested model classes are recovered from field
    annotations and no defaults are filled.
    """
    ordered: dict = {}
    entries: list = []
    for name, field in cls.model_fields.items():
        key = next(
            (
                candidate
                for candidate in (
                    name,
                    getattr(field, "serialization_alias", None),
                    field.alias,
                )
                if candidate and candidate in values and candidate not in ordered
            ),
            None,
        )
        if key is None:
            continue
        item = values[key]
        nested = _model_class_of(field.annotation)
        child = (
            _pretty_plain_mapping(item, nested, prefix + (key,), plan)
            if nested is not None and isinstance(item, dict)
            else _pretty_plain_value(item, prefix + (key,), plan)
        )
        ordered[key] = child
        entries.append((key, child, field))
    for key, item in values.items():
        if key in ordered:
            continue
        child = _pretty_plain_value(item, prefix + (key,), plan)
        ordered[key] = child
        entries.append((key, child, None))
    plan.append((prefix, entries))
    return ordered


def _build_pretty_document(
    root: dict,
    plan: list,
    anchor: Optional[Document],
) -> Document:
    """Create the regenerated document and attach its comment plan.

    Per entry the ``before`` block is composed of (optionally) a separating
    blank line, the ``Field(description=...)`` lines and the carried source
    comments; the source ``inline`` comment is carried, and ``after`` comments
    only for the root mapping's last entry (trailing file comments). Comments
    between two entries live in the following entry's ``before`` block, so
    nothing else is lost.
    """
    config = getattr(anchor, "_config", None) if anchor is not None else None
    document = Document.new(root, config=config)
    carry = anchor is not None
    for level_path, entries in plan:
        previous: Any = None
        for index, (key, value, field) in enumerate(entries):
            path = level_path + (key,)
            before: list = []
            inline = None
            after: list = []
            if carry:
                try:
                    carried = anchor._get_comments(path)
                except PathError:
                    # Filled fields and other paths absent from the source
                    # have nothing to carry over.
                    carried = {"before": [], "inline": None, "after": []}
                before = _dedent_lines(_strip_blank_edges(carried["before"]))
                inline = carried["inline"]
                if level_path == () and index == len(entries) - 1:
                    after = _dedent_lines(_strip_blank_edges(carried["after"]))
            if field is not None and field.description:
                lines = _description_lines(field.description)
                existing = {line.strip() for line in before}
                if not all(line in existing for line in lines):
                    before = lines + before
            if index and (_is_nonempty_container(previous) or _is_nonempty_container(value)):
                before = ["", *before]
            if before:
                document._set_comment(path, "before", before)
            if inline:
                document._set_comment(path, "inline", inline)
            if after:
                document._set_comment(path, "after", after)
            previous = value
    return document


class YAMLSerializationMixin:
    """Round-trip YAML (de)serialization shared by :class:`YAMLModel` and
    :class:`pythonizeyaml.YAMLSettings`."""

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[Any] = None,
        **kwargs: Any,
    ) -> Self:
        """Validate ``obj`` into a model instance.

        When ``obj`` is a :class:`~pythonizeyaml.document.Document` (the
        result of ``pythonizeyaml.load``), it is flattened for validation and
        then *adopted* as the instance's style anchor: the instance dumps back
        through that document, preserving its comments and styles. The
        document may be updated in place when the model changes. Every other
        input is forwarded to pydantic's own ``model_validate`` unchanged.
        """
        anchor = obj if isinstance(obj, Document) else None
        if anchor is None:
            return super().model_validate(
                obj,
                strict=strict,
                from_attributes=from_attributes,
                context=context,
                **kwargs,
            )
        data = _plain_value(anchor)
        if data is None:
            data = {}
        instance = super().model_validate(
            data,
            strict=strict,
            from_attributes=from_attributes,
            context=context,
            **kwargs,
        )
        object.__setattr__(instance, _ANCHOR_ATTR, anchor)
        return instance

    @classmethod
    def model_validate_yaml(
        cls,
        source: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[Any] = None,
        **kwargs: Any,
    ) -> Self:
        """Validate YAML source (``str``, ``bytes`` or a readable stream).

        The source is parsed with the round-trip engine, so comments, scalar
        styles and layout survive: ``model_validate_yaml(y).model_dump_yaml()``
        returns ``y`` unchanged whenever the validated values did not change.
        Multi-document streams raise
        :class:`~pythonizeyaml.errors.ComposerError`; an empty source behaves
        like an empty mapping.
        """
        document = _load_single_document(source)
        return cls.model_validate(
            document if document is not None else {},
            strict=strict,
            from_attributes=from_attributes,
            context=context,
            **kwargs,
        )

    def model_dump(self, *, pretty: bool = False, **kwargs: Any) -> Document:
        """Dump the model as a style-aware :class:`~pythonizeyaml.document.Document`.

        Without arguments the anchored source document (if any) is updated in
        place with the current field values — unchanged subtrees keep their
        original bytes — and returned. Fields absent from the source are
        appended when they hold a non-default value. Passing any pydantic
        keyword (``include``, ``exclude``, ``mode``, ``by_alias``, ...) builds
        a fresh document without source styling instead.

        With ``pretty=True`` the document is always regenerated: mapping keys
        follow the model's declaration order (recursively through nested
        models), absent defaulted fields are filled in,
        ``Field(description=...)`` becomes a comment block above the key, and
        entries adjacent to a non-empty container are separated by blank
        lines. Comments from the anchored source document travel with their
        keys; scalar and collection styles are re-emitted with the library
        defaults. Combined with other pydantic keywords, pretty still orders,
        comments and spaces the filtered values but skips default filling,
        undeclared keys and comment carry-over.
        """
        anchor = getattr(self, _ANCHOR_ATTR, None)
        if not pretty:
            if kwargs or anchor is None:
                return Document.new(super().model_dump(**kwargs))
            _sync_mapping(anchor, self, type(self))
            return anchor
        plan: list = []
        if kwargs:
            values = super().model_dump(**kwargs)
            root = _pretty_plain_mapping(values, type(self), (), plan)
            return _build_pretty_document(root, plan, None)
        extras: list = []
        if anchor is not None:
            for key in anchor:
                if key not in type(self).model_fields:
                    extras.append((key, _plain_value(anchor[key])))
        root = _pretty_instance_mapping(self, type(self), (), plan, extras)
        return _build_pretty_document(root, plan, anchor)

    def model_dump_yaml(
        self,
        *,
        stream: Optional[Any] = None,
        encoding: Optional[str] = None,
        pretty: bool = False,
    ) -> Any:
        """Serialize the model to YAML.

        Returns the YAML text, or writes it to ``stream`` and returns ``None``.
        With ``encoding``, returns ``bytes`` (or writes bytes to a binary
        stream). The output preserves the anchored source document's bytes
        wherever the validated values did not change; ``pretty=True``
        regenerates the document instead (see :meth:`model_dump`).
        """
        document = self.model_dump(pretty=pretty)
        if encoding is not None:
            data = document.dump().encode(encoding)
            if stream is not None:
                stream.write(data)
                return None
            return data
        return document.dump(stream)


class YAMLModel(YAMLSerializationMixin, BaseModel):
    """A Pydantic model that round-trips YAML byte-for-byte.

    >>> class AppConfig(YAMLModel):
    ...     host: str
    ...     port: int = 8080
    >>> cfg = AppConfig.model_validate_yaml("host: db\\nport: 5432\\n")
    >>> cfg.model_dump_yaml()
    'host: db\\nport: 5432\\n'

    Requires the ``pydantic`` extra: ``pip install pythonizeyaml[pydantic]``.
    """
