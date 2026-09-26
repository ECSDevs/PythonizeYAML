# Documents and style editing

Every round-trip load returns a `Document` — a style-aware object that also
behaves like the ordinary `dict`, `list`, or scalar it wraps. Every value
reachable through it is a round-trip wrapper (a `dict`/`list` subclass, or a
subclass of the scalar's own type) that carries the styling API directly, so
values are read, replaced, and styled through one protocol. This page is the
reference for that object model: the `Document` classes, styling values,
comment access, and multi-document streams.

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
iteration, `document[key]`, `document.get(key)`, `document[key] = value`,
`del document[key]`, and, for mapping roots, `keys()`, `items()`, and
`values()` — with `items()` and `values()` reading alias entries through to
their target values. Sequence roots expose the full `list` interface
(`append()`, `insert()`, `pop()`, `remove()`, `sort()`, ...). Nested values
are read and edited by chaining subscripts
(`document["service"]["ports"][0]`). `str(document)` returns the wrapped
scalar for scalar roots and the dumped YAML text for container roots, and
`copy.deepcopy(document)` returns a fully independent copy (handle-backed
documents are reloaded from their dumped text, keeping the byte-identical
formatting). Scalar roots coerce through `str()`, `int()`, `float()`,
`complex()`, and `bool()`.

### `Document.new(root=None, *, config=None)`

Classmethod returning a new `Document` wrapping *root*, which defaults to
`None`. New data has no source layout, so `dump()` emits it with *config*.

### `Document.value`

The document root value as a Python scalar or round-trip container.
Assigning to `value` replaces the whole root. The root value itself carries
the styling API: for container roots the document *is* the root container
(`document.style = ...` works), and for scalar roots
`document.value.style = ...` styles the wrapped scalar.

### `Document.data`

The document root value. Read-only twin of `Document.value` kept for
explicitness at call sites that mutate the returned containers in place.
Alias entries created with `alias()` read through to the target's current
value: when any alias is registered the returned mapping/sequence is a
shallow resolved copy rather than the live container; without aliases the
underlying data object is returned unchanged.

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

### Reading and writing: the container protocol

A document reads and writes like the `dict`, `list`, or scalar it wraps.
Missing paths raise `PathError`. Alias nodes resolve to their target value:
entries created with `alias()` read through to the target's current value,
and aliases loaded from the source share the target's Python object.

```python
>>> document = yaml.load("service:\n  ports: [8080, 8081]\n")
>>> document["service"]["ports"][0]
8080
```

### `Document.get(key, default=None)`

Return the value at *key*, or *default* when there is no node there. A
tuple or list key is treated as a nested path: `document.get(("a", "b"))`
reads `a.b`.

```python
>>> document.get("service", {}).get("port", 8080)
8080
```

### `document[key] = value`

Assign the child *value* at *key*. The parent must exist (create nested
levels by assigning intermediate containers first, exactly like a plain
`dict`). Assigned scalars are wrapped and bound to the document, and plain
`dict`/`list` values are converted to round-trip containers, so the assigned
subtree immediately carries the styling API: `document["extra"] = "x"` and
then `document["extra"].set(style="single")` just works. Assigning a value
keeps any style already attached to the node; restyle it through the new
value (see [Styling values](#styling-values)).

### `del document[key]`

Remove the child at *key* — a mapping key on mapping roots, an index on
sequence roots (`del document[0]`). The node's subtree is removed together
with its comments, styles, tags, and anchors. Raises `AliasError` when the
node still has aliases pointing at it; removing an alias entry itself
(unlinking `*name`) is allowed.

The same edits apply at any depth through the wrapped containers:
`del document["items"][0]`, `document["items"].pop()`,
`document["items"].insert(1, "x")`, `document["items"].append("x")`,
`document["items"].reverse()`, and `document["items"].sort()` all follow
normal `list` semantics. When items shift, the document automatically moves
or drops the style/comment/tag/anchor overrides attached to the affected
positions so they keep describing the same nodes.

Metadata (styles, comments, tags, anchors) is managed through the values
themselves — see [Styling values](#styling-values).

### `Document.alias(*path, target, anchor=None)`

Make the node at *path* an alias of *target*. *path* may already exist (its
current value becomes the alias) or be new — missing intermediate mapping
keys are created, and the new entry holds the target's value as an alias.

- **\\*path** – path parts of the node that should become the alias.
- **target** – the value to alias — the wrapper read from this document
  (`document["base"]`) — or a path (a tuple, or a single key) pointing at the
  anchor source. Aliasing across documents raises `AliasError`.
- **anchor** – (`str | None`) anchor name to attach to the target. When
  omitted and the target has no anchor, a free name (`id001`, `id002`, ...)
  is generated.

Returns the alias entry's value (which reads through to the target). The
anchor lives on the target node.

```python
>>> document = yaml.load("default: 1\noverride: 2\n")
>>> document.alias("override", target=document["default"])
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
>>> document == "0.3.0", document.value.style
(True, <ScalarStyle.SINGLE: 'single'>)
```

## Styling values

Every value reachable through a document is a round-trip wrapper that carries
the styling API, so there is no separate node handle:

- mappings are `dict` subclasses (`RoundTripMap`); sequences are `list`
  subclasses (`RoundTripList`);
- loaded scalars are subclasses of their own type — `RoundTripStr`,
  `RoundTripInt`, `RoundTripFloat`, `RoundTripBytes`, `RoundTripDecimal`,
  and `RoundTripDatetime`/`RoundTripDate`/`RoundTripTime` for timestamps;
- `bool` and `None` have no subclassable Python type and stay plain — they
  are the only loaded scalars without this API.

Wrappers compare and hash exactly like the plain values they wrap, so they
work as `dict` keys, in `json.dumps`, and everywhere else a plain value would.
The `safe_load`/`full_load` plain-data APIs never return wrappers.

Paths are resolved by value identity at access time: a wrapper follows its
own value through insertions and removals (read it, shift the list, and
`value.path` still points at it), and styling a value that is no longer in
the document raises `PathError`. Reading through an alias entry resolves to
the anchor target, so styling through an alias styles the target. Property
assignments validate the requested style against the node's value before
mutating.

### `value.path`

The `tuple` of path parts identifying the node — its *current* path,
re-resolved by identity on every access.

### `value.value`

The node's Python value. Assigning replaces the value; a style already
attached to the node is validated against the new value first.

### `value.span`

A `SourceSpan` with the byte offsets and one-based line/column of the node
in the original text, or `None` for nodes without source metadata.

### `value.style`

The scalar style (`ScalarStyle | None`): `plain`, `single`, `double`,
`literal`, or `folded`. Assigning a style that does not fit the value raises
`StyleError`.

### `value.collection_style`

The collection style (`CollectionStyle | None`): `block` or `flow`. Only
meaningful for mappings and sequences.

### `value.chomping`

The chomping indicator (`Chomping | None`): `clip`, `strip`, or `keep`.
Only literal and folded scalars can carry it; assigning it to any other
style raises `StyleError`. Assign `None` to clear the override.

### `value.block_indent_indicator`

The explicit indentation indicator (`int | None`, `1`–`9`) for block
scalars. Assign `None` to clear it.

### `value.tag`

The node tag (`str | None`). Assigned values must start with `!`.

### `value.anchor`

The anchor name (`str | None`). Renaming an anchor rewrites the aliases
that point at it; removing an anchor that still has aliases raises
`AliasError`.

### `value.comments`

The `Comments` view for this node's entry.

### `value.set(**values)`

Apply several fields in one atomic step and return the value now stored at
the node's path. The path is resolved once up front, so the fields stay
pinned to the node even when `value` swaps the stored wrapper.

- **\\*\\*values** – any of `value`, `style`, `collection_style`, `chomping`,
  `block_indent_indicator`, `tag`, `anchor`, `before`, `inline`, `after`,
  with the same semantics as the corresponding properties and comment
  fields.

Unknown fields raise `TypeError`; invalid combinations raise `StyleError`
with the document restored to its previous state, so the update never
applies partially.

```python
>>> document["message"].set(style="double", inline="# shown to users")
>>> document.dump()
'message: "greeting"  # shown to users\n'
```

## `Comments`

Accessed through `value.comments`. Comments are stored on the mapping
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
>>> document["channel"].comments.before = ["# Published channel"]
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
