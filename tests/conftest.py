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

"""Shared fixtures and helpers for the pythonizeyaml test suite.

Valid fixtures live directly in ``tests/fixtures/`` and are the corpus used by the
byte-identical round-trip test. Malformed inputs live in
``tests/fixtures/invalid/`` so they are never swept into that corpus.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
INVALID_DIR = FIXTURES_DIR / "invalid"

# Every valid fixture, sorted for stable test ids.
FIXTURE_FILES: List[Path] = sorted(FIXTURES_DIR.glob("*.yaml"))
FIXTURE_IDS: List[str] = [path.name for path in FIXTURE_FILES]


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def invalid_dir() -> Path:
    return INVALID_DIR


@pytest.fixture(scope="session")
def read_fixture(fixtures_dir: Path):
    """Return ``read_fixture(name) -> str`` for a valid fixture file."""

    def _read(name: str) -> str:
        return (fixtures_dir / name).read_text(encoding="utf-8")

    return _read


@pytest.fixture(params=FIXTURE_FILES, ids=FIXTURE_IDS)
def fixture_path(request: pytest.FixtureRequest) -> Path:
    """Parameterize a test over every valid fixture file."""
    return request.param


@pytest.fixture
def fixture_text(fixture_path: Path) -> str:
    return fixture_path.read_text(encoding="utf-8")