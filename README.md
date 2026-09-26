# pythonizeyaml

English | [简体中文](README.zh_CN.md)

`pythonizeyaml` is a YAML library with a PyYAML-compatible API and a lossless
round-trip engine implemented in Rust. Loading and dumping an untouched document
reproduces its source text, including comments, blank lines, indentation, scalar
styles, document markers, anchors, and multi-document layout.

The parser and emitter are compiled through PyO3 and Maturin. There is no Python
YAML runtime dependency.

## Comparison with Other YAML Libraries

The table below compares `pythonizeyaml` 0.3.0 with PyYAML, `yamltrip`, and
`ruamel.yaml`.

| Area | pythonizeyaml | PyYAML | yamltrip | ruamel.yaml |
|---|---|---|---|---|
| Primary purpose | PyYAML-style YAML API with lossless round trips | General YAML serializer/parser | Format-preserving YAML file editor and query API | General YAML with strong round-trip support |
| Main API | `load`, `load_all`, `dump`, `dump_all`, `safe_*`, `YAML` | Same function-oriented API, plus lower-level scanner/parser APIs | `load`/`loads` return `Document`; immutable edits plus `Editor` | Class-oriented `YAML()` API; legacy top-level functions are deprecated |
| Document API | `load`/`load_all` return mutable `Document` objects; `load_document`/`load_documents` and `read_document`/`read_documents` are explicit spellings; path-based `NodeRef` for style editing | No mutable document wrapper; use Python values or low-level nodes/events | `Document`/`Editor` centered editing and query API | `YAML().load()` returns mutable `CommentedMap`/`CommentedSeq` documents |
| Return model | `Document` roots (`dict`/`list` subclasses); nested standard Python scalars, `RoundTripMap`/`List`/`Set`, `Decimal`, `Tagged` | Plain Python objects and YAML AST/event/token objects | `Document` wrapper around plain Python values | `CommentedMap`, `CommentedSeq`, scalar subclasses |
| Backend | Custom Rust parser/emitter through PyO3 | Pure Python plus optional LibYAML C extension | `tree-sitter-yaml` through Rust `yamlpath`/`yamlpatch` | Python plus optional C parser |
| Unchanged round trip | Exact source text, including comments, blanks, styles, markers, and line layout | No preservation guarantee; output is regenerated | Preserves source and format while patching edits | Preserves comments and styles in round-trip mode, but output remains emitter-controlled |
| Comments and whitespace | Preserved exactly for unchanged documents | Lost or normalized | Preserved | Preserved, generally |
| Indentation and flow style | Original formatting retained; explicit `IndentConfig` can override | Regenerated according to dumper settings | Preserved | Retained in normal round-trip workflows, with indentation configurable |
| Scalar quotes/styles | Preserved, including redundant quotes and block styles | Rewritten | Preserved as raw source | Preserved, including `preserve_quotes` support |
| Mutation model | Mutate loaded `Document` objects (dict-like/list-like); unchanged bytes are retained | Mutate plain objects, then regenerate | Immutable `Document` methods or mutable `Editor`; minimal patches | Mutate `CommentedMap`/`CommentedSeq` objects |
| Style editing API | `NodeRef` edits scalar/collection styles, comments, tags, anchors, aliases, chomping, directives, and markers | Dumper options and low-level representers; no source style editing API | Path/editor operations preserve selected source formatting | Object attributes and `YAML` emitter options expose round-trip style controls |
| Structural edit fidelity | Local edits are patched; replaced/new subtrees may be canonically emitted | Full regeneration | Designed for minimal structural patches | Strong preservation of attached comments and formatting |
| YAML schema | YAML 1.2 core by default; `%YAML 1.1` switches legacy booleans | YAML 1.1-oriented resolver by default | Focused on editable YAML values; tags are not interpreted | YAML 1.2 by default |
| Large integers | Arbitrary-precision Python `int` | Arbitrary-precision Python `int` | May lose precision outside signed 64-bit range | Arbitrary-precision Python `int` |
| Decimal values | Exact binary64-representable decimals become `float`; others become `Decimal`; `!!decimal` forces `Decimal` | Normally `float`; custom constructors needed for `Decimal` | Basic scalar conversion; no special big-decimal support | Normally `float`; custom representers/constructors needed for `Decimal` |
| Unknown/application tags | Returned as `Tagged`; never executed | Depends on loader/constructors; unsafe loaders can construct Python objects | Not interpreted | Preserved; constructors can define behavior |
| Safe loading | `safe_load` rejects non-standard tags | `safe_load` uses `SafeLoader` | No separate safe/unsafe object-construction model | `YAML(typ="safe")` or safe loading APIs |
| Anchors and aliases | Parsed, preserved, resolved to shared Python objects | Resolved; dumper may emit anchors | Detected but not resolved during extraction | Resolved and preserved |
| Multi-document streams | Supported | Supported | Not supported | Supported |
| Custom classes | No constructor/representer plugin API | `YAMLObject`, constructors, representers | No custom class serialization | Constructors, representers, and plug-ins |
| Events/nodes | No public scan/parse/event API | Full scanner, parser, composer, node APIs | Tree/query/path API instead | Full event/node APIs |
| Errors | PyYAML-compatible hierarchy | PyYAML hierarchy | `YAMLTripError` hierarchy | ruamel-specific `YAMLError` hierarchy |
| Encoding | UTF-8 input through `str`/`bytes`/streams | Several YAML encodings depending on reader | UTF-8 only | Configurable, broad encoding support |
| Maturity | New 0.3.0 custom implementation | Very mature, widely deployed | Newer focused library, version 0.4.x | Very mature round-trip implementation |

The biggest practical distinctions:

- **Compared with PyYAML:** `pythonizeyaml` keeps source layout by default, but is
  much younger and lacks PyYAML's mature event API, custom constructor ecosystem,
  encoding breadth, and long-term compatibility history. Unlike unsafe PyYAML
  loaders, it does not execute `!!python/...` tags.
- **Compared with yamltrip:** yamltrip is optimized around editing and querying
  YAML files through `Document`/`Editor`; it explicitly does not support
  multi-document streams, tag interpretation, anchor resolution, or
  arbitrary-size integer preservation. `pythonizeyaml` provides a PyYAML-style
  data API and broader YAML semantics, but its structural-edit patching is less
  specialized than yamltrip's.
- **Compared with ruamel.yaml:** ruamel is the mature reference for mutable
  comment-preserving YAML objects. `pythonizeyaml` instead promises exact source
  replay for unchanged documents and uses Rust-native parsing, `Decimal`
  precision policy, and `Tagged` values. It does not yet offer ruamel's class
  registration, plug-in ecosystem, or depth of YAML conformance coverage.

Sources: [PyYAML repository](https://github.com/yaml/pyyaml),
[yamltrip README](https://github.com/usethis-python/yamltrip), and
[ruamel.yaml repository](https://github.com/pycontribs/ruamel-yaml).
## Requirements

- Python 3.10 or newer
- Rust 1.83 or newer when building from source
- [Maturin](https://www.maturin.rs/) 1.15 or newer for extension development

## Installation

```console
pip install pythonizeyaml
```

For a source checkout:

```console
poetry install
poetry run maturin develop
```

## Quickstart

```python
import pythonizeyaml as yaml

document = yaml.load(open("config.yaml", encoding="utf-8"))
document["service"]["port"] = 9090
text = yaml.dump(document)
```

Only the changed scalar is rewritten. Comments and formatting elsewhere remain
byte-identical. Pass a writable stream as the second argument to write directly:

```python
with open("config.yaml", "w", encoding="utf-8") as handle:
    yaml.dump(document, handle)
```

## Numeric Resolution

Integers use Python's arbitrary-precision `int`. Decimal and exponent literals
are compared exactly with IEEE 754 binary64:

```python
from decimal import Decimal
import pythonizeyaml as yaml

assert type(yaml.load("value: 1.5\n")["value"]) is float
assert type(yaml.load("value: 0.1\n")["value"]) is Decimal
assert type(yaml.load("value: 1e400\n")["value"]) is Decimal
```

Use `!!float` to force `float` or `!!decimal` to force `Decimal`.

## Tags and Safety

The core and common standard YAML tags are resolved, including `!!binary`,
`!!timestamp`, `!!set`, and merge keys. Unknown application tags are returned as
`pythonizeyaml.Tagged(tag, value)` and preserve their spelling during round trips.

Use `safe_load` or `safe_load_all` for untrusted YAML. These functions reject
non-standard tags instead of constructing arbitrary Python objects.

```python
value = yaml.safe_load("enabled: true\n")
```

## API

The module exposes:

- `load`, `load_all`, `dump`, `dump_all`
- `safe_load`, `safe_load_all`, `safe_dump`, `safe_dump_all`
- `round_trip_load`, `round_trip_load_all`, `round_trip_dump`, `round_trip_dump_all`
- `YAML`, `SafeYAML`, `IndentConfig`, `DEFAULT_CONFIG`, `Tagged`
- `Document`, `DocumentStream`, `NodeRef`, and `Comments`
- `load_document`, `load_documents`, `read_document`, and `read_documents`
- `ScalarStyle`, `CollectionStyle`, `Chomping`, and `SourceSpan`
- `YAMLError` and its PyYAML-compatible subclasses

`Loader=`, `sort_keys`, `default_flow_style`, `allow_unicode`, and `encoding` are
accepted for migration compatibility and ignored where they conflict with
lossless output.

## Advanced Style Documents

`load()`, `load_all()`, and `load_document()` all return mutable, style-aware
`Document` objects. For explicit control over comments, scalar styles,
collection styles, tags, anchors, aliases, directives, and document markers,
use the NodeRef style API on the loaded document:

```python
from pythonizeyaml import ScalarStyle, load_document

document = load_document("name: example\nitems:\n  - one\n  - two\n")
document.node("name").style = ScalarStyle.DOUBLE
document.node("name").comments.before = ["# service name"]
document.node("items").collection_style = "flow"

text = document.dump()
```

`load_document()` returns one mutable `Document`; `load_documents()` returns a
list-like `DocumentStream`. Collection roots load as `DocumentMapping` or
`DocumentSequence` (`dict`/`list` subclasses) and scalar roots as
`DocumentScalar`. `Document.node(*path)` returns a `NodeRef`, while
`Document.at(*path)` and direct `document[path]` access return ordinary Python
values. Use `Document.new()` or `Document.set(...)` to create styled documents.

`NodeRef` exposes `style`, `collection_style`, `chomping`,
`block_indent_indicator`, `tag`, `anchor`, `comments`, `is_alias`, and
`alias_target`. Its `update(...)` method applies multiple fields atomically.
Style changes are validated before mutation; see `StyleError`, `PathError`, and
`AliasError` for failures.

For repository setup, testing, and contribution conventions, see
[`CONTRIBUTING.md`](CONTRIBUTING.md).
## Indentation Configuration

`IndentConfig(mapping=2, sequence=2, offset=0, width=80, preserve_quotes=True)`
controls newly created data and explicit re-layout requests. Loaded documents
retain their original layout unless an override is supplied.

## Development

```console
cargo test --manifest-path rust/Cargo.toml
poetry run maturin develop
poetry run pytest
poetry build
```

Tests run against `tests/fixtures/`; add malformed inputs under
`tests/fixtures/invalid/`.

## Root Scalar Documents

Root scalars load as `DocumentScalar`, a `Document` wrapper that keeps source
metadata and scalar styles (quotes, block headers) but is not a `str`/`int`
subclass. It compares equal to the wrapped value and coerces through `str()`,
`int()`, `float()`, and `bool()`; nested scalars are ordinary Python values
with their original style and formatting retained.





