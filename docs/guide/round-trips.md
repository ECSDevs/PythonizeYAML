# Build a release metadata command

This example updates a release file used by a small Python project. The
function API is enough for value changes; the document API is useful when the
command also owns comments, quotes, or collection style.

## 1. Start with a release file

Create `release.yaml`:

```yaml
# Published by release.py.
version: '0.3.0'
channel: stable
artifacts:
  - pythonizeyaml
  - pythonizeyaml-docs
```

## 2. Load the document and update its metadata

Create `release.py`:

```python
from pathlib import Path

from pythonizeyaml import ScalarStyle, load_document


def publish(version: str) -> None:
    path = Path("release.yaml")
    document = load_document(path.read_text(encoding="utf-8"))

    document.node("version").update(
        value=version,
        style=ScalarStyle.SINGLE,
        inline="# Release version",
    )
    document.node("channel").comments.before = ["# Published channel"]
    path.write_text(document.dump(), encoding="utf-8")


if __name__ == "__main__":
    publish("0.4.0")
```

`NodeRef.update()` validates all requested style fields before applying the
change. If a later field is invalid, the document is restored to its previous
state.

## 3. Verify the result

Running `python release.py` produces:

```yaml
# Published by release.py.
# Published channel
version: '0.4.0'  # Release version
channel: stable
artifacts:
  - pythonizeyaml
  - pythonizeyaml-docs
```

The original quote style is retained and the new comment is attached to the
specific node. `document.source` remains the original source text; use
`document.dump()` for the current representation.

## 4. Add a new field with style metadata

`Document.set()` creates missing mapping paths and returns a `NodeRef`:

```python
document.set(
    "build",
    "command",
    value="python -m build",
    style=ScalarStyle.DOUBLE,
    before="# Command used by CI",
)
```

Use `document.node("artifacts").collection_style = "flow"` when a collection
should be emitted as `[pythonizeyaml, pythonizeyaml-docs]`.
