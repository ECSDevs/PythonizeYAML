# Loading and dumping

The module-level functions mirror the PyYAML entry points. All of the
round-trip functions delegate to a lazily created, process-wide default
engine; instantiate `YAML` instead when you need your own configuration or
thread isolation.

Input parameters named *stream* accept a `str`, UTF-8 `bytes`, or an object
with a `.read()` method returning either.

## `load()`

```python
load(stream, Loader=None)
```

Load the first YAML document from *stream* with the lossless round-trip
engine. Comments, scalar styles, anchors, aliases, and layout are attached to
the returned object instead of being discarded.

- **stream** – the YAML source: a `str`, UTF-8 `bytes`, or a readable stream.
- **Loader** – accepted for PyYAML migration compatibility and ignored; the
  round-trip engine is always used.

Returns a `Document`: a `DocumentMapping` or `DocumentSequence` for mapping
and sequence roots (subclasses of `dict` and `list`), or a `DocumentScalar`
for a scalar root. Raises a `YAMLError` subclass (typically `ScannerError` or
`ParserError`) when the input is not valid YAML.

```python
>>> import pythonizeyaml as yaml
>>> config = yaml.load("port: 8080\n")
>>> config["port"]
8080
```

## `load_all()`

```python
load_all(stream, Loader=None)
```

Load every YAML document from *stream*.

- **stream** – the YAML stream to read.
- **Loader** – accepted for PyYAML migration compatibility and ignored.

Returns a `list` of `Document` objects, one per document in the stream, in
source order. Raises the same errors as `load()`. Use `load_documents()`
when the ordered `DocumentStream` wrapper is preferred.

```python
>>> for doc in yaml.load_all("---\nname: one\n---\nname: two\n"):
...     doc["name"]
'one'
'two'
```

## `dump()`

```python
dump(data, stream=None, *, indent=None, width=None, explicit_start=None,
     allow_unicode=None, default_flow_style=None, sort_keys=None,
     encoding=None, Dumper=None)
```

Serialize *data* to YAML while preserving its original layout.

- **data** – plain Python data, or a `Document`. For a `Document`, `dump()`
  delegates to `Document.dump()`: an unchanged document replays its source
  text exactly, and modified nodes are patched locally.
- **stream** – a writable stream. When `None` (the default), the YAML text is
  returned as a `str`; otherwise the text is written to *stream* and `None`
  is returned.
- **indent** – (`int | None`) sets the indentation width for nested mappings
  and sequences and resets the sequence offset to zero, approximating
  PyYAML's `indent` behavior. Loaded documents keep their original layout
  unless this is given.
- **width** – (`int | None`) the preferred maximum line width used when the
  emitter must choose a layout for new data.
- **explicit_start** – (`bool | None`) emit a leading `---` document marker.
- **allow_unicode**, **default_flow_style**, **sort_keys**, **encoding**,
  **Dumper** – accepted for PyYAML migration compatibility and ignored,
  because source layout and Unicode output are always preserved.

Any other keyword argument raises `TypeError`.

```python
>>> yaml.dump({"name": "demo"}, indent=4, explicit_start=True)
'---\nname: demo\n'
```

## `dump_all()`

```python
dump_all(documents, stream=None, *, indent=None, width=None,
         explicit_start=None, allow_unicode=None, default_flow_style=None,
         sort_keys=None, encoding=None, Dumper=None)
```

Serialize an iterable of documents as a multi-document stream, separated by
`---` markers.

- **documents** – an iterable of YAML-representable values or `Document`
  objects. A `DocumentStream` returned by `load_documents()` is accepted as
  well and is replayed exactly while none of its documents changed.
- **stream** – same contract as `dump()`.
- remaining keyword arguments – same as `dump()`.

Generators are consumed before emission. Without `explicit_start`, the
first document is written without a leading marker.

```python
>>> yaml.dump_all([{"name": "one"}, {"name": "two"}], explicit_start=True)
'---\nname: one\n---\nname: two\n'
```

## `safe_load()`

```python
safe_load(stream)
```

Load the first document using the safe engine, which returns plain Python
values without document wrappers.

- **stream** – the YAML source to read.

Returns an ordinary `dict`, `list`, or scalar. Unknown application tags are
not resolved into Python objects: input such as `!!python/object/apply:...`
raises `ConstructorError` instead of executing anything.

```python
>>> yaml.safe_load("enabled: true\n")
{'enabled': True}
```

## `safe_load_all()`

```python
safe_load_all(stream)
```

Load every document with the safe engine.

- **stream** – the YAML stream to read.

Returns a `list` of plain Python values. Tag restrictions are the same as
`safe_load()`.

## `safe_dump()`

```python
safe_dump(data, stream=None, *, indent=None, width=None, explicit_start=None,
          allow_unicode=None, default_flow_style=None, sort_keys=None,
          encoding=None, Dumper=None)
```

Serialize *data* using the safe representation; only plain YAML types are
emitted.

- **data** – plain Python data. `Tagged` values anywhere in *data* raise
  `RepresenterError`.
- **stream** – same contract as `dump()`.
- remaining keyword arguments – same as `dump()`.

```python
>>> yaml.safe_dump({"enabled": True})
'enabled: true\n'
```

## `safe_dump_all()`

```python
safe_dump_all(documents, stream=None, *, indent=None, width=None,
              explicit_start=None, allow_unicode=None,
              default_flow_style=None, sort_keys=None, encoding=None,
              Dumper=None)
```

Serialize an iterable of documents with the safe representation.

- **documents** – an iterable of plain YAML-representable values.
- **stream** – same contract as `dump()`.
- remaining keyword arguments – same as `dump()`.

## Explicit round-trip spellings

```python
round_trip_load(stream, Loader=None)
round_trip_load_all(stream, Loader=None)
round_trip_dump(data, stream=None, **kwargs)
round_trip_dump_all(documents, stream=None, **kwargs)
```

Aliases for `load()`, `load_all()`, `dump()`, and `dump_all()`, provided for
call sites that want to state the round-trip intent explicitly.

## Engine objects

The module-level functions share one default engine per flavor. Instantiate
`YAML` or `SafeYAML` directly to isolate configuration or use several
configurations at once.

```python
YAML(config=None)
SafeYAML(config=None)
```

- **config** – an `IndentConfig`, or `None` to use `DEFAULT_CONFIG`.

`SafeYAML` has the same methods, rejects non-standard application tags, and
loads plain Python values without document wrappers.

### `YAML.load(stream)`

Load the first document; returns a `Document` (plain values for `SafeYAML`).

### `YAML.load_all(stream)`

Load every document; returns a `list` of `Document` objects (plain values for
`SafeYAML`).

### `YAML.dump(data, stream=None, *, config=None, explicit_start=None)`

Serialize *data*; accepts `Document` objects. A per-call *config* (`IndentConfig | None`)
overrides the engine's configuration for this call only.

### `YAML.dump_all(documents, stream=None, *, config=None, explicit_start=None)`

Serialize an iterable of documents; accepts a `DocumentStream`. The per-call
*config* override behaves as in `YAML.dump()`.

```python
>>> engine = yaml.YAML(yaml.IndentConfig(mapping=4, sequence=4))
>>> engine.dump({"service": {"port": 8080}})
'service:\n    port: 8080\n'
```
