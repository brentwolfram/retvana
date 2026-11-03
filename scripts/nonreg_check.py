"""Check the non-registered account kind (nonreg-accounts spec) against hand calculations.
  .venv/bin/python scripts/nonreg_check.py

Fixed lines first: the named small plan of Requirement 10.5 (hand FV and the starting pools for a
positive and a negative property surplus), the single Account_Kinds definition (Req 1.3) and the
static scan for the removed `base_nonreg_p2` (Req 4.4). Then the seeded property loops of the
design's "Seeds, edge cases and failure lines": each runs its labelled edge cases, then at least 100
random cases, where random case i draws every input from np.random.default_rng([seed, i]), so one
case can be rebuilt from the seed and the index alone. A property prints one PASS or FAIL line with
its number, seed, case counts and, on failure, the first three failing cases with repr inputs.

Plans are built from example_plan() in legacy mode with the accounts replaced per case. Expected
values come from the rule written out here; the property surplus and the option proceeds are inputs
to the pool rule (design, Testing Strategy), and the option proceeds are written out by hand too.
"""
import ast
import dataclasses
import glob
import math
import os
import re
import sys
import time
import numpy as np
from retvana import analysis
from retvana import property_model as pm
from retvana.analysis import _plan_for_year, _starts_for_year
from retvana.config import ACCOUNT_KINDS, Account, example_plan
from retvana.engine import options_net_proceeds, project, starting_position
from retvana.vector import Starts, project_many

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def close(a, b, tol=0.01):
    return abs(a - b) <= tol


# ------------------------------------------------------------------ seeds (design seed table)
SEED_P1 = 101            # Property 1: unknown kinds are rejected by name
SEED_P2 = 102            # Property 2: Engine Retirement_Value is the hand FV
SEED_P3 = 103            # Property 3: vector growth (account draws and the shock matrix)
SEED_P4_ENGINE = 104     # Property 4, Engine: the pool split rule
SEED_P4_VECTOR = 204     # Property 4, vector
SEED_P5 = 105            # Property 5: registered and TFSA starts do not depend on nonreg accounts
SEED_P6 = 106            # Property 6: the three random balances of the Equivalent_Account grid
MIN_RANDOM = 100         # every loop runs at least this many random cases after its edge cases
SHOW = 3                 # failing cases shown on a FAIL line

# Rule constants written out
CUR = 2026               # example_plan().current_year
TFSA_LIMIT = 7000        # plan TFSA limit, 2026 (public constant)


# ------------------------------------------------------------------ harness
def case_rng(seed, i):
    """The generator for random case i of a property: its own stream, independent of earlier cases."""
    return np.random.default_rng([seed, i])


def run_property(title, seed, edge_cases, draw, test, n_random=MIN_RANDOM):
    """Run one property loop and print its PASS/FAIL line.

    title       e.g. 'Property 4 (Engine)'
    edge_cases  list of (label, inputs): run first, in order
    draw        draw(rng) -> inputs, for random case i with rng = case_rng(seed, i)
    test        test(inputs) -> None when the case holds, else a short reason string; an exception
                raised by test counts as a failure with its repr as the reason
    Returns True when every case holds."""
    if n_random < MIN_RANDOM:
        raise ValueError(f'{title}: {n_random} random cases, the design asks for at least {MIN_RANDOM}')
    cases = [(f'edge: {label}', inputs) for label, inputs in edge_cases]
    cases += [(f'case {i}', draw(case_rng(seed, i))) for i in range(n_random)]
    failed = []
    for tag, inputs in cases:
        try:
            reason = test(inputs)
        except Exception as e:                     # noqa: BLE001 - every error is a failing case
            reason = repr(e)
        if reason is not None:
            failed.append((tag, inputs, reason))
    n = len(cases)
    if failed:
        first = '; '.join(f'[{tag}] {inputs!r} -> {reason}' for tag, inputs, reason in failed[:SHOW])
        check(f'{title} seed={seed}: {len(failed)} of {n} cases failed; first {min(SHOW, len(failed))}: {first}',
              False)
    else:
        check(f'{title} seed={seed}: {n} cases ({len(edge_cases)} edge, {n_random} random)', True)
    return not failed


def plan_with(accounts, start_year=2032, p2_name='Sam'):
    """example_plan() in legacy mode with the accounts replaced (and, if asked, the retirement year and
    Person 2's name). The other example inputs (properties, options, expenses) stay as they are."""
    p = example_plan()
    p.property_mode = 'legacy'
    p.start_year = start_year
    p.accounts = list(accounts)
    p.person('P2').name = p2_name
    p.sync_end_year()
    return p


def nonreg(name, owner, balance, rate=0.0, contribution=0.0, tfsa_limit=False, vol=0.0):
    """A non-registered account."""
    return Account(name, owner, 'nonreg', balance, rate, contribution, tfsa_limit, vol)


def hand_fv(balance, rate, pmt, years):
    """Req 2.1: grow year by year, contribution added at year end, no tax: bal = bal x (1 + rate) + pmt."""
    bal = float(balance)
    for _ in range(years):
        bal = bal * (1 + rate) + pmt
    return bal


def hand_options(p):
    """engine-baseline Req 2.2: Person 1's option benefit, half of it taxed at the marginal rate."""
    total = 0.0
    for g in p.option_grants:
        benefit = max(g.available * (p.options_share_price - g.grant_price), 0.0)
        total += benefit * (1 - 0.5 * p.options_marginal_rate)
    return total


def hand_pools(o, n1, n2, s):
    """Req 3.1-3.3: Person 2's pool takes the surplus; a shortfall beyond N2 comes from Person 1."""
    after = n2 + s
    return {'nonreg_p2': max(0.0, after), 'nonreg_p1': o + n1 + min(0.0, after), 'shortfall_from_p1': -min(0.0, after)}


# ------------------------------------------------------------------ Req 10.5 the named small plan
print('--- Req 10.5: small plan with a non-registered account for each person')
SMALL = [nonreg('P1 non-registered', 'P1', 100_000, 0.05, 10_000),
         nonreg('P2 non-registered', 'P2', 200_000, 0.04, 0, tfsa_limit=True)]
p = plan_with(SMALL)
years = p.start_year - p.current_year
check('small plan inputs are the stated values',
      p.current_year == CUR and p.start_year == 2032 and p.tfsa_limit == TFSA_LIMIT and p.property_mode == 'legacy'
      and [a.kind for a in p.accounts] == ['nonreg', 'nonreg'])
fv1 = hand_fv(100_000, 0.05, 10_000, years)          # $10,000 a year
fv2 = hand_fv(200_000, 0.04, TFSA_LIMIT, years)      # "TFSA limit" on: the plan's $7,000
st = starting_position(p)
fv_ok = (close(st.account_fv['P1 non-registered'], fv1) and close(st.account_fv['P2 non-registered'], fv2)
         and close(st.nonreg_total_p1, fv1) and close(st.nonreg_total_p2, fv2)
         and st.reg_p1 == st.reg_p2 == st.tfsa_p1 == st.tfsa_p2 == 0.0)
check(f'Retirement_Value by hand FV over {years} years within $0.01: P1 non-registered {fv1:,.2f}, '
      f'P2 non-registered {fv2:,.2f}; nonreg_total_p1/p2 are those values, registered and TFSA starts 0',
      fv_ok, '' if fv_ok else f'got {st.account_fv}, totals {st.nonreg_total_p1:,.2f} / {st.nonreg_total_p2:,.2f}')

values, _ = pm.sale_values(p, p.start_year)
o = hand_options(p)
bad, signs = [], []
for price in (0.0, 3_000_000.0):
    st = starting_position(p, (values, price))
    s = st.waterfall.surplus                         # input to the pool rule (checked in property_check)
    signs.append(fv2 + s)
    want = hand_pools(o, fv1, fv2, s)
    for f, w in want.items():
        if not close(getattr(st, f), w):
            bad.append(f'price {price:,.0f} {f}: {getattr(st, f):,.2f} vs {w:,.2f}')
check(f'pools follow Req 3.1-3.3 for a $0 townhouse (N2 + S = {signs[0]:,.0f} > 0) and a $3,000,000 townhouse '
      f'(N2 + S = {signs[1]:,.0f} < 0): nonreg_p2 = max(0, N2 + S), nonreg_p1 = options + N1 + min(0, N2 + S), '
      'shortfall_from_p1 = -min(0, N2 + S)',
      not bad and signs[0] > 0 and signs[1] < 0, '; '.join(bad))

# ------------------------------------------------------------------ Req 1.3 one Account_Kinds definition
print('--- Req 1.3: the accepted kinds come from config.ACCOUNT_KINDS')


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


app_src, ana_src, eng_src = read('app.py'), read('src/retvana/analysis.py'), read('src/retvana/engine.py')
# A literal list of kinds anywhere but config.py would be a second definition.
kind_list = re.compile(r"""['"]registered['"]\s*,\s*['"]tfsa['"]""")
second = [rel for rel in ['app.py'] + sorted(os.path.relpath(f, ROOT) for f in glob.glob(os.path.join(ROOT, 'src', 'retvana', '*.py')))
          if not rel.endswith('config.py') and kind_list.search(read(rel))]
check("ACCOUNT_KINDS == ('registered', 'tfsa', 'nonreg'); app.py offers SelectboxColumn(options=list(ACCOUNT_KINDS)); "
      'analysis.py keys its totals by ACCOUNT_KINDS; engine.py and analysis.py call check_account_kind; no other '
      'file writes the kind list',
      ACCOUNT_KINDS == ('registered', 'tfsa', 'nonreg')
      and 'SelectboxColumn(options=list(ACCOUNT_KINDS))' in app_src
      and re.search(r'for k in ACCOUNT_KINDS\}', ana_src) is not None
      and 'check_account_kind(a)' in ana_src and 'check_account_kind(a)' in eng_src and not second,
      f'kind list written in {second}' if second else '')

# ------------------------------------------------------------------ Req 4.4 no base_nonreg_p2 left
print('--- Req 4.4: base_nonreg_p2 only in the Plan_Loader conversion and the checks that test it')
LEGACY = 'base_nonreg_p2'
ALLOWED_FILES = {'scripts/plan_check.py', 'scripts/plan_io_check.py', 'scripts/nonreg_check.py', 'scripts/smoke_test.py'}


def config_allowed_lines():
    """config.py: the LEGACY_NONREG_KEY assignment and the conversion helper _legacy_nonreg_account
    (its docstring names the key it converts); the Plan_Loader conversion of Req 5."""
    tree = ast.parse(read('src/retvana/config.py'))
    lines = set()
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'LEGACY_NONREG_KEY' for t in node.targets)) \
                or (isinstance(node, ast.FunctionDef) and node.name == '_legacy_nonreg_account'):
            lines.update(range(node.lineno, node.end_lineno + 1))
    return lines


cfg_ok = config_allowed_lines()
scan = ['app.py'] + sorted(os.path.relpath(f, ROOT).replace(os.sep, '/')
                           for pat in ('src/retvana/*.py', 'scripts/*.py') for f in glob.glob(os.path.join(ROOT, pat)))
found = []
for rel in scan:
    if rel in ALLOWED_FILES:
        continue
    for n, line in enumerate(read(rel).splitlines(), 1):
        if LEGACY in line and not (rel == 'src/retvana/config.py' and n in cfg_ok):
            found.append(f'{rel}:{n}')
check(f'no {LEGACY} in src/retvana, app.py or scripts ({len(scan)} files) outside the LEGACY_NONREG_KEY line and '
      f'conversion helper of config.py and {", ".join(sorted(os.path.basename(f) for f in ALLOWED_FILES))}',
      not found and cfg_ok, f'found at {", ".join(found)}' if found else '')

# ------------------------------------------------------------------ properties (tasks 8.2 to 8.7)
# Each property is a function that calls run_property once per line (Property 4 has an Engine and a
# vector line) and is registered with @prop. They run in registration order after the fixed lines.
# Tag each with a comment: # Feature: nonreg-accounts, Property N: <title>
PROPERTIES = []


def prop(fn):
    PROPERTIES.append(fn)
    return fn


# Feature: nonreg-accounts, Property 1: Unknown kinds are rejected by name
BAD_KINDS = ('', 'Registered', 'TFSA', 'other')
LETTERS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ _-'
VALID_ACCOUNT = ('registered', 'tfsa', 'nonreg')       # kinds for the other, valid accounts of a case
def p1_draw(rng):
    """A bad kind (one of BAD_KINDS or a random letter string not in ACCOUNT_KINDS) on a random account,
    placed among 0 to 3 valid accounts; a retirement year from 2026 to 2040."""
    if rng.random() < 0.4:
        kind = BAD_KINDS[int(rng.integers(len(BAD_KINDS)))]
    else:
        kind = ''.join(rng.choice(list(LETTERS), int(rng.integers(1, 12))))
        while kind in ACCOUNT_KINDS:
            kind += 'x'
    name = 'Account ' + ''.join(rng.choice(list(LETTERS), int(rng.integers(0, 8))))
    bad = (name, str(rng.choice(['P1', 'P2'])), kind, round(float(rng.uniform(-50_000, 2_000_000)), 2))
    others = [(f'Valid {j}', str(rng.choice(['P1', 'P2'])), str(rng.choice(VALID_ACCOUNT)),
               round(float(rng.uniform(0, 500_000)), 2)) for j in range(int(rng.integers(0, 4)))]
    others.insert(int(rng.integers(len(others) + 1)), bad)
    return {'bad': bad, 'accounts': others, 'start_year': int(rng.integers(2026, 2041)), 'p2_name': 'Sam'}
def p1_test(c):
    """Both functions raise ValueError whose message holds repr(name) and repr(kind)."""
    name, _, kind, _ = c['bad']
    p = plan_with([Account(n, o, k, b, 0.04, 1_000, False, 0.1) for n, o, k, b in c['accounts']],
                  start_year=c['start_year'], p2_name=c['p2_name'])
    pre = p.start_year - p.current_year
    z = np.random.default_rng(SEED_P1).standard_normal((4, max(pre, 1)))
    calls = {'starting_position': lambda: starting_position(p),
             '_starts_for_year': lambda: _starts_for_year(p, p.start_year, z, 0.0)}
    for fname, call in calls.items():
        try:
            call()
        except ValueError as e:
            msg = str(e)
            if repr(name) not in msg or repr(kind) not in msg:
                return f'{fname} message {msg!r} lacks {name!r} or {kind!r}'
            continue
        return f'{fname} raised no ValueError'
    return None
@prop
def property_1():
    """Property 1: unknown kinds are rejected by name (Req 1.4, 1.5, 10.8)"""
    def only(balance, p2_name='Sam'):
        bad = ('Account X', 'P2', 'other', balance)
        return {'bad': bad, 'accounts': [bad], 'start_year': 2032, 'p2_name': p2_name}
    edges = [('only account', only(100_000.0)),
             ('balance 0', only(0)),
             ('balance -0.0', only(-0.0)),
             ('balance negative', only(-50_000.0)),
             ('P2 name empty', only(100_000.0, p2_name=''))]
    for k in BAD_KINDS:                            # the named bad kinds, each at least once
        bad = ('Account X', 'P1', k, 100_000.0)
        edges.append((f'kind {k!r}', {'bad': bad, 'accounts': [('Valid 0', 'P2', 'nonreg', 50_000.0), bad],
                                      'start_year': 2032, 'p2_name': 'Sam'}))
    run_property('Property 1', SEED_P1, edges, p1_draw, p1_test)
# Feature: nonreg-accounts, Property 2: Engine Retirement_Value is the hand FV
P2_RANDOM = 200
def p2_account(rng, owner, j):
    """A nonreg account with the design's ranges; the name is unique within the case."""
    return (f'{owner} nonreg {j}', owner, round(float(rng.uniform(-50_000, 2_000_000)), 2),
            round(float(rng.uniform(-0.05, 0.12)), 4), round(float(rng.uniform(0, 30_000)), 2),
            bool(rng.random() < 0.3))
def p2_draw(rng):
    """0 to 3 nonreg accounts per person and a retirement year from 2026 to 2040 (0 to 14 years)."""
    accounts = [p2_account(rng, owner, j) for owner in ('P1', 'P2') for j in range(int(rng.integers(0, 4)))]
    order = rng.permutation(len(accounts))
    return {'accounts': [accounts[k] for k in order], 'start_year': int(rng.integers(2026, 2041)), 'p2_name': 'Sam'}
def p2_test(c):
    """account_fv[name] is the hand loop; nonreg_total_p1/p2 are the per-owner sums of the hand values."""
    p = plan_with([nonreg(n, o, b, r, pmt, flag) for n, o, b, r, pmt, flag in c['accounts']],
                  start_year=c['start_year'], p2_name=c['p2_name'])
    years = c['start_year'] - CUR
    st = starting_position(p)
    want = {n: hand_fv(b, r, TFSA_LIMIT if flag else pmt, years) for n, _, b, r, pmt, flag in c['accounts']}
    if set(st.account_fv) != set(want):
        return f'account_fv names {sorted(st.account_fv)} vs {sorted(want)}'
    for n, w in want.items():
        if not close(st.account_fv[n], w):
            return f'account_fv[{n!r}] {st.account_fv[n]!r} vs hand {w!r}'
    for owner, got in (('P1', st.nonreg_total_p1), ('P2', st.nonreg_total_p2)):
        w = sum((want[n] for n, o, *_ in c['accounts'] if o == owner), 0.0)
        if not close(got, w):
            return f'nonreg_total_{owner.lower()} {got!r} vs hand {w!r}'
    return None
@prop
def property_2():
    """Property 2: Engine Retirement_Value is the hand FV (Req 1.1, 1.2, 2.1, 2.2, 2.3, 10.5)"""
    def case(accounts, p2_name='Sam', start_year=2032):
        return {'accounts': accounts, 'start_year': start_year, 'p2_name': p2_name}
    both = [('P1 nonreg 0', 'P1', 100_000.0, 0.05, 10_000.0, False),
            ('P2 nonreg 0', 'P2', 200_000.0, 0.04, 0.0, True)]
    edges = [('balance 0', case([('P1 nonreg 0', 'P1', 0, 0.05, 10_000.0, False)])),
             ('balance -0.0', case([('P2 nonreg 0', 'P2', -0.0, 0.05, 0.0, False)])),
             ('balance negative', case([('P1 nonreg 0', 'P1', -50_000.0, 0.05, 10_000.0, True)])),
             ('no accounts', case([])),
             ('no nonreg P2', case([both[0]])),
             ('no nonreg P1', case([both[1]])),
             ('P2 name empty', case(both, p2_name=''))]
    run_property('Property 2', SEED_P2, edges, p2_draw, p2_test, n_random=P2_RANDOM)
# Feature: nonreg-accounts, Property 3: Vector growth follows each account's own rate and volatility
P3_PATHS = 100
REL_TOL = 1e-9           # relative tolerance of the hand per-path loop
ABS_FLOOR = 1e-6         # absolute floor, in dollars, for totals near 0 (balance 0, -0.0, no accounts)
def p3_account(rng, owner, j):
    """Property 2's account plus a volatility in [0, 0.3]."""
    return p2_account(rng, owner, j) + (round(float(rng.uniform(0, 0.3)), 4),)
def p3_draw(rng):
    """0 to 3 nonreg accounts per person, a retirement year from 2027 to 2040, and the seed of the
    100-path shock matrix (drawn from the case's own generator, so the case rebuilds from seed and index;
    the matrix itself is not stored, to keep failure lines short)."""
    accounts = [p3_account(rng, owner, j) for owner in ('P1', 'P2') for j in range(int(rng.integers(0, 4)))]
    order = rng.permutation(len(accounts))
    return {'accounts': [accounts[k] for k in order], 'start_year': int(rng.integers(2027, 2041)),
            'p2_name': 'Sam', 'z_seed': int(rng.integers(2**32))}
def p3_hand_paths(balance, rate, pmt, vol, z, years):
    """Req 2.4, 2.5: path by path, year by year: g = exp(ln(1 + rate) + vol x z[i, t]) - 1, then
    bal = bal x (1 + g) + pmt, the contribution added at year end."""
    out = np.empty(z.shape[0])
    for i in range(z.shape[0]):
        bal = float(balance)
        for t in range(years):
            g = math.exp(math.log(1 + rate) + vol * float(z[i, t])) - 1
            bal = bal * (1 + g) + pmt
        out[i] = bal
    return out
def p3_rel_bad(got, want):
    """Paths where got differs from want by more than REL_TOL relative (ABS_FLOOR near 0)."""
    return np.flatnonzero(np.abs(got - want) > np.maximum(REL_TOL * np.abs(want), ABS_FLOOR))
def p3_totals(accounts, c, z, risk):
    """The per-path non-registered totals (N1, N2) from _starts_for_year.

    Isolation: with a surplus of 0.0 the returned `after` is N2 + 0.0, Person 2's total alone, with no
    option proceeds and no max/min of the pool rule in the way. For N1 the same accounts are run once more
    with Person 1's nonreg accounts given to Person 2 and Person 2's dropped, so that run's `after` is N1.
    Growth depends only on an account's own inputs and the shocks (Req 2.4), not on its owner, so the
    relabelled run grows Person 1's accounts exactly as the first run does."""
    def after_for(accs):
        p = plan_with([nonreg(n, o, b, r, pmt, flag, vol) for n, o, b, r, pmt, flag, vol in accs],
                      start_year=c['start_year'], p2_name=c['p2_name'])
        p.mc_pre_retirement = risk
        _, after = _starts_for_year(p, c['start_year'], z, 0.0)
        return np.asarray(after, dtype=float)
    n2 = after_for([a for a in accounts if a[1] == 'P2'])
    n1 = after_for([(a[0], 'P2') + a[2:] for a in accounts if a[1] == 'P1'])
    return n1, n2
def p3_test(c):
    """With pre-retirement risk on, the per-path totals are the hand per-path loop (relative 1e-9); with it
    off, every path equals the Engine's nonreg_total_p1/p2 within $0.01."""
    years = c['start_year'] - CUR
    z = np.random.default_rng(c['z_seed']).standard_normal((P3_PATHS, max(years, 1)))
    accounts = c['accounts']
    n1, n2 = p3_totals(accounts, c, z, risk=True)
    for owner, got in (('P1', n1), ('P2', n2)):
        want = np.zeros(P3_PATHS)
        for _, o, b, r, pmt, flag, vol in accounts:
            if o == owner:
                want = want + p3_hand_paths(b, r, TFSA_LIMIT if flag else pmt, vol, z, years)
        bad = p3_rel_bad(got, want)
        if bad.size:
            i = int(bad[0])
            return f'risk on: {owner} total path {i} {got[i]!r} vs hand {want[i]!r} ({bad.size} paths off)'
    n1, n2 = p3_totals(accounts, c, z, risk=False)
    p = plan_with([nonreg(n, o, b, r, pmt, flag, vol) for n, o, b, r, pmt, flag, vol in accounts],
                  start_year=c['start_year'], p2_name=c['p2_name'])
    st = starting_position(p)
    for owner, got, eng in (('P1', n1, st.nonreg_total_p1), ('P2', n2, st.nonreg_total_p2)):
        bad = np.flatnonzero(np.abs(got - eng) > 0.01)
        if bad.size:
            i = int(bad[0])
            return f'risk off: {owner} total path {i} {got[i]!r} vs Engine {eng!r} ({bad.size} paths off)'
    return None
@prop
def property_3():
    """Property 3: Vector growth follows each account's own rate and volatility (Req 2.4, 2.5, 2.6)"""
    def case(accounts, p2_name='Sam', start_year=2032):
        return {'accounts': accounts, 'start_year': start_year, 'p2_name': p2_name, 'z_seed': SEED_P3}
    both = [('P1 nonreg 0', 'P1', 100_000.0, 0.05, 10_000.0, False, 0.15),
            ('P2 nonreg 0', 'P2', 200_000.0, 0.04, 0.0, True, 0.1)]
    edges = [('balance 0', case([('P1 nonreg 0', 'P1', 0, 0.05, 10_000.0, False, 0.15)])),
             ('balance -0.0 vol 0', case([('P2 nonreg 0', 'P2', -0.0, 0.05, 0.0, False, 0.0)])),
             ('balance -0.0 vol 0.3', case([('P2 nonreg 0', 'P2', -0.0, 0.05, 0.0, False, 0.3)])),
             ('balance negative', case([('P1 nonreg 0', 'P1', -50_000.0, 0.05, 10_000.0, True, 0.15)])),
             ('no accounts', case([])),
             ('no nonreg P2', case([both[0]])),
             ('no nonreg P1', case([both[1]])),
             ('P2 name empty', case(both, p2_name=''))]
    t0 = time.perf_counter()
    run_property('Property 3', SEED_P3, edges, p3_draw, p3_test)
    print(f'      Property 3: {P3_PATHS} paths per case, {time.perf_counter() - t0:.1f} s')
# Feature: nonreg-accounts, Property 4: The pool split rule
P4_RANDOM = 200          # Engine cases (design table)
P4_MIN_SIGN = 20         # each sign of N2 + S at least this often among the Engine's random cases
P4_PRICE_MAX = 3_000_000
P4_PATHS = 100
POOL_FIELDS = ('nonreg_p2', 'nonreg_p1', 'shortfall_from_p1')
def p4_engine_draw(rng):
    """Property 2's case plus a townhouse price in [0, 3,000,000], so the surplus takes both signs."""
    c = p2_draw(rng)
    c['price'] = round(float(rng.uniform(0, P4_PRICE_MAX)), 2)
    return c
def p4_engine_start(c):
    """The plan of case c and its Start with sale = (sale values at retirement, the case's price)."""
    p = plan_with([nonreg(n, o, b, r, pmt, flag) for n, o, b, r, pmt, flag in c['accounts']],
                  start_year=c['start_year'], p2_name=c['p2_name'])
    values, _ = pm.sale_values(p, p.start_year)
    return p, starting_position(p, (values, c['price']))
P4_SIGNS = {}            # id(case) -> sign of N2 + S, filled by p4_engine_test
def p4_engine_test(c):
    """The three pool fields follow Req 3.1-3.3 from the hand N1, N2 and options, with S read from the
    waterfall (an input to the pool rule); with c['exact_zero'] N2 + S is 0.0 and both 0.0 fields are exact."""
    p, st = p4_engine_start(c)
    years = c['start_year'] - CUR
    s = st.waterfall.surplus
    n = {owner: sum((hand_fv(b, r, TFSA_LIMIT if flag else pmt, years)
                     for _, o, b, r, pmt, flag in c['accounts'] if o == owner), 0.0) for owner in ('P1', 'P2')}
    after = n['P2'] + s
    P4_SIGNS[id(c)] = (after > 0) - (after < 0)
    want = hand_pools(hand_options(p), n['P1'], n['P2'], s)
    for f in POOL_FIELDS:
        if not close(getattr(st, f), want[f]):
            return f'{f} {getattr(st, f)!r} vs hand {want[f]!r} (S {s!r}, N1 {n["P1"]!r}, N2 {n["P2"]!r})'
    if c.get('exact_zero'):
        if after != 0.0:
            return f'hand N2 + S is {after!r}, not 0.0 (S {s!r})'
        if not (st.nonreg_p2 == 0.0 and st.shortfall_from_p1 == 0.0):
            return f'N2 + S = 0.0 but nonreg_p2 {st.nonreg_p2!r}, shortfall_from_p1 {st.shortfall_from_p1!r}'
    return None
def p4_vector_draw(rng):
    """Property 3's case plus the seed of the per-path surplus normal(0, 500,000, 100) (drawn from the
    case's own generator; the array is rebuilt from it, to keep failure lines short)."""
    c = p3_draw(rng)
    c['s_seed'] = int(rng.integers(2**32))
    return c
def p4_surplus(c):
    """The case's per-path surplus: a short pattern tiled over the paths (edge cases) or the seeded normals."""
    if 'surplus_pattern' in c:
        return np.resize(np.array(c['surplus_pattern'], dtype=float), P4_PATHS)
    return np.random.default_rng(c['s_seed']).normal(0, 500_000, P4_PATHS)
def p4_vector_test(c):
    """With risk on, Starts.nonreg_p2 = max(0, N2 + S) and nonreg_p1 = O + N1 + min(0, N2 + S) on every
    path, and the returned After_Surplus is N2 + S, with N1, N2 the hand per-path totals (relative 1e-9)."""
    years = c['start_year'] - CUR
    z = np.random.default_rng(c['z_seed']).standard_normal((P4_PATHS, max(years, 1)))
    s = p4_surplus(c)
    p = plan_with([nonreg(n, o, b, r, pmt, flag, vol) for n, o, b, r, pmt, flag, vol in c['accounts']],
                  start_year=c['start_year'], p2_name=c['p2_name'])
    p.mc_pre_retirement = True
    st, got_after = _starts_for_year(p, c['start_year'], z, s)
    n = {owner: np.zeros(P4_PATHS) for owner in ('P1', 'P2')}
    for _, o, b, r, pmt, flag, vol in c['accounts']:
        n[o] = n[o] + p3_hand_paths(b, r, TFSA_LIMIT if flag else pmt, vol, z, years)
    after = n['P2'] + s
    want = {'after': after, 'nonreg_p2': np.maximum(0.0, after),
            'nonreg_p1': hand_options(p) + n['P1'] + np.minimum(0.0, after)}
    got = {'after': np.asarray(got_after, dtype=float), 'nonreg_p2': st.nonreg_p2, 'nonreg_p1': st.nonreg_p1}
    for f, w in want.items():
        g = np.asarray(got[f], dtype=float)
        if g.shape != w.shape:
            return f'{f} shape {g.shape} vs {w.shape}'
        bad = p3_rel_bad(g, w)
        if bad.size:
            i = int(bad[0])
            return f'{f} path {i} {g[i]!r} vs hand {w[i]!r} (S {s[i]!r}; {bad.size} paths off)'
    return None
@prop
def property_4():
    """Property 4: The pool split rule (Req 3.1, 3.2, 3.3, 3.4, 10.5)"""
    # Engine: the Property 2 edge cases at a $0 and a $3,000,000 townhouse, then After_Surplus exactly 0
    def case(accounts, price, p2_name='Sam', start_year=2032):
        return {'accounts': accounts, 'start_year': start_year, 'p2_name': p2_name, 'price': price}
    both = [('P1 nonreg 0', 'P1', 100_000.0, 0.05, 10_000.0, False),
            ('P2 nonreg 0', 'P2', 200_000.0, 0.04, 0.0, True)]
    p2_edges = [('balance 0', [('P1 nonreg 0', 'P1', 0, 0.05, 10_000.0, False)], 'Sam'),
                ('balance -0.0', [('P2 nonreg 0', 'P2', -0.0, 0.05, 0.0, False)], 'Sam'),
                ('balance negative', [('P1 nonreg 0', 'P1', -50_000.0, 0.05, 10_000.0, True)], 'Sam'),
                ('no accounts', [], 'Sam'),
                ('no nonreg P2', [both[0]], 'Sam'),
                ('no nonreg P1', [both[1]], 'Sam'),
                ('P2 name empty', both, '')]
    edges = [(f'{label}, price {price:,.0f}', case(accs, price, p2_name=name))
             for price in (0.0, float(P4_PRICE_MAX)) for label, accs, name in p2_edges]
    for price in (0.0, float(P4_PRICE_MAX)):        # S of both signs; the account's balance is -S
        _, st0 = p4_engine_start(case([], price))
        s = st0.waterfall.surplus
        c = case([('P2 nonreg 0', 'P2', -s, 0.0, 0.0, False)], price)
        c['exact_zero'] = True
        edges.append((f'after 0, price {price:,.0f}', c))
    P4_SIGNS.clear()
    t0 = time.perf_counter()
    run_property('Property 4 (Engine)', SEED_P4_ENGINE, edges, p4_engine_draw, p4_engine_test, n_random=P4_RANDOM)
    edge_ids = {id(c) for _, c in edges}
    rand = [sg for k, sg in P4_SIGNS.items() if k not in edge_ids]
    neg, pos = rand.count(-1), rand.count(1)
    check(f'Property 4 (Engine) seed={SEED_P4_ENGINE}: both signs of N2 + S covered, at least {P4_MIN_SIGN} each '
          f'among {len(rand)} random cases: {neg} with N2 + S < 0, {pos} with N2 + S > 0',
          len(rand) == P4_RANDOM and neg >= P4_MIN_SIGN and pos >= P4_MIN_SIGN)
    print(f'      Property 4 (Engine): {time.perf_counter() - t0:.1f} s')

    # vector: per-path surplus arrays, risk on, hand per-path totals
    def vcase(accounts, pattern, p2_name='Sam', start_year=2032):
        return {'accounts': accounts, 'start_year': start_year, 'p2_name': p2_name, 'z_seed': SEED_P4_VECTOR,
                'surplus_pattern': pattern}
    vboth = [a + (vol,) for a, vol in zip(both, (0.15, 0.1))]
    mixed = (0.0, -0.0, 250_000.0, -250_000.0, -1_000_000.0, 1_000_000.0)
    vedges = [('surplus 0', vcase(vboth, (0.0,))),
              ('surplus mixed', vcase(vboth, mixed)),
              ('no accounts', vcase([], mixed)),
              ('no nonreg P2', vcase([vboth[0]], mixed)),
              ('no nonreg P1', vcase([vboth[1]], mixed))]
    t0 = time.perf_counter()
    run_property('Property 4 (vector)', SEED_P4_VECTOR, vedges, p4_vector_draw, p4_vector_test)
    print(f'      Property 4 (vector): {P4_PATHS} paths per case, {time.perf_counter() - t0:.1f} s')
# Feature: nonreg-accounts, Property 5: Registered and TFSA starts do not depend on non-registered accounts
P5_PATHS = 100
P5_FIELDS = ('reg_p1', 'reg_p2', 'tfsa_p1', 'tfsa_p2')
def p5_account(rng, owner, kind, j):
    """An account of the given kind: Property 3's ranges (balance, rate, contribution, TFSA-limit flag,
    volatility), as (name, owner, kind, balance, rate, contribution, flag, vol); unique name per case."""
    _, o, b, r, pmt, flag, vol = p3_account(rng, owner, j)
    return (f'{owner} {kind} {j}', o, kind, b, r, pmt, flag, vol)
def p5_draw(rng):
    """0 to 3 accounts per person per kind (registered, TFSA, nonreg) in random order, a retirement year
    from 2027 to 2040, a townhouse price in [0, 3,000,000] for the Engine, and the seeds of the shock
    matrix and of the per-path surplus normal(0, 500,000) (rebuilt from the seeds, to keep failure lines short)."""
    accounts = [p5_account(rng, owner, kind, j) for owner in ('P1', 'P2') for kind in ACCOUNT_KINDS
                for j in range(int(rng.integers(0, 4)))]
    order = rng.permutation(len(accounts))
    return {'accounts': [accounts[k] for k in order], 'start_year': int(rng.integers(2027, 2041)),
            'p2_name': 'Sam', 'price': round(float(rng.uniform(0, P4_PRICE_MAX)), 2),
            'z_seed': int(rng.integers(2**32)), 's_seed': int(rng.integers(2**32))}
def p5_plan(accounts, c):
    return plan_with([Account(n, o, k, b, r, pmt, flag, vol) for n, o, k, b, r, pmt, flag, vol in accounts],
                     start_year=c['start_year'], p2_name=c['p2_name'])
def p5_test(c):
    """reg_p1, reg_p2, tfsa_p1 and tfsa_p2 are identical with and without the case's nonreg accounts: `==` in
    the Engine (plan's own sale and the case's townhouse price), np.array_equal per path in the Vector_Start
    (the same shocks, risk on and off, a nonzero per-path surplus)."""
    full = c['accounts']
    bare = [a for a in full if a[2] != 'nonreg']
    p_full, p_bare = p5_plan(full, c), p5_plan(bare, c)
    values, _ = pm.sale_values(p_full, p_full.start_year)
    for label, sale in (('plan sale', None), (f'price {c["price"]:,.2f}', (values, c['price']))):
        st_full = starting_position(p_full) if sale is None else starting_position(p_full, sale)
        st_bare = starting_position(p_bare) if sale is None else starting_position(p_bare, sale)
        for f in P5_FIELDS:
            if not getattr(st_full, f) == getattr(st_bare, f):
                return f'Engine ({label}) {f} {getattr(st_full, f)!r} with nonreg vs {getattr(st_bare, f)!r} without'
    years = c['start_year'] - CUR
    z = np.random.default_rng(c['z_seed']).standard_normal((P5_PATHS, max(years, 1)))
    s = np.random.default_rng(c['s_seed']).normal(0, 500_000, P5_PATHS)
    if not np.all(s != 0.0):
        return 'surplus has a zero path'
    for risk in (True, False):
        p_full.mc_pre_retirement = p_bare.mc_pre_retirement = risk
        v_full, _ = _starts_for_year(p_full, c['start_year'], z, s)
        v_bare, _ = _starts_for_year(p_bare, c['start_year'], z, s)
        for f in P5_FIELDS:
            g, w = getattr(v_full, f), getattr(v_bare, f)
            if not np.array_equal(g, w):
                bad = np.flatnonzero(np.asarray(g) != np.asarray(w))
                i = int(bad[0]) if bad.size else -1
                return (f'Vector_Start (risk {"on" if risk else "off"}) {f} differs on {bad.size} paths; '
                        f'path {i}: {np.asarray(g)[i]!r} vs {np.asarray(w)[i]!r}')
    return None
@prop
def property_5():
    """Property 5: Registered and TFSA starts do not depend on non-registered accounts (Req 3.5)"""
    def case(accounts):
        return {'accounts': accounts, 'start_year': 2032, 'p2_name': 'Sam', 'price': 1_500_000.0,
                'z_seed': SEED_P5, 's_seed': SEED_P5 + 1}
    others = [('P1 registered 0', 'P1', 'registered', 400_000.0, 0.05, 10_000.0, False, 0.15),
              ('P2 tfsa 0', 'P2', 'tfsa', 80_000.0, 0.04, 0.0, True, 0.1),
              ('P2 registered 0', 'P2', 'registered', 250_000.0, 0.06, 5_000.0, False, 0.2),
              ('P1 tfsa 0', 'P1', 'tfsa', 60_000.0, 0.03, 0.0, True, 0.05)]
    def with_nonreg(balance):
        return [others[0], ('P2 nonreg 0', 'P2', 'nonreg', balance, 0.05, 0.0, False, 0.15), others[1],
                ('P1 nonreg 0', 'P1', 'nonreg', balance, 0.04, 2_000.0, False, 0.1)] + others[2:]
    edges = [('no accounts', case([])),
             ('no nonreg accounts', case(others)),
             ('balance 0', case(with_nonreg(0))),
             ('balance -0.0', case(with_nonreg(-0.0))),
             ('balance negative', case(with_nonreg(-50_000.0)))]
    t0 = time.perf_counter()
    run_property('Property 5', SEED_P5, edges, p5_draw, p5_test)
    print(f'      Property 5: {P5_PATHS} paths per case, {time.perf_counter() - t0:.1f} s')
# Feature: nonreg-accounts, Property 6: An Equivalent_Account reproduces the legacy base exactly
# Property 6 is a fixed grid (design, "Property 6 grid (Req 10.6)"), not a random loop: its only random
# inputs are three balances drawn with case_rng(SEED_P6, i), i = 0..2. run_property asks for at least
# MIN_RANDOM random cases, which would add draws the design does not have, so the grid runs through
# run_grid below, which prints the same PASS/FAIL line (property, seed, failing count, first 3 cases).
# Every comparison is exact: ==, DataFrame.equals, np.array_equal. No tolerances.
P6_FIXED = (-400_000.0, -1.0, 0, -0.0, 0.01, 150_000.0, 1_400_000.0)
P6_N_DRAWS = 3
P6_YEARS = tuple(range(2027, 2037))
P6_MODES = ('legacy', 'recovery')
P6_PATHS = 100
P6_SURPLUS_SEED = 2026   # surplus_distribution's default seed, written out as the design's call does
SAM_NR = 'Sam non-registered'
P6_REG_TFSA = ('reg_p1', 'reg_p2', 'tfsa_p1', 'tfsa_p2')
def run_grid(title, seed, cases, test, n_drawn):
    """Run a fixed list of labelled cases and print one PASS/FAIL line in run_property's format."""
    failed = []
    for label, inputs in cases:
        try:
            reason = test(inputs)
        except Exception as e:                     # noqa: BLE001 - every error is a failing case
            reason = repr(e)
        if reason is not None:
            failed.append((label, inputs, reason))
    n = len(cases)
    if failed:
        first = '; '.join(f'[{tag}] {inputs!r} -> {reason}' for tag, inputs, reason in failed[:SHOW])
        check(f'{title} seed={seed}: {len(failed)} of {n} cases failed; first {min(SHOW, len(failed))}: {first}',
              False)
    else:
        check(f'{title} seed={seed}: {n} grid cases ({n_drawn} of the balances drawn from the seed)', True)
    return not failed
def p6_plans(c):
    """Step 1: q0 = _plan_for_year(base, y), base = example_plan() without "Sam non-registered" and with the
    case's mode and pre-retirement risk setting; q1 = q0 plus the Equivalent_Account of balance B."""
    base = example_plan()
    base.accounts = [a for a in base.accounts if a.name != SAM_NR]
    base.property_mode = c['mode']
    base.mc_pre_retirement = c['risk']
    q0 = _plan_for_year(base, c['year'])
    q1 = q0.copy()
    q1.accounts.append(Account(SAM_NR, 'P2', 'nonreg', c['B'], 0.0, 0, False, 0.0))
    return q0, q1
def p6_engine(c, q0, q1):
    """Steps 2 and 3: Start == the legacy rule on q0's start, and project(q1) equals project(q0, start=want)."""
    B = c['B']
    st0, st1 = starting_position(q0), starting_position(q1)
    S = st0.waterfall.surplus
    want = dataclasses.replace(st0, nonreg_p2=max(0.0, B + S), nonreg_p1=st0.options_net + min(0.0, B + S),
                               shortfall_from_p1=-min(0.0, B + S), nonreg_total_p2=B,
                               account_fv={**st0.account_fv, SAM_NR: B})
    if c.get('after_zero') and B + S != 0.0:
        return f'step 2: B + S is {B + S!r}, not 0.0 (S {S!r})'
    if not st1 == want:
        diff = [f.name for f in dataclasses.fields(want) if not getattr(st1, f.name) == getattr(want, f.name)]
        return f'step 2: Start differs in {diff} (S {S!r})'
    if not project(q1)[0].equals(project(q0, start=want)[0]):
        return 'step 3: project(q1) differs from project(q0, start=want)'
    return None
def p6_vector(c, q0, q1):
    """Steps 4 and 5: Starts per path with np.array_equal, then project_many key by key."""
    B, y = c['B'], c['year']
    z = analysis.market_shocks(q0, P6_PATHS)
    if c['mode'] == 'legacy':
        S = starting_position(q0).waterfall.surplus
    else:
        S = pm.surplus_distribution(q0, [y], P6_PATHS, P6_SURPLUS_SEED)['surplus'][y]
    s0, _ = _starts_for_year(q0, y, z, S)
    s1, _ = _starts_for_year(q1, y, z, S)
    want = Starts(nonreg_p1=options_net_proceeds(q0) + np.minimum(0.0, B + S), nonreg_p2=np.maximum(0.0, B + S),
                  reg_p1=s0.reg_p1, reg_p2=s0.reg_p2, tfsa_p1=s0.tfsa_p1, tfsa_p2=s0.tfsa_p2)
    for f in ('nonreg_p1', 'nonreg_p2') + P6_REG_TFSA:
        g, w = np.broadcast_to(getattr(s1, f), (P6_PATHS,)), np.broadcast_to(getattr(want, f), (P6_PATHS,))
        if not np.array_equal(g, w):
            bad = np.flatnonzero(g != w)
            i = int(bad[0]) if bad.size else -1
            return f'step 4: Starts.{f} differs on {bad.size} paths; path {i}: {g[i]!r} vs {w[i]!r}'
    if s1.corp is not None:
        return f'step 4: Starts.corp is {s1.corp!r}, not None'
    R = analysis._returns_for_year(q0, y, z)
    got, exp = project_many(q1, s1, R), project_many(q0, want, R)
    if set(got) != set(exp):
        return f'step 5: project_many keys {sorted(got)} vs {sorted(exp)}'
    for k in exp:
        if not np.array_equal(got[k], exp[k]):
            return f'step 5: project_many[{k!r}] differs'
    return None
def p6_test(c):
    q0, q1 = p6_plans(c)
    reason = p6_engine(c, q0, q1)
    if reason is None and not c.get('after_zero'):    # the B = -S cases are the Engine part only
        reason = p6_vector(c, q0, q1)
    return reason
@prop
def property_6():
    """Property 6: An Equivalent_Account reproduces the legacy base exactly (Req 3.6, 3.7, 6.3, 10.6)"""
    drawn = tuple(float(case_rng(SEED_P6, i).uniform(-500_000, 2_000_000)) for i in range(P6_N_DRAWS))
    balances = P6_FIXED + drawn
    cases = [(f'B={B!r}, {y}, {mode}, risk {"on" if risk else "off"}',
              {'B': B, 'year': y, 'mode': mode, 'risk': risk})
             for B in balances for y in P6_YEARS for mode in P6_MODES for risk in (True, False)]
    for y in P6_YEARS:                                 # Engine part: B = -S, so B + S is exactly 0.0
        for mode in P6_MODES:
            c = {'B': 0.0, 'year': y, 'mode': mode, 'risk': True}
            q0, _ = p6_plans(c)
            c['B'] = -starting_position(q0).waterfall.surplus
            c['after_zero'] = True
            cases.append((f'after 0: B={c["B"]!r}, {y}, {mode}, risk on', c))
    t0 = time.perf_counter()
    run_grid('Property 6', SEED_P6, cases, p6_test, P6_N_DRAWS)
    print(f'      Property 6: {len(balances)} balances x {len(P6_YEARS)} years x {len(P6_MODES)} modes x 2 risk '
          f'settings + {len(P6_YEARS) * len(P6_MODES)} B = -S cases, {P6_PATHS} paths, '
          f'{time.perf_counter() - t0:.1f} s')


for fn in PROPERTIES:
    print(f'--- {fn.__doc__.splitlines()[0] if fn.__doc__ else fn.__name__}')
    fn()

print('\nNONREG CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
