# Edit a service configuration

This example builds a tiny configuration command for a web service. The
command changes a port without rewriting the comments or indentation that a
person maintains in `config.yaml`.

## 1. Create the project

```console
mkdir service-config
cd service-config
python -m pip install pythonizeyaml
```

Create `config.yaml`:

```yaml
# Settings for the local web service.
service:
  host: 127.0.0.1
  port: 8080 # Change this for another local process.
```

## 2. Write the update command

Create `set_port.py`:

```python
from pathlib import Path
import sys

import pythonizeyaml as yaml


def set_port(path: Path, port: int) -> None:
    document = yaml.load(path.read_text(encoding="utf-8"))
    document["service"]["port"] = port
    path.write_text(yaml.dump(document), encoding="utf-8")


if __name__ == "__main__":
    set_port(Path("config.yaml"), int(sys.argv[1]))
```

`load()` accepts a string, bytes, or readable stream. The default loader keeps
the source metadata attached to mappings and sequences, so changing a nested
value produces a local edit when `dump()` is called.

## 3. Run it

```console
python set_port.py 9090
```

The resulting file keeps its comment and layout:

```yaml
# Settings for the local web service.
service:
  host: 127.0.0.1
  port: 9090 # Change this for another local process.
```

## 4. Handle multiple environments

For a YAML stream containing one document per environment, use `load_all()` and
`dump_all()`:

```python
documents = yaml.load_all(Path("environments.yaml").read_text(encoding="utf-8"))
for document in documents:
    document["service"]["port"] += 1
Path("environments.yaml").write_text(yaml.dump_all(documents), encoding="utf-8")
```

`load_all()` returns a list. Use the document API when you need per-document
comments, styles, or markers as first-class properties.
