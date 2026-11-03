"""Check the consulting-income rules against hand calculations.
  .venv/bin/python scripts/consulting_check.py

People, the retirement year and the job years are read from the example plan; the CPP, YMPE,
YAMPE and RRSP figures are the public 2026 rules, written out.
"""
import sys
from retvana.config import ConsultingIncome, example_plan   # noqa: E402
from retvana.engine import consulting_schedule, project      # noqa: E402
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
base = plan_with([])
df0, _ = project(base)
START = base.start_year
B1, B2 = base.person('P1').birth_year, base.person('P2').birth_year
Y18 = START - (B2 + 18)                                      # Person 2's years from 18 to retirement
LAST = B2 + 68                                               # last consulting year (Person 2 is 68)
p = plan_with([('P2', 100_000, START + 1, LAST, True, True)])   # Person 2 from retirement + 1 to 68, RRSP on
df1, _ = project(p)
sched, extra = consulting_schedule(p)
infl = p.inflation
y = START + 2
W = 100_000 * (1 + infl) ** (y - 2026)
ympe, yampe = 74_600 * (1 + infl) ** (y - 2026), 85_000 * (1 + infl) ** (y - 2026)
cpp = 0.119 * (min(W, ympe) - 3500) + 0.08 * (min(W, yampe) - ympe)
rrsp = min(0.18 * 100_000 * (1 + infl) ** (y - 1 - 2026), 33_810 * (1 + infl) ** (y - 2026))
s = sched[y]['P2']
check('income indexed to inflation', abs(s['W'] - W) < 0.01, f'${s["W"]:,.0f}')
check('self-employed CPP: 11.9% to YMPE + 8% CPP2 to YAMPE', abs(s['cpp'] - cpp) < 0.01, f'${s["cpp"]:,.0f}')
check('RRSP = 18% of last year, within the dollar limit', abs(s['rrsp'] - rrsp) < 0.01, f'${s["rrsp"]:,.0f}')
check('first year has no RRSP room yet', sched[START + 1]['P2']['rrsp'] == 0)
r = df1.loc[y]
check('consulting is in other income (AA)', abs(r['AA'] - df0.loc[y, 'AA'] - W) < 0.01)
dq = r['AD'] - (r['T'] * p.person('P2').taxable_share + r['AA'] + r['BS'])
check('taxable income less RRSP and half the CPP', abs(dq + rrsp + cpp / 2) < 0.01, f'{dq:,.2f}')
check('RRSP contribution goes into registered next year',
      abs(df1.loc[y + 1, 'V'] - (r['V'] + r['W'] - r['BH'] - r['BI'] + r['X']
                                 - (r['BK'] if r['S'] + r['T'] - r['BC'] - r['BK'] < 0 else 0))) < 0.01)
check('no CPP contributions from 65 (CPP starts at 65)',
      all(sched[yy]['P2']['cpp'] == 0 for yy in range(B2 + 65, LAST + 1)) and sched[B2 + 64]['P2']['cpp'] > 0)
want_extra = sum(min(1.0, sched[yy]['P2']['W'] / (74_600 * (1 + infl) ** (yy - 2026)))
                 for yy in range(START + 1, B2 + 65))
check('consulting before 65 adds CPP contributory years', abs(extra['P2'] - want_extra) < 1e-9,
      f'+{extra["P2"]:.1f} years')
cpp0, cpp1 = df0.loc[B2 + 65, 'CJ'], df1.loc[B2 + 65, 'CJ']
ratio = min(1.0, (Y18 + want_extra) / 39) / min(1.0, Y18 / 39)
check(f'CPP pension rises by the contributory factor: min(1, ({Y18} + {want_extra:.1f}) / 39) / ({Y18} / 39)',
      cpp1 > cpp0 and abs(cpp1 / cpp0 - ratio) < 1e-9, f'${cpp0:,.0f} -> ${cpp1:,.0f}')
check('RRSP contributions stop after 71', all(sched[yy]['P2']['rrsp'] == 0 for yy in range(B2 + 72, B2 + 82)))
check('nothing after the last consulting year',
      sched[LAST + 1]['P2']['W'] == 0 and sched[LAST + 2]['P2']['rrsp'] == 0 and sched[LAST + 1]['P2']['rrsp'] > 0)
# consulting after 65 raises the OAS clawback; no RRSP keeps more cash, more tax
q = plan_with([('P1', 150_000, B1 + 65, B1 + 70, True, False)])    # Person 1 65-70, no RRSP
dq_, _ = project(q)
y0, y1 = B1 + 66, B1 + 71                                    # the clawback lags income by a year
check('consulting after 65 increases the OAS clawback',
      dq_.loc[y0:y1, 'CF'].sum() > df0.loc[y0:y1, 'CF'].sum(),
      f'${df0.loc[y0:y1, "CF"].sum():,.0f} -> ${dq_.loc[y0:y1, "CF"].sum():,.0f}')
check('RRSP off: no contributions', all(v['P1']['rrsp'] == 0 for v in consulting_schedule(q)[0].values()))
check('more capital with consulting', df1['C'].iloc[-1] > df0['C'].iloc[-1],
      f'${df0["C"].iloc[-1] / 1e6:,.2f}M -> ${df1["C"].iloc[-1] / 1e6:,.2f}M')
# death stops consulting
d = plan_with([('P1', 80_000, START + 1, B1 + 85, True, True)], use_death_ages=True)
d.person('P1').death_age = 80                               # dies at the end of the year they turn 80
d.sync_end_year()
sd, _ = consulting_schedule(d)
check('consulting stops at death', sd[B1 + 80]['P1']['W'] > 0 and sd[B1 + 81]['P1']['W'] == 0)
print('\nCONSULTING CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
