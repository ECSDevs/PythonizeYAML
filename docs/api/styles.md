# Configuration, styles, and tagged values

Public value types used to configure emission and to describe or edit node
styles. All of them are exported from the package root.

## `IndentConfig`

```python
IndentConfig(mapping=2, sequence=2, offset=0, width=80, preserve_quotes=True)
```

An immutable dataclass with the indentation, line width, and quote-retention
settings used when the emitter must choose a layout: for data created in
Python, replaced subtrees, and explicit re-layout requests. Loaded nodes
keep their original layout unless an override applies.

- **mapping** – indentation width for nested mappings; must be `>= 1`.
- **sequence** – indentation width for nested sequences; must be `>= 1`.
- **offset** – distance between the sequence dash and its parent indent;
  must be `>= 0` and smaller than *sequence*.
- **width** – preferred maximum line width; must be `>= 1`.
- **preserve_quotes** – keep redundant scalar quotes (`'x'` vs `"x"`) on a
  round trip.

Invalid combinations raise `ValueError` at construction.

```python
>>> yaml.IndentConfig(offset=2)
Traceback (most recent call last):
    ...
ValueError: sequence offset must be smaller than the sequence indent
```

## `DEFAULT_CONFIG`

The default `IndentConfig()` instance: two-space indentation with the
sequence dash flush with its parent key, width 80, and quote preservation.

## `ScalarStyle`

```python
ScalarStyle(value)
```

A `str`-based enum describing how a scalar is written. Constructing from a
string is accepted, so `ScalarStyle("double")` and `ScalarStyle.DOUBLE` are
the same object.

- **PLAIN** (`'plain'`) – unquoted; `key: value`.
- **SINGLE** (`'single'`) – single quotes; `key: 'value'`.
- **DOUBLE** (`'double'`) – double quotes; `key: "value"`.
- **LITERAL** (`'literal'`) – literal block style; `key: |`.
- **FOLDED** (`'folded'`) – folded block style; `key: >`.

Literal and folded styles require string values; `plain` refuses strings
whose plain spelling would resolve to a different YAML type.

## `CollectionStyle`

A `str`-based enum for mapping and sequence layout.

- **BLOCK** (`'block'`) – one entry per line, the usual indented form.
- **FLOW** (`'flow'`) – inline `{...}` / `[...]` form.

## `Chomping`

A `str`-based enum for the trailing-newline behavior of block scalars.

- **CLIP** (`'clip'`) – default; a single trailing newline is kept.
- **STRIP** (`'strip'`) – emitted as `|-` or `>-`; no trailing newline.
- **KEEP** (`'keep'`) – emitted as `|+` or `>+`; all trailing newlines are
  kept.

## `SourceSpan`

```python
SourceSpan(start, end, line, column)
```

An immutable dataclass locating a node in the original text, available
through `value.span` for loaded documents.

- **start** – first byte offset of the node.
- **end** – byte offset just past the node.
- **line** – one-based line number of `start`.
- **column** – one-based column number of `start`.

## `Tagged`

```python
Tagged(tag, value)
```

An immutable tag/value pair for application-specific YAML tags, which have
no native Python representation. The round-trip engine returns unknown tags
as `Tagged` instead of executing or dropping them, and emits the original
tag spelling back.

- **tag** – the tag as written, including the leading `!`.
- **value** – the parsed value below the tag.

`Tagged` compares equal to another `Tagged` with the same tag and value.

```python
>>> job = yaml.load("job: !runner {name: tests}\n")["job"]
>>> job.tag, job.value
('!runner', {'name': 'tests'})
```
