# Tasks: retvana engine baseline

All tasks are complete. They were done on the original private code before the open-source Migration
and are restated here against the retvana names; the checks they added moved to this repository
unchanged in substance and were rebased on the Example_Plan.

These tasks only add checks. None of them change model behaviour. If a check shows that the code
differs from `requirements.md`, stop and decide which one is wrong: either fix the code in a
separate change, or correct the requirement. Do not adjust the check to fit the code.

Each new check is a script in `scripts/`. It follows the existing pattern:
- hand calculations written out from the rule;
- a small plan built in the check, or `example_plan()`;
- at most 200 Monte Carlo paths;
- a PASS/FAIL line per assertion and a non-zero exit on failure.

- [x] 1. Verification runner
  - Add `scripts/verify.py` to run every `*_check.py` and `smoke_test.py` in turn, print a summary
    table with the time taken, and exit non-zero if any check fails.
  - Add `make verify` to the Makefile. It runs on the host venv, not in the container.
  - _Requirements: 20.5_

- [x] 2. `plan_check.py`
  - 2.1 Saving to JSON and loading back gives an equal plan, for both `example_plan()` and the
    app defaults (`fresh_plan()` settings).
  - 2.2 An unknown top-level key is ignored. A missing key takes its default.
  - 2.3 The end year is the second death year with life expectancy on, and `fixed_end_year` with it
    off.
  - 2.4 `plan.copy()` is independent: changing the copy leaves the original unchanged.
  - _Requirements: 1.1, 1.2, 1.5_

- [x] 3. `property_check.py`
  - 3.1 The mortgage balance at sale is checked against a hand amortization with monthly
    compounding, the current term and then the renewal rate.
  - 3.2 The waterfall is checked by hand: commission with HST, capital gains tax on a property that
    is not a principal residence with the ACB set, land transfer tax just below and just above each
    bracket edge, and the surplus sign.
  - 3.3 For all four legacy scenarios, the factor matches the formula. The townhouse stays at
    today's price when "follows the market" is off.
  - 3.4 The recovery model with no shocks matches the closed recurrence. The sale discount is applied
    to the studio only.
  - 3.5 Common random numbers: `simulate` gives identical values for a shared year whether it is
    asked for horizon 2030 or 2045 (P5).
  - 3.6 On the median path, the surplus from `waterfall` equals `surplus_distribution` path by path
    on a 50-path run (rule coded twice).
  - 3.7 `monte_carlo` picks, for P10, P50 and P90, the path at that percentile of surplus.
  - _Requirements: 3, 4, 5; design P5 and the rules-coded-twice table_

- [x] 4. `tax_check.py`
  - 4.1 `income_tax` matches hand values at $0, at the BPA, at each threshold ±$1 and at $500K.
  - 4.2 The BPA and additional personal amounts are credited at the lowest rate. The dividend credit
    cannot take the tax below 0.
  - 4.3 The brackets are indexed to the retirement year and then by inflation each year (read back
    from the `thr*` columns).
  - 4.4 The taxable income identity (Req 8.4) holds in every row of a plan with consulting and
    corporate dividends.
  - _Requirements: 8_

- [x] 5. `benefits_check.py`
  - 5.1 The CPP early and late factors are correct at 60, 65 and 70. The contributory factor is
    correct with and without consulting years.
  - 5.2 OAS is checked for deferral to 70, the 10% increase at 75, and inflation indexing.
  - 5.3 The OAS clawback uses the previous year's taxable income, including the extra registered draw
    when accurate extra tax is on. It is capped at the gross OAS.
  - _Requirements: 11_

- [x] 6. `projection_check.py`
  - 6.1 Spending switches phase after year 15 and is multiplied by the survivor share after the
    first death.
  - 6.2 The draw cascade order is checked, including the rule that non-registered is drawn all or
    nothing, the $0.01 TFSA threshold, and extra registered split by balance.
  - 6.3 The TFSA top-up room rises in $500 steps, and only living people get room. The surplus goes
    to the survivor.
  - 6.4 The RRIF factors match `RRIF_FACTORS`, including the inherited pre-2015 table from 71.
    Person 1 starts at retirement. Person 2 starts at the later of retirement and age 55.
  - 6.5 The "defer" strategy has no minimum until 72. The "bracket" fill formula is checked by hand.
    The optimizer grid is 17 targets × 3 ages.
  - 6.6 The estate is checked by hand. `estate_after_tax` equals the inline formula in
    `_market_success` on the same final row (rule coded twice).
  - 6.7 Raising the balance of Person 2's non-registered account ("Sam non-registered" in the
    Example_Plan) never lowers total capital in any year, over a sweep of 10 values, in legacy and
    recovery modes (P2). *Amended by nonreg-accounts* (was: raising `base_nonreg_p2`).
  - 6.8 Each analysis entry point leaves its input plan unchanged (P6).
  - _Requirements: 6, 7, 9.1–9.5, 9.7, 17; design P2, P6_

- [x] 7. `market_check.py`
  - 7.1 The median retirement return across paths is within tolerance of `return_rate`.
  - 7.2 The first-year shock changes only the first retirement-year return.
  - 7.3 Common random numbers across retirement years: shock *t* is the same calendar year for 2030
    and 2033.
  - 7.4 With volatility off, `_starts_for_year` equals `starting_position` (rule coded twice).
  - 7.5 The year-comparison columns are correct for each mode: legacy, recovery, and with market
    risk.
  - _Requirements: 14, 15; design P5_

- [x] 8. Add a monotonicity sweep to `spending_check.py`
  - Over scales 0.5–2.0, the estate never rises and "money lasts" never switches from fail back to
    pass (P3).
  - Record in the check that the spending solver ignores `success_floor` (inherited inconsistency).
  - _Requirements: 16; design P3_

- [x] 9. `export_check.py`
  - The sheet names are correct for legacy mode, recovery mode, market risk on, and a strategy table
    present.
  - The Summary contains the life expectancy, strategy, market risk and spending solver entries.
  - The workbook holds no formulas.
  - _Requirements: 18_

- [x] 10. `deploy_check.py` (static file checks)
  - `docker-compose.yml` publishes `127.0.0.1:8501`, is read-only, drops capabilities and mounts
    the host Data_Dir.
  - The Dockerfile runs as a non-root user.
  - `.streamlit/config.toml` sets `server.address = "localhost"`.
  - _Requirements: 19.3, 19.4_

- [x] 11. Run `make verify`, confirm everything passes, and record the result
  - Fix any mismatches found by the steps above, either in the code (separate change) or in the
    requirements. Note each one under a "Findings" heading in this file.
  - _Requirements: 20_

## Findings

- **Finding 1 (task 3): Req 5.1 drift term.** The requirement said the recovery recurrence adds `g`;
  `property_model.simulate` adds `ln(1 + g)`. By 2045 the two differed by up to 0.26% on the
  properties and the townhouse. The requirement was corrected to `ln(1 + g)`, which makes the value
  grow at the same (1 + g) rate as fair value. No code change.
- **Finding 2 (task 3): LTT above $3M.** The land transfer tax brackets stop at $3M, so no tax is
  charged on the part of a price above $3M, while real Ontario LTT continues at 2.5%. Req 3.5 does
  not cover this. Left open; no change made. `property_check.py` records the current behaviour.
- **Finding 3 (task 8): P3 after depletion.** P3 as first written ("a higher spending scale never
  raises the estate") failed, but only at scales where the money had already run out: with both the
  spreadsheet settings and the app defaults, a step up in scale past depletion raised a small leftover
  estate slightly. The cause is leftover non-registered money that is never drawn under the inherited
  all-or-nothing rule (Req 7.2.1 / 7.5). While the money lasts the estate never rises, and "money
  lasts" never goes from fail back to pass. The spending solver is not affected because its test also
  requires the money to last. Resolution: P3 narrowed in design.md to "while the money lasts"; no
  code change. `spending_check.py` gates on the narrowed P3 and reports the strict sweep as an
  informational "(inherited)" line. The check also records the inherited `success_floor`
  inconsistency: the solver gives the same scale with or without a floor, while `_run_year` fails.
- **Finding 4 (task 9): Req 18.1 chart location.** The requirement said the Cash flow sheet carries
  the chart. `export.py` places the "Total capital and expenses" chart on the Summary sheet, under the
  property sale table, as a front-page overview; its series read from the Cash flow sheet. The
  requirement was corrected to put the chart on Summary (and to name the Market risk chart). No code
  change. `export_check.py` checks that the Summary chart's series all reference `'Cash flow'!`. The
  requirement does not fix the sheet order (Market risk and Withdrawals come before Compare years), so
  the check compares sheet names only.
- **Finding 5 (tasks 4–7): requirement wording clarifications.** The checks showed five places
  where the requirement wording was looser than the code. Each was corrected to state what the code
  already does and the checks already assert. No code change.
  - Req 8.4: OAS enters taxable income net of the clawback. "Registered draws assigned to the
    person" means the planned draws after pension splitting. Extra registered draws are taxed
    separately, as the tax with the draw minus the tax without it (or at the top rate).
  - Req 11.4: the clawback threshold is indexed to the income year (the previous year).
  - Req 9.5: under "bracket", minimums start at 72, as under "defer". With fill-until 64, nothing
    is planned at ages 65–71.
  - Req 7.2.2: a TFSA draw is capped at the TFSA balance plus that year's return.
  - Req 15: "first-year draw" is the first-year expense / capital ratio.
- **Finding 6 (task 6): P6 and `sync_end_year`.** `market_shocks` and `project` re-derive
  `end_year` on the plan passed in. A plan whose `end_year` is out of date is therefore corrected in
  place, which strictly counts as a change under P6. P6 was checked on plans whose end year was
  already up to date. Left open; no change made.
- **Finding 7 (tasks 6, 7, 9): coverage gaps.** The comparison table the app shows with market risk
  on is merged inside `app.py`'s `compute()`, using only the success rate and P10/P50 columns.
  `market_check.py` tests `analysis.market_compare` and `export_check.py` rebuilds the merge, but the
  app's own merge is covered only by `smoke_test.py`. Also, the bracket strategy's "capped at
  balance + growth" branch is not exercised by `projection_check.py`. Left open; no change made.

### Verification result

October 2026, on the original code: `make verify` ran 15 checks, the smoke test and the spreadsheet
parity check included, and all passed in about a minute. The spreadsheet parity check was a one-time
Migration check and is not part of this repository; here `regression_check.py` against the
Example_Plan's regression golden takes its place, and `make verify` runs the checks in `scripts/`.
