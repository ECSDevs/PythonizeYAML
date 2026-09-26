# Contributing to pythonizeyaml

Thanks for your interest in contributing! This document describes the project
layout, how to build and test a development checkout, and what to include when
submitting changes.

English | [简体中文](CONTRIBUTING.zh_CN.md)

## Project Structure

- `src/pythonizeyaml/`: Python API, round-trip container wrappers, errors, and configuration.
- `rust/src/`: custom Rust lexer/parser, lossless model, resolver, emitter, and PyO3 bridge.
- `tests/`: pytest coverage and YAML fixtures; malformed fixtures live in `tests/fixtures/invalid/`.
- `docs/`: VuePress documentation site; English pages under `docs/`, Chinese pages under `docs/zh_CN/`.
- `.github/workflows/`: test and wheel-release automation.

## Development Setup

Python 3.10+, Rust 1.83+, and Poetry are required.

```console
poetry install                              # install Python dependencies
cargo test --manifest-path rust/Cargo.toml --no-default-features  # run Rust unit tests
poetry run maturin develop                  # build the native extension
poetry run pytest                           # run Python tests
poetry build                                # build the Python wheel/sdist
```

Run `poetry run maturin develop` after changing any Rust code. Python-only
edits are picked up from the editable checkout without rebuilding.

## Documentation

The documentation site is built with VuePress and pnpm 12.6.0.

```console
pnpm install --frozen-lockfile  # install documentation dependencies
pnpm docs:build                 # build the documentation site
```

The built site is written to `docs/.vuepress/dist`.

## Coding Style

- Follow PEP 8 in Python and standard `cargo fmt` formatting in Rust.
- Use four-space indentation in Python, `snake_case` for functions and
  modules, `PascalCase` for types, and `UPPER_SNAKE_CASE` for constants.
- Keep public Python type hints, and propagate Rust errors through `Result`.
- Match the style of nearby code and avoid unrelated formatting changes.

## Testing Guidelines

- Use pytest for Python behavior and Rust unit tests for parser internals.
- Name test files `test_<feature>.py` and test functions `test_<behavior>`.
- Every preservation, numeric, tag, alias, or mutation change should include a
  focused regression test.
- Round-trip tests should assert exact source text where applicable.
- Add malformed YAML inputs under `tests/fixtures/invalid/`.
- Documentation changes must be made in both languages: keep `docs/zh_CN/` in
  sync with `docs/`, and `README.zh_CN.md` in sync with `README.md`.

## Reporting Issues

When filing a bug report, include a minimal YAML snippet that reproduces the
problem, the expected behavior, the actual behavior, and your Python version.
For round-trip or formatting issues, show the original text, the mutated
code, and the dumped output.

## Submitting Changes

- Keep commit subjects concise and imperative (for example, `fix broken
  python 3.10` or `docs: fix 404 assets`).
- Pull requests should describe the behavior change, list the test commands
  you ran, and note any compatibility or security impact.
- For formatting changes, include before/after YAML examples.

## Security & Compatibility

- Use `safe_load`/`safe_load_all` for untrusted input in examples and tests.
- Do not weaken unknown-tag rejection or expose native parser exceptions
  directly.
- Preserve the documented PyYAML-compatible public API unless a change is
  explicitly approved in the associated issue or discussion.
