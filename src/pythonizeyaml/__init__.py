# Copyright (c) 2026 PythonizeYAML contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""pythonizeyaml - a YAML library that preserves what PyYAML throws away.

The public API is PyYAML-compatible, so migrating is usually a one-line import
change, but a load/dump round trip keeps the original comments, indentation and
scalar styles (plain, single/double quoted, literal ``|`` and folded ``>``).
"""

from __future__ import annotations

from .api import (
    dump,
    dump_all,
    full_load,
    full_load_all,
    load,
    load_all,
    round_trip_dump,
    round_trip_dump_all,
    round_trip_load,
    round_trip_load_all,
    safe_dump,
    safe_dump_all,
    safe_load,
    safe_load_all,
    unsafe_load,
    unsafe_load_all,
)
from .config import DEFAULT_CONFIG, IndentConfig
from .document import Document, DocumentMapping, DocumentSequence, DocumentScalar, DocumentStream, Comments, load_document, load_documents, read_document, read_documents
from .styles import Chomping, CollectionStyle, ScalarStyle, SourceSpan
from .engine import SafeYAML, YAML
from .tagged import Tagged
from .errors import (
    AliasError,
    PathError,
    StyleError,
    ComposerError,
    ConstructorError,
    EmitterError,
    MarkedYAMLError,
    ParserError,
    RepresenterError,
    ScannerError,
    SerializerError,
    YAMLError,
)

__version__ = "0.4.0"

__all__ = [
    "__version__",
    # PyYAML-compatible functions
    "load",
    "load_all",
    "full_load",
    "full_load_all",
    "unsafe_load",
    "unsafe_load_all",
    "dump",
    "dump_all",
    "safe_load",
    "safe_load_all",
    "safe_dump",
    "safe_dump_all",
    # explicit round-trip spellings
    "round_trip_load",
    "round_trip_load_all",
    "round_trip_dump",
    "round_trip_dump_all",
    # engines
    "YAML",
    "SafeYAML",
    # configuration
    "IndentConfig",
    "DEFAULT_CONFIG",
    # style-aware documents
    "Document",
    "DocumentMapping",
    "DocumentSequence",
    "DocumentScalar",
    "DocumentStream",
    "Comments",
    "ScalarStyle",
    "CollectionStyle",
    "Chomping",
    "SourceSpan",
    "load_document",
    "load_documents",
    "read_document",
    "read_documents",
    # tagged values
    "Tagged",
    # errors
    "YAMLError",
    "MarkedYAMLError",
    "ScannerError",
    "ParserError",
    "ComposerError",
    "ConstructorError",
    "EmitterError",
    "RepresenterError",
    "SerializerError",
    "PathError",
    "StyleError",
    "AliasError",
]






