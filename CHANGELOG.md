# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-28

First public release.

### Added

- The `retvana` package: the year-by-year projection engine, a vectorized engine for many paths, the
  property sale and purchase model with legacy scenarios and a mean-reversion recovery model, the
  property and market-risk Monte Carlo analyses, the retirement-year comparison, the withdrawal
  strategy search, the sustainable spending solver and the Excel export. Rules are 2026 federal and
  Ontario values.
- The Streamlit app (`app.py`), with plans loaded from and saved to a private data directory
  (`RETVANA_DATA_DIR`, or the platform user data directory). An unreadable saved plan gives a warning
  and a fallback to the example household, and the file is left untouched.
- A synthetic example household (`example_plan()`, `examples/example_household.json`).
- Plain-script model checks, a regression golden generated from the example household, a headless smoke
  test, and `make verify` to run them all.
- Docker and Docker Compose deployment bound to localhost, run with `make up`.
- Leak guards: gitleaks, a forbidden-file check, a commit email check and a release gate, in pre-commit
  hooks and CI.
- The engine baseline spec, Kiro steering files, and the project docs.

[0.1.0]: https://github.com/brentwolfram/retvana/releases/tag/v0.1.0
