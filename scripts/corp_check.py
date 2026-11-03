"""Check the consulting-corporation rules against hand calculations.

  .venv/bin/python scripts/corp_check.py

The tax rates are the public 2026 CCPC rules, written out; the years are read from the example plan.
"""
import sys


from retvana.config import ConsultingIncome, example_plan          # noqa: E402
from retvana.engine import (consulting_schedule, corp_after_tax, corp_pay, corp_step,   # noqa: E402
                            income_tax, project)

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def plan_with(jobs, **kw):
    p = example_plan()
    p.property_mode = 'legacy'
    for k, v in kw.items():
        setattr(p, k, v)
    p.consulting = [ConsultingIncome(*j) for j in jobs]
    p.sync_end_year()
    return p


_ex = example_plan()
Y1 = _ex.start_year + 1                       # first year of corporate work
Y65 = _ex.person('P2').birth_year + 65        # Person 2 turns 65
YEND = Y65 + 5                                # last year of corporate work in the TOSI cases

# ---- corporate tax and dividend capacity, one year, no investments
p = plan_with([('P2', 100_000, Y1, Y1, False, False, 'c', True)], dividend_policy='all')
cs = corp_step(p, 0.0, 0.0, 0.0, 100_000, 0.055, 0.75)
check('small-business tax 11.2% on active income', abs(cs['atax'] - 11_200) < 0.01, f'${cs["atax"]:,.0f}')
check('can pay out the after-tax profit', abs(cs['dmax'] - 88_800) < 0.01, f'${cs["dmax"]:,.0f}')

# ---- investment income: 50.17% tax, 30.67% refundable, 38.33% refund on dividends, CDA
cs = corp_step(p, 1_000_000, 0.0, 0.0, 0.0, 0.055, 0.75)
inv, tinv = 55_000, 41_250
check('passive tax 50.17% on the taxable part', abs(cs['ptax'] - 0.5017 * tinv) < 0.01, f'${cs["ptax"]:,.0f}')
check('30.67% goes into RDTOH', abs(cs['R'] - 0.3067 * tinv) < 0.01, f'${cs["R"]:,.0f}')
check('untaxed part paid as a capital dividend', abs(cs['cda'] - (inv - tinv)) < 0.01, f'${cs["cda"]:,.0f}')
cp = corp_pay(p, cs, 20_000)
check('refund = 38.33% of dividends (while RDTOH lasts)', abs(cp['refund'] - 0.3833 * 20_000) < 0.01)
cp = corp_pay(p, cs, 200_000)
check('refund capped at the RDTOH balance', abs(cp['refund'] - cs['R']) < 0.01 and cp['R'] == 0)

# ---- small-business limit ground down by passive income over $50K
cs = corp_step(p, 0, 0, 150_000, 600_000, 0.055, 0.75)
check('SBD limit shrinks $5 per $1 of passive income over $50K',
      abs(cs['atax'] - 0.112 * 0 - 0.265 * 600_000) < 0.01, f'${cs["atax"]:,.0f} on $600K (limit $0)')

# ---- in the projection: dividends grossed up, DTC, no CPP / RRSP, cash to spend
p = plan_with([('P2', 100_000, Y1, Y1 + 7, False, True, 'c', True)], dividend_policy='all')
df, _ = project(p)
sched, extra = consulting_schedule(p)
r = df.loc[Y1 + 1]
check('no CPP contributions or RRSP room on dividends',
      sched[Y1 + 1]['P2']['cpp'] == 0 and sched[Y1 + 2]['P2']['rrsp'] == 0 and extra['P2'] == 0)
check('corporate revenue in the schedule', sched[Y1 + 1]['corp'] == 100_000)
thr = [r[f'thr{j}'] for j in range(9)]
cum = [0.0]
for j in range(1, 9):
    cum.append(cum[-1] + (thr[j] - thr[j - 1]) * p.tax_rates[j - 1])
base_AD = r['T'] * p.person('P2').taxable_share + r['AA'] + r['BS'] - r['X'] - r['AB']
check('grossed-up dividend in taxable income', abs(r['AD'] - base_AD - 1.15 * r['D_P2']) < 0.01,
      f'dividend ${r["D_P2"]:,.0f}, taxable ${r["AD"]:,.0f}')
expect = income_tax(r['AD'], thr, cum, p.tax_rates, r['AG'], r['AC'], 0.110201 * 1.15 * r['D_P2'])
check('dividend tax credit applied', abs(r['BJ'] - expect) < 0.01, f'tax ${r["BJ"]:,.0f}')
check('all after-tax profit paid out each year', abs(r['D_P2'] - 88_800) < 0.01)

# ---- integration: total tax on $100K, corp + dividend vs personal consulting
pp = plan_with([('P2', 100_000, Y1, Y1, False, False, 'p', False)])
dp, _ = project(pp)
d0, _ = project(plan_with([]))
tax_personal = dp.loc[Y1, 'AE'] - d0.loc[Y1, 'AE'] + consulting_schedule(pp)[0][Y1]['P2']['cpp']
pc = plan_with([('P2', 100_000, Y1, Y1, False, False, 'c', True)], dividend_policy='all')
dc, _ = project(pc)
tax_corp = dc.loc[Y1, 'AE'] - d0.loc[Y1, 'AE'] + 0.112 * 100_000
print(f'      $100K in {Y1}: personal tax + CPP ${tax_personal:,.0f} vs corporate + dividend tax ${tax_corp:,.0f}')
check('integration: corporate route within ~5% of personal when paid out (before CPP)',
      abs(tax_corp - (tax_personal - consulting_schedule(pp)[0][Y1]['P2']['cpp'])) / 100_000 < 0.05)

# ---- TOSI: Person 1 only when working in the business or Person 2 is 65+
p = plan_with([('P2', 150_000, Y1, YEND, False, False, 'c', True)], p1_shareholder=True,
              dividend_target=250_000)
df, _ = project(p)
check('Person 1 gets no dividends before Person 2 is 65 (not working in it)', (df.loc[Y1:Y65 - 1, 'D_P1'] == 0).all())
check(f'Person 1 gets dividends from {Y65} (Person 2 65)', (df.loc[Y65:YEND, 'D_P1'] > 0).all(),
      f'{Y65} ${df.loc[Y65, "D_P1"]:,.0f}')
check('without shares, Person 1 never gets dividends',
      (project(plan_with([('P2', 150_000, Y1, YEND, False, False, 'c', True)], dividend_target=250_000))[0]['D_P1']
       == 0).all())
p = plan_with([('P2', 150_000, Y1, YEND, False, False, 'c', True), ('P1', 30_000, Y1 + 2, Y1 + 3, False, False, 'c', True)],
              p1_shareholder=True, dividend_target=80_000)
df, _ = project(p)
check('Person 1 can be paid in the years they work in the business',
      df.loc[Y1 + 2, 'D_P1'] > 0 and df.loc[Y1 + 1, 'D_P1'] == 0 and df.loc[Y1 + 4, 'D_P1'] == 0)

# ---- target policy keeps money in the corporation; wind-up valued in the estate
p = plan_with([('P2', 200_000, Y1, Y1 + 7, False, False, 'c', True)], dividend_target=60_000)
df, _ = project(p)
check('target policy retains profit in the corporation', df.loc[Y1 + 8, 'CORP'] > 0,
      f'${df.loc[Y1 + 8, "CORP"]:,.0f} in {Y1 + 8}')
row = df.iloc[-1]
w = float(corp_after_tax(p, row['CORP'], row['RDTOH']))
check('wind-up value: final dividend at the top dividend rate', 0 < w < row['CORP'] + row['RDTOH'],
      f'corp ${row["CORP"]:,.0f} -> ${w:,.0f} after tax')
check('RDTOH never negative', (df['RDTOH'] >= -1e-6).all())

print('\nCORP CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
