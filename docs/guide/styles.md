# Comments, styles, tags, and anchors

The previous chapters edited values. This chapter uses the same objects to
edit everything PyYAML throws away: comments, quoting, block scalar
details, collection layout, tags, and anchors. Every value in a document
carries this API directly, so there are no separate node handles to learn.

## 1. Values are the node handles

Values read out of a document are round-trip wrappers: mappings and
sequences are `dict`/`list` subclasses, and scalars are subclasses of their
own type. They expose the value's source position, every style property as
attributes, and the node's comments:

```python
import pythonizeyaml as yaml

document = yaml.load("version: '0.3.0'\nchannel: stable\n")
version = document["version"]
version.style
version.span
version.comments
```

Wrappers compare and hash like the plain values they wrap, so they work
anywhere a plain value would. A wrapper resolves its location by identity:
after insertions or removals shift siblings around, the same object still
styles the same node, and styling a value that has been removed from the
document raises `PathError`.

## 2. Comments

Comments live in three positions and survive value edits:

```python
document["channel"].comments.before = ["# Published channel"]
document["channel"].comments.inline = "# stable or beta"
document["channel"].comments.after = []  # clear comments below
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

Quoting and block styles are properties of the value:

```python
document["version"].style = "single"     # keeps '0.4.0' quoted
document["notes"].style = "literal"      # block style with |
document["notes"].chomping = "keep"      # | + keeps trailing newlines
document["notes"].block_indent_indicator = 2
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
document["artifacts"].collection_style = "flow"
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
document["base"].tag = "!custom"
document["base"].anchor = "base-values"

document.alias("override", target=document["base"])
```

The `alias()` call anchors the target if needed and makes the path an
alias (`*base-values`). The target can be the value itself, as above, or a
path (`target="base"`). Alias entries read through to their target, so
styling through an alias styles the anchor target. Removing an anchor that
still has aliases raises `AliasError` — drop the aliases first.

## 6. Document-level metadata

Directives and document markers are properties of the document. A
container-root document is also its own root value, so the styling API
applies to the whole document the same way:

```python
document.directives = ["%YAML 1.1"]
document.explicit_start = True
document.explicit_end = True
```

Assigning `directives` replaces all of them; each line must start with `%`.
The boolean markers control the leading `---` and trailing `...`.

## 7. Atomic multi-field edits

`set()` applies several fields in one validated step:

```python
document["version"].set(
    value="0.4.0",
    style="double",
    inline="# release version",
)
```

The whole set of changes is validated first; if any field is invalid the
document is restored and nothing is applied. Unknown field names raise
`TypeError`, which catches misspellings that silent assignment would let
through.

For the complete member list of `Document` and the value API, see the
[reference](../api/documents.md). The next chapter covers loading YAML
whose contents you do not trust.
