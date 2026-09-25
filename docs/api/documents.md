# Documents and style editing

The document API exposes source metadata and mutation operations as Python
objects. Use it when a tool needs to control comments, styles, tags, anchors,
aliases, markers, or exact paths.

## Loading documents

```python
load_document(stream: Any) -> Document
load_documents(stream: Any) -> DocumentStream
read_document(path: str | Path) -> Document
read_documents(path: str | Path) -> DocumentStream
```

The `load_*` functions accept strings, UTF-8 bytes, and readable streams.
`read_*` read UTF-8 text from a filesystem path. `load_document()` returns one
document; `load_documents()` preserves the ordered multi-document stream.

```python
document = yaml.load_document("name: demo\n")
document.node("name").comments.inline = "# Display name"
print(document.dump())
```

## `Document`

```python
Document.new(root: Any = None, *, config: IndentConfig | None = None) -> Document
Document.value: Any
Document.data: Any
Document.root: NodeRef
Document.source: str
Document.directives: list[str]
Document.explicit_start: bool
Document.explicit_end: bool
Document.at(*path: Any) -> Any
Document.node(*path: Any) -> NodeRef
Document.set(*path: Any, value: Any, style: ScalarStyle | str | None = None,
             collection_style: CollectionStyle | str | None = None,
             chomping: Chomping | str | None = None,
             block_indent_indicator: int | None = None,
             tag: str | None = None, anchor: str | None = None,
             before: str | Iterable[str] | None = None,
             inline: str | None = None,
             after: str | Iterable[str] | None = None) -> NodeRef
Document.append(*path: Any, value: Any, **style_options: Any) -> NodeRef
Document.insert(*path: Any, index: int, value: Any,
                **style_options: Any) -> NodeRef
Document.remove(*path: Any) -> Any
Document.alias(*path: Any, target: NodeRef | tuple[Any, ...],
               anchor: str | None = None) -> NodeRef
Document.dump(stream: Any = None, *, config: IndentConfig | None = None,
              explicit_start: bool | None = None) -> str | None
```

Paths are mapping keys or sequence indexes. `at()` raises `PathError` when a
path does not exist. `set()` can create missing mapping paths, applies style
options atomically, and returns the new node. `append()` and `insert()` require
a sequence path; `remove()` rejects the root and nodes that still have aliases.
`alias()` creates a shared alias and generates an anchor name when necessary.

`source` is the original loaded text. `dump()` returns text or writes to a
stream. An unchanged loaded document is replayed exactly; modified nodes are
patched locally. `config` and `explicit_start` override emission for that call.

```python
document = yaml.Document.new({"items": []})
document.append("items", value="first", style="single")
document.set("enabled", value=True, inline="# Feature flag")
print(document.dump())
```

## `NodeRef`

```python
NodeRef.path: tuple[Any, ...]
NodeRef.value: Any
NodeRef.span: SourceSpan | None
NodeRef.style: ScalarStyle | None
NodeRef.collection_style: CollectionStyle | None
NodeRef.chomping: Chomping | None
NodeRef.block_indent_indicator: int | None
NodeRef.tag: str | None
NodeRef.anchor: str | None
NodeRef.is_alias: bool
NodeRef.alias_target: NodeRef | None
NodeRef.comments: Comments
NodeRef.update(**values: Any) -> NodeRef
```

Scalar styles are `plain`, `single`, `double`, `literal`, and `folded`.
Collection styles are `block` and `flow`. Chomping is `clip`, `strip`, or
`keep`; it only applies to literal and folded strings. Block indentation
indicators must be integers from 1 through 9. Tags must start with `!`, and
anchor names cannot contain YAML indicator characters.

`update()` accepts `value`, all style properties, `tag`, `anchor`, and the
comment fields `before`, `inline`, and `after`. Unknown fields raise
`TypeError`; invalid combinations raise `StyleError` without partial mutation.

```python
ref = document.node("message")
ref.update(style="double", inline="# Shown to users")
print(ref.path, ref.value, ref.style)
```

## `Comments`

```python
Comments.before: list[str]
Comments.inline: str | None
Comments.after: list[str]
```

Before and after comments accept a string or iterable of lines. Every non-empty
line must include its leading `#`. Inline comments must be one line.

## `DocumentStream`

```python
DocumentStream(documents: Iterable[Document] = (), *,
               source: str = "", handle: Any = None)
len(stream) -> int
stream[index] -> Document
stream.append(document: Document) -> None
stream.insert(index: int, document: Document) -> None
stream.remove(index: int) -> Document
stream.dump(stream: Any = None, *, config: IndentConfig | None = None,
            explicit_start: bool = True) -> str | None
```

`DocumentStream` is ordered and mutable. Its `dump()` method preserves an
unchanged source stream exactly and otherwise emits each document with
document markers.

## Configuration and public types

```python
IndentConfig(mapping: int = 2, sequence: int = 2, offset: int = 0,
             width: int = 80, preserve_quotes: bool = True)
Tagged(tag: str, value: Any)
SourceSpan(start: int, end: int, line: int, column: int)
```

`IndentConfig` validates positive indentation and width, a non-negative offset
smaller than `sequence`, and controls newly emitted or explicitly re-laid-out
data. `Tagged` is an immutable representation of unknown application tags.
`SourceSpan` reports byte offsets and zero-based line and column positions.
