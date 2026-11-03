# Requirements Document

## Introduction

Today the model holds non-registered money in one scalar, `Plan.base_nonreg_p2`: Person 2's
non-registered balance at the retirement year, which does not grow before retirement and takes no
contributions. Person 1 has no non-registered input at all; Person 1's non-registered pool at retirement
is only the employee stock option proceeds, less any property shortfall.

This feature folds all non-registered money for both people into the plan's accounts list. A new account
kind sits alongside `'registered'` and `'tfsa'`. Each non-registered account grows at its own rate and
takes its own contribution until retirement, under the same rule the other kinds already follow
(engine-baseline Requirement 2.1). At retirement each person's non-registered accounts sum into that
person's non-registered pool; the property surplus and the option proceeds flow into the pools as they do
today. From the retirement year on nothing changes: the pools are drawn, taxed, reinvested, rolled to the
survivor and counted in the estate under the existing rules.

`base_nonreg_p2` is removed from the Plan, the App, the checks and the docs. A saved plan that still
carries the key is converted on load into an equivalent Person 2 non-registered account, so no saved plan
loses money. The App's "Registered and TFSA accounts" table becomes "Investment accounts".

Code verified for this spec (branch `nonreg-accounts`, from main):

- `src/retvana/config.py`: `Account.kind` is `'registered'` or `'tfsa'`; `Plan.base_nonreg_p2: float =
  0.0`; `example_plan()` sets `p.base_nonreg_p2 = 150_000`; `Plan.from_dict` ignores unknown top-level
  keys.
- `src/retvana/engine.py` `starting_position()`: grows every account with `fv()`, then sums by
  `(owner, kind)` for `'registered'` and `'tfsa'` only, so an account of any other kind is silently
  dropped; `after = plan.base_nonreg_p2 + wf.surplus`, `nonreg_p2 = max(0, after)`,
  `nonreg_p1 = options + min(0, after)`, `shortfall_from_p1 = -min(0, after)`.
- `src/retvana/analysis.py` `_starts_for_year()`: the same rule per path; its totals dictionary has keys
  for `'registered'` and `'tfsa'` only, so an account of any other kind raises `KeyError`.
- `src/retvana/vector.py` reads only the `Starts` it is given and has no kind logic.
- `src/retvana/export.py`: the inputs sheet table titled "Registered and TFSA accounts", `Type` column =
  `a.kind`.
- `app.py`: the "Registered and TFSA accounts" data editor with `Type` options `['registered', 'tfsa']`;
  the "{Person 2} base non-registered" number input (minimum 0); the shortfall info message that quotes
  `plan.base_nonreg_p2`.
- Checks that read `base_nonreg_p2` or the kind list: `property_check.py` (starting position by hand),
  `market_check.py` (`hand_starts`), `projection_check.py` (the P2 sweep of `base_nonreg_p2` from
  −$400K to $1.4M). `examples/example_household.json` carries `"base_nonreg_p2": 150000`.
- `scripts/regression_golden.json` stores `example_plan_sha256`, the hash of `example_plan().to_json()`,
  and `regression_check.py` fails when the hash differs. Any change to `example_plan()` therefore
  requires regenerating the golden, even when every projection row is unchanged.

Exact equivalence: an account with a 0% return, no contribution and 0% volatility keeps its balance
unchanged to the retirement year in both engines. `fv(0, n, 0, B)` returns `B`, and the Monte Carlo
growth `exp(ln(1 + 0) + 0 × z) − 1` is exactly 0. So a Person 2 non-registered account with balance `B`
on those terms reproduces today's `base_nonreg_p2 = B`, bit for bit. Requirements 3, 5 and 6 rely on this.

### Resolved decisions

The user decided each question below. The requirements are written to these decisions and the
affected criteria are marked with the question number.

- **Q1. Kind value name.** Decided: `'nonreg'`, matching the existing `nonreg_p1` / `nonreg_p2` field
  names. The App and the export show the kind value as they do today (`registered`, `tfsa`, `nonreg`).
- **Q2. Tax on pre-retirement non-registered growth.** In retirement, 75% of the non-registered return
  is taxed every year (Req 6.4). The model computes no tax before retirement for any account. Decided:
  a non-registered account grows at its own rate before retirement with no tax deducted; a household
  that wants the drag reflects it in the account's growth rate, and docs/assumptions.md states this as a
  simplification. The alternative, taxing 75% of each year's pre-retirement return, needs a
  pre-retirement income and tax model that does not exist and is not part of this spec.
- **Q3. Conversion of a saved `base_nonreg_p2`.** Decided: one Person 2 non-registered account with
  balance = the saved value, return 0%, contribution 0, "TFSA limit" off, volatility 0%, named
  "<Person 2's name> non-registered" ("Person 2 non-registered" when the name is empty), with " (2)",
  " (3)" and so on added when the name is already taken. These terms reproduce today's results exactly;
  the user then edits the return and contribution in the App. A value of 0 adds no account. A negative
  value (possible in a hand-edited file, not from the App) converts as-is, since that also reproduces
  today's results.
- **Q4. Example_Plan account terms.** Decided: "Sam non-registered", Person 2, balance $150,000, return
  0%, contribution 0, volatility 0%. This keeps every regression row identical, so the golden changes only
  in its plan hash. The alternative, a growing account (for example 5%), would show the new feature in
  the example but change the golden rows and the example's results, and was not chosen. Growth of
  non-registered accounts is proved in a check on a small plan built in the check (Requirement 10), not
  through the Example_Plan.
- **Q5. "Contribute TFSA limit" on a non-registered account.** Today the flag is honoured on any kind,
  with no validation. Decided: no change; a non-registered account with the flag on contributes the TFSA
  limit, as a registered account would today.
- **Q6. Unknown kinds.** Today the Engine silently drops an account of an unknown kind (money vanishes)
  and the Vector_Start raises `KeyError`. Decided: both raise `ValueError` naming the account and the
  kind. Loading a plan file is unchanged (no kind validation at load), so a bad kind in `plan.json`
  surfaces when the projection runs.

## Glossary

- **Plan**: the `Plan` dataclass in `src/retvana/config.py` holding every model input.
- **Account**: an entry of `Plan.accounts`: name, owner (`'P1'` or `'P2'`), kind, balance at the current
  year, return rate until retirement, yearly contribution, "TFSA limit" flag and volatility.
- **Account_Kinds**: the accepted values of `Account.kind`: `'registered'`, `'tfsa'` and `'nonreg'`
  (Q1), defined once in `config.py`.
- **Non_Registered_Account**: an Account whose kind is `'nonreg'`.
- **Legacy_Base**: the `base_nonreg_p2` key in a saved plan JSON or plan dictionary written before this
  feature.
- **Plan_Loader**: `Plan.from_dict` and `Plan.from_json`, the only code that builds a Plan from saved
  data (`plan_io` and the examples go through them).
- **Engine**: `engine.starting_position()` and `engine.project()`, the reference projection.
- **Vector_Start**: `analysis._starts_for_year()`, the per-path starting position used by the Monte
  Carlo and retirement-year analyses before `vector.project_many()`.
- **Retirement_Value**: an Account's value at the retirement year: Excel `FV(rate, years, −contribution,
  −balance)` in the Engine; the year-by-year growth with the account's own rate and volatility in the
  Vector_Start.
- **Non_Registered_Total(P)**: the sum of the Retirement_Values of person P's Non_Registered_Accounts;
  0 when P has none.
- **Property_Surplus**: the waterfall surplus at the retirement year (engine-baseline Requirement 3), which
  may be negative.
- **Option_Proceeds**: `engine.options_net_proceeds()`, Person 1's after-tax employee stock option
  proceeds (engine-baseline Requirement 2.2).
- **After_Surplus**: Non_Registered_Total(P2) + Property_Surplus.
- **Non_Registered_Pool(P)**: the starting non-registered balance of person P in the projection
  (`nonreg_p1`, `nonreg_p2` on `Start` and `Starts`).
- **Equivalent_Account**: a Person 2 Non_Registered_Account with return 0%, contribution 0, "TFSA limit"
  off and volatility 0%.
- **App**: the Streamlit app in `app.py`.
- **Export**: the Excel export in `src/retvana/export.py`.
- **Example_Plan**: `example_plan()` in `config.py`, serialized in `examples/example_household.json`.
- **Regression_Golden**: `scripts/regression_golden.json`, written only by
  `scripts/make_regression_golden.py` and read by `scripts/regression_check.py`.
- **Baseline_Spec**: `.kiro/specs/engine-baseline/requirements.md` and its `design.md`.
- **Checks**: the `scripts/*_check.py` scripts run by `make verify`.

## Requirements

### Requirement 1: Non-registered account kind

**User Story:** As a planner, I want to enter each non-registered account for either person in the same
list as my RRSPs and TFSAs, so that all my investment money is in one place.

#### Acceptance Criteria

1. THE Plan SHALL accept `'nonreg'` as an Account kind alongside `'registered'` and `'tfsa'` (Q1).
2. THE Plan SHALL hold zero or more Non_Registered_Accounts for each of Person 1 and Person 2.
3. THE Engine, THE Vector_Start, THE App and THE Export SHALL take the accepted kinds from the single
   Account_Kinds definition in `config.py`.
4. IF an Account's kind is not in Account_Kinds, THEN THE Engine SHALL raise a `ValueError` that names
   the Account and the kind (Q6).
5. IF an Account's kind is not in Account_Kinds, THEN THE Vector_Start SHALL raise a `ValueError` that
   names the Account and the kind (Q6).

### Requirement 2: Growth and contributions before retirement

**User Story:** As a planner, I want my non-registered accounts to grow at their own return and take my
contributions until I retire, so that they are treated like my other accounts.

#### Acceptance Criteria

1. THE Engine SHALL compute the Retirement_Value of each Non_Registered_Account as Excel `FV(rate, years,
   −contribution, −balance)` with contributions at year end, the same rule as registered and TFSA
   Accounts.
2. WHERE a Non_Registered_Account has "TFSA limit" on, THE Engine SHALL use the plan's TFSA limit as the
   yearly contribution, the same rule as the other kinds (Q5).
3. THE Engine SHALL grow each Non_Registered_Account before retirement at the Account's return rate with
   no tax deducted (Q2).
4. WHERE pre-retirement market risk is on, THE Vector_Start SHALL grow each Non_Registered_Account with
   the Account's own return rate and volatility, driven by the same yearly shock as the other Accounts.
5. WHERE pre-retirement market risk is off, THE Vector_Start SHALL give each Non_Registered_Account the
   same Retirement_Value as the Engine on every path, within $0.01.
6. WHEN the retirement year changes (the retirement-year comparison, engine-baseline Requirement 15),
   THE Vector_Start SHALL grow each Non_Registered_Account to that retirement year.

### Requirement 3: Starting non-registered pools at retirement

**User Story:** As a planner, I want each person's non-registered accounts to start retirement in that
person's non-registered pool, with the property surplus and option proceeds flowing in as before, so that
the drawdown starts from the right balances.

#### Acceptance Criteria

1. THE Engine SHALL set Non_Registered_Pool(P2) = max(0, After_Surplus).
2. THE Engine SHALL set Non_Registered_Pool(P1) = Option_Proceeds + Non_Registered_Total(P1) +
   min(0, After_Surplus), so a property shortfall beyond Person 2's non-registered money is funded from
   Person 1.
3. THE Engine SHALL set `shortfall_from_p1` = −min(0, After_Surplus).
4. THE Vector_Start SHALL apply the rules of criteria 1 to 3 on every path, with each path's
   Retirement_Values and Property_Surplus.
5. THE Engine and THE Vector_Start SHALL compute the registered and TFSA starting balances from the
   registered and TFSA Accounts only, unchanged from today.
6. FOR ALL plans and retirement years, a plan with Legacy_Base = B and a plan identical except that the
   Legacy_Base is replaced by one Equivalent_Account of balance B, and with no Person 1
   Non_Registered_Accounts, SHALL produce equal starting positions (every field of `Start`, and every path
   of `Starts`), in legacy and recovery property modes, with pre-retirement market risk on and off.
7. FROM the retirement year on, THE Engine and THE vector engine SHALL apply the existing rules to the
   Non_Registered_Pools unchanged: one return for all accounts in a year (Req 6.3), 75% of the return
   taxable (Req 6.4), the all-or-nothing draw (Req 7.2), the surplus cross-allocation (Req 7.4), the
   survivor rollover (Req 10.2) and the estate (Req 17.1).

### Requirement 4: Removal of `base_nonreg_p2`

**User Story:** As a contributor, I want one way to enter non-registered money, so that the model has no
person-specific field for it.

#### Acceptance Criteria

1. THE Plan SHALL have no `base_nonreg_p2` field, and `Plan.to_json` SHALL emit no `base_nonreg_p2` key.
2. THE App SHALL show no "base non-registered" input.
3. WHEN `shortfall_from_p1` is greater than 0, THE App SHALL state the shortfall, Person 2's
   Non_Registered_Total it is measured against, and that it is funded from Person 1's non-registered
   money (option proceeds and Person 1's Non_Registered_Accounts).
4. THE `src/retvana` package, `app.py` and the Checks SHALL contain no reference to `base_nonreg_p2`
   other than the Plan_Loader conversion of Requirement 5 and the Checks that test it.

### Requirement 5: Loading a plan saved before this feature

**User Story:** As a planner with a saved plan, I want my base non-registered balance carried into the
new accounts list when I load the plan, so that I do not lose money or have to re-enter it.

#### Acceptance Criteria

1. WHEN the Plan_Loader reads data with a Legacy_Base other than 0, THE Plan_Loader SHALL append one
   Equivalent_Account with balance equal to the Legacy_Base to the Plan's accounts (Q3).
2. WHEN the Plan_Loader converts a Legacy_Base, THE Plan_Loader SHALL name the Equivalent_Account
   "<Person 2's name> non-registered", or "Person 2 non-registered" when the plan has no Person 2 or
   Person 2's name is empty (Q3).
3. IF the converted account name equals the name of an existing Account, THEN THE Plan_Loader SHALL add
   the smallest suffix " (2)", " (3)", … that makes the name unique (Q3).
4. WHEN the Plan_Loader reads data with a Legacy_Base equal to 0, or with no Legacy_Base, THE Plan_Loader
   SHALL add no Account.
5. WHEN the Plan_Loader reads data with a negative Legacy_Base, THE Plan_Loader SHALL convert the value
   as-is under criterion 1 (Q3).
6. FOR ALL plan data with a Legacy_Base, loading, serializing with `to_json` and loading again SHALL
   produce a Plan equal to the first load, with exactly one converted Account (idempotent conversion).
7. FOR ALL Plans containing Non_Registered_Accounts, `Plan.from_json(plan.to_json())` SHALL equal the
   Plan (round trip).
8. WHEN the App loads a `plan.json` that has a Legacy_Base, THE App SHALL leave the file unchanged on
   disk until the user clicks "Save as default".

### Requirement 6: Example_Plan, example file and Regression_Golden

**User Story:** As a contributor, I want the synthetic example to use the new account kind without
changing its results, so that the regression contract still holds.

#### Acceptance Criteria

1. THE Example_Plan SHALL replace `base_nonreg_p2 = 150_000` with one Equivalent_Account named "Sam
   non-registered" with balance $150,000 (Q4).
2. THE `examples/example_household.json` file SHALL equal `example_plan().to_json()` plus one trailing
   newline, regenerated with the command in `scripts/examples_check.py`.
3. WHEN the Example_Plan has changed and before the Regression_Golden is regenerated,
   `scripts/regression_check.py` run against the existing Regression_Golden SHALL pass every row and
   column comparison, and fail only the "Example_Plan hash matches the golden" line.
4. WHEN criterion 3 holds and `scripts/make_regression_golden.py` regenerates the Regression_Golden, THE
   Regression_Golden SHALL differ from the previous version in the `example_plan_sha256` value only.
5. IF any row or column comparison fails under criterion 3, THEN THE Regression_Golden SHALL stay
   unchanged until this spec states the cause and the justification for the new values.

### Requirement 7: App "Investment accounts" table

**User Story:** As a planner, I want one "Investment accounts" table where I choose each account's type,
so that I enter non-registered accounts the same way as the others.

#### Acceptance Criteria

1. THE App SHALL title the accounts table "Investment accounts".
2. THE App SHALL offer every value in Account_Kinds in the table's `Type` column.
3. WHEN the user adds a row without choosing a type, THE App SHALL give the Account the kind
   `'registered'`, as today.
4. WHEN the user edits a Non_Registered_Account's balance, growth, volatility or contribution, THE App
   SHALL use the edited values in the projection on the next rerun.

### Requirement 8: Excel export

**User Story:** As a planner sharing a scenario, I want the export to list my non-registered accounts with
the others, so that the shared workbook shows all inputs.

#### Acceptance Criteria

1. THE Export SHALL title the inputs sheet's accounts table "Investment accounts".
2. THE Export SHALL list every Account, including each Non_Registered_Account, with its owner, type,
   balance, growth rate, yearly contribution and Retirement_Value.

### Requirement 9: Amendments to the Baseline_Spec

**User Story:** As a maintainer, I want the behaviour change written into the baseline spec first, so
that the checks and the golden follow the spec and not the other way round.

#### Acceptance Criteria

1. THE Baseline_Spec SHALL amend Requirement 1.2 to state that a Legacy_Base is converted on load under
   this spec's Requirement 5, an exception to "unknown top-level keys are ignored".
2. THE Baseline_Spec SHALL amend Requirement 2.1 to apply the FV rule to every Account kind, including
   `'nonreg'`.
3. THE Baseline_Spec SHALL amend Requirement 2.3 to the rules of this spec's Requirement 3, criteria 1 to
   3, with no reference to `base_nonreg_p2`.
4. THE Baseline_Spec SHALL amend Requirement 14.2 to state that Non_Registered_Accounts also use their
   own rate and volatility before retirement.
5. THE Baseline_Spec SHALL replace the `base_nonreg_p2` mentions in its `design.md` and in
   `engine-baseline/tasks.md` item 6.7 with the Non_Registered_Account form.
6. THE Baseline_Spec SHALL mark each amended criterion "Amended by nonreg-accounts" and keep Requirements
   6.3, 6.4, 7.2, 7.4, 10.2 and 17.1 unchanged in substance.

### Requirement 10: Checks

**User Story:** As a maintainer, I want hand-calculated checks for the new rules, so that `make verify`
proves the feature and catches regressions.

#### Acceptance Criteria

1. THE Checks SHALL derive every expected value from the rule written out in the Check, with inputs from
   `example_plan()` or a small plan built in the Check, and never from the function under test.
2. THE `property_check.py` starting-position hand calculation SHALL compute Non_Registered_Total for each
   person by FV and apply Requirement 3, criteria 1 to 3.
3. THE `market_check.py` `hand_starts` SHALL include Non_Registered_Accounts in the per-path growth and
   apply Requirement 3, criteria 1 to 3, per path.
4. THE `projection_check.py` P2 sweep SHALL vary the balance of one Person 2 Equivalent_Account over the
   same 10 values from −$400K to $1.4M, in legacy and recovery modes, and check that total capital never
   falls in any year.
5. THE Checks SHALL verify, on a small plan with a Non_Registered_Account for each person at a non-zero
   return and contribution, that each Retirement_Value equals the hand FV within $0.01 and that the
   Non_Registered_Pools follow Requirement 3, criteria 1 to 3, for a positive and a negative
   Property_Surplus.
6. THE Checks SHALL verify Requirement 3, criterion 6, exactly (float equality), for the Engine over
   retirement years 2027 to 2036 and for the Vector_Start over the same years on at least 100 market paths,
   in legacy and recovery modes.
7. THE Checks SHALL verify Requirement 5, criteria 1 to 7, including a name collision and a plan with no
   people.
8. THE Checks SHALL verify Requirement 1, criteria 4 and 5, with an Account of kind `'other'`.
9. THE Checks SHALL verify that the Export's inputs sheet has the "Investment accounts" table with one row
   per Account, including a Non_Registered_Account.
10. WHEN all changes are in place, `make verify` SHALL pass.

### Requirement 11: Documentation

**User Story:** As a reader of the model, I want the docs to describe non-registered accounts as they now
work, so that the assumptions stay inspectable.

#### Acceptance Criteria

1. THE `docs/assumptions.md` file SHALL state that Non_Registered_Accounts grow at their own rate and
   take contributions until retirement, with no tax on that growth (Q2), and list this as a
   simplification.
2. THE `docs/assumptions.md` file SHALL state that one return applies to every account in retirement,
   including the non-registered pools, unchanged (Req 6.3).
3. THE `docs/assumptions.md` file SHALL describe the conversion of a saved `base_nonreg_p2` and its terms
   (Q3).
4. THE `CHANGELOG.md` file SHALL record the new account kind, the removal of `base_nonreg_p2`, the load
   conversion and the renamed "Investment accounts" table.
5. THE documentation, Checks, examples and this spec SHALL use only the synthetic Example_Plan names and
   generic names ("Person 1", "Person 2") with round values.

## Out of Scope

- Adjusted cost base tracking, realized capital gains, and the deemed disposition of non-registered gains
  at death.
- Per-account returns in retirement: one return applies to every account in a year (Req 6.3).
- Tax on non-registered growth before retirement.
- Separate non-registered pools per account after retirement: each person keeps one pool.
- Changes to the draw order, the all-or-nothing rule, the surplus cross-allocation, the TFSA top-up or the
  survivor rules.
- Validation of Account kinds or of the "TFSA limit" flag at load time.
