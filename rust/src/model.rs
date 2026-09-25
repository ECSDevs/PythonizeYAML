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

use std::ops::Range;

pub type NodeId = usize;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
}

impl Span {
    pub fn new(start: usize, end: usize) -> Self {
        Self { start, end }
    }

    pub fn range(self) -> Range<usize> {
        self.start..self.end
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScalarStyle {
    Plain,
    SingleQuoted,
    DoubleQuoted,
    Literal,
    Folded,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ScalarKind {
    Null,
    Bool(bool),
    Int,
    Float,
    Decimal,
    Str,
    Binary,
    Timestamp,
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct Scalar {
    pub kind: ScalarKind,
    pub raw: String,
    pub value: String,
    pub style: ScalarStyle,
    pub chomping: Option<char>,
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct MappingEntry {
    pub key: NodeId,
    pub value: NodeId,
    pub key_span: Span,
    pub value_span: Span,
    pub entry_span: Span,
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub enum NodeKind {
    Scalar(Scalar),
    Sequence(Vec<NodeId>),
    Mapping(Vec<MappingEntry>),
    Set(Vec<NodeId>),
    Alias(NodeId),
    Tagged { tag: String, value: NodeId },
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct Node {
    pub id: NodeId,
    pub kind: NodeKind,
    pub span: Span,
    pub value_span: Span,
    pub tag: Option<String>,
    pub anchor: Option<String>,
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct Document {
    pub root: NodeId,
    pub span: Span,
    pub explicit_start: bool,
    pub explicit_end: bool,
    pub directives: Vec<String>,
}

#[derive(Debug, Default)]
pub struct Arena {
    pub nodes: Vec<Node>,
}

impl Arena {
    pub fn add(
        &mut self,
        kind: NodeKind,
        span: Span,
        value_span: Span,
        tag: Option<String>,
        anchor: Option<String>,
    ) -> NodeId {
        let id = self.nodes.len();
        self.nodes.push(Node {
            id,
            kind,
            span,
            value_span,
            tag,
            anchor,
        });
        id
    }

    pub fn node(&self, id: NodeId) -> &Node {
        &self.nodes[id]
    }

    pub fn node_mut(&mut self, id: NodeId) -> &mut Node {
        &mut self.nodes[id]
    }
}

#[derive(Debug)]
pub struct NativeDocument {
    pub text: String,
    pub arena: Arena,
    pub documents: Vec<Document>,
}
