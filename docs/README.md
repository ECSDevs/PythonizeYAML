---
home: true
heroText: PythonizeYAML
tagline: A PyYAML-compatible YAML library with lossless round trips.
actions:
  - text: Read the guides
    link: /guide/
    type: primary
  - text: Browse the API
    link: /api/
    type: secondary
features:
  - title: Lossless round trips
    details: Preserve comments, indentation, scalar styles, and document layout while editing values.
  - title: PyYAML-compatible API
    details: Load and dump YAML with familiar functions such as load, dump, safe_load, and safe_dump.
  - title: Style-aware documents
    details: Use Document and NodeRef to edit comments, tags, anchors, aliases, and formatting explicitly.
---

PythonizeYAML keeps the existing source layout when a document is loaded,
edited, and dumped again.

## Install

```console
pip install pythonizeyaml
```

## Quick example

```python
import pythonizeyaml as yaml

document = yaml.load("service:\n  port: 8080\n")
document["service"]["port"] = 9090
print(yaml.dump(document))
```

The guides explain how to preserve source formatting, work with the document
API, and load untrusted YAML safely. The API section lists the public loading,
dumping, document, style, and error interfaces.
