# Loading untrusted YAML

YAML files from users, uploads, or third parties are inputs, not code. This
chapter shows how to read them without constructing arbitrary Python
objects, how unknown tags surface, and how to report malformed input.

## 1. The safe engine

`safe_load()` and `safe_load_all()` use the safe engine. They return plain
Python values — no document wrappers — and reject non-standard application
tags instead of resolving them:

```python
import pythonizeyaml as yaml

manifest = yaml.safe_load("steps:\n  - run: python -m pytest\n")
assert manifest == {"steps": [{"run": "python -m pytest"}]}
```

Input such as `!!python/object/apply:os.system` raises
`ConstructorError`; nothing is executed. That makes `safe_load` the default
choice for data that crosses a trust boundary.

The corresponding `safe_dump()` and `safe_dump_all()` only emit plain YAML
types and refuse `Tagged` values with `RepresenterError`.

## 2. A validator sketch

Combining the safe engine with the error hierarchy gives a compact
validator for, say, a CI manifest uploaded by a user:

```python
from pathlib import Path
import pythonizeyaml as yaml


def validate(path: Path) -> list[str]:
    try:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [f"invalid YAML: {error}"]

    problems = []
    if not isinstance(manifest, dict):
        problems.append("the document must be a mapping")
    elif "steps" not in manifest:
        problems.append("missing steps")
    return problems
```

Catching `yaml.YAMLError` covers the whole hierarchy — `ScannerError` and
`ParserError` for malformed text, `ConstructorError` for rejected tags —
and the message includes the source position:

```text
invalid YAML: tab characters must not be used in indentation
  in "unicode string", line 2, column 1
```

## 3. Unknown tags in the regular engine

The round-trip engine does not reject unknown tags, because preserving the
file byte for byte is its job. It returns them as an inert `Tagged` value:
the tag spelling and the parsed value, with nothing executed:

```python
value = yaml.load("job: !runner {name: tests}\n")
assert isinstance(value["job"], yaml.Tagged)
assert value["job"].tag == "!runner"
assert value["job"].value == {"name": "tests"}

assert yaml.dump(value) == "job: !runner {name: tests}\n"
```

The `Tagged` object round-trips verbatim, so tools can edit such files
without understanding the tags — and without the file losing them.

## 4. Choosing the engine

- Configuration you own and edit: `yaml.load()` — you get documents, styles,
  and comments.
- Data from outside: `yaml.safe_load()` — plain values, tags rejected.
- Files with unknown tags that must survive: `yaml.load()` plus the
  `Tagged` passthrough, or `safe_load()` when those files should be
  rejected instead.

Both engines share the same parser and the same error hierarchy, so one
`except yaml.YAMLError` strategy works for either.
