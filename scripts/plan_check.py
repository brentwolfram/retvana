"""Check plan configuration and persistence (Requirement 1.1, 1.2, 1.5), and the loading of plans saved
before non-registered accounts (nonreg-accounts Requirements 4.1 and 5, Properties 7 to 9).
  .venv/bin/python scripts/plan_check.py

The app defaults are reproduced from app.fresh_plan() here, because importing app.py runs the
Streamlit page. Keep the two in step.
"""
import json
import os
import sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
from retvana.config import Account, Plan, Person, Townhouse, example_plan   # noqa: E402
from retvana.engine import project                                          # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def check_property(label, seed, edges, draw, n_random, test):
    """One seeded property line (nonreg-accounts design, "Seeds, edge cases and failure lines").

    edges: list of (edge label, inputs), run first. draw(rng) -> inputs for random case i, with
    rng = np.random.default_rng([seed, i]), so a case can be rebuilt from the seed and index alone.
    test(inputs) -> '' when the case holds, else a short reason. An exception counts as a failure.
    """
    cases = [(f'edge: {name}', inputs) for name, inputs in edges]
    cases += [(f'case {i}', draw(np.random.default_rng([seed, i]))) for i in range(n_random)]
    failed = []
    for tag, inputs in cases:
        try:
            why = test(inputs)
        except Exception as e:                       # noqa: BLE001 - a crash is a failing case
            why = f'raised {type(e).__name__}: {e}'
        if why:
            failed.append(f'[{tag}] {inputs!r} -> {why}')
    if failed:
        check(f'{label} seed={seed}: {len(failed)} of {len(cases)} cases failed; first 3: '
              + '; '.join(failed[:3]), False)
    else:
        check(f'{label} seed={seed}: {len(cases)} cases ({len(edges)} edge, {n_random} random)', True)


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

# --- nonreg-accounts Requirements 4.1 and 5: plans saved with base_nonreg_p2 ---
LEGACY = 'base_nonreg_p2'
TAKEN_POOL = ('Sam non-registered', 'Sam non-registered (2)', 'Person 2 non-registered',
              'Person 2 non-registered (2)')


def legacy_dict(inp: dict) -> dict:
    """A plan dictionary as saved before nonreg-accounts, built from example_plan().to_dict().

    inp: 'B' (the saved base_nonreg_p2; key absent = not saved), 'people' ('Sam', 'empty name', 'no P2'
    or 'no people'), 'taken' (names of accounts already in the plan), 'no_accounts' (drop the rest).
    """
    d = example_plan().to_dict()
    d['accounts'] = [] if inp['no_accounts'] else [a for a in d['accounts'] if a['kind'] != 'nonreg']
    for i, name in enumerate(inp['taken']):
        d['accounts'].append({'name': name, 'owner': 'P2', 'kind': 'nonreg', 'balance': 10_000 * (i + 1),
                              'return_rate': 0.03, 'contribution': 1_000, 'contribution_is_tfsa_limit': False,
                              'volatility': 0.1})
    if inp['people'] == 'empty name':
        next(p for p in d['people'] if p['key'] == 'P2')['name'] = ''
    elif inp['people'] == 'no P2':
        d['people'] = [p for p in d['people'] if p['key'] != 'P2']
    elif inp['people'] == 'no people':
        d['people'] = []
    if 'B' in inp:
        d[LEGACY] = inp['B']
    return d


# Feature: nonreg-accounts, Property 7: the Legacy_Base conversion rule
def draw7(rng) -> dict:
    inp = {}
    c = int(rng.integers(10))
    if c == 1:
        inp['B'] = None
    elif c in (2, 3, 4):
        inp['B'] = (0, 0.0, -0.0)[c - 2]
    elif c in (5, 6):
        inp['B'] = round(float(rng.uniform(-500_000, -0.01)), 2)
    elif c in (7, 8):
        inp['B'] = round(float(rng.uniform(0.01, 2_000_000)), 2)
    elif c == 9:
        inp['B'] = int(rng.integers(1, 2_000_000))
    # c == 0: the key is absent
    inp['people'] = str(rng.choice(['Sam', 'empty name', 'no P2', 'no people'], p=[0.5, 0.2, 0.2, 0.1]))
    inp['taken'] = [TAKEN_POOL[j] for j in rng.permutation(len(TAKEN_POOL)) if rng.random() < 0.5]
    inp['no_accounts'] = bool(rng.random() < 0.1)
    return inp


def test7(inp: dict) -> str:
    d = legacy_dict(inp)
    before = repr(d)                                 # repr keeps -0.0 and None distinguishable
    plan = Plan.from_dict(d)
    saved = [Account(**a) for a in d['accounts']]
    b = inp.get('B')
    if b is None or b == 0:                          # absent, null, 0, 0.0 or -0.0: no account (5.4)
        want = saved
    else:                                            # one Equivalent_Account of balance B, appended (5.1, 5.5)
        p2 = next((p for p in d['people'] if p['key'] == 'P2'), None)
        stem = f'{p2["name"]} non-registered' if p2 is not None and p2['name'] else 'Person 2 non-registered'
        names = {a['name'] for a in d['accounts']}
        # 5.2, 5.3: the stem, else the stem with the smallest free " (k)", k >= 2
        name = next(n for n in [stem] + [f'{stem} ({k})' for k in range(2, len(names) + 3)] if n not in names)
        want = saved + [Account(name=name, owner='P2', kind='nonreg', balance=float(b), return_rate=0.0,
                                contribution=0.0, contribution_is_tfsa_limit=False, volatility=0.0)]
    why = []
    if plan.accounts != want:
        why.append(f'accounts {[(a.name, a.kind, a.balance) for a in plan.accounts[len(saved):]]} '
                   f'after the saved ones, want {[(a.name, a.kind, a.balance) for a in want[len(saved):]]}')
    if LEGACY in plan.to_dict():
        why.append(f'to_dict() holds {LEGACY}')        # 4.1
    if repr(d) != before:
        why.append('input dictionary changed')
    return '; '.join(why)


base7 = {'people': 'Sam', 'taken': [], 'no_accounts': False}
edges7 = [
    ('B 0', {'B': 0, **base7}),
    ('B 0.0', {'B': 0.0, **base7}),
    ('B -0.0', {'B': -0.0, **base7}),
    ('B None', {'B': None, **base7}),
    ('B absent', dict(base7)),
    ('B negative', {'B': -50_000, **base7}),
    ('no accounts', {'B': 150_000, **base7, 'no_accounts': True}),
    ('name taken', {'B': 150_000, **base7, 'taken': ['Sam non-registered']}),
    ('name and (2) taken', {'B': 150_000, **base7, 'taken': ['Sam non-registered', 'Sam non-registered (2)']}),
    ('only (2) taken', {'B': 150_000, **base7, 'taken': ['Sam non-registered (2)']}),
    ('no P2', {'B': 150_000, **base7, 'people': 'no P2'}),
    ('no P2, Person 2 name taken', {'B': 150_000, **base7, 'people': 'no P2', 'taken': ['Person 2 non-registered']}),
    ('no people', {'B': 150_000, **base7, 'people': 'no people'}),
    ('P2 name empty', {'B': 150_000, **base7, 'people': 'empty name'}),
]
check_property('Property 7 (Legacy_Base conversion)', 107, edges7, draw7, 100, test7)


# Feature: nonreg-accounts, Property 8: conversion is idempotent
def draw8(rng) -> dict:
    """A Property 7 draw with a non-zero B: a zero, None or absent B is replaced from the same rng."""
    inp = draw7(rng)
    if not inp.get('B'):
        inp['B'] = round(float(rng.uniform(0.01, 2_000_000)), 2)
    return inp


def test8(inp: dict) -> str:
    d = legacy_dict(inp)
    once = Plan.from_dict(d)
    again = Plan.from_json(once.to_json())
    why = []
    if again != once:                                # 5.6: a second load adds nothing
        why.append(f'reloaded accounts {[(a.name, a.balance) for a in again.accounts]} '
                   f'!= {[(a.name, a.balance) for a in once.accounts]}')
    if len(once.accounts) != len(d['accounts']) + 1:
        why.append(f'{len(once.accounts)} accounts, want {len(d["accounts"]) + 1}')
    return '; '.join(why)


edges8 = [(name, inp) for name, inp in edges7 if inp.get('B')]
check_property('Property 8 (conversion is idempotent)', 108, edges8, draw8, 100, test8)


# Feature: nonreg-accounts, Property 9: JSON round trip with non-registered accounts
def plan9(inp: dict) -> Plan:
    """A Plan from example_plan() with its nonreg accounts replaced by inp['nonreg'].

    inp: 'nonreg' (list of (owner, balance, return_rate, contribution, volatility)), 'others' (keep the
    registered and TFSA accounts), 'people' ('Sam', 'empty name' or 'no P2'; with no P2, only P1
    accounts are kept).
    """
    p = example_plan()
    p.accounts = [a for a in p.accounts if a.kind != 'nonreg'] if inp['others'] else []
    for i, (owner, bal, rate, contrib, vol) in enumerate(inp['nonreg']):
        p.accounts.append(Account(name=f'Person {owner[1]} non-registered {i + 1}', owner=owner, kind='nonreg',
                                  balance=bal, return_rate=rate, contribution=contrib,
                                  contribution_is_tfsa_limit=False, volatility=vol))
    if inp['people'] == 'empty name':
        p.person('P2').name = ''
    elif inp['people'] == 'no P2':
        p.people = [x for x in p.people if x.key != 'P2']
        p.accounts = [a for a in p.accounts if a.owner != 'P2']
    return p


def draw9(rng) -> dict:
    nonreg = []
    for _ in range(int(rng.integers(1, 5))):
        c = int(rng.integers(8))
        bal = ((0, 0.0, -0.0)[c] if c < 3 else round(float(rng.uniform(-500_000, -0.01)), 2) if c == 3
               else int(rng.integers(1, 2_000_000)) if c == 4 else round(float(rng.uniform(0.01, 2_000_000)), 2))
        nonreg.append((str(rng.choice(['P1', 'P2'])), bal, round(float(rng.uniform(0, 0.1)), 4),
                       float(rng.choice([0.0, round(float(rng.uniform(0, 20_000)), 2)])),
                       round(float(rng.uniform(0, 0.3)), 4)))
    people = str(rng.choice(['Sam', 'empty name', 'no P2'], p=[0.6, 0.2, 0.2]))
    if people == 'no P2':                            # keep at least one nonreg account in the plan
        nonreg[0] = ('P1',) + nonreg[0][1:]
    return {'nonreg': nonreg, 'others': bool(rng.random() < 0.8), 'people': people}


def test9(inp: dict) -> str:
    p = plan9(inp)
    text = p.to_json()
    b = Plan.from_json(text)
    why = []
    if b != p:                                       # 5.7
        why.append('from_json(to_json()) != plan')
    if repr(b.accounts) != repr(p.accounts):         # == treats -0.0 as 0.0 and 1 as 1.0; repr does not
        why.append(f'accounts came back as {[(a.name, a.balance) for a in b.accounts]}, '
                   f'want {[(a.name, a.balance) for a in p.accounts]}')
    if b.to_json() != text:
        why.append('second serialization differs')
    return '; '.join(why)


nr1, nr2 = ('P1', 80_000, 0.04, 5_000.0, 0.1), ('P2', 150_000, 0.0, 0.0, 0.0)
base9 = {'nonreg': [nr1, nr2], 'others': True, 'people': 'Sam'}
edges9 = [
    ('balance 0', {**base9, 'nonreg': [nr1, ('P2', 0, 0.0, 0.0, 0.0)]}),
    ('balance -0.0', {**base9, 'nonreg': [nr1, ('P2', -0.0, 0.0, 0.0, 0.0)]}),
    ('balance negative', {**base9, 'nonreg': [nr1, ('P2', -50_000, 0.0, 0.0, 0.0)]}),
    ('no accounts', {**base9, 'nonreg': [], 'others': False}),
    ('no nonreg P1', {**base9, 'nonreg': [nr2]}),
    ('no nonreg P2', {**base9, 'nonreg': [nr1]}),
    ('no P2', {**base9, 'people': 'no P2'}),
    ('P2 name empty', {**base9, 'people': 'empty name'}),
]
check_property('Property 9 (JSON round trip with non-registered accounts)', 109, edges9, draw9, 100, test9)

# the pre-feature Example_Plan: "Sam non-registered" was base_nonreg_p2 = 150,000
d = example_plan().to_dict()
d['accounts'] = [a for a in d['accounts'] if a['name'] != 'Sam non-registered']
d[LEGACY] = 150_000
check('the pre-feature Example_Plan dictionary loads to a Plan equal to example_plan()',
      Plan.from_dict(d) == example_plan())
check(f"'{LEGACY}' is not in example_plan().to_dict()", LEGACY not in example_plan().to_dict())

print('\nPLAN CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
