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
