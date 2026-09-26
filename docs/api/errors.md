# Errors

The exception hierarchy mirrors PyYAML: every error raised by the package
derives from `YAMLError`, so `except yaml.YAMLError` catches all of them.
Parser-side errors carry a source position; the remaining errors describe
path, style, alias, and emission failures.

## Hierarchy

```text
YAMLError
├── MarkedYAMLError
│   ├── ScannerError
│   ├── ParserError
│   ├── ComposerError
│   └── ConstructorError
├── EmitterError
├── RepresenterError
├── SerializerError
├── PathError
├── StyleError
└── AliasError
```

## `MarkedYAMLError`

Base class for errors that carry a source position from the Rust parser.
Its `str()` is a multi-line message ending in a mark such as
`  in "unicode string", line 1, column 7`.

- **context** – description of what was being parsed, or `None`.
- **context_mark** – position where the enclosing construct started.
- **problem** – the actual problem description.
- **problem_mark** – position where the problem was detected.
- **note** – additional explanation, or `None`.

### `ScannerError`

Lexing failed: a quote or bracket is unterminated, a character is not valid
in the current context, or indentation is malformed.

### `ParserError`

The token stream does not form valid YAML grammar, for example a flow
sequence that is never closed. The parser also enforces a 128-level nesting
depth limit (matching libyaml's default): input nested deeper than that
raises `ParserError` instead of exhausting the stack.

### `ComposerError`

The document structure is invalid before construction: an alias `*name`
references no defined anchor, or the input holds more than one document
where a single document was expected.

### `ConstructorError`

A value could not be constructed. Raised for duplicate mapping keys and,
in the safe engine, for non-standard application tags such as
`!!python/object/apply:...`.

## `EmitterError`

The native emitter failed while writing YAML text.

## `RepresenterError`

A value cannot be represented. Raised by the safe engine when `Tagged`
values or custom application tags appear in `safe_dump()` input, and when a
value such as a complex number is dumped in a place where no YAML
representation exists.

## `SerializerError`

The serialization step failed before emission, for example when a mapping
key cannot be represented: complex numbers are supported as values but
raise `SerializerError` when used as mapping keys.

## `PathError`

A path does not exist. Raised by `Document.at()` and `Document.node()` for
missing paths, by `Document.remove()` for the root, and by assignments
below a scalar node.

```python
>>> yaml.load("a: 1\n").at("missing")
Traceback (most recent call last):
    ...
PathError: no YAML node at path ('missing',)
```

## `StyleError`

A style request does not fit the value or the request is malformed: a
non-string value with `single`/`double`/`literal`/`folded` style, chomping
or a block indentation indicator on a non-block scalar, a comment line
without `#`, a tag not starting with `!`, an invalid anchor name, or an
inline comment spanning several lines.

## `AliasError`

An alias operation is impossible: removing a node that still has aliases,
removing an anchor still referenced by aliases, or aliasing across two
documents.
