# Editing values

This chapter is about changing data: reading nested values, assigning to
them, creating new nodes, and reshaping sequences — all while the rest of
the file stays byte-identical.

## 1. Assignment works like Python

A loaded document is a `dict` or `list` subclass, so ordinary assignment is
already a round-trip edit:

```python
import pythonizeyaml as yaml

document = yaml.load("service:\n  host: 127.0.0.1\n  port: 8080\n")
document["service"]["port"] = 9090

assert yaml.dump(document) == "service:\n  host: 127.0.0.1\n  port: 9090\n"
```

Only the `8080` scalar was rewritten; the key order, indentation, and any
comments elsewhere are untouched.

## 2. Paths and `at()`

For programmatic access — paths computed at runtime, deep lookups — use
`Document.at()`. Path parts are mapping keys and sequence indexes, read
from the outside in:

```python
document.at("service", "port")          # 9090
document.at("artifacts", 0)             # first list item
document.at(("service", "port"))        # a tuple works too
```

A missing path raises `PathError` rather than returning `None`, which keeps
typos and schema drift loud:

```python
from pythonizeyaml import PathError

try:
    document.at("service", "poort")
except PathError as error:
    print(error)  # no YAML node at path ('service', 'poort')
```

`document[key]` and `document.at(...)` return plain Python values for
scalars and round-trip containers for nested collections; both support
assignment through `document[key] = value`.

## 3. Creating and replacing nodes with `set()`

Assignment requires the parent to exist. `Document.set()` instead creates
missing mapping keys along the path, applies style options in the same
call, and returns a `NodeRef` for the written node:

```python
document = yaml.load("service:\n  host: 127.0.0.1\n")
ref = document.set("service", "healthcheck", value="GET /health")
```

Every style option from the [next chapter](./styles.md) can ride along —
comments, quotes, tags, anchors:

```python
document.set(
    "service", "timeout",
    value=30,
    inline="# seconds before we give up",
)
```

All arguments are validated before anything is applied. An invalid
combination raises `StyleError` and leaves the document exactly as it was.

## 4. Working with sequences

Sequences have dedicated operations that keep item styles and source
metadata aligned with the data:

```python
document = yaml.load("artifacts:\n  - pythonizeyaml\n")

document.append("artifacts", value="pythonizeyaml-docs")
document.insert("artifacts", index=0, value="mirror")
removed = document.remove("artifacts", 0)
```

`append()` and `insert()` accept the same style options as `set()` and
return the `NodeRef` of the affected item. `remove()` returns the removed
value and refuses to remove the document root or any node that still has
aliases pointing at it.

## 5. Building documents from scratch

`Document.new()` creates a document from plain Python data — useful for
generating config files that should still look hand-written:

```python
document = yaml.Document.new(
    {
        "service": {"host": "127.0.0.1", "port": 8080},
        "artifacts": ["pythonizeyaml"],
    }
)
document.set("service", "debug", value=False, inline="# set true locally")

text = document.dump()
```

New data has no source layout to preserve, so the
[IndentConfig](../api/styles.md#indentconfig) settings decide the
indentation — two spaces by default, with the sequence dash flush against
its parent key.

## 6. How emission stays lossless

`dump()` does not re-serialize the data. For an unchanged document it
replays the original source text byte for byte. For edited documents it
patches the changed spans in place:

- Unchanged subtrees keep their exact source bytes, comments included.
- Modified scalars are rewritten only within their own span.
- Replaced or newly created subtrees are emitted canonically with the
  active `IndentConfig`.

The practical consequence: a tool that changes one value produces a diff
with one changed line, which is exactly what human reviewers and
`git blame` expect.
