# Loading and dumping

This chapter covers the core loop of the library: reading YAML into editable
Python objects, writing them back out, and the round-trip guarantee that
makes the output identical to the input wherever you did not change
anything.

## 1. Install

```console
python -m pip install pythonizeyaml
```

The examples use the conventional PyYAML-style import:

```python
import pythonizeyaml as yaml
```

## 2. Load YAML

`yaml.load()` reads one document:

```python
document = yaml.load(
    """
# Settings for the local web service.
service:
  host: 127.0.0.1
  port: 8080
"""
)
```

The return value is a `Document`. For mapping and sequence roots it is a
`dict` or `list` subclass (`DocumentMapping`, `DocumentSequence`), so
everything you already know about Python containers applies:

```python
document["service"]["port"]     # 8080
len(document)                   # 1
"service" in document           # True
```

The difference from PyYAML is invisible in plain use and decisive under the
hood: this object remembers where each value came from — its comments, its
quoting, its indentation — and keeps that memory attached while you edit.

`load()` also accepts UTF-8 `bytes` and any object with a `.read()` method,
so file handles and network responses work without preprocessing:

```python
with open("config.yaml", encoding="utf-8") as handle:
    document = yaml.load(handle)
```

## 3. Dump YAML

`yaml.dump()` is the mirror image. Without a stream it returns the YAML
text; with a writable stream it writes and returns `None`:

```python
text = yaml.dump(document)

with open("out.yaml", "w", encoding="utf-8") as handle:
    yaml.dump(document, handle)
```

Dump options are keyword-only and shared by all dump functions:

```python
yaml.dump(data, indent=4)           # nested indent width, dash flush with parent
yaml.dump(data, width=100)          # preferred maximum line width
yaml.dump(data, explicit_start=True)  # emit a leading ---
```

Several PyYAML keywords — `allow_unicode`, `default_flow_style`,
`sort_keys`, `encoding`, `Dumper` — are accepted and ignored: they would
conflict with byte-level preservation, which is the whole point of the
library. Any other keyword raises `TypeError`.

## 4. The round-trip guarantee

Loading an untouched document and dumping it again reproduces the source
exactly:

```python
source = """\
# Published by release.py.
version: '0.3.0'
artifacts:
  - pythonizeyaml
  - pythonizeyaml-docs
"""

assert yaml.dump(yaml.load(source)) == source
```

The single quotes around `0.3.0`, the block sequence dashes, the comment,
and the blank lines all survive. When you edit a value, only that value's
bytes are rewritten — and its style is preserved, so a quoted scalar stays
quoted:

```python
document = yaml.load(source)
document["version"] = "0.4.0"

assert yaml.dump(document) == source.replace("'0.3.0'", "'0.4.0'")
```

## 5. Multi-document streams

A file may hold several YAML documents separated by `---`. `load_all()`
returns them as a list of `Document` objects, and `dump_all()` writes a
list back as a stream:

```python
documents = yaml.load_all(Path("environments.yaml").read_text(encoding="utf-8"))
for document in documents:
    document["service"]["port"] += 1

text = yaml.dump_all(documents)
```

If you want the stream itself as one object — with the ability to add,
insert, or remove whole documents — use `yaml.load_documents()`, which
returns a `DocumentStream`; see the
[API reference](../api/documents.md#documentstream).

## 6. Choosing an engine

The module-level functions share process-wide default engines. When you
need isolated configuration — different indentation, or a parser you can
reconfigure without touching global state — instantiate the engine class:

```python
engine = yaml.YAML(yaml.IndentConfig(mapping=4, sequence=4))
text = engine.dump({"service": {"port": 8080}})
```

`yaml.YAML` round-trips and returns documents; `yaml.SafeYAML` has the same
methods, loads plain Python values, and rejects non-standard tags. The next
chapters edit documents in place; the [safety chapter](./safety.md) covers
when to prefer the safe engine.
