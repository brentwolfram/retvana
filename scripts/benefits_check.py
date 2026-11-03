"""Check the CPP and OAS rules (Requirement 11) against hand calculations.
  .venv/bin/python scripts/benefits_check.py

CPP, OAS and the clawback are written out from the rule in every projection row and compared
with the engine's CC/CJ (CPP), CD/CK (OAS gross) and CF/CM (clawback) columns. Death ages are off
so no survivor top-up enters the CPP columns (that rule is covered by survivor_check.py).
"""
import dataclasses
import sys
from retvana.config import ConsultingIncome, example_plan            # noqa: E402
from retvana.engine import project, starting_position                # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def close(a, b, tol=0.005):
    return abs(a - b) <= tol


# Rule constants written out (Req 11, 2026 values)
INFL = 0.028                 # plan inflation and CPP inflation
OAS_MONTHLY, OAS_THR, CLAW = 751.97, 95_323, 0.15
YMPE = 74_600


def base_plan():
    p = example_plan()
    p.property_mode = 'legacy'
    p.use_death_ages = False
    p.sync_end_year()
    return p


p = base_plan()
# Household inputs read from the example plan: CPP estimates at 65 (per month), birth years
# and the retirement year. Contributory years from 18 to retirement follow from them.
CPP65 = {k: p.person(k).cpp_monthly_at_65 for k in ('P1', 'P2')}
BORN = {k: p.person(k).birth_year for k in ('P1', 'P2')}
START = p.start_year
YEARS18 = {k: START - (BORN[k] + 18) for k in ('P1', 'P2')}
check('plan CPP/OAS rule inputs are the stated values',
      p.inflation == INFL and p.cpp_inflation == INFL
      and p.oas_max_monthly == OAS_MONTHLY and p.oas_threshold == OAS_THR and p.oas_clawback_rate == CLAW
      and p.oas_uplift_75 == 0.10 and p.cpp_full_years == 39 and p.ympe_2026 == YMPE and p.cpp_proportional)
check('example plan: Person 1 has at least 39 years from 18 to retirement, Person 2 fewer',
      YEARS18['P1'] >= 39 > YEARS18['P2'], f'P1 {YEARS18["P1"]}, P2 {YEARS18["P2"]}')


def hand_cpp(key, year, start_age, contrib):
    """Req 11.1: estimate x 12, indexed from the year turning 65, x early/late factor x contributory."""
    if year - BORN[key] < start_age:
        return 0.0
    adj = 1 - 0.072 * (65 - start_age) if start_age < 65 else 1 + 0.084 * (start_age - 65)
    return CPP65[key] * 12 * (1 + INFL) ** (year - (BORN[key] + 65)) * adj * contrib


def cpp_rows(plan, key, start_age, contrib):
    df, _ = project(plan)
    col = 'CC' if key == 'P1' else 'CJ'
    bad = [f'{y}: {r[col]:,.2f} vs {hand_cpp(key, y, start_age, contrib):,.2f}'
           for y, r in df.iterrows() if not close(r[col], hand_cpp(key, y, start_age, contrib), 0.01)]
    return df, bad


# ------------------------------------------------------------------ 5.1 CPP factors
# Person 2: retirement - (birth year + 18) years to retirement, over 39. Person 1 has 39 or more
# years, so the factor is 1.
contrib_p2 = min(1.0, YEARS18['P2'] / 39)
for age, factor in ((60, 1 - 0.072 * 5), (65, 1.0), (70, 1 + 0.084 * 5)):
    p = base_plan()
    p.person('P2').cpp_start_age = age
    df, bad = cpp_rows(p, 'P2', age, contrib_p2)
    first = df.index[df['CJ'] > 0][0]
    want0 = CPP65['P2'] * 12 * 1.028 ** (first - (BORN['P2'] + 65)) * factor * contrib_p2
    check(f'CPP from {age}: factor {factor:.3f}, first paid {BORN["P2"] + age}, hand value in every row '
          f'({len(df)} rows)',
          not bad and first == BORN['P2'] + age and close(df.loc[first, 'CJ'], want0, 0.01),
          f'first {first} {df.loc[first, "CJ"]:,.2f} vs {want0:,.2f}; ' + '; '.join(bad[:3]))

p = base_plan()
_, bad = cpp_rows(p, 'P1', 65, 1.0)
check(f'Person 1 contributory factor: {YEARS18["P1"]} years from 18 to retirement gives 1.0', not bad,
      '; '.join(bad[:3]))

p = base_plan()
p.cpp_proportional = False
_, bad = cpp_rows(p, 'P2', 65, 1.0)
check('proportional CPP off: contributory factor is 1.0', not bad, '; '.join(bad[:3]))

# With consulting: Person 2 earns $40K (not indexed) in the two years after retirement, before
# 65; each year adds min(1, 40,000 / YMPE that year). Work at 65+ and work through the
# corporation add nothing.
y65 = BORN['P2'] + 65
p = base_plan()
p.consulting = [
    ConsultingIncome('P2', 40_000, START + 1, START + 2, indexed=False, rrsp=False),
    ConsultingIncome('P2', 40_000, y65, y65 + 2, indexed=False, rrsp=False),        # age 65-67
    ConsultingIncome('P2', 90_000, START + 6, START + 8, indexed=False, rrsp=False, via_corp=True),
]
extra = sum(min(1.0, 40_000 / (YMPE * 1.028 ** (y - 2026))) for y in range(START + 1, START + 3))
want = min(1.0, (YEARS18['P2'] + extra) / 39)
_, bad = cpp_rows(p, 'P2', 65, want)
check(f'contributory factor with consulting before 65: ({YEARS18["P2"]} + {extra:.4f}) / 39 = {want:.5f}; '
      'consulting at 65+ and corporate work add no years', want < 1 and not bad, '; '.join(bad[:3]))

p = base_plan()
p.consulting = [ConsultingIncome('P2', 100_000, START + 1, START + 10, indexed=False, rrsp=False)]
extra = sum(min(1.0, 100_000 / (YMPE * 1.028 ** (y - 2026))) for y in range(START + 1, START + 11))
_, bad = cpp_rows(p, 'P2', 65, 1.0)
check(f'contributory factor caps at 1.0 ({YEARS18["P2"]} + {extra:.2f} years > 39)',
      YEARS18['P2'] + extra > 39 and START + 10 < y65 and not bad, '; '.join(bad[:3]))


# ------------------------------------------------------------------ 5.2 OAS
def hand_oas(key, year, start_age):
    """Req 11.3: $751.97/month (2026) indexed, +10% from 75, x (1 + 7.2% x years deferred)."""
    age = year - BORN[key]
    if age < start_age:
        return 0.0
    return (OAS_MONTHLY * 12 * (1 + INFL) ** (year - 2026) * (1.10 if age >= 75 else 1.0)
            * (1 + 0.072 * (start_age - 65)))


for start_age in (65, 70):
    p = base_plan()
    p.person('P1').oas_start_age = start_age
    df, _ = project(p)
    bad = [f'{y}: {r["CD"]:,.2f} vs {hand_oas("P1", y, start_age):,.2f}'
           for y, r in df.iterrows() if not close(r['CD'], hand_oas('P1', y, start_age), 0.01)]
    first = df.index[df['CD'] > 0][0]
    check(f'Person 1 OAS from {start_age}: first paid {first}, hand value in every row ({len(df)} rows)',
          not bad and first == BORN['P1'] + start_age, '; '.join(bad[:3]))
    if start_age == 70:
        y70 = BORN['P1'] + 70
        want = OAS_MONTHLY * 12 * 1.028 ** (y70 - 2026) * 1.36
        check(f'OAS deferred to 70 is 36% higher: 751.97 x 12 x 1.028^{y70 - 2026} x 1.36 in {y70}',
              close(df.loc[y70, 'CD'], want, 0.01), f'{df.loc[y70, "CD"]:,.2f} vs {want:,.2f}')
    else:
        y65, y75 = BORN['P1'] + 65, BORN['P1'] + 75
        check('OAS rises by inflation (1.028) year to year before 75',
              all(close(df.loc[y + 1, 'CD'] / df.loc[y, 'CD'], 1.028, 1e-12) for y in range(y65, y75 - 1)))
        check(f'OAS rises by 1.028 x 1.10 in the year Person 1 turns 75 ({y75}), then by 1.028 again',
              close(df.loc[y75, 'CD'] / df.loc[y75 - 1, 'CD'], 1.028 * 1.10, 1e-12)
              and close(df.loc[y75 + 1, 'CD'] / df.loc[y75, 'CD'], 1.028, 1e-12))
        want = OAS_MONTHLY * 12 * 1.028 ** (y75 - 2026) * 1.10
        check(f'OAS at 75 written out: 751.97 x 12 x 1.028^{y75 - 2026} x 1.10', close(df.loc[y75, 'CD'], want, 0.01),
              f'{df.loc[y75, "CD"]:,.2f} vs {want:,.2f}')


# ------------------------------------------------------------------ 5.3 clawback
def clawback_plan(accurate):
    """Spending tripled and no non-registered or TFSA money, so extra registered draws (BE/BI)
    fund every year until the registered money runs out. Tuned for the example household: the
    plan retires the year Person 1 turns 65, so OAS is paid while the large extra draws last and
    some years' incomes are high enough for the clawback to reach the full OAS."""
    p = base_plan()
    p.start_year = BORN['P1'] + 65
    p.accurate_extra_tax = accurate
    for e in p.expenses:
        e.monthly *= 3
        if e.monthly_later is not None:
            e.monthly_later *= 3
    st = dataclasses.replace(starting_position(p), nonreg_p1=0.0, nonreg_p2=0.0, tfsa_p1=0.0, tfsa_p2=0.0)
    df, _ = project(p, start=st)
    return df


def claw_bad(df, accurate):
    """Req 11.4: min(15% x max(last year's taxable income - threshold, 0), OAS). The threshold is
    the 2026 value indexed to the income year (last year). Last year's income includes the extra
    registered draw when accurate extra tax is on."""
    bad, stats = [], {'claw': 0, 'capped': 0, 'extra_matters': 0}
    years = list(df.index)
    for y in years:
        for key, q, be, gross_col, claw_col in (('P1', 'Q', 'BE', 'CD', 'CF'), ('P2', 'AD', 'BI', 'CK', 'CM')):
            gross = hand_oas(key, y, 65)
            if y == years[0]:
                base = base_q = prev_be = 0.0
            else:
                pr = df.loc[y - 1]
                base_q, prev_be = pr[q], pr[be]
                base = base_q + (prev_be if accurate else 0.0)
            thr = OAS_THR * (1 + INFL) ** (y - 1 - 2026)
            want = min(CLAW * max(base - thr, 0.0), gross)
            got = df.loc[y, claw_col]
            if not close(got, want, 0.01):
                bad.append(f'{y} {key}: {got:,.2f} vs {want:,.2f}')
            stats['claw'] += want > 0
            stats['capped'] += want > 0 and close(want, gross, 1e-9)
            # would the clawback differ if the extra draw were (accurate off) / were not (on) included?
            stats['extra_matters'] += not close(min(CLAW * max(base_q + prev_be - thr, 0.0), gross),
                                                min(CLAW * max(base_q - thr, 0.0), gross), 0.01)
    return bad, stats


df = clawback_plan(True)
bad, stats = claw_bad(df, True)
check(f'accurate extra tax on: clawback = hand value on last year\'s income incl. the extra registered '
      f'draw, every row ({stats["claw"]} clawback rows)', not bad and stats['claw'] > 0, '; '.join(bad[:3]))
check('the extra registered draw changes the clawback in some rows (the test above is not trivial)',
      stats['extra_matters'] > 0, f'{stats["extra_matters"]} rows')
check('clawback is capped at the gross OAS (and reaches the cap in some row)', stats['capped'] > 0
      and all(df['CF'] <= df['CD'] + 1e-9) and all(df['CM'] <= df['CK'] + 1e-9), f'{stats["capped"]} capped rows')

df = clawback_plan(False)
bad, stats = claw_bad(df, False)
check(f'accurate extra tax off: clawback uses last year\'s taxable income without the extra draw, every '
      f'row ({stats["claw"]} clawback rows; the extra draw would change it in {stats["extra_matters"]})',
      not bad and stats['extra_matters'] > 0, '; '.join(bad[:3]))

print('\nBENEFITS CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
