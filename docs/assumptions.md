# Model assumptions

This page summarizes what the retvana model assumes, where it simplifies, and what it does not model.
The full rules are in the engine baseline spec,
[.kiro/specs/engine-baseline/requirements.md](../.kiro/specs/engine-baseline/requirements.md) and
[design.md](../.kiro/specs/engine-baseline/design.md). "Req" numbers below refer to its requirements.

retvana is not financial advice. The rules below are a model of the tax and benefit system, not the
system itself.

## Tax year and province

- Tax rules, thresholds and benefit amounts are **2026 federal and Ontario** values: 9 combined federal +
  Ontario brackets, the basic personal amount, CPP (YMPE $74,600, YAMPE $85,000), OAS ($751.97/month,
  clawback threshold $95,323), the TFSA limit ($7,000), the land transfer tax brackets and the
  corporate rates.
- Brackets and the basic personal amount are indexed from 2026 to the retirement year (when "index
  brackets" is on, the default) and by inflation every later year (Req 8.2). Future legislative changes
  are not modelled.
- Only Ontario is modelled.

## Main economic assumptions

These are plan settings with these defaults; change them in the Inputs tab.

| Setting | Default |
|---|---|
| Return in retirement, all accounts | 5.5% a year (one rate for every account in a year, including both non-registered pools, Req 6.3) |
| Inflation, expense CPI and CPP inflation | 2.8% |
| Taxable share of non-registered returns | 75% |
| Go-go phase | 15 years of the go-go spending amount, then the later amount (Req 6.2) |
| Survivor spending | 70% of the couple's spending (Req 10.2) |
| End of plan | the second death when life expectancy is on, otherwise 2080 (Req 1.5) |
| Market risk | yearly volatility 10% around the plan return, seed 1971 (Req 14) |
| Property recovery model | per-type fair value, speed, growth, market beta and volatility; seed 2026 (Req 5) |

Two setting groups matter when reading results:

- **The spreadsheet settings** (the dataclass defaults, as in `example_plan()`): the legacy property
  mode, TFSA top-up, marginal-rate extra tax and life expectancy all off. With these, the engine
  reproduces the original spreadsheet it was ported from.
- **The app defaults** (`fresh_plan()` in `app.py`): the recovery property model, TFSA top-up,
  marginal-rate extra tax and life expectancy all on. The app starts here.

## Accounts before retirement

Each account, registered, TFSA or non-registered, grows from its current balance at its own rate until
the retirement year, with its yearly contribution added at year end (Req 2.1). With market risk on,
each account also has its own volatility on the shared yearly shock (Req 14.2). At retirement each
person's non-registered accounts are added into one non-registered pool. The property surplus goes
into Person 2's pool; a shortfall larger than Person 2's non-registered money is taken from Person 1's
pool, which also holds the employee stock option proceeds (Req 2.3). From retirement on, one return
applies to every account in a year (Req 6.3).

## Inherited rules

These rules were carried over from the original spreadsheet and kept so the port could be proved
against it. Each is marked **(inherited)** in the baseline spec and needs a deliberate spec change to
alter.

| Rule | Where | Effect |
|---|---|---|
| Non-registered returns are treated as cash received in the year, with 75% of the return taxable every year | Req 6.4 | No tracking of the adjusted cost base or of when gains are realized; tax on non-registered growth is paid every year rather than on sale |
| Non-registered is drawn only if it can cover the whole shortfall | Req 7.2.1 | If it cannot, the year is funded from the TFSA and registered accounts instead, and the leftover non-registered money is never drawn |
| Extra registered withdrawals are taxed at the top rate (53.53%) | Req 7.3 | Overstates tax on extra draws, unless "accurate extra tax" is on, which uses the person's actual marginal tax instead |
| Pre-2015 RRIF minimum factors from age 71 | Req 9.1 | Forces larger RRIF withdrawals than current law (see the table below); overstates taxable income and OAS clawback from 71, most of all under the "defer" and "bracket" strategies |
| The tax on an extra registered draw is paid from non-registered when that account can pay it, otherwise from registered | design, draw cascade | Follows the original spreadsheet's next-year opening balance formula |
| The spending solver's "money lasts" test ignores `success_floor` | design, rules coded twice | The year comparison tests capital against max(`success_floor`, spending), the solver against spending only, so a floor changes one and not the other |
| Employee stock options belong to Person 1 | Req 2.2 | Not a plan setting; the option proceeds always go to Person 1's non-registered account |

Two further formulas also come from the original spreadsheet unchanged: the cross-allocation of a
surplus between the two non-registered accounts (Req 7.4) and the pension income splitting formula
(Req 9.6).

## Simplifications

Each is marked **(simplification)** in the baseline spec.

| Simplification | Where | Effect |
|---|---|---|
| Capital gains tax on a property sale uses the top marginal rate (53.53%) in a single year | Req 3.4 | Overstates the tax for a household whose income in the sale year is below the top bracket; no spreading of gains |
| Municipal land transfer tax luxury tiers above $3M are not modelled | Req 3.5 | Provincial and municipal brackets are identical up to $3M, and no tax is charged on the part of a price above $3M (Finding 2 in the baseline tasks) |
| Capital cannot reach exactly $0 | Req 7.5 | Because of the all-or-nothing non-registered rule, "running out" is tested as capital below one year of spending |
| The survivor CPP under-65 flat-rate part and the CPP death benefit are not modelled | Req 10.3 | A survivor under 65 gets only the 37.5% share of the deceased's pension, with no flat-rate amount and no death benefit |
| Corporate investment income: the untaxed 25% is paid out the same year as a tax-free capital dividend | Req 13.3 | The taxable 75% is taxed at 50.17% (30.67% of it added to RDTOH); the tax-free part is never held back in the corporation |
| Estate after tax has no deemed disposition of non-registered gains and no probate | Req 17.1 | Registered balances are taxed at the top rate and the corporation is wound up, but non-registered and TFSA pass as-is |
| Non-registered accounts grow before retirement with no tax on the growth | Req 2.1 | Overstates the non-registered balance at retirement for a taxable account; enter an after-tax growth rate to reflect the drag |

## Limitations

Marked **(limitation)** in the baseline spec:

- An unknown key inside a nested plan object (a person, an account) raises an error when a plan loads;
  unknown top-level keys are ignored and missing keys take their defaults (Req 1.2), except a saved
  `base_nonreg_p2`, which is converted on load (see "Plans saved before non-registered accounts"
  below). Full schema validation and migration of saved plans are left to a later spec.
- A saved plan that cannot be read no longer stops the app: it warns, starts from the example household
  and leaves the file untouched (Req 1.3).

## Plans saved before non-registered accounts

A plan saved with the old "base non-registered" amount (`base_nonreg_p2`) loads with that amount as one
Person 2 non-registered account: same balance, 0% growth, no contribution, "TFSA limit" off and 0%
volatility, named "<Person 2's name> non-registered" (with " (2)", " (3)" … if the name is taken).
These terms give the same results as before. Edit the growth and contribution in the Investment
accounts table, then use "Save as default". The file is not changed until you save. (Req 1.2)

## RRIF minimum factors

The minimum withdrawal is the factor for the person's age (the year minus the birth year) times the
opening registered balance (Req 9.1). Below 55 the factor is 0. From 55 to 70 it is 1 / (90 − age),
which matches current law. From 71 the model uses the table from before 2015 **(inherited)**:

| Age | Factor | | Age | Factor |
|---|---|---|---|---|
| 71 | 7.38% | | 84 | 9.93% |
| 72 | 7.48% | | 85 | 10.33% |
| 73 | 7.59% | | 86 | 10.79% |
| 74 | 7.71% | | 87 | 11.33% |
| 75 | 7.85% | | 88 | 11.96% |
| 76 | 7.99% | | 89 | 12.71% |
| 77 | 8.15% | | 90 | 13.62% |
| 78 | 8.33% | | 91 | 14.73% |
| 79 | 8.53% | | 92 | 16.12% |
| 80 | 8.75% | | 93 | 17.92% |
| 81 | 8.99% | | 94 and over | 20.00% |
| 82 | 9.27% | | | |
| 83 | 9.58% | | | |

The current CRA factors are lower, for example 5.28% at 71 and 6.82% at 80. The table is
`RRIF_FACTORS` in `src/retvana/config.py`.

Person 1's RRIF starts at retirement. Person 2's starts at the later of retirement and age 55, when the
LIRA unlocks (Req 9.2).

## Not modelled

- Other provinces, other tax years' rules, or a household of other than two people.
- Changes to tax law after 2026, other than indexing.
- Adjusted cost base tracking and realized capital gains on non-registered investments (see Req 6.4).
- Different returns for different accounts in retirement: one return applies to every account in a year.
- Probate, the deemed disposition of non-registered gains at death, the CPP death benefit and the
  survivor CPP under-65 flat-rate part.
- Municipal land transfer tax above $3M.
- Anything not described in the engine baseline spec.

## Known divergences and open findings

The baseline spec's `tasks.md` lists its findings. Those left open:

- Land transfer tax above $3M (Finding 2, above).
- After the money runs out, a higher spending scale can raise a small leftover estate slightly, because
  of the inherited all-or-nothing rule. The spending solver is not affected (Finding 3).
- `project` and `market_shocks` correct an out-of-date `end_year` on the plan passed in (Finding 6).
- Some app-only merges and one bracket-strategy branch are covered only indirectly (Finding 7).
