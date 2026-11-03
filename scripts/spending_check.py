"""Check the sustainable-spending solver.

  .venv/bin/python scripts/spending_check.py

- The answer meets the goal and a slightly higher spend does not (it is the edge).
- Scaling 'all' at 1.0 reproduces the plan exactly; 'discretionary' only touches those items.
- Higher estate targets give lower spending; market answers fall as confidence rises.
- P3: over scales 0.5-2.0 the estate never rises while the money lasts and "money lasts" never
  goes from fail back to pass (fixed return, 'all' and 'discretionary', spreadsheet settings and
  app defaults); the market share meeting the goal never rises (200 paths).
- (inherited, informational) after depletion the estate can rise slightly, because leftover
  non-registered money is never drawn under the all-or-nothing rule; reported, does not gate.
- (inherited) the spending solver ignores success_floor; _run_year applies it."""
import sys
import time

import numpy as np


from retvana import analysis as a                 # noqa: E402
from retvana.config import example_plan           # noqa: E402
from retvana.engine import project                # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def info(label, cond, detail=''):
    """Report a recorded behaviour without affecting the overall result."""
    print(f'{"INFO" if cond else "NOTE"}  {label}{"  " + detail if detail else ""}')


p = example_plan()
p.property_mode, p.use_death_ages, p.tfsa_topup, p.accurate_extra_tax = 'recovery', True, True, True
p.sync_end_year()

df0, _ = project(p)
df1, _ = project(a.scale_spending(p, 1.0, 'all'))
check('scale 1.0 reproduces the plan', (abs(df0['C'] - df1['C']) < 1e-6).all())
q = a.scale_spending(p, 0.5, 'discretionary')
check('discretionary mode only scales discretionary items',
      all((e.monthly == f.monthly * 0.5) == e.discretionary or not e.discretionary and e.monthly == f.monthly
          for e, f in zip(q.expenses, p.expenses)))

for mode in ('all', 'discretionary'):
    prev = None
    for target in (0, 1_000_000, 3_000_000):
        t = time.time()
        r = a.solve_spending(p, target, mode)
        el = time.time() - t
        s = r['scale']
        o_at = a.spending_outcome(p, s, mode)
        o_up = a.spending_outcome(p, s * 1.002 + 1e-4, mode)
        meets = o_at['lasts'] and o_at['estate_today'] >= target - 1
        edge = not (o_up['lasts'] and o_up['estate_today'] >= target)
        check(f'{mode:<13} estate >= ${target / 1e6:.1f}M: x{s:.3f} = ${o_at["first_year_today"]:,.0f}/yr today',
              meets and edge, f'estate ${o_at["estate_today"] / 1e6:.2f}M, +0.2% breaks it: {edge} ({el:.2f}s)')
        if prev is not None:
            check(f'{mode:<13} higher target -> lower spending', s <= prev + 1e-9)
        prev = s

prev = None
for conf in (0.5, 0.75, 0.9):
    t = time.time()
    r = a.solve_spending(p, 1_000_000, 'all', confidence=conf, n_paths=1000)
    el = time.time() - t
    check(f'markets {conf:.0%} confidence, estate >= $1M: x{r["scale"]:.3f} '
          f'(${r["outcome"]["first_year_today"]:,.0f}/yr today)',
          r['success_rate'] >= conf and (prev is None or r['scale'] <= prev + 1e-9),
          f'success {r["success_rate"]:.1%} ({el:.2f}s)')
    prev = r['scale']


# ------------------------------------------------------------------ P3 monotonicity (design)
def base_plan():
    """The spreadsheet settings (legacy property values, no top-up, top-rate extra tax, fixed 2080)."""
    q = example_plan()
    q.property_mode = 'legacy'
    q.use_death_ages = False
    q.sync_end_year()
    return q


def app_plan():
    """The app defaults (fresh_plan in app.py)."""
    q = example_plan()
    q.property_mode = 'recovery'
    q.tfsa_topup = q.accurate_extra_tax = q.use_death_ages = True
    q.sync_end_year()
    return q


SCALES = [round(0.5 + 0.05 * i, 2) for i in range(31)]          # 0.50 .. 2.00
WIDE = [round(0.5 + 0.05 * i, 2) for i in range(41)]            # 0.50 .. 2.50: discretionary lasts past 2.0
t0 = time.time()
for label, mk in (('spreadsheet settings', base_plan), ('app defaults', app_plan)):
    for mode in ('all', 'discretionary'):
        q = mk()
        sc = SCALES if mode == 'all' else WIDE
        rng = f'x{sc[0]:.2f}-{sc[-1]:.2f}'
        outs = [a.spending_outcome(q, s, mode) for s in sc]
        rises = [(sc[i], sc[i + 1], outs[i]['estate_today'], outs[i + 1]['estate_today'], outs[i]['lasts'])
                 for i in range(len(outs) - 1) if outs[i + 1]['estate_today'] > outs[i]['estate_today'] + 1e-6]
        back = [(sc[i], sc[i + 1]) for i in range(len(outs) - 1)
                if not outs[i]['lasts'] and outs[i + 1]['lasts']]
        lasts = [o['lasts'] for o in outs]
        cross = (f'lasts to x{max(s for s, l in zip(sc, lasts) if l):.2f}' if any(lasts) else 'never lasts')
        crossed = any(lasts) and not all(lasts)
        # P3 (design): the estate never rises while the money lasts. This is what the bisection needs
        # (its test is lasts AND estate >= target).
        r_ok = [r for r in rises if r[4]]
        check(f'P3 {label:<20} {mode:<13} estate never rises while the money lasts over {rng}', not r_ok,
              '; '.join(f'x{a_:.2f}->x{b_:.2f}: ${e0:,.0f} -> ${e1:,.0f}' for a_, b_, e0, e1, _ in r_ok[:3]))
        # (inherited) after depletion the estate can rise slightly: leftover non-registered money is
        # never drawn under the all-or-nothing rule (Req 7.2.1 / 7.5). Informational, does not gate.
        info(f'(inherited) {label:<20} {mode:<13} estate never rises over {rng} (incl. after depletion)',
             not rises, f'{len(rises)} rises: ' + '; '.join(
                 f'x{a_:.2f}->x{b_:.2f}: ${e0:,.0f} -> ${e1:,.0f}{"" if l0 else " (money already fails)"}'
                 for a_, b_, e0, e1, l0 in rises[:3]) if rises else '')
        detail = '; '.join(f'fails at x{a_:.2f}, lasts at x{b_:.2f}' for a_, b_ in back[:3])
        if back:   # report the failing year at the first scale that fails before passing again
            o = a.spending_outcome(q, back[0][0], mode)
            df, _ = project(a.scale_spending(q, back[0][0], mode))
            e = df[df['A'] <= q.end_year]
            bad = e[e['C'] < e['B']].iloc[0]
            detail += f'; at x{back[0][0]:.2f} {int(bad["A"])}: capital ${bad["C"]:,.0f} < spending ${bad["B"]:,.0f}'
        check(f'P3 {label:<20} {mode:<13} money lasts never goes fail -> pass ({cross})',
              not back and crossed, detail or ('' if crossed else 'grid does not cross pass -> fail'))
el_det = time.time() - t0

# market-risk share meeting the goal never rises with the scale (same 200 histories at each scale)
t0 = time.time()
for label, mk in (('spreadsheet settings', base_plan), ('app defaults', app_plan)):
    q = mk()
    z = a.market_shocks(q, 200)
    surp = a._surpluses(q, [q.start_year], 200)[q.start_year]
    for target in (0, 1_000_000):
        rates = [a._market_success(q, s, 'all', z, surp, target) for s in SCALES]
        rises = [(SCALES[i], SCALES[i + 1], rates[i], rates[i + 1])
                 for i in range(len(rates) - 1) if rates[i + 1] > rates[i]]
        check(f'P3 markets {label:<20} estate >= ${target / 1e6:.0f}M: share never rises '
              f'({rates[0]:.0%} at x0.50 -> {rates[-1]:.0%} at x2.00)', not rises,
              '; '.join(f'x{a_:.2f}->x{b_:.2f}: {r0:.1%} -> {r1:.1%}' for a_, b_, r0, r1 in rises[:3]))
el_mkt = time.time() - t0
print(f'      (P3 sweeps: fixed return {el_det:.1f}s, markets {el_mkt:.1f}s)')

# ------------------------------------------------------------------ success_floor (inherited inconsistency)
# _run_year (market Monte Carlo, safe_spending) counts a year as failed when capital < max(success_floor,
# spending). spending_outcome and _market_success (the spending solver) use capital < spending only, so the
# solver ignores success_floor. Recorded as current behaviour; a later spec should pick one rule.
q = base_plan()
z0 = np.zeros((1, q.end_year - q.current_year + 1))                 # zero shocks = the plan return (P4)
s0 = a._surpluses(q, [q.start_year], 1)[q.start_year]
o = a.spending_outcome(q, 1.0, 'all')
df, _ = project(q)
e = df[df['A'] <= q.end_year]
floor = float(e['C'].min()) + 1.0                                     # just above the plan's lowest capital
r_nofloor = a._run_year(q, q.start_year, z0, s0)
q_floor = q.copy()
q_floor.success_floor = floor
r_floor = a._run_year(q_floor, q.start_year, z0, s0)
o_floor = a.spending_outcome(q_floor, 1.0, 'all')
m_nofloor = a._market_success(q, 1.0, 'all', z0, s0, 0.0)
m_floor = a._market_success(q_floor, 1.0, 'all', z0, s0, 0.0)
s_nofloor = a.solve_spending(q, 0.0, 'all')['scale']
s_floor = a.solve_spending(q_floor, 0.0, 'all')['scale']
check('success_floor 0: _run_year and spending_outcome agree (plan lasts)',
      o['lasts'] and bool(r_nofloor.success[0]) and m_nofloor == 1.0)
check(f'(inherited) success_floor ${floor:,.0f} (> lowest capital): _run_year fails in '
      f'{int(r_floor.depleted_year[0])}, but spending_outcome and _market_success still pass',
      not r_floor.success[0] and o_floor['lasts'] and m_floor == 1.0)
check(f'(inherited) the spending solver ignores success_floor: x{s_floor:.4f} with it = x{s_nofloor:.4f} without',
      s_floor == s_nofloor)

print('\nSPENDING CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
