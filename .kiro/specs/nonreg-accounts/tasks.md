# Implementation Plan: nonreg-accounts

## Overview

The plan follows the order the design requires. A behaviour change starts with a spec change, so the
engine-baseline amendments come first. Then the code, from the bottom of the dependency direction up:
`config.py`, `engine.py`, `analysis.py`, `export.py`, `app.py`. Then the Example_Plan and the example
file, then the checks, then the golden procedure of Requirement 6, then the docs, the CHANGELOG and
`structure.md`, and a final `make verify`.

Between the Example_Plan change (task 7) and the golden regeneration (task 10), `regression_check.py`
fails its "Example_Plan hash matches the golden" line. That is expected. Every other check must pass at the
checkpoint (task 9).

The golden procedure has a stop: if any row or column comparison fails against the existing golden, do not
regenerate it. Find the cause and, if the change is intended, write the cause and the justification into
this spec first (Req 6.5).

Property loops are seeded loops in the plain check scripts, with the edge cases, seeds and failure-line
format in the design's "Seeds, edge cases and failure lines". No task is optional.

## Tasks

- [x] 1. Amend the Baseline_Spec
  - [x] 1.1 Amend `.kiro/specs/engine-baseline/requirements.md`
    - Requirement 1.2: append the "Amended by nonreg-accounts" paragraph on converting a non-zero
      `base_nonreg_p2` on load
    - Requirement 2.1: replace the criterion with the FV rule for every kind, `registered`, `tfsa` or
      `nonreg`, with no tax on non-registered growth before retirement, marked as a simplification
    - Requirement 2.3: replace the criterion with the N1/N2 pool rules (`nonreg_p2`, `nonreg_p1`,
      `shortfall_from_p1`), with no reference to `base_nonreg_p2`
    - Requirement 14.2: replace the second sentence so non-registered accounts use their own rate and
      volatility
    - Use the exact text in the design's "Baseline_Spec amendments"; mark each "Amended by
      nonreg-accounts"; leave Requirements 6.3, 6.4, 7.2, 7.4, 10.2 and 17.1 unedited
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6_
  - [x] 1.2 Amend `.kiro/specs/engine-baseline/design.md` and `tasks.md`
    - `design.md` Data model paragraph: kinds `registered`/`tfsa`/`nonreg`; drop `base_nonreg_p2` from the
      scalar list and add the conversion sentence
    - `tasks.md` item 6.7: the sweep of Person 2's non-registered account balance, marked "Amended by
      nonreg-accounts"
    - Leave the `open-source-release` spec as written
    - _Requirements: 9.5, 9.6_

- [x] 2. Update `src/retvana/config.py`
  - [x] 2.1 Add `ACCOUNT_KINDS` and `check_account_kind()`
    - `ACCOUNT_KINDS = ('registered', 'tfsa', 'nonreg')` above `Account`; `check_account_kind(account)`
      raises `ValueError` naming the account and the kind, with the message in the design
    - Update the `Account.kind` comment; the loader does not call the validator
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 2.2 Remove `Plan.base_nonreg_p2` and add the Legacy_Base conversion
    - Delete the `base_nonreg_p2` field
    - Add `LEGACY_NONREG_KEY` and `_legacy_nonreg_account(plan, balance)`: stem "<Person 2's name>
      non-registered" or "Person 2 non-registered" with no `P2` person or an empty name; smallest free
      " (k)" suffix, k ≥ 2; balance as given, return 0.0, contribution 0.0, "TFSA limit" off, volatility 0.0
    - At the end of `Plan.from_dict`, after the existing loop builds the Plan, append the account when the
      key is present, not `None` and `float(value) != 0`; never mutate the input dictionary; let a
      non-numeric value raise `TypeError` or `ValueError`
    - _Requirements: 4.1, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 3. Update `src/retvana/engine.py`
  - [x] 3.1 Sum non-registered accounts in `starting_position()`
    - Add `nonreg_total_p1` and `nonreg_total_p2` to `Start` after `shortfall_from_p1`
    - Call `check_account_kind(a)` inside the existing FV loop, before any FV
    - `tot(owner, kind)` as a left-to-right `sum(..., 0.0)`; `n1`, `n2`; `after = n2 + wf.surplus`;
      `nonreg_p1 = options + n1 + min(0.0, after)`, `nonreg_p2 = max(0.0, after)`,
      `shortfall_from_p1 = -min(0.0, after)`; registered and TFSA totals in the same order as today
    - _Requirements: 1.3, 1.4, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.5, 3.7_

- [x] 4. Update `src/retvana/analysis.py`
  - [x] 4.1 Sum non-registered accounts per path in `_starts_for_year()`
    - Key the totals by `(owner, kind)` for every kind in `ACCOUNT_KINDS`, imported from `config`
    - Call `check_account_kind(a)` before the account's growth; leave the growth loop unchanged
    - `after = tot[('P2', 'nonreg')] + surplus`; pools by the same rule elementwise, `nonreg_p1 = options +
      tot[('P1', 'nonreg')] + np.minimum(0.0, after)`; return `after` as today
    - _Requirements: 1.3, 1.5, 2.4, 2.5, 2.6, 3.4, 3.5_

- [x] 5. Update `src/retvana/export.py`
  - [x] 5.1 Retitle the inputs-sheet accounts table
    - `title='Investment accounts'`; rows unchanged (every account, `Type = a.kind`, value at retirement
      from `start.account_fv`)
    - _Requirements: 8.1, 8.2_

- [x] 6. Update `app.py`
  - [x] 6.1 The "Investment accounts" table, the removed input and the shortfall message
    - Title the table "**Investment accounts**"; the `Type` column is
      `SelectboxColumn(options=list(ACCOUNT_KINDS))` with `ACCOUNT_KINDS` imported from `retvana.config`;
      keep `r['Type'] or 'registered'` for new rows
    - Delete the `base_nonreg_p2` number input (key `w_bnr`); leave `cc[1]` empty
    - Replace the shortfall message with the design's text, reading `start.nonreg_total_p2`
    - _Requirements: 1.3, 4.2, 4.3, 7.1, 7.2, 7.3, 7.4_

- [x] 7. Update the Example_Plan and the example file
  - [x] 7.1 Replace the Example_Plan's base with "Sam non-registered"
    - In `example_plan()`, delete `p.base_nonreg_p2 = 150_000` and append `Account('Sam non-registered',
      'P2', 'nonreg', 150_000, 0.0, 0, False, 0.0)` after `'Sam TFSA'`, as the last account
    - _Requirements: 6.1, 11.5_
  - [x] 7.2 Regenerate `examples/example_household.json`
    - Run the command printed by `scripts/examples_check.py`; run the check (passes); `git diff` shows only
      the `base_nonreg_p2` line removed and the "Sam non-registered" account added
    - _Requirements: 6.2_

- [x] 8. Write and update the checks
  - [x] 8.1 Create `scripts/nonreg_check.py` with its harness and fixed lines
    - Harness: per-property seed constants from the design's seed table; random case `i` draws from
      `np.random.default_rng([seed, i])`; each loop runs its labelled edge cases, then at least 100 random
      cases; PASS and FAIL lines in the design's format (property number and part, seed, failing count,
      first three failing cases by index or edge label with `repr` inputs); exit non-zero on any failure
    - Plans built from `example_plan()` in legacy mode with the accounts replaced per case
    - Fixed lines: the Req 10.5 small plan ("P1 non-registered" $100,000 at 5% with $10,000 a year, "P2
      non-registered" $200,000 at 4% with "TFSA limit" on; hand FV within $0.01; pools for a $0 and a
      $3,000,000 townhouse price); the Req 1.3 static line; the Req 4.4 static scan for `base_nonreg_p2`
      with the allowed places listed in the design
    - _Requirements: 1.3, 4.4, 10.1, 10.5, 11.5_
  - [x] 8.2 Write Property 1 in `nonreg_check.py`
    - **Property 1: Unknown kinds are rejected by name** (seed 101)
    - Random kind strings not in `ACCOUNT_KINDS`, including `''`, `'Registered'`, `'TFSA'` and `'other'`;
      `starting_position()` and `_starts_for_year()` raise `ValueError` containing `repr(name)` and
      `repr(kind)`; the design's Property 1 edge cases first
    - **Validates: Requirements 1.4, 1.5, 10.8**
  - [x] 8.3 Write Property 2 in `nonreg_check.py`
    - **Property 2: Engine Retirement_Value is the hand FV** (seed 102)
    - 0–3 nonreg accounts per person, generator ranges as in the design; hand loop `bal = bal × (1 + rate)
      + pmt` vs `account_fv` and `nonreg_total_p1/p2` within $0.01; the Property 2 edge cases first
    - **Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3, 10.5**
  - [x] 8.4 Write Property 3 in `nonreg_check.py`
    - **Property 3: Vector growth follows each account's own rate and volatility** (seed 103)
    - 100 plans × 100 paths, retirement year 2027–2040; hand per-path loop vs `_starts_for_year` within
      relative 1e-9; with risk off, equal to the Engine on every path within $0.01; the Property 3 edge
      cases first
    - **Validates: Requirements 2.4, 2.5, 2.6**
  - [x] 8.5 Write Property 4 in `nonreg_check.py`
    - **Property 4: The pool split rule** (seed 104 for the Engine line, 204 for the vector line)
    - Engine: Property 2's generator with a drawn townhouse price in [0, 3,000,000]; assert at least 20
      cases with `N2 + S < 0` and 20 with `N2 + S > 0`; vector: per-path surplus `normal(0, 500_000, 100)`;
      the Property 4 edge cases first, including After_Surplus exactly 0
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 10.5**
  - [x] 8.6 Write Property 5 in `nonreg_check.py`
    - **Property 5: Registered and TFSA starts do not depend on non-registered accounts** (seed 105)
    - A random plan and the same plan with its nonreg accounts removed; registered and TFSA fields `==` in
      the Engine and `np.array_equal` per path; the Property 5 edge cases first
    - **Validates: Requirements 3.5**
  - [x] 8.7 Write Property 6 in `nonreg_check.py`
    - **Property 6: An Equivalent_Account reproduces the legacy base exactly** (seed 106 for the three
      random balances)
    - The design's grid: balances {−400,000, −1, 0, −0.0, 0.01, 150,000, 1,400,000} plus three draws,
      years 2027–2036, legacy and recovery, risk on and off, plus B = −S in the Engine part; steps 1 to 5
      of the grid (`Start ==`, `project` `.equals`, `Starts` and `project_many` with `np.array_equal` on
      100 paths)
    - **Validates: Requirements 3.6, 3.7, 6.3, 10.6**
  - [x] 8.8 Update `scripts/property_check.py`
    - Starting-position hand calculation: `n1`, `n2` from the hand FV totals of kind `nonreg`, `after = n2
      + surplus`, check the three pool fields and `nonreg_total_p1/p2`; drop "base" from the labels
    - _Requirements: 10.1, 10.2_
  - [x] 8.9 Update `scripts/market_check.py`
    - `hand_starts`: kinds `('registered', 'tfsa', 'nonreg')` written out; `after = tot[('P2', 'nonreg')] +
      surplus`; `nonreg_p1 = options + tot[('P1', 'nonreg')] + np.minimum(0.0, after)`; docstring cites
      Req 2.1/2.3 as amended; keep every existing comparison
    - _Requirements: 10.1, 10.3_
  - [x] 8.10 Update the P2 sweep in `scripts/projection_check.py`
    - **Property 10: More Person 2 non-registered money never lowers capital** (no seed: fixed sweep)
    - Set the balance of the Person 2 nonreg account instead of `p.base_nonreg_p2`; same 10 values from
      −$400K to $1.4M, legacy and recovery; label "raising Person 2's non-registered account"
    - **Validates: Requirements 3.1, 3.7, 10.4**
  - [x] 8.11 Write Property 7 and the fixed conversion lines in `scripts/plan_check.py`
    - **Property 7: The Legacy_Base conversion rule** (seed 107)
    - Legacy dictionaries from `example_plan().to_dict()` with random B, Person 2 name and pre-existing
      account names, as in the design; the Property 7 edge cases first (zero, `-0.0`, `None`, absent,
      negative, name collisions including " (2)", no Person 2, no people, empty name); check the accounts,
      the name, `to_dict()` without the key, and the input dictionary unchanged
    - Fixed lines: the pre-feature Example_Plan dictionary loads to a Plan equal to `example_plan()`;
      `'base_nonreg_p2' not in example_plan().to_dict()`; the existing unknown-key line unchanged
    - **Validates: Requirements 4.1, 5.1, 5.2, 5.3, 5.4, 5.5, 10.7**
  - [x] 8.12 Write Property 8 in `scripts/plan_check.py`
    - **Property 8: Conversion is idempotent** (seed 108)
    - `Plan.from_json(Plan.from_dict(d).to_json()) == Plan.from_dict(d)` with exactly one more account than
      `d['accounts']`; the Property 7 edge cases with a non-zero B first
    - **Validates: Requirements 5.6, 10.7**
  - [x] 8.13 Write Property 9 in `scripts/plan_check.py`
    - **Property 9: JSON round trip with non-registered accounts** (seed 109)
    - Plans with nonreg accounts for either person; `Plan.from_json(p.to_json()) == p` and the same text on
      a second serialization; the Property 9 edge cases first
    - **Validates: Requirements 5.7, 10.7**
  - [x] 8.14 Update `scripts/plan_io_check.py`
    - In a temporary Data_Dir, a legacy `plan.json` loads with the converted account and no error; the
      file bytes are unchanged; `save_plan` then writes the account and no `base_nonreg_p2`
    - _Requirements: 5.8, 10.7_
  - [x] 8.15 Update `scripts/export_check.py`
    - Inputs sheet A1 is "Investment accounts"; the rows hold exactly the plan's account names; the "Sam
      non-registered" row has Type `nonreg`, owner "Sam" and value 150,000 at 2032; no cell reads
      "Registered and TFSA accounts"
    - _Requirements: 8.1, 8.2, 10.9_
  - [x] 8.16 Update `scripts/smoke_test.py`
    - Default run: a markdown element reads "**Investment accounts**" and no number input has key `w_bnr`
    - A second `AppTest` run with a temporary Data_Dir holding a legacy `plan.json`: no exception, the
      session plan holds "Sam non-registered", the file bytes are unchanged
    - _Requirements: 4.2, 5.8, 7.1_

- [x] 9. Checkpoint: every check passes except the golden hash line
  - Run `scripts/verify.py`; every check passes except `FAIL  Example_Plan hash matches the golden` in
    `regression_check.py`. Ensure all tests pass, ask the user if questions arise.

- [x] 10. Run the golden procedure (Requirement 6)
  - [x] 10.1 Confirm the example file
    - Run `scripts/examples_check.py` (passes); `git diff examples/example_household.json` shows only the
      `base_nonreg_p2` line removed and the "Sam non-registered" account added. If the Example_Plan changed
      after task 7.2, regenerate with the same command first
    - _Requirements: 6.2_
  - [x] 10.2 Run `regression_check.py` against the existing golden, and stop on any other failure
    - `.venv/bin/python scripts/regression_check.py | grep '^FAIL'` prints exactly one line, `FAIL
      Example_Plan hash matches the golden`, and every row and column comparison passes
    - If any other line fails: stop. Do not regenerate the golden. Report the failing lines to the user,
      find the cause, and if the change is intended write the cause and the justification for the new
      values into this spec before going on
    - _Requirements: 6.3, 6.5_
  - [x] 10.3 Regenerate the golden and confirm the diff
    - Only after 10.2 passes: `.venv/bin/python scripts/make_regression_golden.py`
    - `git diff --numstat scripts/regression_golden.json` prints `1  1`, and `git diff -U0` shows only the
      `example_plan_sha256` value changed
    - _Requirements: 6.4_
  - [x] 10.4 Re-run `regression_check.py`
    - Every line passes
    - _Requirements: 6.3, 6.4_

- [x] 11. Update the docs, the CHANGELOG and `structure.md`
  - [x] 11.1 Update `docs/assumptions.md`
    - The "Return in retirement, all accounts" row; the new "Accounts before retirement" section; the new
      simplification row; the new "Plans saved before non-registered accounts" section; text as in the
      design, with only Example_Plan and generic names
    - _Requirements: 11.1, 11.2, 11.3, 11.5_
  - [x] 11.2 Update `CHANGELOG.md`
    - The `[Unreleased]` section above `[0.1.0]` as in the design
    - _Requirements: 11.4_
  - [x] 11.3 Update `.kiro/steering/structure.md`
    - Add `nonreg` to the list of model areas under "Where checks live"
    - _Requirements: 10.10_

- [x] 12. Final verification
  - [x] 12.1 Run `make verify`
    - Every check and the smoke test pass. Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 10.10_

## Notes

- No task is optional; the design marks none.
- Tasks 8.2 to 8.7 write to `nonreg_check.py` and tasks 8.11 to 8.13 to `plan_check.py`, so each runs in
  its own wave.
- Task 10.3 runs only when 10.2 passes. A failing row or column comparison in 10.2 stops the plan until
  this spec records the cause (Req 6.5).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "4.1", "5.1"] },
    { "id": 3, "tasks": ["6.1", "7.1"] },
    { "id": 4, "tasks": ["7.2"] },
    { "id": 5, "tasks": ["8.1", "8.8", "8.9", "8.10", "8.11", "8.14", "8.15", "8.16"] },
    { "id": 6, "tasks": ["8.2", "8.12"] },
    { "id": 7, "tasks": ["8.3", "8.13"] },
    { "id": 8, "tasks": ["8.4"] },
    { "id": 9, "tasks": ["8.5"] },
    { "id": 10, "tasks": ["8.6"] },
    { "id": 11, "tasks": ["8.7"] },
    { "id": 12, "tasks": ["10.1"] },
    { "id": 13, "tasks": ["10.2"] },
    { "id": 14, "tasks": ["10.3"] },
    { "id": 15, "tasks": ["10.4"] },
    { "id": 16, "tasks": ["11.1", "11.2", "11.3"] },
    { "id": 17, "tasks": ["12.1"] }
  ]
}
```
