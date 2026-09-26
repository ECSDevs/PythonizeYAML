"""Standalone smoke check for the pythonizeyaml native extension.

Run it against the currently installed extension after building it:

    poetry run maturin develop
    poetry run python smoke_check.py

It round-trips every valid fixture under ``tests/fixtures/*.yaml`` and asserts
the output is byte-identical to the source, then runs a few representative
load/dump value checks. Each check prints PASS or FAIL and the script exits
with status 1 if anything failed.
"""

from __future__ import annotations

import pathlib
import sys

import pythonizeyaml as py

FIXTURES_DIR = pathlib.Path(__file__).parent / "tests" / "fixtures"


def check_round_trip(path: pathlib.Path) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        output = py.dump(py.load(source))
    except py.ComposerError:
        # Multi-document streams need the *_all spellings.
        output = py.dump_all(py.load_all(source))
    if output != source:
        raise AssertionError(
            f"round trip is not byte-identical ({len(source)} -> {len(output)} bytes)"
        )


def check_safe_load_values() -> None:
    data = py.safe_load("count: 3\nname: plain\nratio: 1.5\n")
    assert data == {"count": 3, "name": "plain", "ratio": 1.5}, repr(data)


def check_dump_layout() -> None:
    text = py.dump({"a": 1, "b": [1, 2]})
    assert text == "a: 1\nb:\n- 1\n- 2\n", repr(text)


def check_safe_mode_rejects_object_tag() -> None:
    try:
        py.safe_load('!!python/object/apply:os.system ["echo hi"]\n')
    except py.ConstructorError:
        return
    raise AssertionError("safe_load accepted a !!python/object tag")


def check_load_refuses_multi_document() -> None:
    try:
        py.load("---\na: 1\n---\nb: 2\n")
    except py.ComposerError:
        return
    raise AssertionError("load accepted a multi-document stream")


VALUE_CHECKS = [
    ("safe_load resolves plain scalars", check_safe_load_values),
    ("dump uses PyYAML block layout", check_dump_layout),
    ("safe_load rejects python object tags", check_safe_mode_rejects_object_tag),
    ("load refuses multi-document streams", check_load_refuses_multi_document),
]


def run(label, check) -> bool:
    try:
        check()
    except Exception as exc:
        print(f"FAIL {label}: {type(exc).__name__}: {exc}")
        return False
    print(f"PASS {label}")
    return True


def main() -> int:
    print(f"pythonizeyaml {py.__version__} from {py.__file__}")
    failures = 0

    fixtures = sorted(FIXTURES_DIR.glob("*.yaml"))
    if not fixtures:
        print(f"FAIL fixture corpus: no fixtures found under {FIXTURES_DIR}")
        failures += 1
    for path in fixtures:
        if not run(f"round trip {path.name}", lambda p=path: check_round_trip(p)):
            failures += 1

    for label, check in VALUE_CHECKS:
        if not run(label, check):
            failures += 1

    if failures:
        print(f"\n{failures} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
