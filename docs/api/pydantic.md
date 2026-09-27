# Pydantic integration

The optional Pydantic integration maps Pydantic models onto style-aware YAML
documents while keeping the load/dump round trip byte-for-byte. The package
root exports `YAMLModel` when `pydantic` is importable, and `YAMLSettings`,
`YAMLSettingsConfigDict` and `YAMLSettingsSource` when `pydantic-settings` is
importable. All of them are lazy: importing `pythonizeyaml` neither requires
nor imports Pydantic.

```console
poetry add "pythonizeyaml[pydantic]"             # YAMLModel
poetry add "pythonizeyaml[pydantic-settings]"    # YAMLSettings (implies pydantic)
```

The core contract is the exact round trip through validation:

```python
>>> assert Model.model_validate_yaml(original).model_dump_yaml() == original
```

## `YAMLModel`

A `pydantic.BaseModel` subclass. Validation accepts YAML sources and
documents; serialization returns style-aware documents.

```python
>>> from pythonizeyaml import YAMLModel
>>> class Limits(YAMLModel):
...     upload: str
...     retries: int = 3
>>> class AppConfig(YAMLModel):
...     host: str
...     port: int = 8080
...     limits: Limits
>>> cfg = AppConfig.model_validate_yaml("host: db\nport: 5432\n")
>>> cfg.model_dump_yaml()
'host: db\nport: 5432\n'
```

### `model_validate(obj, *, strict=None, from_attributes=None, context=None, **kwargs)`

Overridden classmethod. When `obj` is a `Document` (the result of
`pythonizeyaml.load`), it is flattened for validation and then *adopted* as
the instance's style anchor: the instance dumps back through that document,
preserving its comments and styles. Every other input (plain `dict`,
`from_attributes` objects, ...) is forwarded to Pydantic unchanged and
produces no anchor.

- **obj** – a `Document`, or anything `BaseModel.model_validate` accepts.
- **strict**, **from_attributes**, **context** – forwarded to Pydantic.
- **Returns** – a validated `YAMLModel` instance.

The adopted document is owned by the instance afterwards; it is updated in
place when the model changes and dumped again.

### `model_validate_yaml(source, *, strict=None, from_attributes=None, context=None, **kwargs)`

Parses `source` with the round-trip engine and validates the first document.

- **source** – `str`, `bytes`, or a stream with a `.read()` method.
- **strict**, **from_attributes**, **context** – forwarded to Pydantic.
- **Returns** – a validated instance whose style anchor is the parsed
  document.

Malformed YAML raises the library's own `ScannerError` / `ParserError`; a
stream with more than one document raises `ComposerError`; an empty source
behaves like an empty mapping; a non-mapping root is reported by Pydantic as
a validation error. Unknown application tags on declared fields fail
validation; on ignored extra keys they are kept verbatim.

### `model_dump(*, pretty=False, **kwargs) -> Document`

Without keyword arguments the anchored source document is updated in place
with the current field values and returned. Unchanged subtrees keep their
original bytes; a changed value is rewritten through the container's editing
path, keeping the entry's key style and comments while the new value uses
default styling. Fields absent from the source are appended only when they
hold a non-default value, so defaults never appear just because they exist.
Keys the model does not declare (ignored extras) are preserved.

Passing any Pydantic keyword (`include`, `exclude`, `mode`, `by_alias`, ...)
builds a fresh document without source styling instead.

With `pretty=True` the document is always regenerated — see
[Pretty dumps](#pretty-dumps).

- **Returns** – a `Document` (a `dict` subclass) that can be edited and
  dumped with the normal document API.

### `model_dump_yaml(*, stream=None, encoding=None, pretty=False)`

Serializes the model to YAML text.

- **stream** – write the text to this stream and return `None`.
- **encoding** – return `bytes` (or write bytes to a binary stream).
- **pretty** – regenerate the document instead of patching the anchored one.
- **Returns** – the YAML text, `bytes` when `encoding` is given, or `None`
  when writing to a stream.

### Pretty dumps

`model_dump(pretty=True)` and `model_dump_yaml(pretty=True)` regenerate the
document instead of patching the anchored source. Four things change:

- **Declaration order** – mapping keys follow the model's field order,
  recursively through nested models (including model items inside
  sequences). Keys the model does not declare are appended after the
  declared fields, in source order.
- **Default filling** – every declared field appears; fields missing from
  the source are written with their current (default) value.
- **Field descriptions** – `Field(description=...)` becomes a comment block
  above the key, one line per description line.
- **Container spacing** – inside every block mapping, a blank line separates
  two adjacent entries whenever either of them is a non-empty container (a
  mapping or sequence with items). Scalar neighbours and empty containers
  stay tight; sequence items are not separated.

```python
>>> from pydantic import Field
>>> class Server(YAMLModel):
...     host: str = Field("localhost", description="Address to bind")
...     ports: list[int] = []
>>> class AppConfig(YAMLModel):
...     debug: bool = False
...     server: Server
...     name: str = "app"
>>> print(AppConfig.model_validate_yaml(
...     "name: myapp\nserver:\n  ports: [8080]\n").model_dump_yaml(pretty=True))
debug: false

server:
  # Address to bind
  host: localhost

  ports:
    - 8080

name: myapp
```

Existing comments travel with their keys — comment blocks above a key, its
inline comment, and trailing comments after the last entry — so a
reformatted file keeps its documentation. Comments that already match a
field's description are not duplicated, and running
`model_dump_yaml(pretty=True)` on the re-validated output reproduces the
same text (pretty is idempotent).

Pretty regeneration is a re-emission, not a byte-preserving patch: only
comments travel with their keys, while scalar quoting, collection styles and
other layout choices are re-emitted with the library defaults. The
byte-for-byte contract applies to the default `model_dump()` only. When
pretty is combined with other Pydantic keywords, the filtered values are
still ordered, commented and spaced, but defaults are not filled, undeclared
keys are not appended, and source comments are not carried over.

### Round-trip boundaries

The byte-for-byte guarantee holds whenever validation does not change a
value. These conditions rewrite the affected entry with default styling:

- a value is coerced (e.g. the quoted `"5432"` for an `int` field);
- a field is set after validation (its new value is re-emitted);
- Pydantic keywords are passed to `model_dump` (fresh document).

Key order follows the source document, not the field declaration order, and
fields missing from the source stay missing unless they are set to a
non-default value at runtime. `pretty=True` is the deliberate escape hatch:
it reorders keys by declaration, fills defaults and reformats spacing (see
[Pretty dumps](#pretty-dumps)).

## `YAMLSettings`

A `pydantic_settings.BaseSettings` subclass whose sources include YAML files
read with pythonizeyaml's own parser (PyYAML is never imported).

```python
>>> from pythonizeyaml import YAMLSettings, YAMLSettingsConfigDict
>>> class Settings(YAMLSettings):
...     model_config = YAMLSettingsConfigDict(yaml_file="app.yaml")
...     host: str
...     port: int = 8080
>>> Settings().model_dump_yaml() == Path("app.yaml").read_text()
True
```

### Source priority

`init` values, environment variables, dotenv, the YAML file(s), the secrets
directory — the BaseSettings convention. `settings_customise_sources` can be
overridden for a custom order.

The instance keeps the parsed YAML document as its style anchor, so
`model_dump_yaml()` reproduces the file byte-for-byte except for values
provided by higher-priority sources (or changed after construction), which
are re-emitted with default styling in place.

### `YAMLSettingsConfigDict`

A `pydantic_settings.SettingsConfigDict` extended with:

- **yaml_file** – one path, or an ordered sequence of paths. Later files
  override earlier keys. Missing files are silently skipped.

All other keys are forwarded to `SettingsConfigDict`.

### `YAMLSettingsSource`

The settings source class. It subclasses the built-in
`YamlConfigSettingsSource` and replaces only the file parser, so it supports
the same configuration keys (`yaml_file`, `yaml_file_encoding`,
`yaml_config_section`, `deep_merge`). Instantiate it from
`settings_customise_sources` when you need a custom source order.

Missing files are silently skipped; a non-mapping root raises `ValueError`;
malformed YAML raises the library's own `YAMLError` subclasses.

## Errors

| Situation | Exception |
| --- | --- |
| malformed YAML | `ScannerError` / `ParserError` (subclasses of `YAMLError`) |
| more than one document | `ComposerError` |
| unknown tag on a declared field | Pydantic `ValidationError` |
| field validation failure | Pydantic `ValidationError` |
| non-mapping root in a settings file | `ValueError` |
| missing settings file | silently skipped |
