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