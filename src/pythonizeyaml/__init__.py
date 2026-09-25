"""pythonizeyaml - a YAML library that preserves what PyYAML throws away.

The public API is PyYAML-compatible, so migrating is usually a one-line import
change, but a load/dump round trip keeps the original comments, indentation and
scalar styles (plain, single/double quoted, literal ``|`` and folded ``>``).
"""

from __future__ import annotations

from .api import (
    dump,
    dump_all,
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
)
from .config import DEFAULT_CONFIG, IndentConfig
from .document import Document, DocumentStream, NodeRef, Comments, load_document, load_documents, read_document, read_documents
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

__version__ = "0.3.0"

__all__ = [
    "__version__",
    # PyYAML-compatible functions
    "load",
    "load_all",
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
    "DocumentStream",
    "NodeRef",
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






