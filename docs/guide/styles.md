# Comments, styles, tags, and anchors

The previous chapters edited values. This chapter uses the same objects to
edit everything PyYAML throws away: comments, quoting, block scalar
details, collection layout, tags, and anchors. All of it is reached through
`NodeRef` views, so the chapter starts there.

## 1. Node references

`Document.node()` returns a `NodeRef` — a stable view of one node:

```python
import pythonizeyaml as yaml

document = yaml.load("version: '0.3.0'\nchannel: stable\n")
version = document.node("version")
```

A `NodeRef` is not the value itself; it is a handle to a location. It
exposes the value (`version.value`), the source position
(`version.span`), every style property as attributes, and the node's
comments. Without arguments, `document.node()` is the document root.

## 2. Comments

Comments live in three positions and survive value edits:

```python
document.node("channel").comments.before = ["# Published channel"]
document.node("channel").comments.inline = "# stable or beta"
document.node("channel").comments.after = []  # clear comments below
```

```yaml
# Published channel
channel: stable  # stable or beta
```

The rules are the YAML ones: `before` and `after` accept a string or an
iterable of lines, and every non-empty line must start with `#`. `inline`
must be a single line. Loaded comments are readable through the same
properties without prior assignment.

## 3. Scalar styles

Quoting and block styles are properties of the node:

```python
document.node("version").style = "single"     # keeps '0.4.0' quoted
document.node("notes").style = "literal"      # block style with |
document.node("notes").chomping = "keep"      # | + keeps trailing newlines
document.node("notes").block_indent_indicator = 2
```

- `style` is one of `plain`, `single`, `double`, `literal`, `folded`
  (strings are coerced to the `ScalarStyle` enum).
- `chomping` is `clip`, `strip`, or `keep`, and only applies to literal and
  folded scalars.
- `block_indent_indicator` is the digit between `|` and the chomping sign,
  `1` through `9`.

Validation refuses combinations YAML cannot express — quoting a number
with `single`, chomping a plain scalar — with `StyleError`, and plain
styles that would change the resolved type (writing the string `"true"`
plain, for instance) are rejected as well.

## 4. Collection styles

Mappings and sequences switch between block and flow layout the same way:

```python
document.node("artifacts").collection_style = "flow"
```

```yaml
artifacts: [pythonizeyaml, pythonizeyaml-docs]
```

Flow style requires the content to be expressible inline; a multiline
string inside a flow collection raises `StyleError` instead of producing
invalid YAML.

## 5. Tags, anchors, and aliases

Tags and anchors are node properties; aliases are separate nodes pointing
at an anchor:

```python
document.node("base").tag = "!custom"
document.node("base").anchor = "base-values"

document.alias("override", target=document.node("base"))
```

The `alias()` call anchors the target if needed and makes the path an
alias (`*base-values`). On the alias node, `is_alias` is `True` and
`alias_target` returns the target `NodeRef`; on the target, `anchor`
returns the name. Removing an anchor that still has aliases raises
`AliasError` — drop the aliases first.

## 6. Document-level metadata

Directives and document markers are properties of the document:

```python
document.directives = ["%YAML 1.1"]
document.explicit_start = True
document.explicit_end = True
```

Assigning `directives` replaces all of them; each line must start with `%`.
The boolean markers control the leading `---` and trailing `...`.

## 7. Atomic multi-field edits

`NodeRef.update()` applies several fields in one validated step:

```python
document.node("version").update(
    value="0.4.0",
    style="double",
    inline="# release version",
)
```

The whole set of changes is validated first; if any field is invalid the
document is restored and nothing is applied. Unknown field names raise
`TypeError`, which catches misspellings that silent assignment would let
through. `update()` returns the same `NodeRef`, so calls chain.

For the complete member list of `Document`, `NodeRef`, and friends, see the
[reference](../api/documents.md). The next chapter covers loading YAML
whose contents you do not trust.
