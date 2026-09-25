use crate::model::Span;
use thiserror::Error;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(dead_code)]
pub enum ErrorKind {
    Scanner,
    Parser,
    Composer,
    Constructor,
    Emitter,
    Representer,
    Serializer,
}

#[derive(Clone, Debug, Error)]
#[error("{problem}")]
pub struct YamlError {
    pub kind: ErrorKind,
    pub context: Option<String>,
    pub problem: String,
    pub mark: Span,
}

impl YamlError {
    pub fn new(kind: ErrorKind, problem: impl Into<String>, mark: Span) -> Self {
        Self {
            kind,
            context: None,
            problem: problem.into(),
            mark,
        }
    }
}

pub type Result<T> = std::result::Result<T, YamlError>;
