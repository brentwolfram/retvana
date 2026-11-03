"""Check the income tax rules (Requirement 8) against hand calculations.
  .venv/bin/python scripts/tax_check.py

Hand tax is written out bracket by bracket (rate x the part of income inside each bracket), not
with the cumulative-tax table the engine uses, so the two are independent.
"""
import sys
from retvana.config import ConsultingIncome, example_plan            # noqa: E402
from retvana.engine import income_tax, project                       # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def close(a, b, tol=0.005):
    return abs(a - b) <= tol


# 2026 combined federal + Ontario brackets, written out (Req 8.1)
THR = [0, 62414, 67778, 105180, 124830, 135555, 181980, 210130, 266905]
RATES = [0.2005, 0.2415, 0.2965, 0.3148, 0.3389, 0.3791, 0.4341, 0.4641, 0.5353]
BPA = 19053


def bracket_tax(x, thr):
    """Rate x the slice of income inside each bracket."""
    tax = 0.0
    for j, t in enumerate(thr):
        top = thr[j + 1] if j + 1 < len(thr) else float('inf')
        tax += RATES[j] * max(0.0, min(x, top) - t)
    return tax


def hand_tax(x, thr, bpa, extra=0.0, credit=0.0):
    """Req 8.3: max(bracket tax - (BPA + additional amounts) x lowest rate - dividend credit, 0)."""
    return max(bracket_tax(x, thr) - (bpa + extra) * 0.2005 - credit, 0.0)


def cum_table(thr):
    """The engine's input: cumulative tax at each threshold (whole brackets, by hand)."""
    return [sum(RATES[i] * (thr[i + 1] - thr[i]) for i in range(j)) for j in range(len(thr))]


p = example_plan()
check('plan tax brackets, rates and BPA are the 2026 values', p.tax_thresholds == THR and p.tax_rates == RATES
      and p.bpa == BPA and len(THR) == 9)
CUM = cum_table(THR)

# ------------------------------------------------------------------ 4.1 hand values
points = [0, BPA, 500_000] + [t + d for t in THR[1:] for d in (-1, 0, 1)]
bad = []
for x in points:
    got = income_tax(x, THR, CUM, RATES, BPA)
    want = hand_tax(x, THR, BPA)
    if not close(got, want, 1e-6):
        bad.append(f'{x}: {got:.4f} vs {want:.4f}')
check(f'income_tax matches hand values at $0, the BPA, $500K and each threshold -1/0/+1 ({len(points)} points)',
      not bad, '; '.join(bad[:3]))
check('no tax at $0 or at the BPA', income_tax(0, THR, CUM, RATES, BPA) == 0
      and close(income_tax(BPA, THR, CUM, RATES, BPA), 0, 1e-9))
want = (62414 * 0.2005 + 5364 * 0.2415 + 37402 * 0.2965 + 19650 * 0.3148 + 10725 * 0.3389
        + 46425 * 0.3791 + 28150 * 0.4341 + 56775 * 0.4641 + 233095 * 0.5353 - 19053 * 0.2005)
check('tax at $500K written out bracket by bracket', close(income_tax(500_000, THR, CUM, RATES, BPA), want),
      f'{income_tax(500_000, THR, CUM, RATES, BPA):,.2f} vs {want:,.2f}')

# ------------------------------------------------------------------ 4.2 credits
x = 80_000
base = income_tax(x, THR, CUM, RATES, BPA)
check('additional personal amounts are credited at the lowest rate (20.05%)',
      close(base - income_tax(x, THR, CUM, RATES, BPA, extra_credit=2_000), 2_000 * 0.2005, 1e-6))
check('BPA is credited at the lowest rate, not the marginal rate',
      close(income_tax(x, THR, CUM, RATES, 0) - base, BPA * 0.2005, 1e-6))
check('dividend credit reduces tax dollar for dollar',
      close(base - income_tax(x, THR, CUM, RATES, BPA, credit_dollars=1_000), 1_000, 1e-6))
check('dividend credit cannot take the tax below 0',
      income_tax(x, THR, CUM, RATES, BPA, credit_dollars=base + 5_000) == 0.0
      and income_tax(30_000, THR, CUM, RATES, BPA, extra_credit=20_000, credit_dollars=1_000) == 0.0)

# ------------------------------------------------------------------ 4.3 indexing
for to_start in (True, False):
    p = example_plan()
    p.property_mode = 'legacy'
    p.index_brackets_to_start = to_start
    p.sync_end_year()
    df, _ = project(p)
    worst = 0.0
    for year, r in df.iterrows():
        n = (year - 2026) if to_start else (year - p.start_year)    # years of indexing at 2.8%
        f = 1.028 ** n
        worst = max([worst, abs(r['AG'] / (BPA * f) - 1)] + [abs(r[f'thr{j}'] - THR[j] * f) / max(THR[j] * f, 1)
                                                              for j in range(9)])
    tag = 'on' if to_start else 'off'
    check(f'index to retirement {tag}: thresholds and BPA = 2026 x 1.028^(years) in every row '
          f'({len(df)} rows)', worst < 1e-12, f'max rel diff {worst:.2e}')

# ------------------------------------------------------------------ 4.4 taxable income identity
p = example_plan()
p.property_mode = 'legacy'
p.use_death_ages = True
p.income_splitting = True
p.accurate_extra_tax = True
p.p1_shareholder = True
p.dividend_policy = 'all'          # 'target' pays Person 1 nothing here: their income is already above it
p.consulting = [ConsultingIncome('P1', 60_000, 2033, 2037, True, True, 'personal', False),
                ConsultingIncome('P2', 120_000, 2033, 2046, True, False, 'corp', True)]
p.sync_end_year()
df, _ = project(p)
check('identity plan has personal consulting, CPP contributions, RRSP contributions, dividends to both, '
      'pension splitting and OAS',
      df['W_P1'].sum() > 0 and df['CPP_P1'].sum() > 0 and df['K'].sum() > 0 and df['D_P2'].sum() > 0
      and df['D_P1'].sum() > 0 and (df['BR'] != df['BD']).any() and df['CD'].sum() > 0)
bad = []
for year, r in df.iterrows():
    for who, ret, cpp, oas, claw, work, draw, div, rrsp, cppc in (
            ('P1', 'G', 'CC', 'CD', 'CF', 'W_P1', 'BR', 'D_P1', 'K', 'CPP_P1'),
            ('P2', 'T', 'CJ', 'CK', 'CM', 'W_P2', 'BS', 'D_P2', 'X', 'CPP_P2')):
        # Req 8.4. OAS enters net of the clawback (the clawback is a deduction).
        want = (0.75 * r[ret] + r[cpp] + r[oas] - r[claw] + r[work] + r[draw] + 1.15 * r[div]
                - r[rrsp] - 0.5 * r[cppc])
        got = r['Q' if who == 'P1' else 'AD']
        if not close(got, want, 0.01):
            bad.append(f'{year} {who}: {got:,.2f} vs {want:,.2f}')
check(f'taxable income identity (Req 8.4) holds in every row for both people ({len(df)} rows)',
      not bad, '; '.join(bad[:3]))

bad = []
for year, r in df.iterrows():
    thr = [r[f'thr{j}'] for j in range(9)]
    for who, q, tax, alive, cred, div in (('P1', 'Q', 'BF', 'alive_P1', 'P', 'D_P1'), ('P2', 'AD', 'BJ', 'alive_P2', 'AC', 'D_P2')):
        want = hand_tax(r[q], thr, r['AG'], r[cred], 0.110201 * 1.15 * r[div]) if r[alive] else 0.0
        if not close(r[tax], want, 0.01):
            bad.append(f'{year} {who}: {r[tax]:,.2f} vs {want:,.2f}')
check('projected income tax = hand tax on that row\'s taxable income, brackets, BPA, CPP credit and '
      'dividend credit (Req 8.3)', not bad, '; '.join(bad[:3]))

print('\nTAX CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
