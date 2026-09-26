# Documents and style editing

Every round-trip load returns a `Document` — a style-aware object that also
behaves like the ordinary `dict`, `list`, or scalar it wraps. This page is the
reference for that object model: the `Document` classes, the `NodeRef` style
views, comment access, and multi-document streams.

## `Document`

```python
class Document(data, *, handle=None, root_id=-1, source='', config=None)
```

A mutable, style-aware YAML document. In application code a `Document` is
usually produced by `load()`, `load_all()`, or `load_document()` rather than
constructed directly; use `Document.new()` to build one from Python data.

- **data** – the root Python value: a mapping, sequence, or scalar. The
  document mutates this value in place.
- **handle** – the native parse handle backing the document, if it was
  loaded from YAML text. The handle supplies source metadata (spans, styles,
  anchors, directives) for unchanged nodes.
- **root_id** – the node id of the root inside *handle*; `-1` when there is
  no handle.
- **source** – the original YAML text, used for byte-exact replay and local
  patching. Ignored when *handle* is given.
- **config** – an `IndentConfig` used as the emission fallback for nodes that
  have no source layout. Defaults to `DEFAULT_CONFIG`.

`Document` also implements the container protocol of its root: `len()`,
iteration, `document[key]` and `document[key] = value` (delegating to
`at()`/`set()`), and, for mapping roots, `keys()`, `items()`, and `values()`
— with `items()` and `values()` reading alias entries through to their
target values. `str(document)` returns the wrapped scalar for scalar roots
and the dumped YAML text for container roots, and `copy.deepcopy(document)`
returns a fully independent copy (handle-backed documents are reloaded from
their dumped text, keeping the byte-identical formatting). Scalar roots
coerce through `str()`, `int()`, `float()`, `complex()`, and `bool()`.

### `Document.new(root=None, *, config=None)`

Classmethod returning a new `Document` wrapping *root*, which defaults to
`None`. New data has no source layout, so `dump()` emits it with *config*.

### `Document.value`

The document root value as a Python scalar or round-trip container.
Assigning to `value` replaces the whole root.

### `Document.data`

The document root value. Read-only twin of `Document.value` kept for
explicitness at call sites that mutate the returned containers in place.
Alias entries created with `alias()` read through to the target's current
value: when any alias is registered the returned mapping/sequence is a
shallow resolved copy rather than the live container; without aliases the
underlying data object is returned unchanged.

### `Document.root`

A `NodeRef` for the document root (`path == ()`), giving access to
document-level comments, styles, tags, and anchors.

### `Document.source`

The original loaded text. Empty for documents created with `Document.new()`.

### `Document.directives`

The directive lines (for example `["%YAML 1.1"]`) preceding the first
document. Assigning a list replaces them; every line must start with `%` or
`StyleError` is raised.

### `Document.explicit_start`

Whether the document starts with an explicit `---` marker. Assign a `bool`
to override what the source had.

### `Document.explicit_end`

Whether the document ends with an explicit `...` marker. Assign a `bool` to
override what the source had.

### `Document.at(*path)`

Return the value at *path*.

- **\\*path** – one or more path parts: mapping keys or sequence indexes,
  read from the outside in. A single tuple or list may be passed instead of
  separate arguments.

Missing paths raise `PathError`. Alias nodes resolve to their target value:
entries created with `alias()` read through to the target's current value,
and aliases loaded from the source share the target's Python object.

```python
>>> document = yaml.load("service:\n  ports: [8080, 8081]\n")
>>> document.at("service", "ports", 0)
8080
```

### `Document.node(*path)`

Return a `NodeRef` view for the node at *path*. Without arguments it returns
the root node. Paths that do not exist raise `PathError`.

### `Document.set(*path, value, style=None, collection_style=None, chomping=None, block_indent_indicator=None, tag=None, anchor=None, before=None, inline=None, after=None)`

Set the node at *path* to *value*, optionally applying style metadata in the
same atomic step. Missing intermediate mapping keys are created.

- **\\*path** – path parts of the node to set.
- **value** – the new Python value.
- **style** – (`ScalarStyle | str | None`) scalar style: `plain`, `single`,
  `double`, `literal`, or `folded`. String values are coerced.
- **collection_style** – (`CollectionStyle | str | None`) `block` or `flow`.
- **chomping** – (`Chomping | str | None`) `clip`, `strip`, or `keep`;
  requires a literal or folded style.
- **block_indent_indicator** – (`int | None`) explicit indentation indicator
  for block scalars, `1` through `9`.
- **tag** – (`str | None`) tag for the node; must start with `!`.
- **anchor** – (`str | None`) anchor name; must not contain YAML indicator
  characters.
- **before**, **after** – (`str | Iterable[str] | None`) comment lines placed
  before or after the entry. Every non-empty line must start with `#`.
- **inline** – (`str | None`) a single-line comment placed after the value.

All arguments are validated before anything is applied; an invalid
combination raises `StyleError` and leaves the document unchanged. Returns
the `NodeRef` for the written node.

```python
>>> document = yaml.Document.new({})
>>> document.set("build", "command", value="python -m build", style="double")
NodeRef(path=('build', 'command'))
```

### `Document.append(*path, value, **style_options)`

Append *value* to the sequence at *path* and return the `NodeRef` of the new
item. *path* must point to a `list`, otherwise `StyleError` is raised.
*style_options* are the same style keywords as `Document.set()`.

### `Document.insert(*path, index, value, **style_options)`

Insert *value* into the sequence at *path* before position *index*, shifting
the rest, and return the `NodeRef` of the new item.

- **index** – insertion position; existing items from that position on are
  moved back.

### `Document.remove(*path)`

Remove the node at *path* and return its value.

- **\\*path** – path parts of the node to remove; the root cannot be removed.

Raises `PathError` for missing paths and `AliasError` when the node still
has aliases pointing at it. Style overrides attached to the removed subtree
are discarded.

### `Document.alias(*path, target, anchor=None)`

Make the node at *path* an alias of *target*. *path* may already exist (its
current value becomes the alias) or be new — missing intermediate mapping
keys are created, and the new entry holds the target's value as an alias.

- **\\*path** – path parts of the node that should become the alias.
- **target** – a `NodeRef` in the same document, or a path tuple pointing at
  the anchor source. Aliasing across documents raises `AliasError`.
- **anchor** – (`str | None`) anchor name to attach to the target. When
  omitted and the target has no anchor, a free name (`id001`, `id002`, ...)
  is generated.

Returns the `NodeRef` of the alias node; `is_alias` and `alias_target` are
available on it. The anchor lives on the target node.

```python
>>> document = yaml.load("default: 1\noverride: 2\n")
>>> document.alias("override", target=document.node("default"))
NodeRef(path=('override',))
>>> document.dump()
'default: &id001 1\noverride: *id001\n'
```

### `Document.dump(stream=None, *, config=None, explicit_start=None, explicit_end=None)`

Emit the document.

- **stream** – a writable stream, or `None` to return the text.
- **config** – (`IndentConfig | None`) per-call emission override.
- **explicit_start**, **explicit_end** – (`bool | None`) per-call marker
  overrides; when omitted the document properties apply.

An unchanged loaded document replays its source text exactly; modified nodes
are patched locally, and replaced or newly created subtrees are emitted
canonically with *config*.

## `DocumentMapping`, `DocumentSequence`, and `DocumentScalar`

```python
DocumentMapping(data, *, ...)
DocumentSequence(data, *, ...)
DocumentScalar(data, *, ...)
```

The concrete `Document` subclasses returned by `load()`, `load_all()`, and
`load_document()` according to the root node type. Keyword arguments match
the `Document` constructor. Each inherits every `Document` member and also
behaves like the wrapped value, so it can replace a normal `dict`, `list`,
or scalar directly:

- **DocumentMapping** – a `dict` subclass; compares equal to plain mappings
  and other documents.
- **DocumentSequence** – a `list` subclass.
- **DocumentScalar** – a scalar wrapper; compares equal to the wrapped value
  and coerces through `str()`, `int()`, `float()`, `complex()`, and `bool()`.
  Scalar roots keep their original style and formatting, including quotes
  and block headers.

```python
>>> document = yaml.load("'0.3.0'\n")
>>> document == "0.3.0", document.root.style
(True, <ScalarStyle.SINGLE: 'single'>)
```

## `NodeRef`

A stable view over one node of a `Document`, returned by `Document.node()`,
`Document.set()`, `Document.append()`, `Document.insert()`, and
`Document.alias()`. The view is resolved by node identity, not by a frozen
path: after list insertions or removals shift siblings around, accessing the
ref still reaches the same node, and accessing a ref whose node was removed
raises `PathError`. Nodes created in Python (without native node ids) fall
back to the path the ref was created with. Property assignments validate the
requested style against the node's value before mutating.

### `NodeRef.path`

The `tuple` of path parts identifying the node — the node's *current* path,
re-resolved by identity on every access.

### `NodeRef.value`

The node's Python value. Assigning replaces the value; a style already
attached to the node is validated against the new value first.

### `NodeRef.span`

A `SourceSpan` with the byte offsets and one-based line/column of the node
in the original text, or `None` for nodes without source metadata.

### `NodeRef.style`

The scalar style (`ScalarStyle | None`): `plain`, `single`, `double`,
`literal`, or `folded`. Assigning a style that does not fit the value raises
`StyleError`.

### `NodeRef.collection_style`

The collection style (`CollectionStyle | None`): `block` or `flow`. Only
meaningful for mappings and sequences.

### `NodeRef.chomping`

The chomping indicator (`Chomping | None`): `clip`, `strip`, or `keep`.
Only literal and folded scalars can carry it; assigning it to any other
style raises `StyleError`. Assign `None` to clear the override.

### `NodeRef.block_indent_indicator`

The explicit indentation indicator (`int | None`, `1`–`9`) for block
scalars. Assign `None` to clear it.

### `NodeRef.tag`

The node tag (`str | None`). Assigned values must start with `!`.

### `NodeRef.anchor`

The anchor name (`str | None`). Renaming an anchor rewrites the aliases
that point at it; removing an anchor that still has aliases raises
`AliasError`.

### `NodeRef.is_alias`

Whether the node is an alias (`*name`) of another node.

### `NodeRef.alias_target`

The `NodeRef` of the anchor this alias points at, or `None` when the node is
not an alias.

### `NodeRef.comments`

The `Comments` view for this node's entry.

### `NodeRef.update(**values)`

Apply several fields in one atomic step and return the same `NodeRef`.

- **\\*\\*values** – any of `value`, `style`, `collection_style`, `chomping`,
  `block_indent_indicator`, `tag`, `anchor`, `before`, `inline`, `after`,
  with the same semantics as the corresponding properties and comment
  fields.

Unknown fields raise `TypeError`; invalid combinations raise `StyleError`
with the document restored to its previous state, so the update never
applies partially.

```python
>>> ref = document.node("message")
>>> ref.update(style="double", inline="# shown to users") is ref
True
```

## `Comments`

Accessed through `NodeRef.comments`. Comments are stored on the mapping
entry or sequence item that owns the node, so they survive value edits.

### `Comments.before`

Comment lines above the entry (`list[str]`). Assign a string or an iterable
of lines; every non-empty line must start with `#`.

### `Comments.inline`

The comment on the same line as the value (`str | None`). Must be a single
line starting with `#`.

### `Comments.after`

Comment lines below the entry, before the next sibling (`list[str]`), with
the same rules as `Comments.before`.

```python
>>> document.node("channel").comments.before = ["# Published channel"]
```

## `DocumentStream`

```python
DocumentStream(documents=(), *, source='', handle=None)
```

An ordered, mutable collection of `Document` objects, returned by
`load_documents()` and `read_documents()`. It supports `len()`, iteration,
and `stream[index]`.

- **documents** – initial `Document` objects.
- **source** – the original stream text, replayed exactly while no document
  changed.
- **handle** – native handle backing the stream.

### `DocumentStream.append(document)`

Add *document* at the end. Raises `TypeError` for anything that is not a
`Document`.

### `DocumentStream.insert(index, document)`

Insert *document* at *index*.

### `DocumentStream.remove(index)`

Remove and return the `Document` at *index*.

### `DocumentStream.dump(stream=None, *, config=None, explicit_start=None, explicit_end=None)`

Emit the whole stream.

- **stream** – a writable stream, or `None` to return the text.
- **config** – (`IndentConfig | None`) emission override for changed
  documents.
- **explicit_start** – (`bool | None`) controls the leading `---` marker.
  `None` (the default) keeps each document's own markers, so an unchanged
  stream replays its source exactly; `True` adds any missing marker and
  `False` strips the stream's leading start marker.
- **explicit_end** – (`bool | None`) controls the trailing `...` marker with
  the same semantics; when omitted each document keeps its own.

An unchanged stream replays its source text exactly.
