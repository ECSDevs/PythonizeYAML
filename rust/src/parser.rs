use crate::error::{ErrorKind, Result, YamlError};
use crate::model::{
    Arena, Document, MappingEntry, NativeDocument, NodeId, NodeKind, Scalar, ScalarKind,
    ScalarStyle, Span,
};
use crate::number::{
    integer_to_decimal_string, resolve_number, strip_numeric_separators, NumberKind, SchemaVersion,
};
use std::collections::HashMap;

const CORE_PREFIX: &str = "tag:yaml.org,2002:";

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
        schema: SchemaVersion::Yaml12,
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
    lines
}

struct Parser<'a> {
    source: &'a str,
    lines: Vec<Line>,
    arena: Arena,
    anchors: HashMap<String, NodeId>,
    schema: SchemaVersion,
}

impl<'a> Parser<'a> {
    fn parse_stream(&mut self) -> Result<Vec<Document>> {
        let mut documents: Vec<Document> = Vec::new();
        let mut li = 0usize;
        let mut pending_start = 0usize;
        let mut explicit_start = false;
        let mut explicit_end = false;
        let mut directives = Vec::new();
        while li < self.lines.len() {
            if self.is_marker(li, "---") {
                if self.next_significant(li + 1, self.lines.len()).is_some()
                    || !documents.is_empty()
                {
                    pending_start = self.lines[li].start;
                }
                explicit_start = true;
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
                directives.push(self.content(li).trim().to_owned());
                if self.content(li).contains("%YAML 1.1") {
                    self.schema = SchemaVersion::Yaml11;
                } else if self.content(li).contains("%YAML 1.2") {
                    self.schema = SchemaVersion::Yaml12;
                }
                li += 1;
                continue;
            }
            if self.is_trivia(li) {
                li += 1;
                continue;
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
            let (root, next) = self.parse_block_node(li, self.lines.len(), indent)?;
            let end = self.nodes_span(root).end;
            documents.push(Document {
                root,
                span: Span::new(start, end),
                explicit_start,
                explicit_end,
                directives: std::mem::take(&mut directives),
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

    fn parse_block_node(
        &mut self,
        li: usize,
        end: usize,
        indent: usize,
    ) -> Result<(NodeId, usize)> {
        if li >= end {
            return Err(self.error(ErrorKind::Parser, "expected a node", li, 0));
        }
        let content = self.content(li);
        let rest = content.get(indent..).unwrap_or("").to_owned();
        if rest.starts_with('!') || rest.starts_with('&') {
            let (node, next) = self.parse_inline_node(li, indent, self.line_content_end(li))?;
            if self.is_property_only_null(node) {
                if let Some(next_line) = self.next_significant(next, end) {
                    let next_indent = self.lines[next_line].indent;
                    let next_content = self.content(next_line);
                    let next_is_dash = next_content.get(next_indent..).is_some_and(|rest| {
                        rest.starts_with('-')
                            && rest[1..].chars().next().map_or(true, char::is_whitespace)
                    });
                    if next_indent >= indent
                        || (next_indent == indent
                            && self.find_mapping_colon(next_content, next_indent).is_some())
                        || (next_indent == indent && next_is_dash)
                    {
                        let (child, child_next) =
                            self.parse_block_node(next_line, end, next_indent)?;
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
        if self.find_mapping_colon(content, indent).is_some() {
            return self.parse_block_mapping(li, end, indent, None);
        }
        self.parse_inline_node(li, indent, self.line_content_end(li))
    }

    fn parse_block_mapping(
        &mut self,
        mut li: usize,
        end: usize,
        indent: usize,
        first_col: Option<usize>,
    ) -> Result<(NodeId, usize)> {
        let map_start = first_col.unwrap_or_else(|| self.col_global(li, indent));
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
            let Some(colon) = self.find_mapping_colon(content, active_col) else {
                break;
            };
            if colon == active_col {
                break;
            }
            let key_start = self.col_global(li, active_col);
            let key_end = self.col_global(li, colon);
            let (key, key_next) = self.parse_inline_node(li, active_col, colon)?;
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
                self.parse_inline_node(li, value_col, content_end)?
            } else {
                let next_significant = self.next_significant(li + 1, end);
                if let Some(next_line) = next_significant {
                    let next_indent = self.lines[next_line].indent;
                    let next_content = self.content(next_line);
                    let next_is_marker = self.is_document_marker(next_line);
                    let next_is_dash = next_content.get(next_indent..).is_some_and(|rest| {
                        rest.starts_with('-')
                            && rest[1..].chars().next().map_or(true, char::is_whitespace)
                    });
                    if !next_is_marker
                        && (next_indent > indent || (next_indent == indent && next_is_dash))
                    {
                        self.parse_block_node(next_line, end, next_indent)?
                    } else {
                        let mark = Span::new(
                            self.col_global(li, colon + 1),
                            self.col_global(li, colon + 1),
                        );
                        (self.null_node(mark), li + 1)
                    }
                } else {
                    let mark = Span::new(
                        self.col_global(li, colon + 1),
                        self.col_global(li, colon + 1),
                    );
                    (self.null_node(mark), li + 1)
                }
            };
            if self.is_property_only_null(value) {
                if let Some(next_line) = self.next_significant(next, end) {
                    let next_indent = self.lines[next_line].indent;
                    let next_content = self.content(next_line);
                    let next_is_dash = next_content.get(next_indent..).is_some_and(|rest| {
                        rest.starts_with('-')
                            && rest[1..].chars().next().map_or(true, char::is_whitespace)
                    });
                    if next_indent > indent || (next_indent == indent && next_is_dash) {
                        let (child, child_next) =
                            self.parse_block_node(next_line, end, next_indent)?;
                        self.transfer_properties(value, child);
                        value = child;
                        next = child_next;
                    }
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

    fn parse_block_sequence(
        &mut self,
        mut li: usize,
        end: usize,
        indent: usize,
    ) -> Result<(NodeId, usize)> {
        let start = self.lines[li].start + indent;
        let mut items = Vec::new();
        while li < end {
            if self.is_trivia(li) {
                li += 1;
                continue;
            }
            if self.is_document_marker(li) || self.lines[li].indent != indent {
                break;
            }
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
            let (item, next) = if item_col >= item_end {
                if let Some(next_line) = self.next_significant(li + 1, end) {
                    if self.lines[next_line].indent > indent {
                        self.parse_block_node(next_line, end, self.lines[next_line].indent)?
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
            } else if self.find_mapping_colon(content, item_col).is_some() {
                self.parse_block_mapping(li, end, item_col, Some(item_col))?
            } else {
                self.parse_inline_node(li, item_col, item_end)?
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

    fn parse_inline_node(
        &mut self,
        li: usize,
        start_col: usize,
        end_col: usize,
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
                let (raw_tag, next) = self.read_tag(content, col, end_col)?;
                tag = Some(self.expand_tag(&raw_tag));
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
            let (value, style, next_col) = self.parse_quoted(content, col, end_col, li)?;
            let span = Span::new(self.col_global(li, col), self.col_global(li, next_col));
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
            return Ok((id, li + 1));
        }

        let raw = self.source[self.col_global(li, col)..self.col_global(li, end_col)].to_owned();
        let trimmed = raw.trim_end();
        let span = Span::new(
            self.col_global(li, col),
            self.col_global(li, col + trimmed.len()),
        );
        if trimmed.starts_with(['@', '\u{0060}']) {
            return Err(self.error(
                ErrorKind::Parser,
                "reserved character cannot start a plain scalar",
                li,
                col,
            ));
        }
        let scalar = self.classify_scalar(trimmed.trim(), ScalarStyle::Plain, tag.as_deref());
        let id = self.arena.add(
            NodeKind::Scalar(scalar),
            span,
            span,
            tag.clone(),
            anchor.clone(),
        );
        self.attach_properties(id, tag, anchor);
        Ok((id, li + 1))
    }

    fn parse_flow_node(
        &mut self,
        start_col: usize,
        end_col: usize,
        line_index: usize,
    ) -> Result<FlowNode> {
        let start = self.col_global(line_index, start_col);
        let limit = self.col_global(line_index, end_col);
        let mut flow = FlowParser {
            parser: self,
            pos: start,
            limit,
            line_index,
        };
        let mut node = flow.parse_node()?;
        if flow.pos < limit && !flow.source()[flow.pos..limit].trim().is_empty() {
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

    fn parse_quoted(
        &self,
        content: &str,
        start_col: usize,
        end_col: usize,
        li: usize,
    ) -> Result<(String, ScalarStyle, usize)> {
        let quote = self.byte_at(content, start_col).unwrap();
        let mut value = String::new();
        let mut pos = start_col + 1;
        while pos < end_col {
            let byte = self.byte_at(content, pos).unwrap();
            if byte == quote {
                if quote == b'\'' && self.byte_at(content, pos + 1) == Some(b'\'') {
                    value.push('\'');
                    pos += 2;
                    continue;
                }
                return Ok((
                    value,
                    if quote == b'\'' {
                        ScalarStyle::SingleQuoted
                    } else {
                        ScalarStyle::DoubleQuoted
                    },
                    pos + 1,
                ));
            }
            if quote == b'"' && byte == b'\\' {
                let Some(escaped) = self.decode_escape(content, pos, end_col)? else {
                    continue;
                };
                value.push(escaped.0);
                pos = escaped.1;
                continue;
            }
            let ch = content[pos..].chars().next().unwrap();
            value.push(ch);
            pos += ch.len_utf8();
        }
        Err(self.error(
            ErrorKind::Scanner,
            "unterminated quoted scalar",
            li,
            start_col,
        ))
    }

    fn decode_escape(
        &self,
        content: &str,
        slash: usize,
        end_col: usize,
    ) -> Result<Option<(char, usize)>> {
        let next = slash + 1;
        if next >= end_col {
            return Ok(None);
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
            _ => None,
        };
        if let Some(ch) = simple {
            return Ok(Some((ch, next + 1)));
        }
        let width = match code {
            b'x' => 2,
            b'u' => 4,
            b'U' => 8,
            _ => return Ok(None),
        };
        let hex_start = next + 1;
        let hex_end = (hex_start + width).min(end_col);
        let digits = &content[hex_start..hex_end];
        let value = u32::from_str_radix(digits, 16)
            .map_err(|_| self.error(ErrorKind::Scanner, "invalid escape sequence", 0, slash))?;
        let ch = char::from_u32(value)
            .ok_or_else(|| self.error(ErrorKind::Scanner, "invalid Unicode escape", 0, slash))?;
        Ok(Some((ch, hex_end)))
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
        let mut body_start_line = li + 1;
        while body_start_line < self.lines.len() && self.is_trivia(body_start_line) {
            body_start_line += 1;
        }
        let block_indent = if body_start_line < self.lines.len()
            && self.lines[body_start_line].indent > self.lines[li].indent
        {
            self.lines[body_start_line].indent
        } else {
            self.lines[li].indent + 1
        };
        let mut body_end_line = body_start_line;
        while body_end_line < self.lines.len() {
            if self.is_document_marker(body_end_line) {
                break;
            }
            let line = &self.lines[body_end_line];
            let line_content = self.content(body_end_line);
            if !line_content.trim().is_empty() && line.indent < block_indent {
                break;
            }
            body_end_line += 1;
        }
        let body_start = self
            .lines
            .get(body_start_line)
            .map_or(self.lines[li].end, |line| line.start);
        let body_end = self
            .lines
            .get(body_end_line.saturating_sub(1))
            .map_or(body_start, |line| line.content_end);
        let mut parts = Vec::new();
        for body_line in body_start_line..body_end_line {
            let line_content = self.content(body_line);
            let text = if line_content.trim().is_empty() {
                String::new()
            } else if line_content.len() >= block_indent {
                line_content[block_indent..].to_owned()
            } else {
                String::new()
            };
            parts.push(text);
        }
        let mut value = if marker == b'|' {
            parts.join("\n")
        } else {
            fold_lines(&parts)
        };
        match chomping {
            Some('-') => {
                while value.ends_with('\n') {
                    value.pop();
                }
            }
            Some('+') => value.push('\n'),
            _ => {
                while value.ends_with('\n') {
                    value.pop();
                }
                if body_end_line > body_start_line {
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

    fn classify_scalar(&self, raw: &str, style: ScalarStyle, tag: Option<&str>) -> Scalar {
        let explicit = tag.and_then(|tag| tag.strip_prefix(CORE_PREFIX));
        let (kind, value) = match explicit {
            Some("str") => (ScalarKind::Str, raw.to_owned()),
            Some("null") => (ScalarKind::Null, String::new()),
            Some("bool") => (
                ScalarKind::Bool(matches!(
                    raw.to_ascii_lowercase().as_str(),
                    "true" | "yes" | "on"
                )),
                raw.to_ascii_lowercase(),
            ),
            Some("int") => (
                ScalarKind::Int,
                integer_to_decimal_string(raw).unwrap_or_else(|| raw.to_owned()),
            ),
            Some("float") => (ScalarKind::Float, normalize_float_text(raw)),
            Some("decimal") => (ScalarKind::Decimal, strip_numeric_separators(raw)),
            Some("binary") => (ScalarKind::Binary, raw.to_owned()),
            Some("timestamp") => (ScalarKind::Timestamp, raw.to_owned()),
            _ if style != ScalarStyle::Plain => (ScalarKind::Str, raw.to_owned()),
            _ => self.resolve_plain(raw),
        };
        Scalar {
            kind,
            raw: raw.to_owned(),
            value,
            style,
            chomping: None,
        }
    }

    fn resolve_plain(&self, raw: &str) -> (ScalarKind, String) {
        let lower = raw.to_ascii_lowercase();
        let nulls: &[&str] = if self.schema == SchemaVersion::Yaml11 {
            &["", "~", "null"]
        } else {
            &["", "~", "null"]
        };
        if nulls.contains(&lower.as_str()) {
            return (ScalarKind::Null, String::new());
        }
        let true_values: &[&str] = if self.schema == SchemaVersion::Yaml11 {
            &["true", "yes", "on"]
        } else {
            &["true"]
        };
        let false_values: &[&str] = if self.schema == SchemaVersion::Yaml11 {
            &["false", "no", "off"]
        } else {
            &["false"]
        };
        if true_values.contains(&lower.as_str()) {
            return (ScalarKind::Bool(true), lower);
        }
        if false_values.contains(&lower.as_str()) {
            return (ScalarKind::Bool(false), lower);
        }
        if looks_like_timestamp(raw) {
            return (ScalarKind::Timestamp, raw.to_owned());
        }
        if lower == ".inf" || lower == "+.inf" || lower == "-.inf" || lower == ".nan" {
            return (ScalarKind::Float, normalize_float_text(raw));
        }
        match resolve_number(raw, self.schema) {
            Some(NumberKind::Integer) => (
                ScalarKind::Int,
                integer_to_decimal_string(raw).unwrap_or_else(|| raw.to_owned()),
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
        }
    }
    fn nodes_span(&self, id: NodeId) -> Span {
        self.arena.node(id).span
    }

    fn content(&self, li: usize) -> &'a str {
        let line = self.lines[li];
        &self.source[line.start..line.content_end]
    }

    fn line_content_end(&self, li: usize) -> usize {
        self.content(li).len()
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

    fn read_tag(&self, content: &str, start: usize, end: usize) -> Result<(String, usize)> {
        if content[start..].starts_with("!<") {
            let Some(relative_end) = content[start + 2..end].find('>') else {
                return Err(self.error(ErrorKind::Scanner, "unterminated verbatim tag", 0, start));
            };
            let tag_end = start + 2 + relative_end;
            return Ok((content[start + 2..tag_end].to_owned(), tag_end + 1));
        }
        let (word, next) = self.read_property_word(content, start, end);
        if word.is_empty() {
            return Err(self.error(ErrorKind::Scanner, "invalid tag", 0, start));
        }
        Ok((word, next))
    }

    fn expand_tag(&self, tag: &str) -> String {
        if let Some(local) = tag.strip_prefix("!!") {
            format!("{CORE_PREFIX}{local}")
        } else {
            tag.to_owned()
        }
    }

    fn col_global(&self, li: usize, col: usize) -> usize {
        self.lines[li].start + col
    }

    fn byte_at(&self, content: &str, col: usize) -> Option<u8> {
        content.as_bytes().get(col).copied()
    }

    fn is_trivia(&self, li: usize) -> bool {
        let content = self.content(li);
        let trimmed = content.trim();
        trimmed.is_empty() || trimmed.starts_with('#') || self.is_directive(li)
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
        trimmed == marker
            || trimmed.starts_with(&format!("{marker} "))
            || trimmed.starts_with(&format!("{marker}#"))
    }

    fn is_document_marker(&self, li: usize) -> bool {
        self.is_marker(li, "---") || self.is_marker(li, "...")
    }

    fn next_significant(&self, mut li: usize, end: usize) -> Option<usize> {
        while li < end {
            if !self.is_trivia(li) && !self.is_document_marker(li) {
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
    strip_numeric_separators(raw)
}

fn looks_like_timestamp(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() >= 10
        && bytes.get(4) == Some(&b'-')
        && bytes.get(7) == Some(&b'-')
        && bytes[..4].iter().all(u8::is_ascii_digit)
        && bytes[5..7].iter().all(u8::is_ascii_digit)
        && bytes[8..10].iter().all(u8::is_ascii_digit)
}
fn fold_lines(parts: &[String]) -> String {
    let mut out = String::new();
    for (index, part) in parts.iter().enumerate() {
        if index > 0 {
            if out.ends_with('\n') || part.is_empty() {
                out.push('\n');
            } else {
                out.push(' ');
            }
        }
        out.push_str(part);
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
}

struct FlowParser<'p, 'a> {
    parser: &'p mut Parser<'a>,
    pos: usize,
    limit: usize,
    line_index: usize,
}

impl<'p, 'a> FlowParser<'p, 'a> {
    fn source(&self) -> &'a str {
        self.parser.source
    }

    fn parse_node(&mut self) -> Result<FlowNode> {
        self.skip_space();
        if self.pos >= self.limit {
            return Err(self.error("expected a flow node"));
        }
        let mut tag = None;
        let mut anchor = None;
        while self.pos < self.limit && matches!(self.byte(), Some(b'!') | Some(b'&')) {
            if self.byte() == Some(b'&') {
                let start = self.pos + 1;
                while self.pos < self.limit && !self.is_property_end() {
                    self.pos += 1;
                }
                anchor = Some(self.source()[start..self.pos].to_owned());
            } else {
                let start = self.pos;
                if self.source()[self.pos..self.limit].starts_with("!<") {
                    let Some(end) = self.source()[self.pos + 2..self.limit].find('>') else {
                        return Err(self.error("unterminated verbatim tag"));
                    };
                    self.pos += end + 3;
                    tag = Some(self.source()[start + 2..self.pos - 1].to_owned());
                } else {
                    while self.pos < self.limit && !self.is_property_end() {
                        self.pos += 1;
                    }
                    tag = Some(self.parser.expand_tag(&self.source()[start..self.pos]));
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
            let span = node.span;
            let target = self.flow_to_id(node)?;
            self.parser.anchors.insert(anchor_name, target);
            return Ok(FlowNode {
                kind: FlowKind::Alias(target),
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
            if self.pos >= self.limit {
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
        let ids = items
            .into_iter()
            .map(|item| {
                self.parser.arena.add(
                    match item.kind {
                        FlowKind::Scalar(scalar) => NodeKind::Scalar(scalar),
                        FlowKind::Sequence(items) => NodeKind::Sequence(items),
                        FlowKind::Mapping(entries) => NodeKind::Mapping(entries),
                        FlowKind::Alias(target) => NodeKind::Alias(target),
                    },
                    item.span,
                    item.value_span,
                    None,
                    None,
                )
            })
            .collect();
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
            if self.pos >= self.limit {
                return Err(self.error("expected '}'"));
            }
            let key_flow = self.parse_node()?;
            let key = self.flow_to_id(key_flow)?;
            self.skip_space();
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
        let kind = match flow.kind {
            FlowKind::Scalar(scalar) => NodeKind::Scalar(scalar),
            FlowKind::Sequence(items) => NodeKind::Sequence(items),
            FlowKind::Mapping(entries) => NodeKind::Mapping(entries),
            FlowKind::Alias(target) => NodeKind::Alias(target),
        };
        Ok(self
            .parser
            .arena
            .add(kind, flow.span, flow.value_span, None, None))
    }

    fn parse_quoted(&mut self) -> Result<FlowNode> {
        let start = self.pos;
        let quote = self.byte().unwrap();
        self.pos += 1;
        let mut value = String::new();
        while self.pos < self.limit {
            let ch = self.source()[self.pos..].chars().next().unwrap();
            self.pos += ch.len_utf8();
            if ch == quote as char {
                if quote == b'\'' && self.source()[self.pos..].starts_with('\'') {
                    value.push('\'');
                    self.pos += 1;
                    continue;
                }
                let span = Span::new(start, self.pos);
                return Ok(FlowNode {
                    kind: FlowKind::Scalar(Scalar {
                        kind: ScalarKind::Str,
                        raw: self.source()[span.range()].to_owned(),
                        value,
                        style: if quote == b'\'' {
                            ScalarStyle::SingleQuoted
                        } else {
                            ScalarStyle::DoubleQuoted
                        },
                        chomping: None,
                    }),
                    span,
                    value_span: span,
                    next_line: self.line_index + 1,
                });
            }
            if quote == b'"' && ch == '\\' {
                let (decoded, next) = self.decode_escape(self.pos)?;
                value.push(decoded);
                self.pos = next;
            } else {
                value.push(ch);
            }
        }
        Err(self.error("unterminated quoted scalar"))
    }

    fn decode_escape(&self, slash: usize) -> Result<(char, usize)> {
        let Some(code) = self.source()[slash..].chars().next() else {
            return Err(self.error("unterminated escape"));
        };
        let next = slash + code.len_utf8();
        let simple = match code {
            '0' => Some('\0'),
            'a' => Some('\x07'),
            'b' => Some('\x08'),
            't' => Some('\t'),
            'n' => Some('\n'),
            'v' => Some('\x0b'),
            'f' => Some('\x0c'),
            'r' => Some('\r'),
            'e' => Some('\x1b'),
            ' ' => Some(' '),
            '"' => Some('"'),
            '/' => Some('/'),
            '\\' => Some('\\'),
            _ => None,
        };
        if let Some(ch) = simple {
            return Ok((ch, next));
        }
        let width = match code {
            'x' => 2,
            'u' => 4,
            'U' => 8,
            _ => return Err(self.error("invalid escape sequence")),
        };
        let digits_end = (next + width).min(self.limit);
        let value = u32::from_str_radix(&self.source()[next..digits_end], 16)
            .map_err(|_| self.error("invalid escape sequence"))?;
        let ch = char::from_u32(value).ok_or_else(|| self.error("invalid Unicode escape"))?;
        Ok((ch, digits_end))
    }

    fn parse_alias(&mut self) -> Result<FlowNode> {
        let start = self.pos;
        self.pos += 1;
        let name_start = self.pos;
        while self.pos < self.limit && !self.is_property_end() {
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
    fn parse_plain(&mut self) -> Result<FlowNode> {
        let start = self.pos;
        while self.pos < self.limit {
            let ch = self.source()[self.pos..].chars().next().unwrap();
            if matches!(ch, ',' | ']' | '}' | ':') {
                break;
            }
            self.pos += ch.len_utf8();
        }
        let end = self.pos;
        let raw = self.source()[start..end].trim_end();
        let end = start + raw.len();
        let scalar = self.parser.classify_scalar(raw, ScalarStyle::Plain, None);
        Ok(FlowNode {
            kind: FlowKind::Scalar(scalar),
            span: Span::new(start, end),
            value_span: Span::new(start, end),
            next_line: self.line_index + 1,
        })
    }

    fn skip_space(&mut self) {
        while self.pos < self.limit {
            let ch = self.source()[self.pos..].chars().next().unwrap();
            if ch.is_whitespace() {
                self.pos += ch.len_utf8();
            } else {
                break;
            }
        }
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

#[cfg(test)]
mod tests {
    use super::*;

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
}
