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
