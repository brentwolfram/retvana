"""Check the yearly projection rules (Requirements 6, 7, 9.1-9.5, 9.7, 17; design P2, P6)
against hand calculations.
  .venv/bin/python scripts/projection_check.py

Spending phases and the survivor share, the draw cascade, the TFSA top-up, RRIF factors and start
ages, the defer and bracket strategies, the optimizer grid and the estate are written out from the
rule and compared with the engine's columns row by row. Two invariants are swept: more starting
non-registered money never lowers capital (P2), and no analysis changes the plan it is given (P6).
Birth years and the current and retirement years are read from the example plan; tax, TFSA and
RRIF figures are the public rules, written out.
"""
import dataclasses
import math
import sys
from retvana import analysis                                                # noqa: E402
from retvana.config import RRIF_FACTORS, ConsultingIncome, ExpenseItem, example_plan   # noqa: E402
from retvana.engine import estate_after_tax, project, starting_position, summary      # noqa: E402
from retvana.vector import project_many                                      # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def close(a, b, tol=0.01):
    return abs(a - b) <= tol


def rel_close(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# Rule constants written out
INFL = 0.028
TOP = 0.5353
TFSA_LIMIT = 7000
# Household inputs read from the example plan
_ex = example_plan()
CUR, START = _ex.current_year, _ex.start_year
BORN = {k: _ex.person(k).birth_year for k in ('P1', 'P2')}
TAXABLE = {k: _ex.person(k).taxable_share for k in ('P1', 'P2')}


def base_plan():
    """The spreadsheet settings (legacy property values, no top-up, top-rate extra tax, fixed 2080)."""
    p = example_plan()
    p.property_mode = 'legacy'
    p.use_death_ages = False
    p.sync_end_year()
    return p


def app_plan():
    """The app defaults (fresh_plan in app.py)."""
    p = example_plan()
    p.property_mode = 'recovery'
    p.tfsa_topup = p.accurate_extra_tax = p.use_death_ages = True
    p.sync_end_year()
    return p


def scale_expenses(p, k):
    for e in p.expenses:
        e.monthly *= k
        if e.monthly_later is not None:
            e.monthly_later *= k
    return p


# ------------------------------------------------------------------ 6.1 spending
def hand_spending(p, year, alive_both):
    f = (1 + INFL) ** (p.start_year - CUR)                        # expense CPI to retirement
    gogo = sum(e.monthly * 12 for e in p.expenses) * f
    later = sum((e.monthly if e.monthly_later is None else e.monthly_later) * 12 for e in p.expenses) * f
    amt = gogo if year - p.start_year < 15 else later
    return amt * (1 + INFL) ** (year - p.start_year) * (1.0 if alive_both else 0.70)


for who, death_age_p1, death_age_p2 in (('P1', 80, 94), ('P2', 97, 70)):
    p = base_plan()
    p.use_death_ages = True
    p.person('P1').death_age, p.person('P2').death_age = death_age_p1, death_age_p2
    p.sync_end_year()
    df, _ = project(p)
    first_death = min(BORN['P1'] + death_age_p1, BORN['P2'] + death_age_p2)
    bad = [f'{y}: {r["B"]:,.2f} vs {hand_spending(p, y, y <= first_death):,.2f}'
           for y, r in df.iterrows() if not close(r['B'], hand_spending(p, y, y <= first_death))]
    switch = START + 15                                        # first later-phase year
    ratio_switch = df.loc[switch, 'B'] / df.loc[switch - 1, 'B']
    gogo = sum(e.monthly for e in p.expenses)
    later = sum(e.monthly if e.monthly_later is None else e.monthly_later for e in p.expenses)
    check(f'{who} dies first ({first_death}): spending = go-go to {switch - 1} (year 15), later amount from {switch}, '
          f'x 0.70 from {first_death + 1}, hand value in every row ({len(df)} rows)',
          not bad and close(ratio_switch, later / gogo * 1.028, 1e-12)
          and close(df.loc[first_death + 1, 'B'] / df.loc[first_death, 'B'], 0.70 * 1.028, 1e-12),
          '; '.join(bad[:3]))


# ------------------------------------------------------------------ 6.2 draw cascade
def cascade_bad(df):
    """Req 7.2: non-registered by balance only if it covers the whole shortfall; then TFSA by balance
    if more than $0.01 remains (never more than balance + return); then extra registered by
    registered balance."""
    bad, n = [], {'nonreg': 0, 'all_or_nothing': 0, 'tfsa': 0, 'extra': 0}
    for y, r in df.iterrows():
        BA = r['BA']
        if BA <= 0:
            continue
        F, S, I, V, BU, BX = r['F'], r['S'], r['I'], r['V'], r['BU'], r['BX']
        if F + S > BA:
            bb, bc = F / (F + S) * BA, S / (F + S) * BA
            n['nonreg'] += 1
        else:
            bb = bc = 0.0
            n['all_or_nothing'] += F + S > 0
        rem = BA - bb - bc
        if rem > 0.01 and BU + BX > 0:
            bw, bz = min(BU / (BU + BX) * rem, BU + r['BV']), min(BX / (BU + BX) * rem, BX + r['BY'])
            n['tfsa'] += 1
        else:
            bw = bz = 0.0
        rem2 = rem - bw - bz
        be = I / (I + V) * rem2 if I > 0 and rem2 > 0 else 0.0
        bi = V / (I + V) * rem2 if V > 0 and rem2 > 0 else 0.0
        n['extra'] += be + bi > 0
        for col, want in (('BB', bb), ('BC', bc), ('BW', bw), ('BZ', bz), ('BE', be), ('BI', bi)):
            if not close(r[col], want):
                bad.append(f'{y} {col}: {r[col]:,.2f} vs {want:,.2f}')
    return bad, n


# Spending doubled: non-registered pays early, then cannot cover a whole year (left undrawn), then
# the TFSAs run down, then extra registered draws fund the rest.
p = scale_expenses(base_plan(), 2.0)
df, _ = project(p)
bad, n = cascade_bad(df)
check(f'draw cascade = hand order in every shortfall row (non-reg {n["nonreg"]}, non-reg left undrawn '
      f'{n["all_or_nothing"]}, TFSA {n["tfsa"]}, extra registered {n["extra"]} rows)',
      not bad and all(v > 0 for v in n.values()), '; '.join(bad[:3]))
ex = df[(df['BE'] + df['BI']) > 0]
split_bad = [y for y, r in ex.iterrows() if r['I'] > 0 and r['V'] > 0
             and not rel_close(r['BE'] / (r['BE'] + r['BI']), r['I'] / (r['I'] + r['V']), 1e-9)]
check(f'extra registered is split by registered balance: BE / (BE + BI) = I / (I + V) ({len(ex)} rows)',
      len(ex) > 0 and not split_bad, str(split_bad[:3]) if split_bad else '')
top_bad = [y for y, r in ex.iterrows() if not close(r['BG'], r['BE'] * TOP) or not close(r['BK'], r['BI'] * TOP)]
check('extra registered taxed at the top rate (53.53%) with accurate extra tax off', not top_bad,
      str(top_bad[:3]) if top_bad else '')

# The $0.01 TFSA threshold: no non-registered money and a first-year shortfall of exactly eps.
p = base_plan()
p.expenses = [ExpenseItem('Test', 0.0)]
st = dataclasses.replace(starting_position(p), nonreg_p1=0.0, nonreg_p2=0.0)
ba0 = project(p, start=st)[0].loc[START, 'BA']
for eps, tfsa in ((0.005, False), (0.02, True)):
    q = base_plan()
    q.expenses = [ExpenseItem('Test', (-ba0 + eps) / (12 * (1 + INFL) ** (START - CUR)))]
    st = dataclasses.replace(starting_position(q), nonreg_p1=0.0, nonreg_p2=0.0)
    r = project(q, start=st)[0].loc[START]
    tf, extra = r['BW'] + r['BZ'], r['BE'] + r['BI']
    check(f'shortfall of ${eps:.3f} with TFSA money: ' + ('TFSA pays it' if tfsa else
                                                           'TFSA not drawn, extra registered pays it'),
          ba0 < 0 and close(r['BA'], eps, 1e-6)
          and (close(tf, eps, 1e-6) and extra == 0 if tfsa else tf == 0 and close(extra, eps, 1e-6)),
          f'BA {r["BA"]:.6f}, TFSA {tf:.6f}, extra {extra:.6f}')


# ------------------------------------------------------------------ 6.3 TFSA top-up and survivor surplus
def hand_room(year):
    """Req 7.4: the $7,000 limit indexed to inflation, in $500 steps."""
    return max(TFSA_LIMIT, 500 * math.floor(TFSA_LIMIT * (1 + INFL) ** (year - CUR) / 500 + 0.5))


p = scale_expenses(base_plan(), 0.5)
p.tfsa_topup = True
p.use_death_ages = True
p.person('P1').death_age = 80                    # Person 1 dies first; Person 2 is the survivor
p.sync_end_year()
df, _ = project(p)
rooms = [hand_room(y) for y in df.index]
check(f'TFSA room: multiples of $500, never below $7,000, never falling, '
      f'{rooms[0]:,} in {df.index[0]} to {rooms[-1]:,} in {df.index[-1]}',
      all(x % 500 == 0 for x in rooms) and min(rooms) >= 7000 and rooms == sorted(rooms)
      and rooms[-1] > rooms[0] and all((b - a) % 500 == 0 for a, b in zip(rooms, rooms[1:])))
bad, n = [], {'both': 0, 'full': 0, 'survivor': 0}
for y, r in df.iterrows():
    if r['BA'] >= 0:
        if r['T_P1'] or r['T_P2']:
            bad.append(f'{y}: top-up without a surplus')
        continue
    room, spare = hand_room(y), -r['BA']
    room_p1, room_p2 = (room if r['alive_P1'] else 0.0), (room if r['alive_P2'] else 0.0)
    t1 = min(room_p1, spare / 2)
    t2 = min(room_p2, spare - t1)
    t1 = min(room_p1, spare - t2)
    left = r['BA'] + t1 + t2                     # surplus left for non-registered (<= 0)
    both = r['alive_P1'] and r['alive_P2']
    n['both' if both else 'survivor'] += 1
    n['full'] += close(t1, room) and close(t2, room)
    want = [('T_P1', t1), ('T_P2', t2)]
    if both:
        if not close(r['BB'] + r['BC'], left):
            bad.append(f'{y} BB+BC: {r["BB"] + r["BC"]:,.2f} vs {left:,.2f}')
    else:
        want += [('BB', left if r['alive_P1'] else 0.0), ('BC', 0.0 if r['alive_P1'] else left)]
    for col, w in want:
        if not close(r[col], w):
            bad.append(f'{y} {col}: {r[col]:,.2f} vs {w:,.2f}')
check(f'TFSA top-up = hand room split, only living people get room, rest of the surplus reinvested '
      f'(both alive {n["both"]} rows, room filled for both {n["full"]}, survivor only {n["survivor"]})',
      not bad and n['both'] > 0 and n['full'] > 0 and n['survivor'] > 0, '; '.join(bad[:3]))
dead = df[~df['alive_P1']]
check('after Person 1\'s death: no TFSA room for them, and the surplus goes to Person 2\'s non-registered',
      len(dead) > 0 and (dead['T_P1'] == 0).all() and (dead['BB'] == 0).all()
      and ((dead['BA'] >= 0) | (dead['BC'] <= 0)).all() and (dead['T_P2'] > 0).any())


# ------------------------------------------------------------------ 6.4 RRIF factors and start ages
HAND_RRIF_71 = [0.0738, 0.0748, 0.0759, 0.0771, 0.0785, 0.0799, 0.0815, 0.0833, 0.0853, 0.0875, 0.0899,
                0.0927, 0.0958, 0.0993, 0.1033, 0.1079, 0.1133, 0.1196, 0.1271, 0.1362, 0.1473, 0.1612,
                0.1792, 0.2000, 0.2000]                          # ages 71..95, the pre-2015 table


def hand_factor(age):
    """Req 9.1: 0 below 55, 1 / (90 - age) from 55 to 70 (4 decimals), the pre-2015 table from 71."""
    if age < 55:
        return 0.0
    if age <= 70:
        return 1 / (90 - age)
    return HAND_RRIF_71[min(age, 95) - 71]


tbl_bad = [a for a in range(0, 101) if not close(RRIF_FACTORS[max(k for k in RRIF_FACTORS if k <= a)],
                                                   hand_factor(a), 5e-5 + 1e-12 if 55 <= a <= 70 else 1e-12)]
check('RRIF_FACTORS = 0 below 55, 1/(90 - age) from 55 to 70, pre-2015 table from 71 (7.38%) to 20% from 94',
      not tbl_bad and RRIF_FACTORS[71] == 0.0738 and RRIF_FACTORS[80] == 0.0875,
      f'ages {tbl_bad[:5]}' if tbl_bad else '')
check('example_plan uses RRIF_FACTORS', example_plan().rrif_factors == RRIF_FACTORS)


def table(age):
    return RRIF_FACTORS[max(k for k in RRIF_FACTORS if k <= age)]


Y55 = BORN['P2'] + 55                     # Person 2's earliest RRIF year
for start in (Y55 - 5, Y55 - 2, Y55 + 1):  # retire before (twice) and after Person 2 turns 55
    p = base_plan()
    p.start_year = start
    df, _ = project(p)
    start_p2 = max(start, BORN['P2'] + 55)
    bad = []
    for y, r in df.iterrows():
        want_p1 = table(y - BORN['P1'])
        want_p2 = table(y - BORN['P2']) if y >= start_p2 else 0.0
        if r['L'] != want_p1 or r['Y'] != want_p2:
            bad.append(f'{y}: L {r["L"]} vs {want_p1}, Y {r["Y"]} vs {want_p2}')
        if not close(r['BD'], want_p1 * r['I']) or not close(r['BH'], want_p2 * r['V']):
            bad.append(f'{y}: minimums BD {r["BD"]:,.2f} vs {want_p1 * r["I"]:,.2f}, '
                       f'BH {r["BH"]:,.2f} vs {want_p2 * r["V"]:,.2f}')
    first_p2 = df.index[df['Y'] > 0][0]
    check(f'retire {start}: Person 1\'s RRIF from {start} (age {start - BORN["P1"]}), Person 2\'s from {first_p2} '
          f'(later of retirement and 55 = {start_p2}); factors and minimums by age in every row',
          not bad and first_p2 == start_p2 and df.loc[start, 'L'] > 0, '; '.join(bad[:3]))


# ------------------------------------------------------------------ 6.5 defer, bracket, optimizer grid
COLS = {'P1': dict(I='I', J='J', G='G', N='N', K='K', O='O', F='L', D='BD'),
        'P2': dict(I='V', J='W', G='T', N='AA', K='X', O='AB', F='Y', D='BH')}


def hand_planned(p, key, y, r):
    """Req 9.4/9.5: minimums from 72 (the year after conversion at 71); with 'bracket', through the
    fill-until age, max(minimum, min(balance + growth, target x index - other taxable income))."""
    c = COLS[key]
    age = y - BORN[key]
    rrif_start = p.start_year if key == 'P1' else max(p.start_year, BORN['P2'] + 55)
    if y < rrif_start:
        return 0.0, 'none'
    minimum = table(age) * r[c['I']] if age >= 72 else 0.0
    if p.withdrawal_strategy == 'bracket' and age <= p.fill_until_age:
        other = r[c['G']] * TAXABLE[key] + r[c['N']] - r[c['K']] - r[c['O']]
        target = p.bracket_target * (1 + INFL) ** (y - CUR)
        fill = min(r[c['I']] + r[c['J']], max(0.0, target - other))
        kind = 'min' if minimum >= fill else ('cap' if fill == r[c['I']] + r[c['J']] else 'fill')
        return max(minimum, fill), kind
    return minimum, 'min' if minimum else 'zero'


p = base_plan()
p.withdrawal_strategy = 'defer'
df, _ = project(p)
bad = []
for y, r in df.iterrows():
    for key in ('P1', 'P2'):
        want, _ = hand_planned(p, key, y, r)
        if not close(r[COLS[key]['D']], want):
            bad.append(f'{y} {key}: {r[COLS[key]["D"]]:,.2f} vs {want:,.2f}')
first_p1, first_p2 = df.index[df['BD'] > 0][0], df.index[df['BH'] > 0][0]
check(f'defer: no planned draw before 72, minimums from 72 (Person 1 {first_p1}, Person 2 {first_p2}), every row',
      not bad and first_p1 == BORN['P1'] + 72 and first_p2 == BORN['P2'] + 72, '; '.join(bad[:3]))

for target, until in ((95_000, 71), (150_000, 64)):
    p = base_plan()
    p.withdrawal_strategy, p.bracket_target, p.fill_until_age = 'bracket', float(target), until
    df, _ = project(p)
    bad, kinds = [], {}
    for y, r in df.iterrows():
        for key in ('P1', 'P2'):
            want, kind = hand_planned(p, key, y, r)
            kinds[kind] = kinds.get(kind, 0) + 1
            if not close(r[COLS[key]['D']], want):
                bad.append(f'{y} {key}: {r[COLS[key]["D"]]:,.2f} vs {want:,.2f}')
    check(f'bracket ${target / 1000:.0f}K until {until}: hand fill formula in every row '
          f'(fill {kinds.get("fill", 0)}, capped at balance + growth {kinds.get("cap", 0)}, '
          f'minimum {kinds.get("min", 0)}, nothing {kinds.get("zero", 0)} person-years)',
          not bad and kinds.get('fill', 0) > 0, '; '.join(bad[:3]))

p = base_plan()
grid = analysis.optimize_bracket(p)
want = {(t, a) for t in range(50_000, 210_001, 10_000) for a in (64, 67, 71)}
got = set(zip(grid['Target income'], grid['Fill until age']))
est = list(grid['Estate after tax'])
row0 = grid.iloc[0]
q = base_plan()
q.withdrawal_strategy, q.bracket_target, q.fill_until_age = 'bracket', float(row0['Target income']), int(row0['Fill until age'])
dq, sq = project(q)
check(f'optimizer grid: 17 targets ($50K-$210K by $10K) x 3 ages (64, 67, 71) = {len(grid)} rows, sorted by '
      f'estate; best ${row0["Target income"] / 1000:.0f}K until {int(row0["Fill until age"])} re-run gives the same estate',
      len(grid) == 51 and got == want and est == sorted(est, reverse=True)
      and rel_close(summary(q, dq, sq)['Estate after tax'], row0['Estate after tax']))


# ------------------------------------------------------------------ 6.6 estate after tax
def corp_plan():
    p = base_plan()
    p.corp_balance = 200_000
    p.dividend_target = 0.0                    # nothing paid out, so the corporation is still there at the end
    p.consulting = [ConsultingIncome('P2', 60_000, START + 1, START + 4, via_corp=True)]
    return p


def hand_estate(r):
    """Req 17.1: non-reg + TFSA + registered x (1 - 53.53%) + wind-up dividend (with refund) taxed
    at the top non-eligible rate: (1 + 15%) x (53.53% - 11.0201%)."""
    D = min(r['CORP'] / (1 - 0.3833), r['CORP'] + r['RDTOH'])
    corp = D * (1 - 1.15 * (TOP - 0.110201))
    return r['F'] + r['S'] + r['BU'] + r['BX'] + (r['I'] + r['V']) * (1 - TOP) + corp, corp


for label, p in (('no corporation', base_plan()), ('with corporation', corp_plan())):
    df, st = project(p)
    last = df.iloc[-1]
    want, corp = hand_estate(last)
    s = summary(p, df, st)['Estate after tax']
    check(f'estate after tax by hand, {label} ({int(last["A"])} opening balances, corporation {corp:,.0f})',
          close(estate_after_tax(p, last), want) and close(s, want)
          and ((corp > 0) == (label == 'with corporation')),
          f'{estate_after_tax(p, last):,.2f} / {s:,.2f} vs {want:,.2f}')

# Rule coded twice: the inline formula in _market_success on the same final rows (random returns).
p = corp_plan()
z = analysis.market_shocks(p, 50)
surp = analysis._surpluses(p, [p.start_year], 50)[p.start_year]
_, est, _ = analysis._market_success(p, 1.0, 'all', z, surp, 0.0, return_estates=True)
q = analysis._plan_for_year(p, p.start_year)
starts, _ = analysis._starts_for_year(q, q.start_year, z, surp)
out = project_many(q, starts, analysis._returns_for_year(q, q.start_year, z))
last = [i for i, y in enumerate(out['years']) if y <= q.end_year][-1]
real = (1 + q.inflation) ** (q.end_year - q.current_year)
bad = []
for i in range(50):
    row = {c: float(out[c][i, last]) for c in ('F', 'S', 'BU', 'BX', 'I', 'V', 'CORP', 'RDTOH')}
    a, b = estate_after_tax(q, row), est[i] * real
    if not rel_close(a, b) or not close(a, hand_estate(row)[0]):
        bad.append(f'path {i}: {a:,.2f} vs {b:,.2f}')
check('estate_after_tax = _market_success inline formula on the same final row, 50 market paths with a '
      'corporation', not bad and len(set(est.round(0))) > 1, '; '.join(bad[:3]))


# ------------------------------------------------------------------ 6.7 P2 monotonicity
# Feature: nonreg-accounts, Property 10: More Person 2 non-registered money never lowers capital
BASES = [-400_000 + 200_000 * i for i in range(10)]
for label, mk in (('legacy, spreadsheet settings', base_plan), ('recovery, app defaults', app_plan)):
    caps = []
    for b in BASES:
        p = mk()
        nonreg_p2 = [a for a in p.accounts if a.owner == 'P2' and a.kind == 'nonreg']
        assert len(nonreg_p2) == 1, 'the example plan has one Person 2 non-registered account'
        nonreg_p2[0].balance = float(b)
        caps.append(project(p)[0]['C'])
    bad = [f'{BASES[i]:,}->{BASES[i + 1]:,} in {y}: {caps[i][y]:,.2f} > {caps[i + 1][y]:,.2f}'
           for i in range(len(BASES) - 1) for y in caps[i].index if caps[i + 1][y] < caps[i][y] - 0.01]
    check(f'P2 ({label}): raising Person 2\'s non-registered account from -$400K to $1.4M in 10 steps never '
          f'lowers total capital in any year', not bad, '; '.join(bad[:3]))


# ------------------------------------------------------------------ 6.8 P6 plan unchanged
p = app_plan()
p.consulting = [ConsultingIncome('P2', 60_000, START + 1, START + 4, via_corp=True)]
p.corp_balance = 50_000
N = 50
y0 = p.start_year
calls = [
    ('deterministic', lambda: analysis.deterministic(p, y0 + 2)),
    ('monte_carlo', lambda: analysis.monte_carlo(p, [y0, y0 + 2], N)),
    ('compare_years', lambda: analysis.compare_years(p, [y0, y0 + 2], N)),
    ('property_bands', lambda: analysis.property_bands(p, y0 + 12, N)),
    ('market_shocks', lambda: analysis.market_shocks(p, N)),
    ('market_monte_carlo', lambda: analysis.market_monte_carlo(p, [y0, y0 + 2], N)),
    ('safe_spending', lambda: analysis.safe_spending(p, y0, 0.9, N)),
    ('market_compare', lambda: analysis.market_compare(p, [y0, y0 + 2], N)),
    ('strategy_metrics', lambda: analysis.strategy_metrics(p)),
    ('optimize_bracket', lambda: analysis.optimize_bracket(p)),
    ('compare_strategies', lambda: analysis.compare_strategies(p, n_paths=N)),
    ('scale_spending', lambda: analysis.scale_spending(p, 1.3, 'all')),
    ('spending_outcome', lambda: analysis.spending_outcome(p, 1.3, 'discretionary')),
    ('solve_spending (fixed)', lambda: analysis.solve_spending(p, 500_000)),
    ('solve_spending (markets)', lambda: analysis.solve_spending(p, 500_000, confidence=0.8, n_paths=N)),
    ('best_dividend_target', lambda: analysis.best_dividend_target(p)),
    ('corp_vs_personal', lambda: analysis.corp_vs_personal(p)),
]
for mode in ('recovery', 'legacy'):
    p.property_mode = mode
    changed = []
    for name, fn in calls:
        before = p.to_json()
        fn()
        if p.to_json() != before:
            changed.append(name)
    check(f'P6 ({mode}): {len(calls)} analysis entry points leave the plan unchanged', not changed,
          ('changed by ' + ', '.join(changed)) if changed else '')

print('\nPROJECTION CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
