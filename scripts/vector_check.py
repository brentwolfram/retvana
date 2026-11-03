"""Check the vectorized projection (vector.py) against the reference engine (engine.project),
which itself matches the original spreadsheet.

  .venv/bin/python scripts/vector_check.py

Cases: the golden-master input combinations with the fixed return, plus random
yearly returns (crashes, booms) where capital runs out on some paths."""
import sys

import numpy as np


from retvana import property_model as pm                 # noqa: E402
from retvana.analysis import market_shocks, _starts_for_year, _returns_for_year  # noqa: E402
from retvana.config import example_plan                  # noqa: E402
from retvana.engine import project, starting_position    # noqa: E402
from retvana.vector import Starts, project_many          # noqa: E402

COLS = ('B', 'C', 'F', 'I', 'S', 'V', 'BU', 'BX', 'N', 'AA', 'R', 'AE', 'Q', 'AD', 'BA', 'BB', 'BC',
        'BD', 'BH', 'BE', 'BI', 'BW', 'BZ', 'CF', 'CM', 'T_P1', 'T_P2', 'K', 'X', 'CORP', 'RDTOH', 'D_P1', 'D_P2')


def compare(plan, returns, label):
    st = starting_position(plan)
    one = lambda v: np.array([v])
    starts = Starts(one(st.nonreg_p1), one(st.nonreg_p2), one(st.reg_p1), one(st.reg_p2),
                    one(st.tfsa_p1), one(st.tfsa_p2))
    ny = plan.end_year - plan.start_year + 1
    r = np.full((1, ny), plan.return_rate) if returns is None else returns[None, :]
    vec = project_many(plan, starts, r)
    df, _ = project(plan, start=st, returns=None if returns is None else returns)
    worst = 0.0
    for c in COLS:
        d = np.abs(vec[c][0] - df[c].to_numpy())
        rel = d / np.maximum(1.0, np.abs(df[c].to_numpy()))
        worst = max(worst, float(rel.max()))
    ok = worst < 1e-9
    depleted = int((df['C'] < df['B']).sum())
    print(f'{label:<44} max rel diff {worst:.2e}  depleted years {depleted:>2}  {"PASS" if ok else "FAIL"}')
    return ok


oks = []
for year, scen, split, ages in [(2033, 'Base', False, None), (2029, 'Bear', False, None),
                                (2030, 'Bull', True, None), (2032, 'Base', False, (60, 70, 70, 67)),
                                (2027, 'Base', False, None)]:
    p = example_plan()
    p.property_mode, p.legacy_scenario, p.start_year, p.income_splitting = 'legacy', scen, year, split
    if ages:
        p1, p2 = p.person('P1'), p.person('P2')
        p1.cpp_start_age, p2.cpp_start_age, p1.oas_start_age, p2.oas_start_age = ages
    oks.append(compare(p, None, f'{year} {scen}{" split" if split else ""}{" ages" if ages else ""}'))

rng = np.random.default_rng(5)

# death ages and survivor rules: either spouse first, long and short survivor periods
for death_age_p1, death_age_p2, extra in [(97, 94, {}), (80, 94, {}), (97, 70, {}), (75, 95, dict(withdrawal_strategy='bracket',
                      tfsa_topup=True, accurate_extra_tax=True)), (88, 66, dict(income_splitting=True)),
                      (70, 70, {})]:
    for rnd in (False, True):
        p = example_plan()
        p.property_mode, p.use_death_ages = 'recovery', True
        p.person('P1').death_age, p.person('P2').death_age = death_age_p1, death_age_p2
        for k, v in extra.items():
            setattr(p, k, v)
        p.sync_end_year()
        r = rng.normal(0.05, 0.14, p.end_year - p.start_year + 1) if rnd else None
        oks.append(compare(p, r, f'death P1 {death_age_p1}/P2 {death_age_p2}{" " + ",".join(extra) if extra else ""}{" rand" if rnd else ""}'))
for i in range(6):
    p = example_plan()
    p.property_mode, p.start_year = 'recovery', int(rng.integers(2028, 2036))
    p.income_splitting = bool(i % 2)
    ny = p.end_year - p.start_year + 1
    r = rng.normal(0.04, 0.16, ny)
    if i >= 3:                       # force depletion: deep early crashes and 3x spending
        r[:6] = -0.35
        for e in p.expenses:
            e.monthly *= 3
            e.monthly_later = None if e.monthly_later is None else e.monthly_later * 3
    oks.append(compare(p, r, f'random returns #{i + 1} (start {p.start_year})'))

# withdrawal strategies, TFSA top-up and marginal-rate extra tax, fixed and random returns
for strat, target, until, topup, acc in [('defer', 0, 71, False, False), ('defer', 0, 71, True, True),
                                         ('bracket', 95_000, 71, True, True), ('bracket', 60_000, 65, False, True),
                                         ('bracket', 150_000, 80, True, False), ('minimums', 0, 0, True, True)]:
    for rnd in (False, True):
        p = example_plan()
        p.property_mode, p.start_year = 'recovery', 2030 + (target // 50_000)
        p.withdrawal_strategy, p.bracket_target, p.fill_until_age = strat, target, until
        p.tfsa_topup, p.accurate_extra_tax = topup, acc
        ny = p.end_year - p.start_year + 1
        r = rng.normal(0.05, 0.14, ny) if rnd else None
        label = f'{strat} {target // 1000}K<= {until} topup={int(topup)} acc={int(acc)}{" rand" if rnd else ""}'
        oks.append(compare(p, r, label))

# consulting income: either person, before/after 65, RRSP on/off, with strategies and survivor rules
from retvana.config import ConsultingIncome   # noqa: E402
for jobs, extra in [([('P1', 60_000, 2033, 2037, True, True)], {}),
                    ([('P2', 120_000, 2033, 2041, True, False), ('P1', 30_000, 2036, 2043, False, True)],
                     dict(withdrawal_strategy='bracket', tfsa_topup=True, accurate_extra_tax=True)),
                    ([('P2', 90_000, 2034, 2050, True, True)], dict(use_death_ages=True, income_splitting=True)),
                    ([('P1', 200_000, 2033, 2034, True, True)], dict(use_death_ages=True))]:
    for rnd in (False, True):
        p = example_plan()
        p.property_mode = 'recovery'
        for k, v in extra.items():
            setattr(p, k, v)
        p.consulting = [ConsultingIncome(*j) for j in jobs]
        p.sync_end_year()
        r = rng.normal(0.05, 0.14, p.end_year - p.start_year + 1) if rnd else None
        lbl = '+'.join(f'{j[0]}{j[1] // 1000}K {j[2]}-{j[3]}' for j in jobs)
        oks.append(compare(p, r, f'consulting {lbl}{" rand" if rnd else ""}'))

# consulting through the corporation: dividend policies, Person 1 as shareholder, survivor
for jobs, extra in [([('P2', 120_000, 2033, 2040, True, False, 'corp', True)], {}),
                    ([('P2', 150_000, 2033, 2038, True, False, 'corp', True)], dict(dividend_policy='all')),
                    ([('P2', 100_000, 2033, 2042, True, False, 'corp', True),
                      ('P1', 40_000, 2034, 2036, True, False, 'corp', True)],
                     dict(p1_shareholder=True, dividend_target=70_000, withdrawal_strategy='bracket',
                          tfsa_topup=True, accurate_extra_tax=True)),
                    ([('P2', 200_000, 2033, 2050, True, False, 'corp', True)],
                     dict(use_death_ages=True, p1_shareholder=True, corp_balance=50_000)),
                    ([('P2', 90_000, 2033, 2045, True, False, 'corp', True)], dict(use_death_ages=True))]:
    for rnd in (False, True):
        p = example_plan()
        p.property_mode = 'recovery'
        for k, v in extra.items():
            setattr(p, k, v)
        if p.use_death_ages:
            p.person('P2').death_age = 75 if 'corp_balance' in extra else 94
        p.consulting = [ConsultingIncome(*j) for j in jobs]
        p.sync_end_year()
        r = rng.normal(0.05, 0.14, p.end_year - p.start_year + 1) if rnd else None
        lbl = '+'.join(f'{j[0]}{j[1] // 1000}K {j[2]}-{j[3]}' for j in jobs)
        oks.append(compare(p, r, f'corp {lbl} {",".join(extra)[:28]}{" rand" if rnd else ""}'))

# the Monte Carlo start-balance builder with zero volatility must equal the deterministic FV
p = example_plan()
p.property_mode = 'legacy'
for a in p.accounts:
    a.volatility = 0.0
z = market_shocks(p, 3)
st0 = starting_position(p)
v, price = pm.sale_values(p, p.start_year)
s, _ = _starts_for_year(p, p.start_year, z, pm.waterfall(p, p.start_year, v, price).surplus)
d = max(abs(s.reg_p1[0] - st0.reg_p1), abs(s.reg_p2[0] - st0.reg_p2), abs(s.tfsa_p1[0] - st0.tfsa_p1),
        abs(s.nonreg_p1[0] - st0.nonreg_p1), abs(s.nonreg_p2[0] - st0.nonreg_p2))
p.return_vol = 0.0
r = _returns_for_year(p, p.start_year, z)
ok = d < 1e-6 and np.allclose(r, p.return_rate)
print(f'{"zero-volatility MC == deterministic plan":<44} max diff ${d:.6f}  {"PASS" if ok else "FAIL"}')
oks.append(ok)
print('VECTOR CHECK', 'PASS' if all(oks) else 'FAIL')
sys.exit(0 if all(oks) else 1)
