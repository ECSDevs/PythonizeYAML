# Validate a CI manifest safely

Suppose a CI service accepts a YAML manifest uploaded by a user. The validator
only needs ordinary YAML values, so it should reject application-specific tags
at the input boundary.

## 1. Create a validator

Create `validate_ci.py`:

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


if __name__ == "__main__":
    for problem in validate(Path("ci.yaml")):
        print(problem)
```

## 2. Test valid input

`ci.yaml` can contain ordinary YAML values:

```yaml
steps:
  - run: python -m pytest
```

`safe_load()` returns a normal Python mapping and sequence. It accepts the
same string, bytes, and readable-stream inputs as `load()`.

## 3. See how tags are handled

The regular API preserves an unknown tag as `Tagged` without executing it:

```python
value = yaml.load("job: !runner {name: tests}\n")
assert isinstance(value["job"], yaml.Tagged)
assert value["job"].tag == "!runner"
```

The safe API rejects the same input with `ConstructorError`. Use `safe_load`
and `safe_load_all` for data that crosses a trust boundary. `safe_dump` and
`safe_dump_all` also reject `Tagged` values.
