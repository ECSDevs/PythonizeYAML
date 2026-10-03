// Copyright (c) 2026 PythonizeYAML contributors
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

use crate::error::{ErrorKind, Result, YamlError};
use crate::model::{
    Arena, Document, MappingEntry, NativeDocument, NodeId, NodeKind, Scalar, ScalarKind,
    ScalarStyle, Span,
};
use crate::number::{
    integer_to_decimal_string, resolve_number, sexagesimal_float_value, strip_numeric_separators,
    NumberKind, SchemaVersion,
};
use std::collections::HashMap;

const CORE_PREFIX: &str = "tag:yaml.org,2002:";

/// Maximum collection nesting depth, matching libyaml's default. Deeper
/// documents are rejected with a catchable error instead of overflowing the
/// stack like PyYAML's `RecursionError`.
const MAX_NESTING_DEPTH: usize = 128;

#[derive(Clone, Copy)]
struct Line {
    start: usize,
    content_end: usize,
    end: usize,
    indent: usize,
}

pub fn parse(source: &str) -> Result<NativeDocument> {
    validate_indentation(source)?;
    let lines = collect_lines(source);
    let mut parser = Parser {
        source,
        lines,
        arena: Arena::default(),
        anchors: HashMap::new(),
        // PyYAML always applies its YAML 1.1 resolvers; a `%YAML 1.2`
        // directive switches a document to the core schema.
        schema: SchemaVersion::Yaml11,
        tag_handles: Parser::default_tag_handles(),
        depth: 0,
    };
    let documents = parser.parse_stream()?;
    Ok(NativeDocument {
        text: source.to_owned(),
        arena: parser.arena,
        documents,
    })
}

fn collect_lines(source: &str) -> Vec<Line> {
    let mut lines = Vec::new();
    let mut start = 0usize;
    for chunk in source.split_inclusive('\n') {
        let end = start + chunk.len();
        let without_lf = chunk.strip_suffix('\n').unwrap_or(chunk);
        let content_end = start + without_lf.strip_suffix('\r').unwrap_or(without_lf).len();
        let content = &source[start..content_end];
        let indent = content.bytes().take_while(|byte| *byte == b' ').count();
        lines.push(Line {
            start,
            content_end,
            end,
            indent,
        });
        start = end;
    }
    if start < source.len() {
        let content = &source[start..];
        let indent = content.bytes().take_while(|byte| *byte == b' ').count();
        lines.push(Line {
            start,
            content_end: source.len(),
            end: source.len(),
            indent,
        });
    }
    // A single byte-order mark at the very start of the stream is
    // transparent to the grammar: skip it when computing the first line's
    // content, but keep the bytes in `source` so untouched round-trips
    // preserve them.
    if source.starts_with('\u{FEFF}') {
        if let Some(line) = lines.first_mut() {
            line.start += '\u{FEFF}'.len_utf8();
            let content = &source[line.start..line.content_end];
            line.indent = content.bytes().take_while(|byte| *byte == b' ').count();
        }
    }
    lines
}

struct Parser<'a> {
    source: &'a str,
    lines: Vec<Line>,
    arena: Arena,
    anchors: HashMap<String, NodeId>,
    schema: SchemaVersion,
    tag_handles: HashMap<String, String>,
    depth: usize,
}

impl<'a> Parser<'a> {
    fn default_tag_handles() -> HashMap<String, String> {
        HashMap::from([
            ("!".to_owned(), "!".to_owned()),
            ("!!".to_owned(), CORE_PREFIX.to_owned()),
        ])
    }

    /// Applies the directives collected before a document: `%TAG` registers
    /// tag handles, `%YAML` selects the schema. Directives only apply to the
    /// document they precede, so every document resets to the PyYAML default.
    fn begin_document(
        &mut self,
        pending: &[String],
        li: usize,
    ) -> Result<(SchemaVersion, HashMap<String, String>)> {
        let mut schema = SchemaVersion::Yaml11;
        let mut handles = Parser::default_tag_handles();
        for directive in pending {
            let trimmed = directive.trim();
            if let Some(rest) = trimmed.strip_prefix("%TAG") {
                let mut parts = rest.split_whitespace();
                let (Some(handle), Some(prefix), None) = (parts.next(), parts.next(), parts.next())
                else {
                    return Err(self.error(
                        ErrorKind::Scanner,
                        "a tag directive must specify exactly a handle and a prefix",
                        li,
                        0,
                    ));
                };
                if !is_tag_handle(handle) || prefix.is_empty() {
                    return Err(self.error(ErrorKind::Scanner, "invalid tag directive", li, 0));
                }
                handles.insert(handle.to_owned(), prefix.to_owned());
            } else if let Some(rest) = trimmed.strip_prefix("%YAML") {
                match rest.trim() {
                    "1.1" => schema = SchemaVersion::Yaml11,
                    "1.2" => schema = SchemaVersion::Yaml12,
                    _ => {}
                }
            }
        }
        Ok((schema, handles))
    }

    /// Column where the document's root node starts when the `---` marker
    /// line carries inline content (`--- 42`), or `None` when the line holds
    /// only the marker (plus an optional comment).
    fn marker_inline_content(&self, li: usize) -> Option<usize> {
        let content = self.content(li);
        let trimmed = content.trim_end();
        if trimmed == "---" || trimmed.starts_with("---#") {
            return None;
        }
        let mut col = 3;
        while self.byte_at(content, col) == Some(b' ') {
            col += 1;
        }
        let end = self.comment_start(content, col).unwrap_or(content.len());
        if col >= end {
            return None;
        }
        Some(col)
    }

    /// PyYAML rejects a mapping whose first key sits on the `---` line
    /// ("mapping values are not allowed here"); block sequences likewise
    /// ("sequence entries are not allowed here").
    fn reject_inline_block_collection(&self, li: usize, content_col: usize) -> Result<()> {
        let content = self.content(li);
        if content[content_col..].trim_end().starts_with('-')
            && content[content_col + 1..]
                .chars()
                .next()
                .is_some_and(char::is_whitespace)
        {
            return Err(self.error(
                ErrorKind::Scanner,
                "sequence entries are not allowed here",
                li,
                content_col,
            ));
        }
        if let Some(colon) = self.find_mapping_colon(content, content_col) {
            return Err(self.error(
                ErrorKind::Scanner,
                "mapping values are not allowed here",
                li,
                colon,
            ));
        }
        Ok(())
    }

    /// PyYAML's scanner rejects `key: value` lines that follow a root scalar
    /// at the same indentation ("mapping values are not allowed here"),
    /// because plain scalars would otherwise have folded them. A scalar that
    /// ends mid-line is also checked for a trailing `: value` (a multi-line
    /// quoted "key" is not a simple key) or other trailing junk, which a
    /// single-line scanner never sees.
    fn reject_mapping_after_scalar_root(&self, root: NodeId, next: usize) -> Result<()> {
        if matches!(self.arena.node(root).kind, NodeKind::Scalar(_)) {
            if let Some((marker_li, marker_col)) =
                self.mapping_after_scalar_root(next, self.lines.len())
            {
                return Err(self.error(
                    ErrorKind::Scanner,
                    "mapping values are not allowed here",
                    marker_li,
                    marker_col,
                ));
            }
            let span = self.arena.node(root).span;
            if span.end > span.start {
                let pos = span.end - 1;
                let last_li = self.lines.partition_point(|line| line.start <= pos) - 1;
                let line = self.lines[last_li];
                let content = self.content(last_li);
                let tail_start = span.end - line.start;
                if tail_start < content.len() {
                    let comment = self.comment_start(content, tail_start);
                    let tail_end = comment.unwrap_or(content.len());
                    if let Some(colon) = self.find_raw_colon(content, tail_start, tail_end) {
                        return Err(self.error(
                            ErrorKind::Scanner,
                            "mapping values are not allowed here",
                            last_li,
                            colon,
                        ));
                    }
                    let tail = &content[tail_start..tail_end];
                    if !tail.trim().is_empty() {
                        let junk_col = tail.len() - tail.trim_start().len();
                        return Err(self.error(
                            ErrorKind::Parser,
                            "expected '<document start>', but found '<scalar>'",
                            last_li,
                            tail_start + junk_col,
                        ));
                    }
                }
            }
        }
        Ok(())
    }

    fn mapping_after_scalar_root(&self, mut li: usize, end: usize) -> Option<(usize, usize)> {
        while li < end {
            if self.is_document_marker(li) || self.is_directive(li) {
                return None;
            }
            if self.is_trivia(li) {
                li += 1;
                continue;
            }
            let content = self.content(li);
            if self.lines[li].indent != 0 {
                return None;
            }
            return self.find_mapping_colon(content, 0).map(|colon| (li, colon));
        }
        None
    }

    /// Builds the error for content that would start a second document
    /// without a `---` marker. PyYAML reports these from two places: the
    /// scanner rejects a leftover required simple key ("could not find
    /// expected ':'") when a block collection is still open at the leftover
    /// line's column, and the parser rejects everything else ("expected
    /// '<document start>', but found ..."; "expected <block end>, but found
    /// '-'/'?'/'<block ...>'" while a collection is open).
    fn leftover_document_error(
        &self,
        li: usize,
        prev_root: Option<NodeId>,
        after_document_end: bool,
    ) -> YamlError {
        let content = self.content(li);
        let indent = self.lines[li].indent;
        let rest = content.get(indent..).unwrap_or("");
        let starts_dash =
            rest.starts_with('-') && rest[1..].chars().next().map_or(true, char::is_whitespace);
        let colon = self.find_mapping_colon(content, indent);
        let prev_kind = prev_root.map(|id| &self.arena.node(id).kind);
        let prev_is_scalar = matches!(
            prev_kind,
            Some(NodeKind::Scalar(_)) | Some(NodeKind::Alias(_)) | Some(NodeKind::Tagged { .. })
        );
        let prev_is_sequence = matches!(prev_kind, Some(NodeKind::Sequence(_)));
        let shape = if starts_dash {
            if indent == 0 {
                "'-'"
            } else {
                "'<block sequence start>'"
            }
        } else if colon == Some(indent) {
            if indent == 0 {
                "':'"
            } else {
                "'<block mapping start>'"
            }
        } else if colon.is_some() && prev_is_sequence && indent == 0 {
            "'?'"
        } else if colon.is_some() {
            "'<block mapping start>'"
        } else {
            "'<scalar>'"
        };
        if after_document_end || prev_is_scalar {
            self.error(
                ErrorKind::Parser,
                format!("expected '<document start>', but found {shape}"),
                li,
                indent,
            )
        } else if indent > 0 || starts_dash || colon.is_some() {
            // A block collection is still open; the leftover line sits inside
            // it rather than after the document.
            self.error(
                ErrorKind::Parser,
                format!("expected <block end>, but found {shape}"),
                li,
                indent,
            )
        } else {
            self.error(
                ErrorKind::Scanner,
                "could not find expected ':'",
                li,
                indent,
            )
        }
    }

    fn parse_stream(&mut self) -> Result<Vec<Document>> {
        let mut documents: Vec<Document> = Vec::new();
        let mut li = 0usize;
        let mut pending_start = 0usize;
        let mut explicit_start = false;
        let mut explicit_end = false;
        let mut pending_directives: Vec<String> = Vec::new();
        while li < self.lines.len() {
            if self.is_marker(li, "---") {
                if self.next_significant(li + 1, self.lines.len()).is_some()
                    || !documents.is_empty()
                {
                    pending_start = self.lines[li].start;
                }
                explicit_start = true;
                let (schema, handles) = self.begin_document(&pending_directives, li)?;
                self.schema = schema;
                self.tag_handles = handles;
                if let Some(content_col) = self.marker_inline_content(li) {
                    self.reject_inline_block_collection(li, content_col)?;
                    // A root scalar folds any following content line (`---
                    // 42\nmore` is the single scalar "42 more"), so the
                    // continuation threshold is 0.
                    let (root, next) =
                        self.parse_block_node(li, self.lines.len(), content_col, true, 0)?;
                    self.reject_mapping_after_scalar_root(root, next)?;
                    let end = self.nodes_span(root).end;
                    documents.push(Document {
                        root,
                        span: Span::new(pending_start.min(self.lines[li].start), end),
                        explicit_start: true,
                        explicit_end: false,
                        directives: std::mem::take(&mut pending_directives),
                    });
                    explicit_start = false;
                    li = next;
                    self.anchors.clear();
                    pending_start = self
                        .lines
                        .get(li)
                        .map_or(self.source.len(), |line| line.start);
                    continue;
                }
                li += 1;
                continue;
            }
            if self.is_marker(li, "...") {
                if let Some(document) = documents.last_mut() {
                    document.explicit_end = true;
                }
                explicit_end = true;
                li += 1;
                continue;
            }
            if self.is_directive(li) {
                pending_directives.push(self.content(li).trim().to_owned());
                li += 1;
                continue;
            }
            if self.is_trivia(li) {
                li += 1;
                continue;
            }
            if explicit_start {
                // The document began at the preceding `---` marker, where the
                // directives were already applied.
            } else {
                if !pending_directives.is_empty() {
                    return Err(self.error(
                        ErrorKind::Parser,
                        "expected '<document start>' after directives",
                        li,
                        0,
                    ));
                }
                if !documents.is_empty() {
                    // A second document can only begin after `---` (or a
                    // directive run followed by `---`): any leftover content
                    // line is an error, like PyYAML's "expected '<document
                    // start>'" / "could not find expected ':'".
                    let prev_root = documents.last().map(|document| document.root);
                    return Err(self.leftover_document_error(li, prev_root, explicit_end));
                }
                self.schema = SchemaVersion::Yaml11;
                self.tag_handles = Parser::default_tag_handles();
            }
            let start = pending_start.min(self.lines[li].start);
            let indent = self.lines[li].indent;
            if indent != 0 {
                return Err(self.error(
                    ErrorKind::Parser,
                    "top-level content must not be indented",
                    li,
                    indent,
                ));
            }
            let (root, next) = self.parse_block_node(li, self.lines.len(), indent, false, 0)?;
            self.reject_mapping_after_scalar_root(root, next)?;
            let end = self.nodes_span(root).end;
            documents.push(Document {
                root,
                span: Span::new(start, end),
                explicit_start,
                explicit_end,
                directives: std::mem::take(&mut pending_directives),
            });
            explicit_start = false;
            explicit_end = false;
            li = next;
            self.anchors.clear();
            pending_start = self
                .lines
                .get(li)
                .map_or(self.source.len(), |line| line.start);
        }
        Ok(documents)
    }

    /// `cont` is the plain-scalar continuation threshold: lines whose indent
    /// is at least `cont` fold into a plain scalar parsed at this level. It
    /// equals the enclosing block's indent + 1, and 0 at the document root,
    /// where PyYAML folds any following content line into a root scalar.
    fn parse_block_node(
        &mut self,
        li: usize,
        end: usize,
        indent: usize,
        inline_root: bool,
        cont: usize,
    ) -> Result<(NodeId, usize)> {
        self.depth += 1;
        if self.depth > MAX_NESTING_DEPTH {
            self.depth -= 1;
            return Err(self.error(
                ErrorKind::Parser,
                "maximum nesting depth exceeded",
                li,
                indent,
            ));
        }
        let result = self.parse_block_node_inner(li, end, indent, inline_root, cont);
        self.depth -= 1;
        result
    }

    fn parse_block_node_inner(
        &mut self,
        li: usize,
        end: usize,
        indent: usize,
        inline_root: bool,
        cont: usize,
    ) -> Result<(NodeId, usize)> {
        if li >= end {
            return Err(self.error(ErrorKind::Parser, "expected a node", li, 0));
        }
        let content = self.content(li);
        let rest = content.get(indent..).unwrap_or("").to_owned();
        if rest.starts_with('!') || rest.starts_with('&') {
            let (node, next) = self.parse_inline_node(
                li,
                indent,
                self.inline_content_end(li, indent),
                Some(cont),
            )?;
            if self.is_property_only_null(node) {
                if let Some(next_line) = self.next_significant(next, end) {
                    let next_indent = self.lines[next_line].indent;
                    let next_content = self.content(next_line);
                    let next_is_dash = next_content.get(next_indent..).is_some_and(|rest| {
                        rest.starts_with('-')
                            && rest[1..].chars().next().map_or(true, char::is_whitespace)
                    });
                    // An inline document root (`--- &anchor`) continues on
                    // the following lines at any indentation.
                    let eligible = inline_root
                        || next_indent >= indent
                        || (next_indent == indent
                            && self.find_mapping_colon(next_content, next_indent).is_some())
                        || (next_indent == indent && next_is_dash);
                    if eligible {
                        let (child, child_next) =
                            self.parse_block_node(next_line, end, next_indent, false, cont)?;
                        self.transfer_properties(node, child);
                        return Ok((child, child_next));
                    }
                }
            }
            return Ok((node, next));
        }
        if rest.starts_with('-') && rest[1..].chars().next().map_or(true, char::is_whitespace) {
            return self.parse_block_sequence(li, end, indent);
        }
        if rest.starts_with('?') && rest[1..].chars().next().map_or(true, char::is_whitespace) {
            // Some(indent) lets the first line sit at the outer collection's
            // indentation for compact items (`- ? k`).
            return self.parse_block_mapping(li, end, indent, Some(indent));
        }
        if self.find_mapping_colon(content, indent).is_some() {
            return self.parse_block_mapping(li, end, indent, None);
        }
        self.parse_inline_node(li, indent, self.inline_content_end(li, indent), Some(cont))
    }

    fn parse_block_mapping(
        &mut self,
        mut li: usize,
        end: usize,
        indent: usize,
        first_col: Option<usize>,
    ) -> Result<(NodeId, usize)> {
        // `first_col` is a column on line `li` (the compact-item callers pass
        // one), so it must become a global offset here; using it raw made the
        // mapping's span start at a bogus small offset for any item whose line
        // was not the first line of the document.
        let map_start = self.col_global(li, first_col.unwrap_or(indent));
        let mut entries = Vec::new();
        while li < end {
            if self.is_trivia(li) {
                li += 1;
                continue;
            }
            let content = self.content(li);
            if self.is_document_marker(li)
                || ((first_col.is_none() || !entries.is_empty()) && self.lines[li].indent < indent)
            {
                break;
            }
            let active_col = if entries.is_empty() {
                first_col.unwrap_or(indent)
            } else {
                indent
            };
            if (first_col.is_none() || !entries.is_empty()) && self.lines[li].indent != active_col {
                break;
            }
            let rest = content.get(active_col..).unwrap_or("");
            // `? key` / `? key\n: value` explicit entries. The `:` value line
            // must sit at the `?`'s indentation; a deeper one is an error in
            // PyYAML, which falls out of the entry loop as a dedent below.
            if rest.starts_with('?') && rest[1..].chars().next().map_or(true, char::is_whitespace) {
                let (key, value, next) =
                    self.parse_explicit_key_entry(li, end, indent, active_col)?;
                entries.push(MappingEntry {
                    key_span: self.nodes_span(key),
                    key,
                    value,
                    value_span: self.nodes_span(value),
                    entry_span: Span::new(self.lines[li].start + active_col, self.lines[li].end),
                });
                li = next;
                continue;
            }
            let Some(colon) = self.find_mapping_colon(content, active_col) else {
                break;
            };
            if colon == active_col {
                break;
            }
            let key_start = self.col_global(li, active_col);
            let key_end = self.col_global(li, colon);
            let (key, key_next) = self.parse_inline_node(li, active_col, colon, None)?;
            if key_next != li + 1 {
                return Err(self.error(
                    ErrorKind::Parser,
                    "mapping keys cannot span lines",
                    li,
                    active_col,
                ));
            }
            let mut value_col = colon + 1;
            while self
                .byte_at(content, value_col)
                .is_some_and(|ch| ch == b' ')
            {
                value_col += 1;
            }
            let content_end = self.inline_content_end(li, value_col);
            if value_col < content_end && self.find_mapping_colon(content, value_col).is_some() {
                return Err(self.error(
                    ErrorKind::Parser,
                    "mapping values are not allowed inside another value",
                    li,
                    value_col,
                ));
            }
            let (mut value, mut next) = if value_col < content_end {
                self.parse_inline_node(li, value_col, content_end, Some(indent + 1))?
            } else {
                self.parse_block_value_on_following_lines(li, colon + 1, end, indent)?
            };
            if self.is_property_only_null(value) {
                if let Some((child, child_next)) =
                    self.parse_property_continuation(value, next, end, indent)?
                {
                    value = child;
                    next = child_next;
                }
            }
            entries.push(MappingEntry {
                key,
                value,
                key_span: Span::new(key_start, key_end),
                value_span: self.nodes_span(value),
                entry_span: Span::new(self.lines[li].start + active_col, self.lines[li].end),
            });
            li = next;
        }
        if entries.is_empty() {
            return Err(self.error(
                ErrorKind::Parser,
                format!(
                    "expected a mapping entry at line {} indent {} first_col {:?}",
                    li + 1,
                    indent,
                    first_col
                ),
                li,
                indent,
            ));
        }
        let start = map_start;
        let end_pos = entries
            .last()
            .map(|entry| self.nodes_span(entry.value).end)
            .unwrap_or(start);
        let id = self.arena.add(
            NodeKind::Mapping(entries),
            Span::new(start, end_pos),
            Span::new(start, end_pos),
            None,
            None,
        );
        Ok((id, li))
    }

    /// Parses one `? key` explicit-key entry starting at `active_col` on line
    /// `li`, returning `(key, value, next_line)`. The key may sit inline after
    /// `? ` (folding across lines like any plain scalar), or on the following
    /// more-indented lines when `?` stands alone. The value comes from a `: `
    /// line at the same indentation, or is null when there is none.
    fn parse_explicit_key_entry(
        &mut self,
        li: usize,
        end: usize,
        indent: usize,
        active_col: usize,
    ) -> Result<(NodeId, NodeId, usize)> {
        let content = self.content(li);
        let mut key_col = active_col + 1;
        while self.byte_at(content, key_col).is_some_and(|ch| ch == b' ') {
            key_col += 1;
        }
        let key_end_col = self.inline_content_end(li, key_col);
        let question_mark = Span::new(
            self.col_global(li, active_col),
            self.col_global(li, active_col + 1),
        );
        let (key, mut next) = if key_col < key_end_col {
            // The key itself may span lines (`? multi\n  line key\n: v`).
            self.parse_inline_node(li, key_col, key_end_col, Some(indent + 1))?
        } else if let Some(next_line) = self.next_significant(li + 1, end) {
            let next_indent = self.lines[next_line].indent;
            if next_indent > indent {
                self.parse_block_node(next_line, end, next_indent, false, indent + 1)?
            } else {
                (self.null_node(question_mark), li + 1)
            }
        } else {
            (self.null_node(question_mark), li + 1)
        };
        // The value must come from a `: ` line at the `?`'s indentation.
        let (value, next) = match self.next_significant(next, end) {
            Some(vli) if !self.is_document_marker(vli) && self.lines[vli].indent == indent => {
                let vcontent = self.content(vli);
                let vrest = vcontent.get(indent..).unwrap_or("");
                let is_value_line = vrest.starts_with(':')
                    && vrest[1..].chars().next().map_or(true, char::is_whitespace);
                if is_value_line {
                    let mut value_col = indent + 1;
                    while self
                        .byte_at(vcontent, value_col)
                        .is_some_and(|ch| ch == b' ')
                    {
                        value_col += 1;
                    }
                    let vcontent_end = self.inline_content_end(vli, value_col);
                    if value_col < vcontent_end {
                        let (value, after) =
                            self.parse_inline_node(vli, value_col, vcontent_end, Some(indent + 1))?;
                        (value, after)
                    } else {
                        let (value, after) =
                            self.parse_block_value_on_following_lines(vli, value_col, end, indent)?;
                        (value, after)
                    }
                } else {
                    (self.null_node(question_mark), next)
                }
            }
            _ => (self.null_node(question_mark), next),
        };
        Ok((key, value, next))
    }

    /// Parses the value of `key:` / `:` when nothing follows the colon on the
    /// same line: a block node on the following more-indented lines (or a
    /// same-indent block sequence), else a null value at the colon.
    fn parse_block_value_on_following_lines(
        &mut self,
        li: usize,
        colon: usize,
        end: usize,
        indent: usize,
    ) -> Result<(NodeId, usize)> {
        let next_significant = self.next_significant(li + 1, end);
        if let Some(next_line) = next_significant {
            let next_indent = self.lines[next_line].indent;
            let next_content = self.content(next_line);
            let next_is_marker = self.is_document_marker(next_line);
            let next_is_dash = next_content.get(next_indent..).is_some_and(|rest| {
                rest.starts_with('-') && rest[1..].chars().next().map_or(true, char::is_whitespace)
            });
            if !next_is_marker && (next_indent > indent || (next_indent == indent && next_is_dash))
            {
                self.parse_block_node(next_line, end, next_indent, false, indent + 1)
            } else {
                let mark = Span::new(
                    self.col_global(li, colon + 1),
                    self.col_global(li, colon + 1),
                );
                Ok((self.null_node(mark), li + 1))
            }
        } else {
            let mark = Span::new(
                self.col_global(li, colon + 1),
                self.col_global(li, colon + 1),
            );
            Ok((self.null_node(mark), li + 1))
        }
    }

    /// Continues a property-only node (`&anchor` / `!tag` with no content)
    /// with the block node on the following eligible lines.
    fn parse_property_continuation(
        &mut self,
        value: NodeId,
        next: usize,
        end: usize,
        indent: usize,
    ) -> Result<Option<(NodeId, usize)>> {
        if let Some(next_line) = self.next_significant(next, end) {
            let next_indent = self.lines[next_line].indent;
            let next_content = self.content(next_line);
            let next_is_dash = next_content.get(next_indent..).is_some_and(|rest| {
                rest.starts_with('-') && rest[1..].chars().next().map_or(true, char::is_whitespace)
            });
            if next_indent > indent || (next_indent == indent && next_is_dash) {
                let (child, child_next) =
                    self.parse_block_node(next_line, end, next_indent, false, indent + 1)?;
                self.transfer_properties(value, child);
                return Ok(Some((child, child_next)));
            }
        }
        Ok(None)
    }

    fn parse_block_sequence(
        &mut self,
        mut li: usize,
        end: usize,
        indent: usize,
    ) -> Result<(NodeId, usize)> {
        let start = self.lines[li].start + indent;
        let mut items = Vec::new();
        // The first line may sit at the *outer* collection's indentation when
        // the sequence is compact-nested (`- - a`): only its dash column
        // matters there. Later lines must sit exactly at `indent`.
        let mut first = true;
        while li < end {
            if self.is_trivia(li) {
                li += 1;
                continue;
            }
            if self.is_document_marker(li) || (!first && self.lines[li].indent != indent) {
                break;
            }
            first = false;
            let content = self.content(li);
            if !content
                .get(indent..)
                .is_some_and(|rest| rest.starts_with('-'))
            {
                break;
            }
            let after_dash = indent + 1;
            if self
                .byte_at(content, after_dash)
                .is_some_and(|ch| ch != b' ')
            {
                break;
            }
            let mut item_col = after_dash;
            while self.byte_at(content, item_col).is_some_and(|ch| ch == b' ') {
                item_col += 1;
            }
            let item_end = self.inline_content_end(li, item_col);
            let item_rest = content.get(item_col..).unwrap_or("");
            let (item, next) = if item_col >= item_end {
                if let Some(next_line) = self.next_significant(li + 1, end) {
                    if self.lines[next_line].indent > indent {
                        self.parse_block_node(
                            next_line,
                            end,
                            self.lines[next_line].indent,
                            false,
                            indent + 1,
                        )?
                    } else {
                        let mark = Span::new(
                            self.col_global(li, after_dash),
                            self.col_global(li, after_dash),
                        );
                        (self.null_node(mark), li + 1)
                    }
                } else {
                    let mark = Span::new(
                        self.col_global(li, after_dash),
                        self.col_global(li, after_dash),
                    );
                    (self.null_node(mark), li + 1)
                }
            } else if (item_rest.starts_with('-')
                && item_rest[1..]
                    .chars()
                    .next()
                    .map_or(true, char::is_whitespace))
                || (item_rest.starts_with('?')
                    && item_rest[1..]
                        .chars()
                        .next()
                        .map_or(true, char::is_whitespace))
            {
                // Compact nested collection: `- - a` or `- ? k`. Routed through
                // `parse_block_node` so the nesting-depth counter applies.
                self.parse_block_node(li, end, item_col, false, indent + 1)?
            } else if self.find_mapping_colon(content, item_col).is_some() {
                self.parse_block_mapping(li, end, item_col, Some(item_col))?
            } else {
                self.parse_inline_node(li, item_col, item_end, Some(indent + 1))?
            };
            items.push(item);
            li = next;
        }
        let end_pos = items
            .last()
            .map(|id| self.nodes_span(*id).end)
            .unwrap_or(start);
        let id = self.arena.add(
            NodeKind::Sequence(items),
            Span::new(start, end_pos),
            Span::new(start, end_pos),
            None,
            None,
        );
        Ok((id, li))
    }

    /// `cont` enables plain-scalar continuation across lines: `Some(threshold)`
    /// folds following lines whose indent is at least `threshold` into a plain
    /// scalar. Implicit mapping keys pass `None` — they cannot span lines.
    fn parse_inline_node(
        &mut self,
        li: usize,
        start_col: usize,
        end_col: usize,
        cont: Option<usize>,
    ) -> Result<(NodeId, usize)> {
        let content = self.content(li);
        let mut col = start_col;
        while self.byte_at(content, col).is_some_and(|ch| ch == b' ') {
            col += 1;
        }
        let mut tag: Option<String> = None;
        let mut anchor: Option<String> = None;
        loop {
            if col >= end_col {
                let mark = Span::new(self.col_global(li, col), self.col_global(li, col));
                let id = self.null_node(mark);
                self.attach_properties(id, tag, anchor);
                return Ok((id, li + 1));
            }
            if self.byte_at(content, col) == Some(b'&') {
                let (name, next) = self.read_property_word(content, col + 1, end_col);
                anchor = Some(name);
                col = next;
                while self.byte_at(content, col).is_some_and(|ch| ch == b' ') {
                    col += 1;
                }
                continue;
            }
            if self.byte_at(content, col) == Some(b'!') {
                let (raw_tag, next) = self.read_tag(content, col, end_col, li)?;
                let expanded = self.expand_tag(&raw_tag).map_err(|handle| {
                    self.error(
                        ErrorKind::Parser,
                        format!("found undefined tag handle '{handle}'"),
                        li,
                        col,
                    )
                })?;
                tag = Some(expanded);
                col = next;
                while self.byte_at(content, col).is_some_and(|ch| ch == b' ') {
                    col += 1;
                }
                continue;
            }
            break;
        }
        if col >= end_col {
            let mark = Span::new(self.col_global(li, col), self.col_global(li, col));
            let id = self.null_node(mark);
            self.attach_properties(id, tag, anchor);
            return Ok((id, li + 1));
        }
        if self.byte_at(content, col) == Some(b'*') {
            let (name, _) = self.read_property_word(content, col + 1, end_col);
            let Some(target) = self.anchors.get(&name).copied() else {
                return Err(self.error(
                    ErrorKind::Composer,
                    format!("undefined alias '*{name}'"),
                    li,
                    col,
                ));
            };
            let span = Span::new(self.col_global(li, col), self.col_global(li, end_col));
            let id = self
                .arena
                .add(NodeKind::Alias(target), span, span, tag, anchor);
            return Ok((id, li + 1));
        }
        if matches!(self.byte_at(content, col), Some(b'|') | Some(b'>')) {
            let id = self.parse_block_scalar(li, col, end_col)?;
            self.attach_properties(id, tag, anchor);
            let next = self.block_scalar_next_line(li, col);
            return Ok((id, next));
        }
        if matches!(self.byte_at(content, col), Some(b'[') | Some(b'{')) {
            let consumed = self.parse_flow_node(col, end_col, li)?;
            let next_line = consumed.next_line;
            let id = self.finish_flow_node(consumed, tag.clone(), anchor.clone())?;
            self.attach_properties(id, tag, anchor);
            return Ok((id, next_line));
        }
        if matches!(self.byte_at(content, col), Some(b'\'') | Some(b'"')) {
            let (value, style, end_li, end_col) = self.parse_quoted_multiline(li, col)?;
            let span = Span::new(self.col_global(li, col), self.col_global(end_li, end_col));
            let scalar = Scalar {
                kind: ScalarKind::Str,
                raw: self.source[span.range()].to_owned(),
                value,
                style,
                chomping: None,
            };
            let id = self.arena.add(
                NodeKind::Scalar(scalar),
                span,
                span,
                tag.clone(),
                anchor.clone(),
            );
            self.attach_properties(id, tag, anchor);
            return Ok((id, end_li + 1));
        }

        let raw = self.source[self.col_global(li, col)..self.col_global(li, end_col)].to_owned();
        let trimmed = raw.trim_end();
        let mut span = Span::new(
            self.col_global(li, col),
            self.col_global(li, col + trimmed.len()),
        );
        let mut text = trimmed.to_owned();
        let mut next = li + 1;
        if let Some(threshold) = cont {
            // A plain scalar folds the following lines only when its own line
            // ran to the end of the content: a trailing comment ends it, like
            // PyYAML's scanner stopping at the comment token.
            if end_col >= content.len() {
                let (folded, span_end, next_line) =
                    self.fold_plain_continuation(li, threshold, trimmed, span.end)?;
                text = folded;
                span.end = span_end;
                next = next_line;
            }
        }
        if trimmed.starts_with(['@', '\u{0060}']) {
            return Err(self.error(
                ErrorKind::Parser,
                "reserved character cannot start a plain scalar",
                li,
                col,
            ));
        }
        let scalar = self.classify_scalar(&text, ScalarStyle::Plain, tag.as_deref(), li, col)?;
        let id = self.arena.add(
            NodeKind::Scalar(scalar),
            span,
            span,
            tag.clone(),
            anchor.clone(),
        );
        self.attach_properties(id, tag, anchor);
        Ok((id, next))
    }

    /// Folds plain-scalar continuation lines after line `li`, whose own text
    /// (`first_text`, ending at `first_span_end`) is already collected. Lines
    /// at an indent below `threshold` end the scalar, as do comment lines,
    /// document markers, and EOF; blank lines fold to that many newlines; a
    /// single break folds to a space. A `: ` on a continuation line is a
    /// mapping-value indicator where a simple key cannot start, matching
    /// PyYAML's "mapping values are not allowed here". Returns the folded
    /// text, the end of the scalar's source span, and the next line index.
    fn fold_plain_continuation(
        &self,
        li: usize,
        threshold: usize,
        first_text: &str,
        first_span_end: usize,
    ) -> Result<(String, usize, usize)> {
        let mut value = first_text.to_owned();
        let mut span_end = first_span_end;
        let mut next = li + 1;
        loop {
            let mut blanks = 0usize;
            while next < self.lines.len() && self.content(next).trim().is_empty() {
                blanks += 1;
                next += 1;
            }
            if next >= self.lines.len() || self.is_document_marker(next) {
                break;
            }
            let line_content = self.content(next);
            if line_content.trim_start().starts_with('#') {
                break;
            }
            let line_indent = self.lines[next].indent;
            if line_indent < threshold {
                break;
            }
            let text_end = self.inline_content_end(next, line_indent);
            let had_comment = text_end < line_content.len();
            if let Some(colon) = self.find_raw_colon(line_content, line_indent, text_end) {
                if colon == line_indent {
                    // A ':' starting a continuation line is a zero-length
                    // chunk in PyYAML: the scalar simply ends here and the
                    // misplaced value indicator is reported by the enclosing
                    // block loop (or the leftover guard).
                    break;
                }
                return Err(self.error(
                    ErrorKind::Scanner,
                    "mapping values are not allowed here",
                    next,
                    colon,
                ));
            }
            let text = line_content[line_indent..text_end].trim_end();
            if !text.is_empty() {
                if blanks == 0 {
                    value.push(' ');
                } else {
                    for _ in 0..blanks {
                        value.push('\n');
                    }
                }
                value.push_str(text);
                span_end = self.col_global(next, line_indent + text.len());
            }
            next += 1;
            // A comment ends the scalar right after the line it trails.
            if had_comment {
                break;
            }
        }
        Ok((value, span_end, next))
    }

    /// Finds a `:` followed by whitespace or the end of the region — a
    /// mapping-value indicator — scanning raw bytes like PyYAML's plain
    /// scalar scanner, which has no notion of quoting mid-scalar.
    fn find_raw_colon(&self, content: &str, start: usize, end: usize) -> Option<usize> {
        let bytes = content.as_bytes();
        let mut pos = start;
        while pos < end {
            if bytes[pos] == b':' {
                let follower = bytes.get(pos + 1).copied();
                if pos + 1 >= end || follower == Some(b' ') || follower == Some(b'\t') {
                    return Some(pos);
                }
            }
            pos += 1;
        }
        None
    }

    fn parse_flow_node(
        &mut self,
        start_col: usize,
        end_col: usize,
        line_index: usize,
    ) -> Result<FlowNode> {
        let start = self.col_global(line_index, start_col);
        let first_limit = self.col_global(line_index, end_col);
        let mut flow = FlowParser {
            parser: self,
            pos: start,
            line_index,
            first_line: line_index,
            first_limit,
        };
        let mut node = flow.parse_node()?;
        if flow.pos < flow.limit() && !flow.source()[flow.pos..flow.limit()].trim().is_empty() {
            return Err(flow.error("unexpected content after flow value"));
        }
        node.span.end = flow.pos;
        node.value_span.end = flow.pos;
        Ok(node)
    }

    fn finish_flow_node(
        &mut self,
        flow: FlowNode,
        tag: Option<String>,
        anchor: Option<String>,
    ) -> Result<NodeId> {
        let kind = match flow.kind {
            FlowKind::Node(id) => return Ok(id),
            FlowKind::Scalar(scalar) => NodeKind::Scalar(scalar),
            FlowKind::Sequence(items) => NodeKind::Sequence(items),
            FlowKind::Mapping(entries) => NodeKind::Mapping(entries),
            FlowKind::Alias(target) => NodeKind::Alias(target),
        };
        let id = self.arena.add(
            kind,
            flow.span,
            flow.value_span,
            tag.clone(),
            anchor.clone(),
        );
        self.attach_properties(id, tag, anchor);
        Ok(id)
    }

    /// Scans a single- or double-quoted scalar starting at `start_col` on line
    /// `li`, folding across lines like PyYAML's `scan_flow_scalar`: real
    /// trailing whitespace before a break is dropped, a single break folds to
    /// a space, each further blank line folds to a newline, and a backslash at
    /// the end of a double-quoted line escapes the break (no space, no
    /// newline). Everything up to the closing quote — `#` included — is
    /// content, so the scan uses the full line length rather than the
    /// comment-trimmed end. Returns the decoded value, the style, and the
    /// closing position.
    fn parse_quoted_multiline(
        &self,
        li: usize,
        start_col: usize,
    ) -> Result<(String, ScalarStyle, usize, usize)> {
        let quote = self.byte_at(self.content(li), start_col).unwrap();
        let mut value = String::new();
        // Number of trailing value characters appended as real (non-escaped)
        // whitespace: those are dropped before a line break folds. Escaped
        // whitespace survives, like PyYAML's escape chunks.
        let mut real_trailing = 0usize;
        let mut escaped_break = false;
        let mut li = li;
        let mut pos = start_col + 1;
        loop {
            let content = self.content(li);
            while pos < content.len() {
                let byte = self.byte_at(content, pos).unwrap();
                if byte == quote {
                    if quote == b'\'' && self.byte_at(content, pos + 1) == Some(b'\'') {
                        value.push('\'');
                        pos += 2;
                        real_trailing = 0;
                        continue;
                    }
                    return Ok((
                        value,
                        if quote == b'\'' {
                            ScalarStyle::SingleQuoted
                        } else {
                            ScalarStyle::DoubleQuoted
                        },
                        li,
                        pos + 1,
                    ));
                }
                if quote == b'"' && byte == b'\\' {
                    if pos + 1 == content.len() {
                        // A backslash as the last character of the line is an
                        // escaped line break.
                        escaped_break = true;
                        break;
                    }
                    let escaped = self.decode_escape(content, pos, content.len(), li)?;
                    value.push(escaped.0);
                    pos = escaped.1;
                    real_trailing = 0;
                    continue;
                }
                let ch = content[pos..].chars().next().unwrap();
                value.push(ch);
                pos += ch.len_utf8();
                if ch == ' ' || ch == '\t' {
                    real_trailing += 1;
                } else {
                    real_trailing = 0;
                }
            }
            // The line ended without the closing quote: fold the next one.
            let mut next = li + 1;
            let mut blanks = 0usize;
            while next < self.lines.len() && self.content(next).trim().is_empty() {
                blanks += 1;
                next += 1;
            }
            if next >= self.lines.len() {
                return Err(self.error(
                    ErrorKind::Scanner,
                    "found unexpected end of stream",
                    li,
                    pos,
                ));
            }
            if self.is_document_marker(next) {
                return Err(self.error(
                    ErrorKind::Scanner,
                    "found unexpected document separator",
                    li,
                    pos,
                ));
            }
            if escaped_break {
                // The escaped break itself contributes nothing; each further
                // blank line contributes one newline.
                escaped_break = false;
                for _ in 0..blanks {
                    value.push('\n');
                }
            } else {
                for _ in 0..real_trailing {
                    value.pop();
                }
                real_trailing = 0;
                if blanks == 0 {
                    value.push(' ');
                } else {
                    for _ in 0..blanks {
                        value.push('\n');
                    }
                }
            }
            let next_content = self.content(next);
            pos = next_content
                .bytes()
                .take_while(|byte| matches!(byte, b' ' | b'\t'))
                .count();
            li = next;
        }
    }

    /// Decodes the escape sequence whose backslash sits at `slash`. Every
    /// failure is a catchable error: the previous `Ok(None)` results made the
    /// caller re-enter its loop without advancing (an infinite loop on
    /// invalid escapes), and the hex digits are collected byte-by-byte so a
    /// multi-byte UTF-8 character can never be sliced mid-character.
    fn decode_escape(
        &self,
        content: &str,
        slash: usize,
        end_col: usize,
        li: usize,
    ) -> Result<(char, usize)> {
        let next = slash + 1;
        if next >= end_col {
            return Err(self.error(
                ErrorKind::Scanner,
                "found unexpected end of a quoted scalar",
                li,
                slash,
            ));
        }
        let code = self.byte_at(content, next).unwrap();
        let simple = match code {
            b'0' => Some('\0'),
            b'a' => Some('\x07'),
            b'b' => Some('\x08'),
            b't' | b'\t' => Some('\t'),
            b'n' => Some('\n'),
            b'v' => Some('\x0b'),
            b'f' => Some('\x0c'),
            b'r' => Some('\r'),
            b'e' => Some('\x1b'),
            b' ' => Some(' '),
            b'"' => Some('"'),
            b'/' => Some('/'),
            b'\\' => Some('\\'),
            b'N' => Some('\u{0085}'),
            b'_' => Some('\u{00A0}'),
            b'L' => Some('\u{2028}'),
            b'P' => Some('\u{2029}'),
            _ => None,
        };
        if let Some(ch) = simple {
            return Ok((ch, next + 1));
        }
        let width = match code {
            b'x' => 2,
            b'u' => 4,
            b'U' => 8,
            _ => {
                return Err(self.error(
                    ErrorKind::Scanner,
                    format!("found unknown escape character '{}'", code as char),
                    li,
                    next,
                ));
            }
        };
        let mut value = 0u32;
        let mut pos = next + 1;
        for _ in 0..width {
            let Some(byte) = self.byte_at(content, pos) else {
                return Err(self.error(
                    ErrorKind::Scanner,
                    format!("expected escape sequence of {width} hexadecimal numbers"),
                    li,
                    pos,
                ));
            };
            let Some(digit) = (byte as char).to_digit(16) else {
                return Err(self.error(
                    ErrorKind::Scanner,
                    format!("expected escape sequence of {width} hexadecimal numbers"),
                    li,
                    pos,
                ));
            };
            value = value * 16 + digit;
            pos += 1;
        }
        let ch = char::from_u32(value)
            .ok_or_else(|| self.error(ErrorKind::Scanner, "invalid Unicode escape", li, slash))?;
        Ok((ch, pos))
    }

    fn parse_block_scalar(&mut self, li: usize, col: usize, end_col: usize) -> Result<NodeId> {
        let content = self.content(li);
        let marker = self.byte_at(content, col).unwrap();
        let mut modifier_end = col + 1;
        while modifier_end < end_col {
            let ch = self.byte_at(content, modifier_end).unwrap();
            if ch == b'+' || ch == b'-' || ch.is_ascii_digit() {
                modifier_end += 1;
            } else {
                break;
            }
        }
        let modifiers = &content[col + 1..modifier_end];
        let chomping = modifiers.chars().find(|ch| *ch == '+' || *ch == '-');
        let increment = modifiers
            .chars()
            .find_map(|ch| ch.to_digit(10).map(|digit| digit as usize));
        let parent_indent = self.lines[li].indent;
        // Blank lines belong to the scalar body; the indentation comes from
        // the first non-empty line (a comment line included) unless the
        // header carries an explicit indentation indicator.
        let first_content = (li + 1..self.lines.len())
            .find(|&candidate| !self.content(candidate).trim().is_empty());
        let block_indent = match increment {
            Some(digit) => parent_indent + digit,
            None => first_content.map_or(parent_indent + 1, |line| {
                self.lines[line].indent.max(parent_indent + 1)
            }),
        };
        let mut body_end_line = li + 1;
        while body_end_line < self.lines.len() {
            if self.is_document_marker(body_end_line) {
                break;
            }
            let line_content = self.content(body_end_line);
            if !line_content.trim().is_empty() && self.lines[body_end_line].indent < block_indent {
                break;
            }
            body_end_line += 1;
        }
        let body_start = self
            .lines
            .get(li + 1)
            .map_or(self.lines[li].end, |line| line.start);
        let body_end = self
            .lines
            .get(body_end_line.saturating_sub(1))
            .map_or(body_start, |line| line.content_end);
        let mut parts = Vec::new();
        for body_line in li + 1..body_end_line {
            let line_content = self.content(body_line);
            // Blank (or whitespace-only) lines shorter than the block indent
            // are line breaks; anything at least `block_indent` wide keeps
            // its text minus the block indentation.
            let text = if line_content.len() >= block_indent {
                line_content[block_indent..].to_owned()
            } else {
                String::new()
            };
            parts.push(text);
        }
        // Trailing blank lines are governed by the chomping indicator, not
        // by the join, and a body without any content line stays empty.
        let trailing_blanks = parts
            .iter()
            .rev()
            .take_while(|part| part.is_empty())
            .count();
        let had_content = parts.len() > trailing_blanks;
        let parts = &parts[..parts.len() - trailing_blanks];
        let mut value = if marker == b'|' {
            parts.join("\n")
        } else {
            fold_lines(parts)
        };
        match chomping {
            Some('-') => {
                while value.ends_with('\n') {
                    value.pop();
                }
            }
            Some('+') => {
                if had_content {
                    value.push('\n');
                }
                for _ in 0..trailing_blanks {
                    value.push('\n');
                }
            }
            _ => {
                while value.ends_with('\n') {
                    value.pop();
                }
                if had_content {
                    value.push('\n');
                }
            }
        }
        let span = Span::new(self.col_global(li, col), body_end);
        let scalar = Scalar {
            kind: ScalarKind::Str,
            raw: self.source[span.range()].to_owned(),
            value,
            style: if marker == b'|' {
                ScalarStyle::Literal
            } else {
                ScalarStyle::Folded
            },
            chomping,
        };
        let id = self
            .arena
            .add(NodeKind::Scalar(scalar), span, span, None, None);
        Ok(id)
    }

    fn block_scalar_next_line(&self, li: usize, col: usize) -> usize {
        let content = self.content(li);
        let end_col = self.inline_content_end(li, col);
        let _ = content;
        let _ = end_col;
        let mut next = li + 1;
        while next < self.lines.len() {
            let line = self.content(next);
            if !line.trim().is_empty() && self.lines[next].indent <= self.lines[li].indent {
                break;
            }
            next += 1;
        }
        next
    }

    fn classify_scalar(
        &self,
        raw: &str,
        style: ScalarStyle,
        tag: Option<&str>,
        li: usize,
        col: usize,
    ) -> Result<Scalar> {
        let explicit = tag.and_then(|tag| tag.strip_prefix(CORE_PREFIX));
        let (kind, value) = match explicit {
            Some("str") => (ScalarKind::Str, raw.to_owned()),
            Some("null") => (ScalarKind::Null, String::new()),
            Some("bool") => {
                // PyYAML's explicit !!bool accepts the boolean words in any
                // case and refuses everything else.
                let lower = raw.to_ascii_lowercase();
                match lower.as_str() {
                    "true" | "yes" | "on" => (ScalarKind::Bool(true), lower),
                    "false" | "no" | "off" => (ScalarKind::Bool(false), lower),
                    _ => {
                        return Err(self.error(
                            ErrorKind::Constructor,
                            format!("could not resolve !!bool value '{raw}'"),
                            li,
                            col,
                        ));
                    }
                }
            }
            Some("int") => (
                ScalarKind::Int,
                integer_to_decimal_string(raw, self.schema).unwrap_or_else(|| raw.to_owned()),
            ),
            Some("float") => (ScalarKind::Float, normalize_float_text(raw)),
            Some("decimal") => (ScalarKind::Decimal, strip_numeric_separators(raw)),
            Some("binary") => (ScalarKind::Binary, raw.to_owned()),
            Some("timestamp") => (ScalarKind::Timestamp, raw.to_owned()),
            _ if style != ScalarStyle::Plain => (ScalarKind::Str, raw.to_owned()),
            _ => self.resolve_plain(raw),
        };
        Ok(Scalar {
            kind,
            raw: raw.to_owned(),
            value,
            style,
            chomping: None,
        })
    }

    fn resolve_plain(&self, raw: &str) -> (ScalarKind, String) {
        // PyYAML applies YAML 1.1 resolvers by default; `%YAML 1.2` switches
        // a document to the core schema. Matching is case-exact like the
        // PyYAML resolver regexes.
        if matches!(raw, "" | "~" | "null" | "Null" | "NULL") {
            return (ScalarKind::Null, String::new());
        }
        let (true_values, false_values): (&[&str], &[&str]) =
            if self.schema == SchemaVersion::Yaml11 {
                (
                    &[
                        "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON",
                    ],
                    &[
                        "false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF",
                    ],
                )
            } else {
                (&["true", "True", "TRUE"], &["false", "False", "FALSE"])
            };
        if true_values.contains(&raw) {
            return (ScalarKind::Bool(true), raw.to_ascii_lowercase());
        }
        if false_values.contains(&raw) {
            return (ScalarKind::Bool(false), raw.to_ascii_lowercase());
        }
        if parse_timestamp(raw).is_some() {
            return (ScalarKind::Timestamp, raw.to_owned());
        }
        if matches!(
            raw,
            ".inf"
                | ".Inf"
                | ".INF"
                | "+.inf"
                | "+.Inf"
                | "+.INF"
                | "-.inf"
                | "-.Inf"
                | "-.INF"
                | ".nan"
                | ".NaN"
                | ".NAN"
        ) {
            return (ScalarKind::Float, normalize_float_text(raw));
        }
        match resolve_number(raw, self.schema) {
            Some(NumberKind::Integer) => (
                ScalarKind::Int,
                integer_to_decimal_string(raw, self.schema).unwrap_or_else(|| raw.to_owned()),
            ),
            Some(NumberKind::Float) => (ScalarKind::Float, normalize_float_text(raw)),
            Some(NumberKind::Decimal) => (ScalarKind::Decimal, strip_numeric_separators(raw)),
            None => (ScalarKind::Str, raw.to_owned()),
        }
    }

    fn null_node(&mut self, span: Span) -> NodeId {
        let scalar = Scalar {
            kind: ScalarKind::Null,
            raw: String::new(),
            value: String::new(),
            style: ScalarStyle::Plain,
            chomping: None,
        };
        self.arena
            .add(NodeKind::Scalar(scalar), span, span, None, None)
    }

    fn attach_properties(&mut self, id: NodeId, tag: Option<String>, anchor: Option<String>) {
        if let Some(tag) = tag {
            self.arena.node_mut(id).tag = Some(tag);
        }
        if let Some(anchor) = anchor {
            self.arena.node_mut(id).anchor = Some(anchor.clone());
            self.anchors.insert(anchor, id);
        }
    }

    fn is_property_only_null(&self, id: NodeId) -> bool {
        let node = self.arena.node(id);
        matches!(
            node.kind,
            NodeKind::Scalar(Scalar {
                kind: ScalarKind::Null,
                ..
            })
        ) && (node.tag.is_some() || node.anchor.is_some())
    }

    fn transfer_properties(&mut self, source: NodeId, target: NodeId) {
        let source = self.arena.node(source).clone();
        self.arena.node_mut(target).tag = source.tag;
        self.arena.node_mut(target).anchor = source.anchor.clone();
        if let Some(anchor) = source.anchor {
            self.anchors.insert(anchor, target);
            // Aliases created while `source` was still the property-only
            // placeholder captured the placeholder's id, so a self-referential
            // structure like `a: &x\n  b: *x` materialized the placeholder
            // (None) instead of the anchored node. Re-point those alias edges
            // at the node the anchor ended up on.
            for node in self.arena.nodes.iter_mut() {
                if let NodeKind::Alias(alias_target) = &mut node.kind {
                    if *alias_target == source.id {
                        *alias_target = target;
                    }
                }
            }
        }
    }
    fn nodes_span(&self, id: NodeId) -> Span {
        self.arena.node(id).span
    }

    fn content(&self, li: usize) -> &'a str {
        let line = self.lines[li];
        &self.source[line.start..line.content_end]
    }

    fn inline_content_end(&self, li: usize, start_col: usize) -> usize {
        let content = self.content(li);
        self.comment_start(content, start_col)
            .unwrap_or(content.len())
    }

    fn comment_start(&self, content: &str, start_col: usize) -> Option<usize> {
        let bytes = content.as_bytes();
        let mut quote = None;
        let mut depth = 0i32;
        let mut pos = start_col;
        while pos < bytes.len() {
            let ch = bytes[pos];
            if let Some(active) = quote {
                if ch == b'\\' && active == b'"' {
                    pos += 2;
                    continue;
                }
                if ch == active {
                    quote = None;
                }
                pos += 1;
                continue;
            }
            match ch {
                b'\'' | b'"' => quote = Some(ch),
                b'[' | b'{' => depth += 1,
                b']' | b'}' => depth -= 1,
                b'#' if depth == 0 && (pos == 0 || bytes[pos - 1].is_ascii_whitespace()) => {
                    return Some(pos)
                }
                _ => {}
            }
            pos += 1;
        }
        None
    }

    fn find_mapping_colon(&self, content: &str, start_col: usize) -> Option<usize> {
        let limit = self
            .comment_start(content, start_col)
            .unwrap_or(content.len());
        let bytes = content.as_bytes();
        let mut quote = None;
        let mut depth = 0i32;
        let mut pos = start_col;
        while pos < limit {
            let ch = bytes[pos];
            if let Some(active) = quote {
                if ch == b'\\' && active == b'"' {
                    pos += 2;
                    continue;
                }
                if ch == active {
                    quote = None;
                }
                pos += 1;
                continue;
            }
            match ch {
                b'\'' | b'"' => quote = Some(ch),
                b'[' | b'{' => depth += 1,
                b']' | b'}' => depth -= 1,
                b':' if depth == 0
                    && (pos + 1 == limit || bytes[pos + 1].is_ascii_whitespace()) =>
                {
                    return Some(pos)
                }
                _ => {}
            }
            pos += 1;
        }
        None
    }

    fn read_property_word(&self, content: &str, start: usize, end: usize) -> (String, usize) {
        let mut pos = start;
        while pos < end
            && !self
                .byte_at(content, pos)
                .is_some_and(|ch| ch.is_ascii_whitespace() || matches!(ch, b',' | b']' | b'}'))
        {
            pos += 1;
        }
        (content[start..pos].to_owned(), pos)
    }

    fn read_tag(
        &self,
        content: &str,
        start: usize,
        end: usize,
        li: usize,
    ) -> Result<(String, usize)> {
        if content[start..].starts_with("!<") {
            let Some(relative_end) = content[start + 2..end].find('>') else {
                return Err(self.error(ErrorKind::Scanner, "unterminated verbatim tag", li, start));
            };
            let tag_end = start + 2 + relative_end;
            return Ok((content[start + 2..tag_end].to_owned(), tag_end + 1));
        }
        let (word, next) = self.read_property_word(content, start, end);
        if word.is_empty() {
            return Err(self.error(ErrorKind::Scanner, "invalid tag", li, start));
        }
        Ok((word, next))
    }

    /// Expands shorthand tags using the document's `%TAG` handles. Named
    /// handles (`!e!name`) must have a directive; the default `!!` handle
    /// maps to the YAML core prefix and a bare `!suffix` stays a local tag
    /// unless the primary handle was redefined. Returns the unexpanded
    /// handle when it is undefined.
    fn expand_tag(&self, tag: &str) -> std::result::Result<String, String> {
        if !tag.starts_with('!') {
            // Verbatim tags arrive with their `!<...>` wrapper stripped.
            return Ok(tag.to_owned());
        }
        if tag == "!" {
            return Ok("!".to_owned());
        }
        if let Some(offset) = tag[1..].find('!') {
            let handle = &tag[..offset + 2];
            let suffix = &tag[offset + 2..];
            let prefix = if handle == "!!" {
                CORE_PREFIX.to_owned()
            } else if let Some(prefix) = self.tag_handles.get(handle) {
                prefix.clone()
            } else {
                return Err(handle.to_owned());
            };
            return Ok(format!("{prefix}{suffix}"));
        }
        let prefix = self
            .tag_handles
            .get("!")
            .cloned()
            .unwrap_or_else(|| "!".to_owned());
        Ok(format!("{prefix}{}", &tag[1..]))
    }

    fn col_global(&self, li: usize, col: usize) -> usize {
        self.lines[li].start + col
    }

    fn byte_at(&self, content: &str, col: usize) -> Option<u8> {
        content.as_bytes().get(col).copied()
    }

    fn is_trivia(&self, li: usize) -> bool {
        // Directive lines are handled in `parse_stream`'s between-documents
        // region; treating them as trivia would silently swallow `%TAG`
        // directives inside document content.
        let content = self.content(li);
        let trimmed = content.trim();
        trimmed.is_empty() || trimmed.starts_with('#')
    }

    fn is_directive(&self, li: usize) -> bool {
        self.content(li).trim_start().starts_with('%')
    }

    fn is_marker(&self, li: usize, marker: &str) -> bool {
        let content = self.content(li);
        if self.lines[li].indent != 0 {
            return false;
        }
        let trimmed = content.trim_end();
        if !trimmed.starts_with(marker) {
            return false;
        }
        matches!(
            trimmed.as_bytes().get(marker.len()),
            None | Some(b' ') | Some(b'#')
        )
    }

    fn is_document_marker(&self, li: usize) -> bool {
        self.is_marker(li, "---") || self.is_marker(li, "...")
    }

    fn next_significant(&self, mut li: usize, end: usize) -> Option<usize> {
        while li < end {
            if !self.is_trivia(li) && !self.is_directive(li) && !self.is_document_marker(li) {
                return Some(li);
            }
            li += 1;
        }
        None
    }

    fn error(
        &self,
        kind: ErrorKind,
        problem: impl Into<String>,
        li: usize,
        col: usize,
    ) -> YamlError {
        let line = self.lines.get(li);
        let mark = line.map_or(Span::new(0, 0), |line| {
            Span::new(line.start + col, line.start + col + 1)
        });
        YamlError::new(kind, problem, mark)
    }
}

fn normalize_float_text(raw: &str) -> String {
    let lower = raw.to_ascii_lowercase();
    if lower == ".inf" || lower == "+.inf" {
        return "inf".to_owned();
    }
    if lower == "-.inf" {
        return "-inf".to_owned();
    }
    if lower == ".nan" {
        return "nan".to_owned();
    }
    // PyYAML folds sexagesimal floats (`1:30.5` -> `90.5`).
    if let Some(value) = sexagesimal_float_value(raw) {
        return format!("{value}");
    }
    strip_numeric_separators(raw)
}

/// Components of a YAML 1.1 timestamp scalar.
#[derive(Debug, PartialEq, Eq)]
pub struct TimestampParts {
    pub year: u16,
    pub month: u8,
    pub day: u8,
    pub time: Option<TimestampTimeParts>,
}

/// Time-of-day components with an optional fixed UTC offset.
#[derive(Debug, PartialEq, Eq)]
pub struct TimestampTimeParts {
    pub hour: u8,
    pub minute: u8,
    pub second: u8,
    pub microsecond: u32,
    pub tz_offset_seconds: Option<i32>,
}

/// Matches PyYAML's `SafeConstructor.timestamp_regexp`. Timestamps are parsed
/// here instead of via `datetime.fromisoformat` so construction stays
/// version-independent: `fromisoformat` only learned the `Z` suffix and
/// 1-6 digit fractions in Python 3.11.
pub fn parse_timestamp(text: &str) -> Option<TimestampParts> {
    let bytes = text.as_bytes();
    let (year, mut pos) = digits_exact(bytes, 0, 4)?;
    if bytes.get(pos) != Some(&b'-') {
        return None;
    }
    pos += 1;
    let (month, pos) = digits_1_2(bytes, pos, b'-', false)?;
    // The day length is ambiguous while the time part stays optional, so try
    // the greedy two-digit match first and backtrack like the regexp does.
    for day_len in [2usize, 1] {
        let Some((day, after_day)) = digits_exact(bytes, pos, day_len) else {
            continue;
        };
        let time = if after_day == bytes.len() {
            None
        } else {
            match parse_timestamp_time(bytes, after_day) {
                Some(time) => Some(time),
                None => continue,
            }
        };
        return Some(TimestampParts {
            year: year as u16,
            month: month as u8,
            day: day as u8,
            time,
        });
    }
    None
}

/// Parses the `[Tt|whitespace]HH:MM:SS[.fraction][Z|±offset]` remainder,
/// which must run to the end of the scalar.
fn parse_timestamp_time(bytes: &[u8], pos: usize) -> Option<TimestampTimeParts> {
    let pos = match bytes.get(pos) {
        Some(b'T') | Some(b't') => pos + 1,
        Some(b' ') | Some(b'\t') => {
            let mut next = pos + 1;
            while matches!(bytes.get(next), Some(b' ') | Some(b'\t')) {
                next += 1;
            }
            next
        }
        _ => return None,
    };
    let (hour, pos) = digits_1_2(bytes, pos, b':', false)?;
    let (minute, pos) = digits_exact(bytes, pos, 2)?;
    if bytes.get(pos) != Some(&b':') {
        return None;
    }
    let (second, pos) = digits_exact(bytes, pos + 1, 2)?;
    let (microsecond, pos) = match bytes.get(pos) {
        Some(b'.') => {
            let start = pos + 1;
            let mut end = start;
            while bytes.get(end).is_some_and(|byte| byte.is_ascii_digit()) {
                end += 1;
            }
            // PyYAML keeps the first six fraction digits and right-pads.
            let used = (end - start).min(6);
            let mut microsecond = 0u32;
            for offset in start..start + used {
                microsecond = microsecond * 10 + u32::from(bytes[offset] - b'0');
            }
            for _ in used..6 {
                microsecond *= 10;
            }
            (microsecond, end)
        }
        _ => (0, pos),
    };
    // The optional offset may be preceded by whitespace and must end the
    // scalar, so bare trailing whitespace never matches.
    let tz_offset_seconds = if pos == bytes.len() {
        None
    } else {
        let mut cursor = pos;
        while matches!(bytes.get(cursor), Some(b' ') | Some(b'\t')) {
            cursor += 1;
        }
        let offset = match bytes.get(cursor) {
            Some(b'Z') => {
                cursor += 1;
                Some(0i32)
            }
            Some(b'+') | Some(b'-') => {
                let sign: i32 = if bytes[cursor] == b'-' { -1 } else { 1 };
                let (hour, after_hour) = digits_1_2(bytes, cursor + 1, b':', true)?;
                // A remaining `:MM` was consumed by the hour match, so the
                // minute digits are mandatory whenever input is left.
                let (minute, after_minute) = if after_hour < bytes.len() {
                    digits_exact(bytes, after_hour, 2)?
                } else {
                    (0, after_hour)
                };
                cursor = after_minute;
                Some(sign * (hour as i32 * 3600 + minute as i32 * 60))
            }
            _ => return None,
        };
        if cursor != bytes.len() {
            return None;
        }
        offset
    };
    Some(TimestampTimeParts {
        hour: hour as u8,
        minute: minute as u8,
        second: second as u8,
        microsecond,
        tz_offset_seconds,
    })
}

/// Reads exactly `count` ASCII digits, returning the value and new position.
fn digits_exact(bytes: &[u8], pos: usize, count: usize) -> Option<(u32, usize)> {
    let mut value = 0u32;
    for offset in 0..count {
        let byte = *bytes.get(pos + offset)?;
        if !byte.is_ascii_digit() {
            return None;
        }
        value = value * 10 + u32::from(byte - b'0');
    }
    Some((value, pos + count))
}

/// Matches `[0-9][0-9]?`, trying two digits first and retrying with one until
/// the match is followed by `follower` (or the end of input when `allow_end`).
/// The delimiter is consumed as part of the match.
fn digits_1_2(bytes: &[u8], pos: usize, follower: u8, allow_end: bool) -> Option<(u32, usize)> {
    for count in [2usize, 1] {
        let Some((value, next)) = digits_exact(bytes, pos, count) else {
            continue;
        };
        match bytes.get(next) {
            Some(&byte) if byte == follower => return Some((value, next + 1)),
            None if allow_end => return Some((value, next)),
            _ => {}
        }
    }
    None
}
/// Folds a folded (`>`) block scalar body following PyYAML: only lines at
/// exactly the block indent join with a space; more-indented lines (which
/// keep their extra spaces after dedenting) and blank lines emit newlines.
fn fold_lines(parts: &[String]) -> String {
    let mut out = String::new();
    let mut index = 0usize;
    // Leading blank lines are part of the value.
    while index < parts.len() && parts[index].is_empty() {
        out.push('\n');
        index += 1;
    }
    let mut previous_more_indented = false;
    let mut pending_blanks = 0usize;
    let mut have_content = false;
    while index < parts.len() {
        let part = &parts[index];
        if part.is_empty() {
            pending_blanks += 1;
            index += 1;
            continue;
        }
        let more_indented = part.starts_with(' ') || part.starts_with('\t');
        if have_content {
            if pending_blanks > 0 {
                for _ in 0..pending_blanks {
                    out.push('\n');
                }
            } else if !previous_more_indented && !more_indented {
                out.push(' ');
            } else {
                out.push('\n');
            }
        }
        pending_blanks = 0;
        out.push_str(part);
        have_content = true;
        previous_more_indented = more_indented;
        index += 1;
    }
    out
}

struct FlowNode {
    kind: FlowKind,
    span: Span,
    value_span: Span,
    next_line: usize,
}

enum FlowKind {
    Scalar(Scalar),
    Sequence(Vec<NodeId>),
    Mapping(Vec<MappingEntry>),
    Alias(NodeId),
    /// A node already added to the arena (used for anchored flow nodes so
    /// the anchor name stays attached to the node itself).
    Node(NodeId),
}

struct FlowParser<'p, 'a> {
    parser: &'p mut Parser<'a>,
    pos: usize,
    line_index: usize,
    /// The caller comment-trims the first line from the node's start column;
    /// continuation lines are trimmed from the line start.
    first_line: usize,
    first_limit: usize,
}

impl<'p, 'a> FlowParser<'p, 'a> {
    fn source(&self) -> &'a str {
        self.parser.source
    }

    /// The flow scan may extend to `pos` on the current line: content up to a
    /// trailing comment. Each line the parser crosses gets its own limit.
    fn limit(&self) -> usize {
        if self.line_index == self.first_line {
            return self.first_limit;
        }
        let line = &self.parser.lines[self.line_index];
        let content = &self.parser.source[line.start..line.content_end];
        line.start
            + self
                .parser
                .comment_start(content, 0)
                .unwrap_or(content.len())
    }

    /// Moves to the next significant line, skipping blank and comment-only
    /// lines. Document markers stop the scan: like PyYAML's parser, which
    /// fails on a document indicator inside a flow collection. Returns false
    /// at the end of the stream, where the enclosing parser reports the
    /// unbalanced-bracket error.
    fn advance_line(&mut self) -> bool {
        let mut next = self.line_index + 1;
        while next < self.parser.lines.len() {
            let content = self.parser.content(next);
            if content.trim().is_empty() || content.trim_start().starts_with('#') {
                next += 1;
                continue;
            }
            break;
        }
        if next >= self.parser.lines.len() || self.parser.is_document_marker(next) {
            return false;
        }
        self.line_index = next;
        true
    }

    /// Skips whitespace, line breaks, and comments: crossing the end of a
    /// line moves to the next significant line inside the flow.
    fn skip_space(&mut self) {
        loop {
            while self.pos < self.limit() {
                let ch = self.source()[self.pos..].chars().next().unwrap();
                if ch.is_whitespace() {
                    self.pos += ch.len_utf8();
                } else {
                    break;
                }
            }
            if self.pos < self.limit() {
                return;
            }
            if !self.advance_line() {
                return;
            }
            self.pos = self.parser.lines[self.line_index].start;
        }
    }

    fn parse_node(&mut self) -> Result<FlowNode> {
        self.parser.depth += 1;
        if self.parser.depth > MAX_NESTING_DEPTH {
            let error = self.error("maximum nesting depth exceeded");
            self.parser.depth -= 1;
            return Err(error);
        }
        let result = self.parse_node_inner();
        self.parser.depth -= 1;
        result
    }

    fn parse_node_inner(&mut self) -> Result<FlowNode> {
        self.skip_space();
        if self.pos >= self.limit() {
            return Err(self.error("expected a flow node"));
        }
        let mut tag = None;
        let mut anchor = None;
        while self.pos < self.limit() && matches!(self.byte(), Some(b'!') | Some(b'&')) {
            if self.byte() == Some(b'&') {
                let start = self.pos + 1;
                while self.pos < self.limit() && !self.is_property_end() {
                    self.pos += 1;
                }
                anchor = Some(self.source()[start..self.pos].to_owned());
            } else {
                let start = self.pos;
                if self.source()[self.pos..self.limit()].starts_with("!<") {
                    let Some(end) = self.source()[self.pos + 2..self.limit()].find('>') else {
                        return Err(self.error("unterminated verbatim tag"));
                    };
                    self.pos += end + 3;
                    tag = Some(self.source()[start + 2..self.pos - 1].to_owned());
                } else {
                    while self.pos < self.limit() && !self.is_property_end() {
                        self.pos += 1;
                    }
                    let raw_tag = self.source()[start..self.pos].to_owned();
                    let expanded = self.parser.expand_tag(&raw_tag).map_err(|handle| {
                        self.error(format!("found undefined tag handle '{handle}'"))
                    })?;
                    tag = Some(expanded);
                }
            }
            self.skip_space();
        }
        let start = self.pos;
        let mut node = match self.byte() {
            Some(b'[') => self.parse_sequence()?,
            Some(b'{') => self.parse_mapping()?,
            Some(b'\'') | Some(b'"') => self.parse_quoted()?,
            Some(b'*') => self.parse_alias()?,
            _ => self.parse_plain()?,
        };
        node.span.start = start;
        node.value_span.start = start;
        if let FlowKind::Scalar(scalar) = &mut node.kind {
            if let Some(tag) = &tag {
                scalar.kind = match tag.strip_prefix(CORE_PREFIX) {
                    Some("str") => ScalarKind::Str,
                    Some("int") => ScalarKind::Int,
                    Some("float") => ScalarKind::Float,
                    Some("decimal") => ScalarKind::Decimal,
                    _ => scalar.kind.clone(),
                };
            }
        }
        if let Some(anchor_name) = anchor {
            // Keep the anchor on the node itself so it can be re-emitted,
            // mirroring how block-context properties are attached.
            let span = node.span;
            let id = self.materialize_flow(node, tag, Some(anchor_name.clone()))?;
            self.parser.anchors.insert(anchor_name, id);
            return Ok(FlowNode {
                kind: FlowKind::Node(id),
                span,
                value_span: span,
                next_line: self.line_index + 1,
            });
        }
        Ok(node)
    }
    fn parse_sequence(&mut self) -> Result<FlowNode> {
        let start = self.pos;
        self.pos += 1;
        let mut items = Vec::new();
        loop {
            self.skip_space();
            if self.byte() == Some(b']') {
                self.pos += 1;
                break;
            }
            if self.pos >= self.limit() {
                return Err(self.error("expected ']'"));
            }
            items.push(self.parse_node()?);
            self.skip_space();
            match self.byte() {
                Some(b',') => {
                    self.pos += 1;
                }
                Some(b']') => {
                    self.pos += 1;
                    break;
                }
                _ => return Err(self.error("expected ',' or ']'")),
            }
        }
        let mut ids = Vec::with_capacity(items.len());
        for item in items {
            let kind = match item.kind {
                FlowKind::Node(id) => {
                    ids.push(id);
                    continue;
                }
                FlowKind::Scalar(scalar) => NodeKind::Scalar(scalar),
                FlowKind::Sequence(items) => NodeKind::Sequence(items),
                FlowKind::Mapping(entries) => NodeKind::Mapping(entries),
                FlowKind::Alias(target) => NodeKind::Alias(target),
            };
            ids.push(
                self.parser
                    .arena
                    .add(kind, item.span, item.value_span, None, None),
            );
        }
        Ok(FlowNode {
            kind: FlowKind::Sequence(ids),
            span: Span::new(start, self.pos),
            value_span: Span::new(start, self.pos),
            next_line: self.line_index + 1,
        })
    }

    fn parse_mapping(&mut self) -> Result<FlowNode> {
        let start = self.pos;
        self.pos += 1;
        let mut entries = Vec::new();
        loop {
            self.skip_space();
            if self.byte() == Some(b'}') {
                self.pos += 1;
                break;
            }
            if self.pos >= self.limit() {
                return Err(self.error("expected '}'"));
            }
            let key_start_line = self.line_index;
            let key_flow = self.parse_node()?;
            let key = self.flow_to_id(key_flow)?;
            self.skip_space();
            // A simple key cannot span lines: PyYAML's scanner drops the saved
            // key candidate once the token is fetched on a later line, so the
            // `:` must sit on the line the key started on.
            if self.line_index != key_start_line {
                return Err(self.error("expected ',' or '}'"));
            }
            if self.byte() != Some(b':') {
                return Err(self.error("expected ':' in flow mapping"));
            }
            let key_span = self.parser.arena.node(key).span;
            self.pos += 1;
            self.skip_space();
            let value_flow = self.parse_node()?;
            let value = self.flow_to_id(value_flow)?;
            let value_span = self.parser.arena.node(value).span;
            entries.push(MappingEntry {
                key,
                value,
                key_span,
                value_span,
                entry_span: Span::new(key_span.start, value_span.end),
            });
            self.skip_space();
            match self.byte() {
                Some(b',') => {
                    self.pos += 1;
                }
                Some(b'}') => {
                    self.pos += 1;
                    break;
                }
                _ => return Err(self.error("expected ',' or '}'")),
            }
        }
        Ok(FlowNode {
            kind: FlowKind::Mapping(entries),
            span: Span::new(start, self.pos),
            value_span: Span::new(start, self.pos),
            next_line: self.line_index + 1,
        })
    }

    fn flow_to_id(&mut self, flow: FlowNode) -> Result<NodeId> {
        self.materialize_flow(flow, None, None)
    }

    fn materialize_flow(
        &mut self,
        flow: FlowNode,
        tag: Option<String>,
        anchor: Option<String>,
    ) -> Result<NodeId> {
        let kind = match flow.kind {
            FlowKind::Node(id) => return Ok(id),
            FlowKind::Scalar(scalar) => NodeKind::Scalar(scalar),
            FlowKind::Sequence(items) => NodeKind::Sequence(items),
            FlowKind::Mapping(entries) => NodeKind::Mapping(entries),
            FlowKind::Alias(target) => NodeKind::Alias(target),
        };
        Ok(self
            .parser
            .arena
            .add(kind, flow.span, flow.value_span, tag, anchor))
    }

    /// Delegates to the shared multi-line quoted scanner: folding and escape
    /// rules are identical in flow context, and `#` inside the quotes is
    /// content.
    fn parse_quoted(&mut self) -> Result<FlowNode> {
        let start = self.pos;
        let start_li = self.line_index;
        let start_col = start - self.parser.lines[start_li].start;
        let (value, style, end_li, end_col) =
            self.parser.parse_quoted_multiline(start_li, start_col)?;
        self.line_index = end_li;
        self.pos = self.parser.col_global(end_li, end_col);
        let span = Span::new(start, self.pos);
        Ok(FlowNode {
            kind: FlowKind::Scalar(Scalar {
                kind: ScalarKind::Str,
                raw: self.source()[span.range()].to_owned(),
                value,
                style,
                chomping: None,
            }),
            span,
            value_span: span,
            next_line: self.line_index + 1,
        })
    }

    fn parse_alias(&mut self) -> Result<FlowNode> {
        let start = self.pos;
        self.pos += 1;
        let name_start = self.pos;
        while self.pos < self.limit() && !self.is_property_end() {
            self.pos += 1;
        }
        let name = &self.source()[name_start..self.pos];
        let Some(target) = self.parser.anchors.get(name).copied() else {
            return Err(self.error(format!("undefined alias '*{name}'")));
        };
        let span = Span::new(start, self.pos);
        Ok(FlowNode {
            kind: FlowKind::Alias(target),
            span,
            value_span: span,
            next_line: self.line_index + 1,
        })
    }

    /// Scans a flow plain scalar, folding continuation lines like PyYAML's
    /// `scan_plain` in flow context: a break folds to a space, blank lines
    /// fold to that many newlines, and the scalar ends when the next
    /// significant line begins with a flow indicator, a comment, or nothing
    /// at all (pending separators are then discarded, like PyYAML's).
    fn parse_plain(&mut self) -> Result<FlowNode> {
        let start = self.pos;
        let mut value = String::new();
        let mut span_end = start;
        let mut seg_start = self.pos;
        loop {
            let mut stopped_at_indicator = false;
            while self.pos < self.limit() {
                let ch = self.source()[self.pos..].chars().next().unwrap();
                if matches!(ch, ',' | ']' | '}') {
                    stopped_at_indicator = true;
                    break;
                }
                if ch == ':' {
                    // A colon only ends a flow plain scalar when a space, a flow
                    // indicator, or the end of the node follows, so values like
                    // `09:00` and `http://x` stay intact.
                    let follower = self.source().as_bytes().get(self.pos + 1).copied();
                    if follower.is_none()
                        || follower.is_some_and(|byte| byte.is_ascii_whitespace())
                        || matches!(follower, Some(b',' | b'[' | b']' | b'{' | b'}'))
                    {
                        stopped_at_indicator = true;
                        break;
                    }
                }
                self.pos += ch.len_utf8();
            }
            let trimmed = self.source()[seg_start..self.pos].trim_end();
            if !trimmed.is_empty() {
                value.push_str(trimmed);
                span_end = seg_start + trimmed.len();
            }
            if stopped_at_indicator {
                break;
            }
            // The line ran out: fold the next significant line or end here.
            let mut next = self.line_index + 1;
            let mut blanks = 0usize;
            while next < self.parser.lines.len() && self.parser.content(next).trim().is_empty() {
                blanks += 1;
                next += 1;
            }
            if next >= self.parser.lines.len() || self.parser.is_document_marker(next) {
                break;
            }
            let next_content = self.parser.content(next);
            if next_content.trim_start().starts_with('#') {
                break;
            }
            let leading = next_content
                .bytes()
                .take_while(|byte| matches!(byte, b' ' | b'\t'))
                .count();
            let ends_here = match next_content.as_bytes().get(leading).copied() {
                Some(b',') | Some(b']') | Some(b'}') | Some(b'?') => true,
                Some(b':') => next_content.as_bytes().get(leading + 1).is_none_or(|byte| {
                    byte.is_ascii_whitespace() || matches!(byte, b',' | b'[' | b']' | b'{' | b'}')
                }),
                _ => false,
            };
            if ends_here {
                break;
            }
            if blanks == 0 {
                value.push(' ');
            } else {
                for _ in 0..blanks {
                    value.push('\n');
                }
            }
            self.line_index = next;
            self.pos = self.parser.lines[next].start + leading;
            seg_start = self.pos;
        }
        let scalar = self.parser.classify_scalar(
            &value,
            ScalarStyle::Plain,
            None,
            self.line_index,
            start.saturating_sub(self.parser.lines[self.line_index].start),
        )?;
        Ok(FlowNode {
            kind: FlowKind::Scalar(scalar),
            span: Span::new(start, span_end),
            value_span: Span::new(start, span_end),
            next_line: self.line_index + 1,
        })
    }

    fn byte(&self) -> Option<u8> {
        self.source().as_bytes().get(self.pos).copied()
    }

    fn is_property_end(&self) -> bool {
        matches!(
            self.byte(),
            Some(b'[') | Some(b'{') | Some(b',') | Some(b']') | Some(b'}') | Some(b':')
        ) || self.byte().is_some_and(|ch| ch.is_ascii_whitespace())
    }

    fn error(&self, message: impl Into<String>) -> YamlError {
        YamlError::new(
            ErrorKind::Parser,
            message,
            Span::new(self.pos, self.pos.saturating_add(1)),
        )
    }
}

fn validate_indentation(source: &str) -> Result<()> {
    let mut offset = 0usize;
    for raw in source.split_inclusive('\n') {
        let content = raw.strip_suffix('\n').unwrap_or(raw);
        let spaces = content.bytes().take_while(|byte| *byte == b' ').count();
        if content.as_bytes().get(spaces) == Some(&b'\t') {
            return Err(YamlError::new(
                ErrorKind::Scanner,
                "tab characters must not be used in indentation",
                Span::new(offset + spaces, offset + spaces + 1),
            ));
        }
        offset += raw.len();
    }
    Ok(())
}

/// A `%TAG` handle: `!`, `!!`, or `!name!`.
fn is_tag_handle(handle: &str) -> bool {
    if handle == "!" {
        return true;
    }
    handle.len() >= 2 && handle.starts_with('!') && handle.ends_with('!')
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Returns the parsed document plus the root node.
    fn parse_root(source: &str) -> (NativeDocument, NodeId) {
        let document = parse(source).unwrap();
        let root = document.documents[0].root;
        (document, root)
    }

    /// Root scalar `(kind, value)` for plain-scalar resolution assertions.
    fn root_scalar(source: &str) -> (ScalarKind, String) {
        let (document, root) = parse_root(source);
        match &document.arena.node(root).kind {
            NodeKind::Scalar(scalar) => (scalar.kind.clone(), scalar.value.clone()),
            other => panic!("expected a scalar root, got {other:?}"),
        }
    }

    fn root_mapping_value(source: &str, key: &str) -> NodeId {
        let (document, root) = parse_root(source);
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected a mapping root");
        };
        entries
            .iter()
            .find(|entry| {
                matches!(&document.arena.node(entry.key).kind,
                NodeKind::Scalar(scalar) if scalar.value == key)
            })
            .map(|entry| entry.value)
            .unwrap_or_else(|| panic!("missing key {key}"))
    }

    /// The document plus the value node of the mapping entry `key`.
    fn root_mapping_entry(source: &str, key: &str) -> (NativeDocument, NodeId) {
        let (document, root) = parse_root(source);
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected a mapping root");
        };
        let value = entries
            .iter()
            .find(|entry| {
                matches!(&document.arena.node(entry.key).kind,
                NodeKind::Scalar(scalar) if scalar.value == key)
            })
            .map(|entry| entry.value)
            .unwrap_or_else(|| panic!("missing key {key}"));
        (document, value)
    }

    fn scalar_value(document: &NativeDocument, id: NodeId) -> String {
        match &document.arena.node(id).kind {
            NodeKind::Scalar(scalar) => scalar.value.clone(),
            other => panic!("expected a scalar, got {other:?}"),
        }
    }

    #[test]
    fn aliases_are_resolved_in_flow_collections() {
        let document = parse("items: [&x {k: 1}, *x]\n").unwrap();
        let root_id = document.documents[0].root;
        let NodeKind::Mapping(entries) = &document.arena.node(root_id).kind else {
            panic!("expected mapping");
        };
        let NodeKind::Sequence(items) = &document.arena.node(entries[0].value).kind else {
            panic!("expected sequence");
        };
        let NodeKind::Alias(target) = document.arena.node(items[1]).kind else {
            panic!("expected alias");
        };
        fn resolve(document: &NativeDocument, mut id: NodeId) -> NodeId {
            loop {
                match &document.arena.node(id).kind {
                    NodeKind::Alias(inner) => id = *inner,
                    _ => return id,
                }
            }
        }
        assert_eq!(resolve(&document, items[0]), target);
    }

    #[test]
    fn indentation_tabs_report_scanner_errors() {
        let error = parse("name: x\n\tnested: y\n").unwrap_err();
        assert_eq!(error.kind, ErrorKind::Scanner);
    }

    #[test]
    fn original_text_is_retained_for_lossless_round_trips() {
        let source = "# comment\nvalue: '1'\n";
        let document = parse(source).unwrap();
        assert_eq!(document.text, source);
    }

    #[test]
    fn timestamps_follow_the_pyyaml_grammar() {
        fn parts(
            hour: u8,
            microsecond: u32,
            tz_offset_seconds: Option<i32>,
        ) -> Option<TimestampParts> {
            Some(TimestampParts {
                year: 2001,
                month: 12,
                day: 15,
                time: Some(TimestampTimeParts {
                    hour,
                    minute: 59,
                    second: 43,
                    microsecond,
                    tz_offset_seconds,
                }),
            })
        }
        assert_eq!(
            parse_timestamp("2001-12-15T02:59:43Z"),
            parts(2, 0, Some(0))
        );
        // Lowercase separator and single-digit hour.
        assert_eq!(
            parse_timestamp("2001-12-15t2:59:43.1Z"),
            parts(2, 100_000, Some(0))
        );
        assert_eq!(
            parse_timestamp("2001-12-15T02:59:43+05:30"),
            parts(2, 0, Some(19_800))
        );
        assert_eq!(
            parse_timestamp("2001-12-15T02:59:43+5"),
            parts(2, 0, Some(18_000))
        );
        // Space separator with an hour-only negative offset and short fraction.
        assert_eq!(
            parse_timestamp("2001-12-14 21:59:43.10 -5"),
            Some(TimestampParts {
                year: 2001,
                month: 12,
                day: 14,
                time: Some(TimestampTimeParts {
                    hour: 21,
                    minute: 59,
                    second: 43,
                    microsecond: 100_000,
                    tz_offset_seconds: Some(-18_000),
                }),
            })
        );
        // Date-only, single-digit month and day.
        assert_eq!(
            parse_timestamp("2001-12-1"),
            Some(TimestampParts {
                year: 2001,
                month: 12,
                day: 1,
                time: None,
            })
        );
        // Long fractions are truncated to six digits.
        assert_eq!(
            parse_timestamp("2001-12-15T02:59:43.123456789")
                .unwrap()
                .time
                .unwrap()
                .microsecond,
            123_456
        );
        // Near-misses stay out of the timestamp type, like PyYAML.
        assert_eq!(parse_timestamp("2001-12-15xx"), None);
        assert_eq!(parse_timestamp("2001-12-15T02:59"), None);
        assert_eq!(parse_timestamp("2001-12-15T02:59:43z"), None);
        assert_eq!(parse_timestamp("2001-12-15 "), None);
        assert_eq!(parse_timestamp("2001-1"), None);
        assert_eq!(parse_timestamp(""), None);
    }

    // --- Item 1: invalid or truncated escapes must error, never loop. ---

    #[test]
    fn unknown_block_escape_is_a_scanner_error() {
        let error = parse(r#"a: "x\q""#).unwrap_err();
        assert_eq!(error.kind, ErrorKind::Scanner);
        assert!(error.problem.contains("unknown escape character"));
    }

    #[test]
    fn block_backslash_at_end_of_line_is_an_error() {
        // A backslash at the very end of the stream is an escaped line break
        // with no following line: PyYAML reports the unexpected end of stream
        // while scanning the quoted scalar.
        let error = parse("a: \"abc\\\n").unwrap_err();
        assert_eq!(error.kind, ErrorKind::Scanner);
        assert!(error.problem.contains("end of stream"));
    }

    #[test]
    fn unknown_flow_escape_is_an_error() {
        let error = parse(r#"a: ["x\q"]"#).unwrap_err();
        assert!(error.problem.contains("unknown escape character"));
    }

    // --- Item 2: hex escapes must not slice into multi-byte characters. ---

    #[test]
    fn hex_escape_rejects_non_ascii_bytes_without_panicking() {
        let error = parse("a: \"\\uAB\u{65e5}x\"").unwrap_err();
        assert_eq!(error.kind, ErrorKind::Scanner);
        assert!(error.problem.contains("hexadecimal"));
        // Surrogates are rejected as well.
        let error = parse("a: \"\\uD800x\"").unwrap_err();
        assert!(error.problem.contains("Unicode escape"));
        let error = parse("a: [\"\\uD8\u{65e5}x\"]").unwrap_err();
        assert!(error.problem.contains("hexadecimal"));
    }

    #[test]
    fn short_and_invalid_hex_escapes_are_errors_with_real_offsets() {
        let error = parse("a: \"\\xZZ\"").unwrap_err();
        assert_eq!(error.mark.start, 6);
        // The closing quote is where the missing hex digit was expected.
        let error = parse("a: \"\\u12\"").unwrap_err();
        assert_eq!(error.mark.start, 8);
    }

    #[test]
    fn valid_escapes_still_decode() {
        let (document, root) = parse_root("a: \"\\u00e9\"\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].value), "é");
        let (document, root) = parse_root("a: [\"\\x41\"]\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        let NodeKind::Sequence(items) = &document.arena.node(entries[0].value).kind else {
            panic!("expected sequence");
        };
        assert_eq!(scalar_value(&document, items[0]), "A");
    }

    // --- Item 3: unbounded recursion must be caught by a depth limit. ---

    #[test]
    fn deep_flow_nesting_is_rejected_not_fatal() {
        let source = "[".repeat(50000) + &"]".repeat(50000);
        let error = parse(&source).unwrap_err();
        assert_eq!(error.kind, ErrorKind::Parser);
        assert!(error.problem.contains("maximum nesting depth exceeded"));
    }

    #[test]
    fn deep_block_nesting_is_rejected_not_fatal() {
        let mut source = String::new();
        for depth in 0..200 {
            source.push_str(&" ".repeat(depth));
            source.push_str("k:\n");
        }
        let error = parse(&source).unwrap_err();
        assert!(error.problem.contains("maximum nesting depth exceeded"));
    }

    #[test]
    fn depth_at_the_limit_still_parses() {
        let source = "[".repeat(127) + &"]".repeat(127);
        assert!(parse(&source).is_ok());
        let mut source = String::new();
        for depth in 0..126 {
            source.push_str(&" ".repeat(depth));
            source.push_str("k:\n");
        }
        source.push_str(&" ".repeat(126));
        source.push_str("v: 1\n");
        assert!(parse(&source).is_ok());
    }

    // --- Item 4: huge exponents must not explode the exact path. ---

    #[test]
    fn huge_exponent_scalars_resolve_without_hanging() {
        let (document, root) = parse_root("value: 1.0e-5000000000\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        let NodeKind::Scalar(scalar) = &document.arena.node(entries[0].value).kind else {
            panic!("expected scalar");
        };
        assert_eq!(scalar.kind, ScalarKind::Float);
        assert_eq!(scalar.value, "1.0e-5000000000");
        // A f64-infinite value still keeps the exact Decimal text.
        let (document, root) = parse_root("value: 1.0e+400\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        let NodeKind::Scalar(scalar) = &document.arena.node(entries[0].value).kind else {
            panic!("expected scalar");
        };
        assert_eq!(scalar.kind, ScalarKind::Decimal);
        assert_eq!(scalar.value, "1.0e+400");
    }

    // --- Item 5: content after an inline `--- ` marker. ---

    #[test]
    fn inline_content_after_document_marker_becomes_the_root() {
        let (kind, value) = root_scalar("--- 42\n");
        assert_eq!(kind, ScalarKind::Int);
        assert_eq!(value, "42");
        let (document, root) = parse_root("--- [1, 2]\n");
        assert!(matches!(
            document.arena.node(root).kind,
            NodeKind::Sequence(_)
        ));
        let (kind, _) = root_scalar("--- 'quoted'\n");
        assert_eq!(kind, ScalarKind::Str);
        let (document, root) = parse_root("--- |\n  text\n");
        assert_eq!(scalar_value(&document, root), "text\n");
        // Round-trip: untouched sources stay byte-identical.
        let document = parse("--- 42\n").unwrap();
        assert_eq!(document.text, "--- 42\n");
    }

    #[test]
    fn marker_line_with_only_a_comment_yields_no_document() {
        // Pre-existing behavior: a `---` line with nothing after it produces
        // no document (PyYAML would yield a null document here).
        let document = parse("--- # comment\n").unwrap();
        assert!(document.documents.is_empty());
    }

    #[test]
    fn inline_block_collections_after_marker_are_rejected_like_pyyaml() {
        let error = parse("--- foo: 1\n").unwrap_err();
        assert!(error
            .problem
            .contains("mapping values are not allowed here"));
        let error = parse("--- - a\n").unwrap_err();
        assert!(error
            .problem
            .contains("sequence entries are not allowed here"));
    }

    #[test]
    fn a_mapping_after_a_root_scalar_is_rejected_like_pyyaml() {
        let error = parse("value\nkey: 1\n").unwrap_err();
        assert!(error
            .problem
            .contains("mapping values are not allowed here"));
        let error = parse("--- 42\nkey: 1\n").unwrap_err();
        assert!(error
            .problem
            .contains("mapping values are not allowed here"));
        // A fresh document after an explicit marker stays legal.
        let document = parse("value\n# comment\n---\nkey: 1\n").unwrap();
        assert_eq!(document.documents.len(), 2);
    }

    // --- Item 6: root scalars must stop at comments. ---

    #[test]
    fn root_plain_scalar_stops_at_a_comment() {
        let (kind, value) = root_scalar("hello # world\n");
        assert_eq!(kind, ScalarKind::Str);
        assert_eq!(value, "hello");
        assert_eq!(root_scalar("hello#world\n").1, "hello#world");
        let document = parse("hello # world\n").unwrap();
        assert_eq!(document.text, "hello # world\n");
    }

    #[test]
    fn root_flow_collection_allows_a_trailing_comment() {
        let (document, root) = parse_root("[1, 2] # comment\n");
        assert!(matches!(
            document.arena.node(root).kind,
            NodeKind::Sequence(_)
        ));
        assert_eq!(document.text, "[1, 2] # comment\n");
    }

    #[test]
    fn nested_value_scalars_stop_at_comments() {
        let document = parse("a:\n  hello # world\nb: [1, 2] # c\n").unwrap();
        let value = root_mapping_value("a:\n  hello # world\nb: [1, 2] # c\n", "a");
        assert_eq!(scalar_value(&document, value), "hello");
    }

    // --- Item 7: block scalars keep leading blank lines and '#'-lines. ---

    #[test]
    fn block_scalar_keeps_leading_blank_lines() {
        for source in ["key: |\n\n  text\n", "key: >\n\n  text\n"] {
            let (document, root) = parse_root(source);
            let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
                panic!("expected mapping");
            };
            assert_eq!(scalar_value(&document, entries[0].value), "\ntext\n");
            assert_eq!(document.text, source);
        }
    }

    #[test]
    fn block_scalar_keeps_hash_lines() {
        let source = "key: |\n  # not a comment\n  text\n";
        let (document, root) = parse_root(source);
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        assert_eq!(
            scalar_value(&document, entries[0].value),
            "# not a comment\ntext\n"
        );
        assert_eq!(document.text, source);
    }

    #[test]
    fn block_scalar_chomping_matches_pyyaml() {
        let cases = [
            ("key: |\n\n\n", ""),
            ("key: |+\n\n\n", "\n\n"),
            ("key: |-\n\n  text\n", "\ntext"),
            ("key: |\n  text\n\n\nother: 1\n", "text\n"),
            ("key: |+\n  text\n\n", "text\n\n"),
            ("key: |-\n  text\n\n\nother: 1\n", "text"),
            // Whitespace-only lines wider than the indent are content.
            ("key: |\n  text\n     \nother: 1\n", "text\n   \n"),
        ];
        for (source, expected) in cases {
            let (document, root) = parse_root(source);
            let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
                panic!("expected mapping for {source:?}");
            };
            assert_eq!(scalar_value(&document, entries[0].value), expected);
        }
    }

    // --- Item 8: flow plain scalars keep inner colons. ---

    #[test]
    fn flow_plain_scalars_keep_inner_colons() {
        let (document, root) = parse_root("[09:00, 10:00]\n");
        let NodeKind::Sequence(items) = &document.arena.node(root).kind else {
            panic!("expected sequence");
        };
        assert_eq!(scalar_value(&document, items[0]), "09:00");
        assert_eq!(scalar_value(&document, items[1]), "600");
        let (document, root) = parse_root("{http://x: 1}\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].key), "http://x");
        assert_eq!(scalar_value(&document, entries[0].value), "1");
        let (document, root) = parse_root("{a:b: c}\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].key), "a:b");
    }

    // --- Item 9: explicit indentation indicators. ---

    #[test]
    fn indentation_indicator_sets_content_indent() {
        let (document, root) = parse_root("key: |2\n    text\n");
        let value = match &document.arena.node(root).kind {
            NodeKind::Mapping(entries) => entries[0].value,
            _ => panic!("expected mapping"),
        };
        assert_eq!(scalar_value(&document, value), "  text\n");
        let (document, root) = parse_root("key: |2\n   text\n");
        let value = match &document.arena.node(root).kind {
            NodeKind::Mapping(entries) => entries[0].value,
            _ => panic!("expected mapping"),
        };
        assert_eq!(scalar_value(&document, value), " text\n");
    }

    // --- Item 10: folded scalars keep more-indented lines. ---

    #[test]
    fn folded_scalars_fold_only_at_the_block_indent() {
        let cases = [
            ("key: >\n  a\n   b\n", "a\n b\n"),
            ("key: >\n  a\n\n  b\n", "a\nb\n"),
            ("key: >\n  a\n  b\n", "a b\n"),
            ("key: >\n  a\n   b\n  c\n", "a\n b\nc\n"),
            ("key: >\n  a\n\n\n  b\n", "a\n\nb\n"),
            ("key: >-\n  a\n   b\n", "a\n b"),
        ];
        for (source, expected) in cases {
            let (document, root) = parse_root(source);
            let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
                panic!("expected mapping for {source:?}");
            };
            assert_eq!(scalar_value(&document, entries[0].value), expected);
        }
    }

    // --- Item 11: a leading BOM is transparent but preserved. ---

    #[test]
    fn bom_is_transparent_for_parsing() {
        let (document, root) = parse_root("\u{FEFF}---\ndoc\n");
        assert_eq!(scalar_value(&document, root), "doc");
        let (document, root) = parse_root("\u{FEFF}key: 1\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].value), "1");
        let (document, root) = parse_root("\u{FEFF}--- 42\n");
        assert_eq!(scalar_value(&document, root), "42");
    }

    #[test]
    fn bom_bytes_survive_round_trips() {
        let source = "\u{FEFF}key: 1\n";
        let document = parse(source).unwrap();
        assert_eq!(document.text, source);
    }

    // --- Item 12: %TAG directives. ---

    #[test]
    fn tag_directives_expand_named_handles() {
        let (document, root) = parse_root("%TAG !e! tag:example.com,2000:\n---\nkey: !e!name v\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        let value = document.arena.node(entries[0].value);
        assert_eq!(value.tag.as_deref(), Some("tag:example.com,2000:name"));
        assert_eq!(
            document.documents[0].directives,
            vec!["%TAG !e! tag:example.com,2000:".to_owned()]
        );
    }

    #[test]
    fn primary_tag_handle_can_be_redefined() {
        let (document, root) = parse_root("%TAG ! tag:example.com,2000:\n---\nkey: !name v\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        assert_eq!(
            document.arena.node(entries[0].value).tag.as_deref(),
            Some("tag:example.com,2000:name")
        );
    }

    #[test]
    fn undefined_tag_handles_are_rejected() {
        let error = parse("key: !x!name v\n").unwrap_err();
        assert!(error.problem.contains("found undefined tag handle '!x!'"));
    }

    #[test]
    fn directives_belong_to_the_following_document_only() {
        // A directive after document content starts the next document's
        // directive region, like PyYAML.
        let document = parse("key: 1\n%TAG !e! tag:x\n--- 2\n").unwrap();
        assert_eq!(document.documents.len(), 2);
        assert!(document.documents[0].directives.is_empty());
        assert_eq!(document.documents[1].directives, vec!["%TAG !e! tag:x"]);
        // Directives must be followed by an explicit document start.
        let error = parse("%YAML 1.2\nyes\n").unwrap_err();
        assert!(error.problem.contains("expected '<document start>'"));
    }

    // --- Item 13: explicit !!bool words. ---

    #[test]
    fn bool_tag_accepts_the_pyyaml_word_set() {
        for word in ["true", "True", "TRUE", "yes", "Yes", "yEs", "on", "ON"] {
            let source = format!("value: !!bool {word}\n");
            let (document, root) = parse_root(&source);
            let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
                panic!("expected mapping");
            };
            let NodeKind::Scalar(scalar) = &document.arena.node(entries[0].value).kind else {
                panic!("expected scalar");
            };
            assert_eq!(scalar.kind, ScalarKind::Bool(true), "for {word:?}");
        }
        for word in ["false", "FALSE", "no", "No", "off", "OFF"] {
            let source = format!("value: !!bool {word}\n");
            let (document, root) = parse_root(&source);
            let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
                panic!("expected mapping");
            };
            let NodeKind::Scalar(scalar) = &document.arena.node(entries[0].value).kind else {
                panic!("expected scalar");
            };
            assert_eq!(scalar.kind, ScalarKind::Bool(false), "for {word:?}");
        }
    }

    #[test]
    fn bool_tag_rejects_unknown_words() {
        for word in ["maybe", "y", "n", "2"] {
            let source = format!("value: !!bool {word}\n");
            let error = parse(&source).unwrap_err();
            assert_eq!(error.kind, ErrorKind::Constructor, "for {word:?}");
        }
    }

    // --- Item 14: sexagesimal integers materialize as decimal text. ---

    #[test]
    fn sexagesimal_scalars_resolve_to_decimal_integers() {
        let (kind, value) = root_scalar("22:00\n");
        assert_eq!(kind, ScalarKind::Int);
        assert_eq!(value, "1320");
        let (kind, value) = root_scalar("-1:30\n");
        assert_eq!(kind, ScalarKind::Int);
        assert_eq!(value, "-90");
        // Minute groups >= 60 stay strings, like PyYAML.
        assert_eq!(root_scalar("1:60\n").0, ScalarKind::Str);
        assert_eq!(root_scalar("09:00\n").0, ScalarKind::Str);
    }

    // --- Item 15: PyYAML-shaped default schema with a %YAML 1.2 escape. ---

    #[test]
    fn default_schema_matches_pyyaml_resolution() {
        assert_eq!(root_scalar("yes\n").0, ScalarKind::Bool(true));
        assert_eq!(root_scalar("OFF\n").0, ScalarKind::Bool(false));
        // Single letters are not booleans in PyYAML's resolver.
        assert_eq!(root_scalar("n\n").0, ScalarKind::Str);
        assert_eq!(root_scalar("y\n").0, ScalarKind::Str);
        // Case-exact nulls.
        assert_eq!(root_scalar("Null\n").0, ScalarKind::Null);
        assert_eq!(root_scalar("nUll\n").0, ScalarKind::Str);
        // Leading-zero octal and 1.1-only forms.
        let (kind, value) = root_scalar("052\n");
        assert_eq!(kind, ScalarKind::Int);
        assert_eq!(value, "42");
        assert_eq!(root_scalar("0o17\n").0, ScalarKind::Str);
        let (kind, value) = root_scalar("0b101\n");
        assert_eq!(kind, ScalarKind::Int);
        assert_eq!(value, "5");
        // Floats need a point and a signed exponent.
        assert_eq!(root_scalar("1.5e3\n").0, ScalarKind::Str);
        assert_eq!(root_scalar("1.5e+3\n").0, ScalarKind::Float);
        assert_eq!(root_scalar("1:30.5\n").0, ScalarKind::Float);
        assert_eq!(root_scalar("1:30\n").0, ScalarKind::Int);
        assert_eq!(root_scalar(".Inf\n").0, ScalarKind::Float);
    }

    #[test]
    fn yaml12_directive_switches_to_the_core_schema() {
        let (kind, _) = root_scalar("%YAML 1.2\n---\nyes\n");
        assert_eq!(kind, ScalarKind::Str);
        let (kind, value) = root_scalar("%YAML 1.2\n---\n010\n");
        assert_eq!(kind, ScalarKind::Int);
        assert_eq!(value, "10");
        let (kind, _) = root_scalar("%YAML 1.2\n---\n0o17\n");
        assert_eq!(kind, ScalarKind::Int);
    }

    #[test]
    fn schema_resets_per_document_in_a_stream() {
        let document = parse("%YAML 1.2\n---\nflag: yes\n---\nflag: yes\n").unwrap();
        assert_eq!(document.documents.len(), 2);
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        let NodeKind::Scalar(scalar) = &document.arena.node(entries[0].value).kind else {
            panic!("expected scalar");
        };
        assert_eq!(scalar.kind, ScalarKind::Str);
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[1].root).kind
        else {
            panic!("expected mapping");
        };
        let NodeKind::Scalar(scalar) = &document.arena.node(entries[0].value).kind else {
            panic!("expected scalar");
        };
        assert_eq!(scalar.kind, ScalarKind::Bool(true));
    }

    // --- Item 16: flow anchors stay on the anchored node. ---

    #[test]
    fn flow_anchors_keep_their_names() {
        let (document, root) = parse_root("items: [&x 1, *x]\n");
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping");
        };
        let NodeKind::Sequence(items) = &document.arena.node(entries[0].value).kind else {
            panic!("expected sequence");
        };
        let anchored = document.arena.node(items[0]);
        assert_eq!(anchored.anchor.as_deref(), Some("x"));
        let NodeKind::Alias(target) = document.arena.node(items[1]).kind else {
            panic!("expected alias");
        };
        assert_eq!(target, items[0]);
        assert_eq!(document.text, "items: [&x 1, *x]\n");
    }

    // --- Item 17: marker detection without allocation, same behavior. ---

    #[test]
    fn marker_lookalikes_stay_plain_scalars() {
        assert_eq!(root_scalar("---42\n").1, "---42");
        assert_eq!(root_scalar("...42\n").1, "...42");
        // `---#x` keeps its historical treatment as a marker line.
        assert!(parse("---#x\n").unwrap().documents.is_empty());
    }

    // --- Item 18: scanner errors carry real positions. ---

    #[test]
    fn unterminated_verbatim_tag_reports_the_real_position() {
        let error = parse("a: !<foo v\n").unwrap_err();
        assert!(error.problem.contains("unterminated verbatim tag"));
        assert_eq!(error.mark.start, 3);
    }

    #[test]
    fn invalid_escape_reports_the_real_position() {
        let error = parse("a: \"x\\q\"\n").unwrap_err();
        // The offending escape character sits at column 6.
        assert_eq!(error.mark.start, 6);
    }

    // --- Multi-line plain scalars in block mappings. ---

    #[test]
    fn mapping_value_plain_scalar_folds_following_lines() {
        // A single break folds to a space; a new key at the mapping's indent
        // ends the scalar.
        let (document, value) = root_mapping_entry("a: multi\n  line\nb: 2\n", "a");
        assert_eq!(scalar_value(&document, value), "multi line");
        assert_eq!(document.text, "a: multi\n  line\nb: 2\n");
    }

    #[test]
    fn mapping_value_plain_scalar_folds_blank_lines() {
        // One blank line -> one newline; two blank lines -> two newlines;
        // trailing blank lines are discarded.
        let (document, value) = root_mapping_entry("a: x\n\n  y\n\n\n  z\nb: 2\n", "a");
        assert_eq!(scalar_value(&document, value), "x\ny\n\nz");
        let (document, value) = root_mapping_entry("a: x\n  y\n\n\nb: 2\n", "a");
        assert_eq!(scalar_value(&document, value), "x y");
    }

    #[test]
    fn mapping_value_plain_scalar_folds_deeper_lines() {
        // Continuation lines keep folding at any indent above the mapping,
        // with their leading whitespace stripped.
        let (document, value) =
            root_mapping_entry("a: multi\n  more\n    deeper\n  line\nb: 2\n", "a");
        assert_eq!(scalar_value(&document, value), "multi more deeper line");
    }

    #[test]
    fn mapping_value_plain_scalar_ends_at_comment_lines() {
        // The comment line is not consumed; a dedented key after it still
        // parses, while a more-indented leftover is an error like PyYAML.
        let (document, value) = root_mapping_entry("a: multi\n# comment\nb: 2\n", "a");
        assert_eq!(scalar_value(&document, value), "multi");
        let (document, value) = root_mapping_entry("a: x\n  y # c\nb: 2\n", "a");
        assert_eq!(scalar_value(&document, value), "x y");
        let error = parse("a: multi\n# comment\n  line\n").unwrap_err();
        assert_eq!(error.kind, ErrorKind::Parser);
        assert!(error.problem.contains("expected <block end>"));
    }

    #[test]
    fn mapping_value_plain_scalar_ends_at_trailing_comment() {
        // A trailing comment on the first line prevents continuation.
        let (document, value) = root_mapping_entry("a: x # comment\nb: 2\n", "a");
        assert_eq!(scalar_value(&document, value), "x");
        let error = parse("a: x # comment\n  line\n").unwrap_err();
        assert!(error.problem.contains("expected <block end>"));
    }

    #[test]
    fn mapping_value_continuation_with_colon_is_rejected() {
        // A `: ` on a continuation line is a mapping-value indicator where no
        // simple key can start, exactly like PyYAML's scanner error.
        let error = parse("a: x\n  b: y\n").unwrap_err();
        assert_eq!(error.kind, ErrorKind::Scanner);
        assert!(error
            .problem
            .contains("mapping values are not allowed here"));
        // A colon without a following space stays scalar content.
        let (document, value) = root_mapping_entry("a: x\n  http://y\n", "a");
        assert_eq!(scalar_value(&document, value), "x http://y");
    }

    #[test]
    fn mapping_value_continuation_absorbs_dash_and_question_lines() {
        // Continuation lines fold `- ` and `? ` text like PyYAML's scanner.
        let (document, value) = root_mapping_entry("a: x\n  - y\n", "a");
        assert_eq!(scalar_value(&document, value), "x - y");
        let (document, value) = root_mapping_entry("a: x\n  ? y\n", "a");
        assert_eq!(scalar_value(&document, value), "x ? y");
    }

    #[test]
    fn nested_mapping_value_continuation_uses_nested_threshold() {
        let source = "outer:\n  a: x\n    y\nb: 2\n";
        let document = parse(source).unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        let NodeKind::Mapping(inner) = &document.arena.node(entries[0].value).kind else {
            panic!("expected nested mapping");
        };
        let NodeKind::Scalar(scalar) = &document.arena.node(inner[0].value).kind else {
            panic!("expected scalar");
        };
        assert_eq!(scalar.value, "x y");
        assert_eq!(document.text, source);
    }

    // --- Multi-line plain scalars in sequences and at the root. ---

    #[test]
    fn sequence_item_plain_scalar_folds_following_lines() {
        let document = parse("- multi\n  line\n- two\n").unwrap();
        let NodeKind::Sequence(items) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected sequence");
        };
        assert_eq!(scalar_value(&document, items[0]), "multi line");
        assert_eq!(scalar_value(&document, items[1]), "two");
        assert_eq!(document.text, "- multi\n  line\n- two\n");
        // A blank line inside the item folds to a newline.
        let document = parse("- x\n\n  y\n- z\n").unwrap();
        let NodeKind::Sequence(items) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected sequence");
        };
        assert_eq!(scalar_value(&document, items[0]), "x\ny");
    }

    #[test]
    fn sequence_item_mapping_spans_are_global_offsets() {
        // A mapping that is a sequence item starts at its first key on the
        // dash's line; the item column must become a global offset, not be
        // used raw, and each item's span must stay inside the source.
        let source = "servers:\n  - host: h1\n    port: 80\n";
        let (document, root) = parse_root(source);
        let NodeKind::Mapping(entries) = &document.arena.node(root).kind else {
            panic!("expected mapping root");
        };
        let NodeKind::Sequence(items) = &document.arena.node(entries[0].value).kind else {
            panic!("expected sequence");
        };
        let item_span = document.arena.node(items[0]).span;
        let host = source.find("host").unwrap();
        let item_end = source.find("port: 80").unwrap() + "port: 80".len();
        assert_eq!(item_span.start, host);
        assert_eq!(item_span.end, item_end);

        // A second item must not inherit the first item's offsets, and no
        // span may point past the end of the source.
        let source = "- host: h1\n  port: 80\n- host: h2\n";
        let (document, root) = parse_root(source);
        let NodeKind::Sequence(items) = &document.arena.node(root).kind else {
            panic!("expected sequence");
        };
        let first = document.arena.node(items[0]).span;
        let second = document.arena.node(items[1]).span;
        assert_eq!(first.start, source.find("host").unwrap());
        assert_eq!(
            first.end,
            source.find("port: 80").unwrap() + "port: 80".len()
        );
        assert_eq!(second.start, source.rfind("host").unwrap());
        assert_eq!(second.end, source.len() - 1);
        assert!(second.end <= source.len());
    }

    #[test]
    fn root_plain_scalar_folds_following_lines() {
        assert_eq!(
            root_scalar("42\nmore\n"),
            (ScalarKind::Str, "42 more".to_owned())
        );
        assert_eq!(root_scalar("--- 42\nmore\n").1, "42 more".to_owned());
        // Root scalars fold lines at column 0, including dash-like text.
        assert_eq!(root_scalar("42\n- x\n").1, "42 - x".to_owned());
        // Comment lines end the scalar; a marker then starts a new document.
        let document = parse("value\n# c\n---\nkey: 1\n").unwrap();
        assert_eq!(document.documents.len(), 2);
        assert_eq!(scalar_value(&document, document.documents[0].root), "value");
        // Trailing blanks are discarded and document-end markers still work.
        assert_eq!(root_scalar("42\nmore\n...\n").1, "42 more");
        assert_eq!(
            parse("42\nmore\n...\n").unwrap().documents[0].explicit_end,
            true
        );
    }

    #[test]
    fn root_scalar_folds_directive_lookalikes_but_not_directives() {
        // At column 0 a %-line folds into a root scalar (threshold 0), while
        // a mapping value stops before it (threshold >= 1) and the directive
        // then requires an explicit document start.
        assert_eq!(root_scalar("42\n%YAML 1.2\n").1, "42 %YAML 1.2");
        let error = parse("a: x\n%YAML 1.2\nb: 2\n").unwrap_err();
        assert!(error.problem.contains("expected '<document start>'"));
    }

    // --- Multi-line flow collections. ---

    #[test]
    fn flow_sequence_spans_multiple_lines() {
        let source = "a: [1,\n  2,\n  3]\n";
        let document = parse(source).unwrap();
        let value = root_mapping_value(&source, "a");
        let NodeKind::Sequence(items) = &document.arena.node(value).kind else {
            panic!("expected sequence");
        };
        assert_eq!(items.len(), 3);
        assert_eq!(scalar_value(&document, items[0]), "1");
        assert_eq!(scalar_value(&document, items[2]), "3");
        assert_eq!(document.text, source);
    }

    #[test]
    fn flow_collection_forms_all_span_lines() {
        for (source, expected_len) in [
            ("a: {\n  k: v\n}", 1),
            ("a: [1, [2,\n  3], {k: v}]", 3),
            ("[1,\n  2]", 2),
            ("a: [x\n, y]", 2),
            ("a: [1,\n\n  2]", 2),
            ("a: [1,\n  2\n# comment\n, 3]", 3),
        ] {
            let document = parse(source).unwrap();
            let root = document.documents[0].root;
            let node = match &document.arena.node(root).kind {
                NodeKind::Mapping(entries) => entries[0].value,
                NodeKind::Sequence(items) => {
                    assert_eq!(items.len(), expected_len, "for {source}");
                    continue;
                }
                _ => panic!("expected collection for {source}"),
            };
            match &document.arena.node(node).kind {
                NodeKind::Sequence(items) => {
                    assert_eq!(items.len(), expected_len, "for {source}");
                }
                NodeKind::Mapping(entries) => {
                    assert_eq!(entries.len(), expected_len, "for {source}");
                }
                _ => panic!("expected a collection value for {source}"),
            }
        }
    }

    #[test]
    fn flow_plain_scalars_fold_across_lines() {
        for (source, expected) in [
            ("a: [x\n  y]", "x y"),
            ("a: [x\n\ny]", "x\ny"),
            ("a: [x\n\n\ny]", "x\n\ny"),
        ] {
            let document = parse(source).unwrap();
            let value = root_mapping_value(source, "a");
            let NodeKind::Sequence(items) = &document.arena.node(value).kind else {
                panic!("expected sequence for {source}");
            };
            assert_eq!(scalar_value(&document, items[0]), expected, "for {source}");
        }
    }

    #[test]
    fn unbalanced_flow_at_end_of_stream_is_an_error() {
        let error = parse("a: [1,\n  2").unwrap_err();
        assert_eq!(error.kind, ErrorKind::Parser);
        assert!(error.problem.contains("expected ',' or ']'"));
        let error = parse("a: {\n  k: v").unwrap_err();
        assert!(error.problem.contains("expected ',' or '}'"));
    }

    #[test]
    fn flow_mapping_key_cannot_span_lines() {
        // PyYAML's scanner drops a simple key candidate once a token is
        // fetched on a later line, so the ':' must be on the key's line.
        let error = parse("a: {k\n: v}").unwrap_err();
        assert!(error.problem.contains("expected ',' or '}'"));
        // But a value on the following line is fine.
        let document = parse("a: {k:\n  v}").unwrap();
        let value = root_mapping_value("a: {k:\n  v}", "a");
        let NodeKind::Mapping(entries) = &document.arena.node(value).kind else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].value), "v");
    }

    // --- Multi-line quoted scalars. ---

    #[test]
    fn quoted_scalars_fold_across_lines() {
        for (source, expected) in [
            ("key: \"multi\n  line\"", "multi line"),
            ("key: 'multi\n  line'", "multi line"),
            ("key: \"x  \n  y\"", "x y"),
            ("key: 'x   \n  y'", "x y"),
            ("key: \"x\n\n  y\"", "x\ny"),
            ("key: \"x\n\n\n  y\"", "x\n\ny"),
            // '#' is content inside quotes, on the first line or later ones.
            ("key: \"multi\n  # line\"", "multi # line"),
        ] {
            let (document, value) = root_mapping_entry(source, "key");
            assert_eq!(scalar_value(&document, value), expected, "for {source}");
            assert_eq!(document.text, source, "for {source}");
        }
    }

    #[test]
    fn double_quoted_escaped_line_breaks() {
        let bs = '\\';
        // Backslash at end of line: no space, no newline; further blanks
        // still contribute newlines.
        let (document, value) = root_mapping_entry(&format!("key: \"x{bs}\n  y\""), "key");
        assert_eq!(scalar_value(&document, value), "xy");
        let (document, value) = root_mapping_entry(&format!("key: \"x{bs}\n\n  y\""), "key");
        assert_eq!(scalar_value(&document, value), "x\ny");
        // Escaped whitespace before the break survives; real whitespace does not.
        let (document, value) = root_mapping_entry(&format!("key: \"x{bs}  \n  y\""), "key");
        assert_eq!(scalar_value(&document, value), "x  y");
        // An escaped backslash is not an escaped break: the break folds.
        let (document, value) = root_mapping_entry(&format!("key: \"x{bs}{bs}\n  y\""), "key");
        assert_eq!(scalar_value(&document, value), "x\\ y");
    }

    #[test]
    fn quoted_scalars_fold_inside_flow() {
        for (source, expected) in [
            ("a: [\"x\n  y\"]", "x y"),
            ("a: [\"x\n\ny\"]", "x\ny"),
            ("a: ['x\n  y']", "x y"),
        ] {
            let document = parse(source).unwrap();
            let value = root_mapping_value(source, "a");
            let NodeKind::Sequence(items) = &document.arena.node(value).kind else {
                panic!("expected sequence for {source}");
            };
            assert_eq!(scalar_value(&document, items[0]), expected, "for {source}");
        }
    }

    #[test]
    fn unterminated_quoted_scalars_report_end_of_stream() {
        for source in ["a: \"x\n  y", "a: 'x\n  y", "a: \"abc\\\n"] {
            let error = parse(source).unwrap_err();
            assert_eq!(error.kind, ErrorKind::Scanner, "for {source}");
            assert!(error.problem.contains("end of stream"), "for {source}");
        }
    }

    #[test]
    fn quoted_scalars_reject_document_markers_inside() {
        let error = parse("key: \"x\n--- y\"").unwrap_err();
        assert_eq!(error.kind, ErrorKind::Scanner);
        assert!(error.problem.contains("document separator"));
    }

    // --- Compact nested sequences. ---

    #[test]
    fn compact_nested_sequences_parse_recursively() {
        let document = parse("- - a\n- - b\n").unwrap();
        let NodeKind::Sequence(outer) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected sequence");
        };
        assert_eq!(outer.len(), 2);
        for (index, item) in outer.iter().enumerate() {
            let NodeKind::Sequence(inner) = &document.arena.node(*item).kind else {
                panic!("expected nested sequence");
            };
            assert_eq!(inner.len(), 1);
            assert_eq!(
                scalar_value(&document, inner[0]),
                if index == 0 { "a" } else { "b" }
            );
        }
        assert_eq!(document.text, "- - a\n- - b\n");
        // Items continue at the nested dash column.
        let document = parse("- - a\n  - b\n- c\n").unwrap();
        let NodeKind::Sequence(outer) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected sequence");
        };
        let NodeKind::Sequence(first) = &document.arena.node(outer[0]).kind else {
            panic!("expected nested sequence");
        };
        assert_eq!(first.len(), 2);
        assert_eq!(scalar_value(&document, outer[1]), "c");
        // A plain item's continuation still folds dash-like lines, while a
        // dash-starting item nests.
        let document = parse("- a\n  - b\n").unwrap();
        let NodeKind::Sequence(items) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected sequence");
        };
        assert_eq!(scalar_value(&document, items[0]), "a - b");
    }

    #[test]
    fn deeply_compact_nesting_is_depth_bounded() {
        let document = parse("- - - a\n").unwrap();
        let mut node = document.documents[0].root;
        for _ in 0..3 {
            let NodeKind::Sequence(items) = &document.arena.node(node).kind else {
                panic!("expected sequence");
            };
            assert_eq!(items.len(), 1);
            node = items[0];
        }
        assert_eq!(scalar_value(&document, node), "a");
        let source = "- ".repeat(200) + "a\n";
        let error = parse(&source).unwrap_err();
        assert!(error.problem.contains("maximum nesting depth exceeded"));
    }

    // --- Explicit keys. ---

    #[test]
    fn explicit_key_with_value_line() {
        let document = parse("? key\n: value\n").unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        assert_eq!(entries.len(), 1);
        assert_eq!(scalar_value(&document, entries[0].key), "key");
        assert_eq!(scalar_value(&document, entries[0].value), "value");
        assert_eq!(document.text, "? key\n: value\n");
    }

    #[test]
    fn explicit_keys_mix_with_implicit_and_null_values() {
        let document = parse("a: 1\n? k\n: v\nb: 2\n").unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        assert_eq!(entries.len(), 3);
        assert_eq!(scalar_value(&document, entries[1].value), "v");
        // A key without a `:` line gets a null value.
        let document = parse("? k\nb: 2\n").unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        assert_eq!(entries.len(), 2);
        assert!(matches!(
            document.arena.node(entries[0].value).kind,
            NodeKind::Scalar(Scalar {
                kind: ScalarKind::Null,
                ..
            })
        ));
    }

    #[test]
    fn explicit_key_continues_across_lines() {
        let document = parse("? multi\n  line key\n: v\n").unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].key), "multi line key");
        let document = parse("? k\n: multi\n  line\n").unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].value), "multi line");
    }

    #[test]
    fn explicit_key_values_can_be_block_nodes() {
        let document = parse("? k\n:\n  a: 1\n").unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        assert!(matches!(
            document.arena.node(entries[0].value).kind,
            NodeKind::Mapping(_)
        ));
        // A block sequence may sit at the mapping's own indentation.
        let document = parse("? k\n:\n- a\n").unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        let NodeKind::Sequence(items) = &document.arena.node(entries[0].value).kind else {
            panic!("expected sequence");
        };
        assert_eq!(scalar_value(&document, items[0]), "a");
    }

    #[test]
    fn explicit_key_with_bare_question_mark() {
        let document = parse("?\n  a\n: v\n").unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].key), "a");
        assert_eq!(scalar_value(&document, entries[0].value), "v");
        let document = parse("?\n: v\n").unwrap();
        let NodeKind::Mapping(entries) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected mapping");
        };
        assert!(matches!(
            document.arena.node(entries[0].key).kind,
            NodeKind::Scalar(Scalar {
                kind: ScalarKind::Null,
                ..
            })
        ));
    }

    #[test]
    fn explicit_keys_nest_in_sequences_and_mappings() {
        let document = parse("- ? k\n  : v\n").unwrap();
        let NodeKind::Sequence(items) = &document.arena.node(document.documents[0].root).kind
        else {
            panic!("expected sequence");
        };
        let NodeKind::Mapping(entries) = &document.arena.node(items[0]).kind else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].value), "v");
        let document = parse("a:\n  ? k\n  : v\n").unwrap();
        let value = root_mapping_value("a:\n  ? k\n  : v\n", "a");
        let NodeKind::Mapping(entries) = &document.arena.node(value).kind else {
            panic!("expected mapping");
        };
        assert_eq!(scalar_value(&document, entries[0].value), "v");
    }

    #[test]
    fn value_colon_line_more_indented_than_question_mark_is_an_error() {
        let error = parse("? key\n  : value\n").unwrap_err();
        assert_eq!(error.kind, ErrorKind::Parser);
        assert!(error.problem.contains("expected <block end>"));
    }

    // --- Leftover content after a document is an error, like PyYAML. ---

    #[test]
    fn leftover_content_after_a_document_is_rejected() {
        for (source, kind, message) in [
            (
                "a: 1\nmore\n",
                ErrorKind::Scanner,
                "could not find expected ':'",
            ),
            (
                "a: 1\n- x\n",
                ErrorKind::Parser,
                "expected <block end>, but found '-'",
            ),
            (
                "- a\nb: 1\n",
                ErrorKind::Parser,
                "expected <block end>, but found '?'",
            ),
            (
                "value\n# c\nx\n",
                ErrorKind::Parser,
                "expected '<document start>', but found '<scalar>'",
            ),
            (
                "a: 1\n...\nb: 2\n",
                ErrorKind::Parser,
                "expected '<document start>', but found '<block mapping start>'",
            ),
        ] {
            let error = parse(source).unwrap_err();
            assert_eq!(error.kind, kind, "for {source}");
            assert!(
                error.problem.contains(message),
                "for {source}: {}",
                error.problem
            );
        }
        // An explicit marker after `...` starts a fresh document.
        let document = parse("a: 1\n...\n---\nb: 2\n").unwrap();
        assert_eq!(document.documents.len(), 2);
    }

    #[test]
    fn multi_line_quoted_root_scalar_rejects_a_trailing_value_indicator() {
        let error = parse("\"a\n  b\": 1\n").unwrap_err();
        assert_eq!(error.kind, ErrorKind::Scanner);
        assert!(error
            .problem
            .contains("mapping values are not allowed here"));
        let error = parse("\"a\n  b\" junk\n").unwrap_err();
        assert!(error.problem.contains("expected '<document start>'"));
    }

    // --- Lossless round trips for multi-line constructs. ---

    #[test]
    fn multiline_constructs_round_trip_byte_identically() {
        for source in [
            "key: multi\n  line\n",
            "a: [1,\n  2,\n  3]\n",
            "key: \"multi\n  line\"\n",
            "- - a\n- - b\n",
            "? key\n: value\n",
            "--- 42\nmore\n",
            "a: x\n\n  y\n\n\n  z\nb: 2\n",
            "a: {\n  k: v,\n  j: w\n}\n",
            "a:\n  ? k\n  : v\n",
        ] {
            let document = parse(source).unwrap();
            assert_eq!(document.text, source, "for {source}");
        }
    }

    #[test]
    fn multiline_node_spans_cover_their_source_region() {
        let source = "a: multi\n  line\nb: 2\n";
        let document = parse(source).unwrap();
        let value = root_mapping_value(source, "a");
        let span = document.arena.node(value).span;
        assert_eq!(&document.text[span.range()], "multi\n  line");

        let source = "a: [1,\n  2]\n";
        let document = parse(source).unwrap();
        let value = root_mapping_value(source, "a");
        let span = document.arena.node(value).span;
        assert_eq!(&document.text[span.range()], "[1,\n  2]");

        let source = "key: \"multi\n  line\"\n";
        let document = parse(source).unwrap();
        let value = root_mapping_value(source, "key");
        let span = document.arena.node(value).span;
        assert_eq!(&document.text[span.range()], "\"multi\n  line\"");

        let source = "? key\n: value\n";
        let document = parse(source).unwrap();
        let span = document.arena.node(document.documents[0].root).span;
        assert_eq!(&document.text[span.range()], "? key\n: value");
    }
}
