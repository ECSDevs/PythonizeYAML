# API reference

PythonizeYAML exposes one PyYAML-compatible API. `load()` and `load_all()`
return style-aware `Document` objects that also behave like the ordinary
`dict` and `list` values they wrap, and `dump()` and `dump_all()` accept those
documents directly. Style editing is layered on the same objects.

The reference is organized as follows:

- [Loading and dumping](./functions.md) – the module-level functions and the
  `YAML` / `SafeYAML` engines, with full signatures and per-argument
  descriptions.
- [Documents and style editing](./documents.md) – the `Document` class and
  its members, the `DocumentMapping` / `DocumentSequence` /
  `DocumentScalar` subclasses, the styling API on values, `Comments`, and
  `DocumentStream`.
- [Configuration, styles, and tagged values](./styles.md) – `IndentConfig`,
  `DEFAULT_CONFIG`, the style enums, `SourceSpan`, and `Tagged`.
- [Errors](./errors.md) – the `YAMLError` hierarchy and when each exception
  is raised.

If you are new to the package, start with the [Tutorial](../guide/) and
return here for exact signatures.
