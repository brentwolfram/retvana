# Product: retvana

retvana is a retirement drawdown planner for a two-person Canadian household. It projects the
household's accounts, taxes, benefits and property decisions year by year, so a household can compare
retirement years, withdrawal strategies and property scenarios side by side. It runs locally as a
Streamlit app, with an Excel export for sharing a scenario.

## Who it is for

- Households planning their own retirement who want a transparent, inspectable model.
- Contributors who want to extend or correct the model, under the rules in `CONTRIBUTING.md`.

It is not financial advice, and it is not a tool for advisers to run on client data.

## Scope

- Two people, keyed `P1` and `P2`, with RRSP/RRIF, LIRA, DC pension, TFSA and non-registered accounts.
- 2026 Ontario and federal tax rules, CPP and OAS (including the OAS clawback), RRIF minimums, LIRA
  unlocking and survivor rules.
- Optional employee stock options, consulting income (direct or through a corporation), and the sale of
  properties into a replacement home, under fixed scenarios or a mean-reversion model.
- Deterministic projections, a vectorized engine for many paths, Monte Carlo property outcomes and a
  retirement-year comparison grid.
- Plans are JSON files saved in the user's Data_Dir (`RETVANA_DATA_DIR`, or the platform user data
  directory), never in the repository.

## Non-goals

- Other provinces, other tax years, or more than two people (not yet modelled; see
  `docs/assumptions.md`).
- Accounts, logins, hosting or any network service: the App binds to localhost by design.
- Investment, tax or legal advice.

## Personal data

No personal data goes anywhere in this repository: code, checks, goldens, examples, docs, specs, issues,
pull requests or commit messages. The only built-in household is the synthetic Example_Plan
(`example_plan()`, `examples/example_household.json`). Use generic names ("Person 1", "Property 2") and
round example values. Real plans live only in the Data_Dir.
