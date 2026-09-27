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

import importlib.util
from typing import TYPE_CHECKING

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

__version__ = "0.5.0"

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


# -- optional Pydantic integration (lazy exports) --------------------------
#
# pydantic is an optional dependency with a non-trivial import cost, and this
# package itself has none. The classes below are therefore exposed through
# module-level ``__getattr__`` (PEP 562) instead of eager imports, and
# ``__all__`` only advertises them when the corresponding package is present
# (checked with ``find_spec``, which never imports anything).

if TYPE_CHECKING:
    from .pydantic import YAMLModel
    from .pydantic_settings import YAMLSettings, YAMLSettingsConfigDict, YAMLSettingsSource


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def __getattr__(name: str):
    if name == "YAMLModel":
        try:
            from .pydantic import YAMLModel
        except ImportError as exc:
            raise ImportError(
                "pythonizeyaml.YAMLModel requires the optional 'pydantic' package; "
                "install it with: pip install 'pythonizeyaml[pydantic]'"
            ) from exc
        globals()["YAMLModel"] = YAMLModel
        return YAMLModel
    if name in ("YAMLSettings", "YAMLSettingsConfigDict", "YAMLSettingsSource"):
        try:
            from . import pydantic_settings
        except ImportError as exc:
            raise ImportError(
                f"pythonizeyaml.{name} requires the optional 'pydantic-settings' "
                "package; install it with: pip install 'pythonizeyaml[pydantic-settings]'"
            ) from exc
        value = getattr(pydantic_settings, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))


if _module_available("pydantic"):
    __all__ = [*__all__, "YAMLModel"]
# YAMLSettings transitively requires pydantic as well; advertise it only when
# both packages are discoverable so ``import *`` never touches a broken import.
if _module_available("pydantic") and _module_available("pydantic_settings"):
    __all__ = [*__all__, "YAMLSettings", "YAMLSettingsConfigDict", "YAMLSettingsSource"]






