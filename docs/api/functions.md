# Loading and dumping

The function API mirrors common PyYAML entry points. The default functions use
the lossless round-trip engine. Input functions accept a `str`, UTF-8 `bytes`,
or an object with a `.read()` method.

## `load()`

```python
load(stream: Any, Loader: Any = None) -> Any
```

Loads the first document. `Loader` is accepted for migration compatibility and
ignored. Editable mappings and sequences retain comments, styles, anchors,
aliases, and source spans.

```python
config = yaml.load("port: 8080\n")
config["port"] = 9090
assert yaml.dump(config) == "port: 9090\n"
```

## `load_all()`

```python
load_all(stream: Any, Loader: Any = None) -> list[Any]
```

Loads every document and returns a list. `Loader` is accepted and ignored.

```python
documents = yaml.load_all("---\nname: one\n---\nname: two\n")
documents[1]["name"] = "updated"
```

## `dump()`

```python
dump(data: Any, stream: Any = None, **kwargs: Any) -> str | None
```

Returns YAML text when `stream` is `None`; otherwise writes to the writable
stream and returns `None`. Supported options are:

```python
dump(data, stream=None, *, indent=None, width=None,
     explicit_start=None, allow_unicode=None,
     default_flow_style=None, sort_keys=None,
     encoding=None, Dumper=None) -> str | None
```

`indent` sets mapping and sequence indentation and resets the sequence offset
to zero. `width` sets the preferred line width. `explicit_start=True` emits a
leading `---`. `allow_unicode`, `default_flow_style`, `sort_keys`, `encoding`,
and `Dumper` are accepted but ignored because source layout and Unicode output
are preserved. Any other keyword raises `TypeError`.

```python
text = yaml.dump({"name": "demo"}, indent=4, explicit_start=True)
```

## `dump_all()`

```python
dump_all(documents: Iterable[Any], stream: Any = None, **kwargs: Any) -> str | None
```

Serializes an iterable of documents. It has the same stream and keyword
behavior as `dump()` and consumes generators before emission.

```python
text = yaml.dump_all([{"name": "one"}, {"name": "two"}])
```

## Safe functions

```python
safe_load(stream: Any) -> Any
safe_load_all(stream: Any) -> list[Any]
safe_dump(data: Any, stream: Any = None, **kwargs: Any) -> str | None
safe_dump_all(documents: Iterable[Any], stream: Any = None, **kwargs: Any) -> str | None
```

Safe loads reject non-standard application tags with `ConstructorError`. Safe
dumps reject `Tagged` values with `RepresenterError`. Dump options and stream
return rules match the regular functions.

```python
settings = yaml.safe_load("enabled: true\n")
safe_text = yaml.safe_dump(settings)
```

## Explicit round-trip names

```python
round_trip_load(stream: Any, Loader: Any = None) -> Any
round_trip_load_all(stream: Any, Loader: Any = None) -> list[Any]
round_trip_dump(data: Any, stream: Any = None, **kwargs: Any) -> str | None
round_trip_dump_all(documents: Iterable[Any], stream: Any = None, **kwargs: Any) -> str | None
```

These names are aliases for the regular lossless functions.

## Engine objects

```python
YAML(config: IndentConfig | None = None)
YAML.load(self, stream: Any) -> Any
YAML.load_all(self, stream: Any) -> list[Any]
YAML.dump(self, data: Any, stream: Any = None, *,
          config: IndentConfig | None = None,
          explicit_start: bool | None = None) -> str | None
YAML.dump_all(self, documents: Iterable[Any], stream: Any = None, *,
              config: IndentConfig | None = None,
              explicit_start: bool | None = None) -> str | None
SafeYAML(config: IndentConfig | None = None)
```

`YAML` keeps configuration isolated in an instance. `SafeYAML` has the same
methods but rejects non-standard tags. A per-call `config` overrides the
engine's `IndentConfig`.

```python
engine = yaml.YAML(yaml.IndentConfig(mapping=4, sequence=4))
text = engine.dump({"service": {"port": 8080}})
```
