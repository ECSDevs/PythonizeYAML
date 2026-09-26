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

## 2. Reading nested values

Nested reads are chained subscripts — a document returns plain Python
values for scalars and round-trip containers for nested collections, so the
same syntax keeps going deeper:

```python
document["service"]["port"]             # 9090
document["artifacts"][0]                # first list item
```

`Document.get()` is the dict-style read with a fallback. A tuple or list is
treated as a nested path:

```python
document.get("service", {}).get("port")  # 9090
document.get(("service", "port"))        # 9090
document.get("missing", "fallback")      # "fallback"
```

Direct subscripts keep typos loud — a missing path raises `PathError`:

```python
from pythonizeyaml import PathError

try:
    document["service"]["poort"]
except PathError as error:
    print(error)  # no YAML node at path ('service', 'poort')
```

## 3. Creating and replacing nodes

Assignment has plain-`dict` semantics: the parent must exist, and
intermediate levels are created by assigning containers first:

```python
document = yaml.load("service:\n  host: 127.0.0.1\n")
document["service"]["healthcheck"] = "GET /health"
```

Styles, comments, tags, and anchors live on the values themselves — see
the [next chapter](./styles.md). `set()` applies several fields in one
validated step:

```python
document["service"]["timeout"] = 30
document["service"]["timeout"].set(
    inline="# seconds before we give up",
)
```

`set()` validates everything before applying anything. An invalid
combination raises `StyleError` and leaves the document exactly as it was.

## 4. Working with sequences

Sequence edits are ordinary `list` calls on the wrapped container, and the
document keeps item styles and source metadata aligned with the data:

```python
document = yaml.load("artifacts:\n  - pythonizeyaml\n")

document["artifacts"].append("pythonizeyaml-docs")
document["artifacts"].insert(0, "mirror")
document["artifacts"].pop(0)
```

Removal also works through `del` — on the document itself for mapping keys
(`del document["key"]`) and on containers for indexes (`del
document["items"][0]`). Removing a node discards its comments, styles,
tags, and anchors together with it, and refuses to remove any node that
still has aliases pointing at it.

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
document["service"]["debug"] = False
document["service"]["debug"].inline = "# set true locally"

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
