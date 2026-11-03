"""Check plan configuration and persistence (Requirement 1.1, 1.2, 1.5).
  .venv/bin/python scripts/plan_check.py

The app defaults are reproduced from app.fresh_plan() here, because importing app.py runs the
Streamlit page. Keep the two in step.
"""
import json
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
from retvana.config import Plan, Person, Townhouse, example_plan   # noqa: E402
from retvana.engine import project                                 # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def fresh_plan() -> Plan:
    """Mirror of app.fresh_plan(): the app defaults."""
    p = example_plan()
    p.property_mode = 'recovery'
    p.tfsa_topup = True
    p.accurate_extra_tax = True
    p.use_death_ages = True
    p.sync_end_year()
    return p


# the mirror above must set exactly what app.fresh_plan() sets (static read; importing app.py runs Streamlit)
import ast   # noqa: E402
src = open(os.path.join(HERE, '..', 'app.py')).read()
fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == 'fresh_plan')
app_sets = {ast.unparse(n).replace(' ', '') for n in fn.body if isinstance(n, (ast.Assign, ast.Expr))}
check('fresh_plan mirror matches app.py', app_sets == {
    'p=example_plan()', "p.property_mode='recovery'", 'p.tfsa_topup=True', 'p.accurate_extra_tax=True',
    'p.use_death_ages=True', 'p.sync_end_year()'}, str(sorted(app_sets)))

# --- 1.1 one Plan object holds every nested input ---
p = example_plan()
check('plan holds nested people, accounts, expenses, grants, properties, mortgages, segments, scenarios',
      all(len(getattr(p, k)) > 0 for k in ('people', 'accounts', 'expenses', 'option_grants', 'properties',
                                           'mortgages', 'segments', 'legacy_scenarios'))
      and isinstance(p.townhouse, Townhouse) and isinstance(p.consulting, list))

# --- 2.1 JSON round trip gives an equal plan ---
for tag, make in (('example_plan()', example_plan), ('app defaults', fresh_plan)):
    a = make()
    if tag == 'example_plan()':
        # exercise optional and nested types that example_plan leaves empty or None
        from retvana.config import ConsultingIncome
        a.consulting = [ConsultingIncome('P2', 60_000, 2034, 2038, via_corp=True)]
        a.properties[2].acb = 600_000.0      # the rental whose ACB example_plan leaves as None
        a.mortgages[0].renewal_rate = 0.045
    b = Plan.from_json(a.to_json())
    check(f'{tag}: JSON round trip gives an equal plan', a == b)
    check(f'{tag}: JSON is stable on a second round trip', b.to_json() == a.to_json())
    check(f'{tag}: rrif_factors keys come back as int', all(isinstance(k, int) for k in b.rrif_factors))

# --- 2.2 unknown top-level keys ignored; missing keys take defaults ---
d = example_plan().to_dict()
d['no_such_setting'] = 123
d['another_unknown'] = {'x': 1}
b = Plan.from_dict(d)
check('unknown top-level keys are ignored', b == example_plan() and not hasattr(b, 'no_such_setting'))

d = example_plan().to_dict()
for k in ('gogo_years', 'tfsa_topup', 'return_rate', 'townhouse', 'consulting', 'ltt_brackets'):
    del d[k]
b = Plan.from_dict(d)
# defaults written out from the Plan dataclass
check('missing top-level keys take their defaults',
      b.gogo_years == 15 and b.tfsa_topup is False and b.return_rate == 0.055 and b.consulting == []
      and b.townhouse == Townhouse() and b.townhouse.price_today == 1_000_000
      and b.ltt_brackets[0] == [0, 55_000, 0.005, 0.005] and len(b.ltt_brackets) == 5,
      f'gogo={b.gogo_years} topup={b.tfsa_topup} return={b.return_rate}')

d = example_plan().to_dict()
del d['people'][0]['death_age'], d['people'][0]['cpp_start_age']
del d['accounts'][0]['volatility']
b = Plan.from_dict(d)
check('missing nested keys take their defaults',
      b.person('P1').death_age == 95 and b.person('P1').cpp_start_age == 65 and b.accounts[0].volatility == 0.12)

d = example_plan().to_dict()
d['people'][0]['nickname'] = 'P1'
try:
    Plan.from_dict(d)
    raised = False
except TypeError:
    raised = True
check('(limitation) an unknown nested key raises TypeError', raised)

# --- 2.3 end year is derived ---
p = example_plan()
p.use_death_ages = True
p.end_year = 2000                          # stale value must not leak in
p.sync_end_year()
P1, P2 = p.person('P1'), p.person('P2')
death1, death2 = P1.birth_year + P1.death_age, P2.birth_year + P2.death_age
expect = max(death1, death2)
check('life expectancy on: end year = second death year (birth year + death age)', p.end_year == expect,
      f'{p.end_year} vs {expect}')
# move the second death before the first: the other person now dies second
second = 'P2' if death1 < death2 else 'P1'
other_death = min(death1, death2)
sp = p.person(second)
sp.death_age = other_death - sp.birth_year - 5
p.sync_end_year()
check('life expectancy on: end year follows whoever dies second', p.end_year == other_death,
      f'{p.end_year} vs {other_death}')

p = example_plan()
p.use_death_ages = False
p.end_year = 2000
p.sync_end_year()
check('life expectancy off: end year = fixed_end_year (2080)', p.end_year == 2080, f'{p.end_year}')
p.fixed_end_year = 2090
p.sync_end_year()
check('life expectancy off: end year follows fixed_end_year', p.end_year == 2090, f'{p.end_year}')

for use, expect in ((True, max(death1, death2)), (False, 2080)):
    p = example_plan()
    p.use_death_ages = use
    p.end_year = 2050                      # stale
    df, _ = project(p)
    check(f'project() derives the end year (life expectancy {"on" if use else "off"})',
          df['A'].iloc[-1] == expect and df['A'].iloc[0] == p.start_year, f'last row {df["A"].iloc[-1]}')

# --- 2.4 copy() is independent ---
orig = fresh_plan()
snap = orig.to_json()
c = orig.copy()
check('copy() equals the original', c == orig)
c.start_year = 2040
c.person('P1').death_age = 70
c.accounts[0].balance = 1.0
c.expenses[0].monthly = 0.0
c.expenses.append(c.expenses[0])
c.townhouse.price_today = 1.0
c.ltt_brackets[0][2] = 0.99
c.tax_rates[0] = 0.99
c.rrif_factors[71] = 0.99
c.segments[0].beta = 9.0
c.mortgages[0].rate = 0.99
c.properties[0].value_today = 1.0
c.option_grants[0].available = 999
c.legacy_scenarios[0].recovery_rate = 0.99
c.people.append(Person('X', 'X', 2000, 0))
check('changing the copy leaves the original unchanged', orig.to_json() == snap and orig == fresh_plan())

print('\nPLAN CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
