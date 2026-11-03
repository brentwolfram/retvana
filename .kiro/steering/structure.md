# Structure

## Layout

```
src/retvana/          the package (src layout; import as `retvana`)
app.py                Streamlit entry point; imports only from retvana
scripts/              checks, verify runner, golden generator, leak guards
examples/             example_household.json = example_plan().to_json()
docs/                 assumptions.md, images/
.kiro/specs/          engine-baseline/ (the model's rules), open-source-release/
.kiro/steering/       these files
.github/              CI and release workflows, templates, dependabot, allowed-emails.txt
Dockerfile, docker-compose.yml, Makefile, pyproject.toml
```

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | Plan dataclasses, JSON round-trip, RRIF factors, `example_plan()` |
| `property_model.py` | property values, mortgages, the sale and purchase waterfall, legacy and recovery scenarios |
| `engine.py` | the year-by-year projection (`project`, `summary`), tax and benefit rules, column labels |
| `vector.py` | the projection run for many paths at once with numpy; `engine.project` is the reference |
| `analysis.py` | Monte Carlo property outcomes and the retirement-year comparison grid |
| `export.py` | Excel export of a scenario (values only, formatted, with charts) |
| `plan_io.py` | Data_Dir resolution, plan load with fallback, atomic save; the only code that touches the plan file |

## Dependency direction

```
config  <-  property_model  <-  engine  <-  vector  <-  analysis
                                   ^
                                export
plan_io -> config
app.py  -> analysis, engine, export, property_model, config, plan_io
```

- `config` imports nothing from the package. Lower modules never import higher ones, and nothing in
  `src/retvana` imports Streamlit.
- File I/O for plans goes through `plan_io` only.

## Where checks live

- `scripts/<area>_check.py`, one per model area (tax, benefits, property, projection, vector, survivor,
  spending, market, consulting, corp, export, plan), plus `regression_check.py`, `examples_check.py`,
  `plan_io_check.py`, `deploy_check.py`, the leak-guard checks and `repo_check.py`.
- `scripts/smoke_test.py` runs the App and the Excel export headless, with a temporary Data_Dir.
- New checks follow the `*_check.py` name so `verify.py` picks them up. Generators and the release gate
  do not use that suffix.
