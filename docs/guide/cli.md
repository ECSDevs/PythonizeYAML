# Command line

Installing the wheel installs a small `yaml` command next to the library.
It edits a single YAML file by path from the shell — handy in scripts, CI,
or when a one-line change does not justify opening an editor:

```console
yaml <file> <get|set|del> <path> [value]
```

```console
$ yaml config.yaml get service.port
8080
$ yaml config.yaml set service.port 9090
$ yaml config.yaml get service.port
9090
```

The same engine powers the command, so everything the command does not
touch keeps its original comments, indentation, and scalar styles.

## 1. Paths

Paths are dot-separated. Each segment descends one mapping key; a segment
that is all digits addresses an item of the sequence at that point:

```console
yaml config.yaml get service.port          # mapping key
yaml config.yaml get servers.0.host        # first item of the `servers` sequence
```

A mapping key that only contains digits stays a string key: `foo.0` reads
the `"0"` key inside `foo`, never a sequence index. Keys containing dots
cannot be addressed. Every segment must be non-empty (`a..b` is rejected).

## 2. `get`

`get` prints the value at the path as YAML. Scalars print on one line
(`8080`, `true`, `hello world`); collections print as a YAML block:

```console
$ yaml config.yaml get servers.0
host: h1
port: 8080
```

A missing path exits with code 1 and names the deepest segment that could
be resolved.

## 3. `set` creates missing chains

`set` writes the value at the path, creating intermediate mappings that do
not exist yet — the whole chain, not just the leaf:

```console
$ yaml config.yaml set tls.enabled true
$ yaml config.yaml get tls
enabled: true
```

This also works on an empty file, so `yaml new.yaml set a.b 1` produces a
valid two-line document.

The value argument is interpreted as YAML, which makes typing explicit:

| Argument | Stored as |
|---|---|
| `123` | integer `123` |
| `true` / `false` | booleans |
| `1.5` | float |
| `null` | null |
| `[1, 2, 3]` | a list |
| `hello world` | the string `"hello world"` |
| `"'123'"` | the string `"123"` (shell-stripped quotes force a string) |

Wrap a value in quotes to keep text like `123` or `true` textual. Setting
into a sequence replaces an existing item (`servers.0.port 8080`); it does
not append or grow the sequence.

## 4. `del`

`del` removes the node at the path — a leaf, a whole block-valued entry,
or a sequence item:

```console
$ yaml config.yaml del service.debug
```

Deleting the last child of an entry leaves `key: {}` (or `key: []` for a
sequence) so the file keeps reading back as an empty collection rather
than null. A missing path exits with code 1 and changes nothing.

## 5. What stays byte-identical

The command loads the file with the same round-trip engine as the library
and patches only the spans it changes:

- comments, blank lines, and formatting elsewhere are preserved exactly;
- a `set` of an existing scalar rewrites just that scalar;
- a newly created chain is appended in canonical form (two-space indents
  by default) — it has no source layout to preserve.

Only single-document files are accepted; a multi-document file exits with
an error instead of silently dropping the other documents.

## 6. Exit codes

| Code | Meaning |
|---|---|
| `0` | success (`get` prints the value) |
| `1` | runtime failure: missing file, missing path, parse error, multi-document input |
| `2` | usage error: unknown command, malformed path, wrong argument count |

`yaml --help` prints the usage summary.
