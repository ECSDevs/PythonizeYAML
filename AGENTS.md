# Repository Guidelines

## Project Structure & Module Organization

- `src/pythonizeyaml/`: Python API, round-trip container wrappers, errors, and configuration.
- `rust/src/`: custom Rust lexer/parser, lossless model, resolver, emitter, and PyO3 bridge.
- `tests/`: pytest coverage and YAML fixtures; malformed fixtures live in `tests/fixtures/invalid/`.
- `.github/workflows/`: test and wheel-release automation.

## Build, Test, and Development Commands

Use Python 3.10+, Rust 1.83+, and Poetry:

```console
poetry install                              # install Python dependencies
cargo test --manifest-path rust/Cargo.toml --no-default-features # run Rust unit tests
poetry run maturin develop                  # build the native extension
poetry run pytest                            # run Python tests
poetry build                                 # build the Python wheel/sdist
```

Run `maturin develop` after changing Rust code. Python-only edits are picked up
from the editable checkout without rebuilding.

## Coding Style & Naming Conventions

Follow PEP 8 and standard Rust formatting (`cargo fmt`). Use four spaces in
Python and `snake_case` functions/modules, `PascalCase` types, and
`UPPER_SNAKE_CASE` constants. Keep public Python type hints and Rust `Result`
error propagation. Match nearby code and avoid unrelated formatting changes.

## Testing Guidelines

Use pytest for Python behavior and Rust unit tests for parser internals. Name
files `test_<feature>.py` and functions `test_<behavior>`. Every preservation,
numeric, tag, alias, or mutation change should include a focused regression.
Round-trip tests should assert exact source text where applicable. There is no
configured coverage threshold.

## Commit & Pull Request Guidelines

This checkout has no Git history, so no established message convention is
available. Use concise imperative subjects. Pull requests should describe the
behavior change, list test commands run, note compatibility or security impact,
and include before/after YAML for formatting changes.

## Security & Compatibility

Use `safe_load`/`safe_load_all` for untrusted input. Do not weaken unknown-tag
rejection or expose native parser exceptions directly. Preserve the documented
PyYAML-compatible public API unless a change is explicitly approved.
