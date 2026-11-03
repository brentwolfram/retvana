"""Check the market-risk Monte Carlo and the retirement-year comparison (Requirements 14, 15;
design P5) against hand calculations.
  .venv/bin/python scripts/market_check.py

The shocks are rebuilt from seed 1971, the retirement and pre-retirement returns are written out
from the rule, and the analysis functions are compared with them: the median return, the
first-year stress test, common random numbers across retirement years and horizons, the starting
balances with volatility off (rule coded twice with engine.starting_position), and the columns and
values of the year comparison in legacy mode, recovery mode and with market risk.
"""
import math
import sys
import numpy as np
from retvana import analysis                                                # noqa: E402
from retvana import property_model as pm                                    # noqa: E402
from retvana.config import example_plan                                     # noqa: E402
from retvana.engine import project, starting_position, summary              # noqa: E402
from retvana.vector import Starts, project_many                             # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def rel_close(a, b, tol=1e-9):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return bool(np.all(np.abs(a - b) <= tol * np.maximum(1.0, np.maximum(np.abs(a), np.abs(b)))))


# Rule constants written out (Req 14)
SEED = 1971
CUR = 2026
RET, VOL = 0.055, 0.10           # plan return (median) and retirement volatility
N = 200                          # paths (<= 200 per the check rules)
YEARS = [2030, 2033]


def base_plan():
    """The spreadsheet settings with market risk on."""
    p = example_plan()
    p.property_mode = 'legacy'
    p.use_death_ages = False
    p.returns_mc = True
    p.sync_end_year()
    return p


def app_plan():
    """The app defaults (fresh_plan in app.py) with market risk on."""
    p = example_plan()
    p.property_mode = 'recovery'
    p.tfsa_topup = p.accurate_extra_tax = p.use_death_ages = True
    p.returns_mc = True
    p.sync_end_year()
    return p


def hand_shocks(n, end_year):
    """Req 14.1: one standard normal per path and calendar year from 2026, seed 1971, drawn as a
    fixed 80-year window (so the draws do not depend on the horizon) and cut to the plan's years."""
    T = end_year - CUR + 1
    return np.random.default_rng(SEED).standard_normal((n, max(T, 80)))[:, :T]


def hand_returns(z, year, shock=0.0):
    """Req 14.2/14.4: exp(ln(1 + r) + vol x z) - 1 from the retirement year's calendar column, plus
    the stress move in the first retirement year."""
    r = np.exp(math.log(1 + RET) + VOL * z[:, year - CUR:]) - 1
    r[:, 0] += shock
    return r


def hand_starts(p, year, z, surplus, vary=True):
    """Req 2.1/2.3 and 14.2: each account grows at its own rate (and, before retirement, its own
    volatility on the same shocks), contributions at year end; the surplus split as in Req 2.3."""
    n = z.shape[0]
    tot = {(o, k): np.zeros(n) for o in ('P1', 'P2') for k in ('registered', 'tfsa')}
    for a in p.accounts:
        pmt = p.tfsa_limit if a.contribution_is_tfsa_limit else a.contribution
        bal = np.full(n, float(a.balance))
        for t in range(year - CUR):
            g = (np.exp(math.log(1 + a.return_rate) + a.volatility * z[:, t]) - 1) if vary else a.return_rate
            bal = bal * (1 + g) + pmt
        tot[(a.owner, a.kind)] += bal
    options = sum(max(g.available * (p.options_share_price - g.grant_price), 0)
                  * (1 - 0.5 * p.options_marginal_rate) for g in p.option_grants)
    after = p.base_nonreg_p2 + np.broadcast_to(np.asarray(surplus, dtype=float), (n,))
    return Starts(nonreg_p1=options + np.minimum(0.0, after), nonreg_p2=np.maximum(0.0, after),
                  reg_p1=tot[('P1', 'registered')], reg_p2=tot[('P2', 'registered')],
                  tfsa_p1=tot[('P1', 'tfsa')], tfsa_p2=tot[('P2', 'tfsa')])


p = base_plan()
check('plan market inputs are the stated values',
      p.return_rate == RET and p.return_vol == VOL and p.current_year == CUR and analysis.MARKET_SEED == SEED
      and p.first_year_shock == 0.0 and p.mc_pre_retirement and p.end_year == 2080)

# ------------------------------------------------------------------ shock construction (Req 14.1)
z = analysis.market_shocks(p, N)
zh = hand_shocks(N, 2080)
check(f'market_shocks = seed 1971 standard normals, {N} paths x {2080 - CUR + 1} calendar years '
      f'(2026-2080)', z.shape == zh.shape == (N, 55) and np.array_equal(z, zh))
check(f'the shocks look standard normal: mean {z.mean():+.4f}, sd {z.std():.4f} over {z.size:,} draws '
      '(4 standard errors: mean within 0.024, sd within 0.017)',
      abs(z.mean()) < 4 / math.sqrt(z.size) and abs(z.std() - 1) < 4 / math.sqrt(2 * z.size))
z50 = analysis.market_shocks(p, 50)
check('fewer paths give the first paths of the same draw (path i is the same history at any path count)',
      np.array_equal(z50, z[:50]))
q = app_plan()                                   # life expectancy on: end year is the second death
zq = analysis.market_shocks(q, N)
check(f'P5 horizon: a plan ending in {q.end_year} gets the same shock for each shared calendar year as '
      f'one ending in 2080', q.end_year < 2080 and zq.shape[1] == q.end_year - CUR + 1
      and np.array_equal(zq, z[:, :zq.shape[1]]))

# ------------------------------------------------------------------ 7.1 median return (Req 14.2)
pr = analysis._plan_for_year(p, 2033)
r = analysis._returns_for_year(pr, 2033, z)
check('retirement returns = exp(ln 1.055 + 10% x z) - 1 from calendar column 2033 - 2026 = 7, every path '
      'and year', r.shape == (N, 2080 - 2033 + 1) and rel_close(r, hand_returns(z, 2033), 1e-12))
# The transform is increasing, so the middle returns are the transforms of the middle shocks. With an
# even count the median is the mean of the two middle values.
med = float(np.median(r))
zs = np.sort(z[:, 7:].ravel())
mid = zs[[zs.size // 2 - 1, zs.size // 2]]
check('median return = mean of exp(ln 1.055 + 10% x z) - 1 at the two middle shocks (the transform keeps order)',
      rel_close(med, float(np.mean(np.exp(math.log(1 + RET) + VOL * mid) - 1)), 1e-12))
# Tolerance: the sample median of m iid N(0,1) has standard error sqrt(pi/2) / sqrt(m); in return
# terms that is (1 + r) x vol x SE. Allow 4 standard errors.
m = r.size
tol_all = 4 * (1 + RET) * VOL * math.sqrt(math.pi / 2) / math.sqrt(m)
check(f'median retirement return over all {m:,} path-years = {med:.4%}, within 4 standard errors '
      f'(+/-{tol_all:.2%}) of the plan return {RET:.2%}', abs(med - RET) <= tol_all)
tol_yr = 4 * (1 + RET) * VOL * math.sqrt(math.pi / 2) / math.sqrt(N)
per_year = np.median(r, axis=0)
worst = float(np.max(np.abs(per_year - RET)))
check(f'median across the {N} paths in each retirement year is within 4 standard errors (+/-{tol_yr:.2%}) '
      f'of {RET:.2%} in all {r.shape[1]} years (largest gap {worst:.2%})', worst <= tol_yr)

# ------------------------------------------------------------------ 7.2 first-year stress (Req 14.4)
ps = analysis._plan_for_year(p, 2033)
ps.first_year_shock = -0.30
rs = analysis._returns_for_year(ps, 2033, z)
d = rs - r
check('first-year shock -30%: the first retirement-year return falls by exactly 0.30 on every path, every '
      'later year is unchanged', rel_close(d[:, 0], -0.30, 1e-12) and np.array_equal(rs[:, 1:], r[:, 1:])
      and rel_close(rs, hand_returns(z, 2033, -0.30), 1e-12))
ps = base_plan()
ps.first_year_shock = -0.30
o0 = analysis.market_monte_carlo(p, [2033], N)[2033]
o1 = analysis.market_monte_carlo(ps, [2033], N)[2033]
check('with the shock, capital at retirement is unchanged (no effect before retirement) and capital a year '
      'later is lower on every path',
      np.array_equal(o0.start_capital, o1.start_capital) and np.all(o1.capital[:, 1] < o0.capital[:, 1]))

# ------------------------------------------------------------------ 7.3 common random numbers (Req 14.1, P5)
r30 = analysis._returns_for_year(analysis._plan_for_year(p, 2030), 2030, z)
check('CRN: retiring in 2030 or 2033, the return in calendar year 2033 + k is the same on every path '
      '(2030 column 3 + k = 2033 column k)', np.array_equal(r30[:, 3:], r))
s33 = hand_starts(p, 2033, z, starting_position(analysis._plan_for_year(p, 2033)).waterfall.surplus)
st33, _ = analysis._starts_for_year(analysis._plan_for_year(p, 2033), 2033, z,
                                    starting_position(analysis._plan_for_year(p, 2033)).waterfall.surplus)
check('retiring in 2033, account growth in 2026-2032 uses shock columns 0-6 (the same calendar years the '
      '2030 retiree lives through in 2030-2032): starting balances = hand growth on every path',
      all(rel_close(getattr(st33, f), getattr(s33, f)) for f in ('reg_p1', 'reg_p2', 'tfsa_p1', 'tfsa_p2',
                                                                  'nonreg_p1', 'nonreg_p2'))
      and np.std(st33.reg_p2) > 0)

res = analysis.market_monte_carlo(p, YEARS, N)
bad = []
for y in YEARS:
    py = analysis._plan_for_year(p, y)
    surplus = starting_position(py).waterfall.surplus
    out = project_many(py, hand_starts(py, y, zh, surplus), hand_returns(zh, y))
    C, B = out['C'], out['B']
    if not rel_close(res[y].capital, C):
        bad.append(f'{y} capital')
    if not np.array_equal(res[y].success, np.all(C >= B, axis=1)):
        bad.append(f'{y} success')
check(f'market_monte_carlo for {YEARS} = the projection on the hand shocks, starts and returns, and '
      'success = capital >= one year of spending in every year', not bad, ', '.join(bad))

# ------------------------------------------------------------------ 7.4 volatility off (rule coded twice)
bad = []
for label, setup in (('mc_pre_retirement off', lambda a, q: setattr(q, 'mc_pre_retirement', False)),
                     ('every account volatility 0', lambda a, q: setattr(a, 'volatility', 0.0))):
    for mk in (base_plan, app_plan):
        for y in range(2029, 2037):
            q = analysis._plan_for_year(mk(), y)
            for a in q.accounts:
                setup(a, q)
            st = starting_position(q)
            stv, after = analysis._starts_for_year(q, y, z, st.waterfall.surplus)
            for f in ('reg_p1', 'reg_p2', 'tfsa_p1', 'tfsa_p2', 'nonreg_p1', 'nonreg_p2'):
                if not rel_close(getattr(stv, f), getattr(st, f)):
                    bad.append(f'{label} {mk.__name__} {y} {f}: {getattr(stv, f)[0]:,.2f} vs {getattr(st, f):,.2f}')
check('volatility off: _starts_for_year = starting_position on every path for retirement 2029-2036, '
      'spreadsheet and app settings, both ways of turning it off', not bad, '; '.join(bad[:3]))

# ------------------------------------------------------------------ Req 14.3 recovery pairs path i with path i
q = app_plan()
resq = analysis.market_monte_carlo(q, YEARS, N)
dist = pm.surplus_distribution(q, YEARS, N, 2026)['surplus']
zq = hand_shocks(N, q.end_year)
bad = []
for y in YEARS:
    py = analysis._plan_for_year(q, y)
    if not np.array_equal(resq[y].surplus, dist[y]):
        bad.append(f'{y} surplus')
    out = project_many(py, hand_starts(py, y, zq, dist[y]), hand_returns(zq, y))
    if not rel_close(resq[y].capital, out['C']):
        bad.append(f'{y} capital')
check('recovery mode: path i uses property path i (seed 2026) and market path i; capital = the projection '
      'on the hand starts and returns', not bad and np.std(dist[2033]) > 0, ', '.join(bad))

# ------------------------------------------------------------------ 7.5 year-comparison columns (Req 15)
CMP_YEARS = [2030, 2033, 2036]
COMMON = ['Retirement year', 'Capital at retirement', 'First-year expenses', 'First-year expense / capital',
          'Worst expense / capital', 'Capital 2050', 'Capital 2065', 'Lifetime income tax']
SUMMARY_KEYS = COMMON[1:]

# Legacy: one deterministic run per year.
p = base_plan()
end = p.end_year
cmp = analysis.compare_years(p, CMP_YEARS, N)
want_cols = set(COMMON) | {'Property surplus', f'Capital {end}'}
bad = []
for i, y in enumerate(CMP_YEARS):
    py = analysis._plan_for_year(p, y)
    df, st = project(py)
    s = summary(py, df, st)
    for k in SUMMARY_KEYS + ['Property surplus', f'Capital {end}']:
        if not rel_close(cmp.iloc[i][k], s[k]):
            bad.append(f'{y} {k}')
    if not rel_close(cmp.iloc[i]['First-year expenses'] / cmp.iloc[i]['Capital at retirement'],
                     cmp.iloc[i]['First-year expense / capital']):
        bad.append(f'{y} draw ratio')
check(f'legacy: compare_years has exactly {sorted(want_cols - set(COMMON))} plus the common columns, one '
      f'row per year, values = the deterministic run for that year',
      set(cmp.columns) == want_cols and list(cmp['Retirement year']) == CMP_YEARS and not bad,
      f'columns differ {sorted(set(cmp.columns) ^ want_cols)}; ' + ', '.join(bad[:5])
      if set(cmp.columns) != want_cols or bad else '')

# Recovery: the median-surplus path, with P10/P50/P90 surplus, shortfall chance and P10/P90 end capital.
q = app_plan()
end = q.end_year
NP = 100
cmp = analysis.compare_years(q, CMP_YEARS, NP)
want_cols = set(COMMON) | {'Property surplus P10', 'Property surplus P50', 'Property surplus P90',
                           'Chance of property shortfall', f'Capital {end}', f'Capital {end} P10',
                           f'Capital {end} P90'}
dist = pm.surplus_distribution(q, CMP_YEARS, NP, 2026)
bad = []
for i, y in enumerate(CMP_YEARS):
    s = dist['surplus'][y]
    row = cmp.iloc[i]
    for k, pct in (('Property surplus P10', 10), ('Property surplus P50', 50), ('Property surplus P90', 90)):
        if not rel_close(row[k], np.percentile(s, pct)):
            bad.append(f'{y} {k}')
    if row['Chance of property shortfall'] != (s < 0).sum() / NP:
        bad.append(f'{y} shortfall chance')
    order = np.argsort(s)
    py = analysis._plan_for_year(q, y)
    for pct, cols in ((50, SUMMARY_KEYS + [f'Capital {end}']), (10, [f'Capital {end} P10']),
                      (90, [f'Capital {end} P90'])):
        idx = int(order[int(round(pct / 100 * (NP - 1)))])
        df, st = project(py, pm.recovery_values(py, y, dist['sim'], idx))
        sm = summary(py, df, st)
        for k in cols:
            if not rel_close(row[k], sm[k.replace(' P10', '').replace(' P90', '')]):
                bad.append(f'{y} {k}')
check(f'recovery: compare_years has the P10/P50/P90 surplus, shortfall chance and {end} P10/P90 capital '
      'columns; values = hand percentiles and the runs on the P50/P10/P90 surplus paths',
      set(cmp.columns) == want_cols and not bad,
      f'columns differ {sorted(set(cmp.columns) ^ want_cols)}; ' + ', '.join(bad[:5])
      if set(cmp.columns) != want_cols or bad else '')

# Market risk: success rate and end capital P10/P50 per year (Req 15).
p = base_plan()
end = p.end_year
mc = analysis.market_compare(p, CMP_YEARS, N)
need = {'Retirement year', 'Success rate (markets)', f'Capital {end} P10 (markets)', f'Capital {end} P50 (markets)'}
bad = []
for i, y in enumerate(CMP_YEARS):
    py = analysis._plan_for_year(p, y)
    out = project_many(py, hand_starts(py, y, zh, starting_position(py).waterfall.surplus), hand_returns(zh, y))
    C = out['C'][:, out['years'] <= end]
    B = out['B'][:, out['years'] <= end]
    e = C[:, -1]
    row = mc.iloc[i]
    for k, want in (('Success rate (markets)', np.all(C >= B, axis=1).mean()),
                    (f'Capital {end} P10 (markets)', np.percentile(e, 10)),
                    (f'Capital {end} P50 (markets)', np.percentile(e, 50)),
                    (f'Capital {end} P90 (markets)', np.percentile(e, 90))):
        if not rel_close(row[k], want):
            bad.append(f'{y} {k}: {row[k]:,.4f} vs {want:,.4f}')
check(f'market risk: market_compare has the success rate and {end} P10/P50 capital (plus P90 and lowest '
      'capital P10); values = hand success and percentiles on the hand paths',
      need <= set(mc.columns) and list(mc['Retirement year']) == CMP_YEARS and not bad,
      f'missing {sorted(need - set(mc.columns))}; ' + '; '.join(bad[:3])
      if not need <= set(mc.columns) or bad else '')

print('\nMARKET CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
