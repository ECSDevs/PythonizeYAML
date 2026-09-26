# Tutorial

This tutorial walks through PythonizeYAML from first principles: loading and
dumping, editing values in place, controlling comments and styles, and
loading untrusted input safely. Each chapter builds on the previous ones and
ends where the [API reference](../api/) takes over.

PythonizeYAML is a YAML library with a PyYAML-compatible API and a lossless
round-trip engine: loading a document, changing a value, and dumping it again
reproduces the original file byte for byte everywhere you did not touch.

The chapters use `import pythonizeyaml as yaml` throughout, so the examples
read like PyYAML code.

1. [Loading and dumping](./basics.md) - `load()`, `dump()`, document
   objects, and the round-trip guarantee.
2. [Editing values](./editing.md) - paths, assignment, `set()`, sequences,
   and building documents from scratch.
3. [Comments, styles, tags, and anchors](./styles.md) - the style-aware
   editing layer carried by the values themselves.
4. [Loading untrusted YAML](./safety.md) - `safe_load()`, `Tagged`, and the
   error model at a trust boundary.

When you want complete, runnable projects instead of isolated snippets, see
the worked examples:

- [Edit a service configuration](./quickstart.md)
- [Build a release metadata command](./round-trips.md)
