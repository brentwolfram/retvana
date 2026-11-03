"""Scenario analysis on top of the engine: Monte Carlo property outcomes and the
retirement-year comparison grid.

Property uncertainty only changes the starting non-registered balances, and more
starting money never lowers capital later, so every capital percentile is the
projection run on the property path at that surplus percentile. Projections are
run on actual simulated paths (no interpolation)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import engine as _engine
from . import property_model as pm
from .config import Plan
from .engine import project, summary
from .vector import Starts, project_many

PCTS = (10, 50, 90)


@dataclass
class YearOutcome:
    year: int
    surplus: np.ndarray                 # all paths
    p_shortfall: float
    runs: dict                          # pct -> (df, start, summary)


def _plan_for_year(plan: Plan, year: int) -> Plan:
    p = plan.copy()
    p.start_year = year
    p.sync_end_year()
    return p


def deterministic(plan: Plan, year: int | None = None):
    p = _plan_for_year(plan, year or plan.start_year)
    df, st = project(p)
    return df, st, summary(p, df, st)


def monte_carlo(plan: Plan, years: list[int], n_paths: int = 2000, seed: int = 2026) -> dict:
    """Recovery-model Monte Carlo for each retirement year on common random paths."""
    mc = pm.surplus_distribution(plan, years, n_paths, seed)
    sim = mc['sim']
    out = {}
    for y in years:
        s = mc['surplus'][y]
        order = np.argsort(s)
        runs = {}
        p = _plan_for_year(plan, y)
        for q in PCTS:
            idx = int(order[min(len(s) - 1, int(round(q / 100 * (len(s) - 1))))])
            sale = pm.recovery_values(p, y, sim, idx)
            df, st = project(p, sale)
            runs[q] = (df, st, summary(p, df, st))
        out[y] = YearOutcome(y, s, float((s < 0).mean()), runs)
    return {'years': out, 'sim': sim}


def compare_years(plan: Plan, years: list[int], n_paths: int = 2000, seed: int = 2026) -> pd.DataFrame:
    """One row per retirement year. Recovery mode adds Monte Carlo P10/P90 columns."""
    rows = []
    mc = monte_carlo(plan, years, n_paths, seed) if plan.property_mode == 'recovery' else None
    for y in years:
        if mc:
            o = mc['years'][y]
            s50, s10, s90 = (o.runs[q][2] for q in (50, 10, 90))
            row = {'Retirement year': y,
                   'Property surplus P10': float(np.percentile(o.surplus, 10)),
                   'Property surplus P50': float(np.percentile(o.surplus, 50)),
                   'Property surplus P90': float(np.percentile(o.surplus, 90)),
                   'Chance of property shortfall': o.p_shortfall}
            base = s50
        else:
            _, _, base = deterministic(plan, y)
            row = {'Retirement year': y, 'Property surplus': base['Property surplus']}
        row.update({
            'Capital at retirement': base['Capital at retirement'],
            'First-year expenses': base['First-year expenses'],
            'First-year expense / capital': base['First-year expense / capital'],
            'Worst expense / capital': base['Worst expense / capital'],
            'Capital 2050': base['Capital 2050'], 'Capital 2065': base['Capital 2065'],
            f'Capital {plan.end_year}': base[f'Capital {plan.end_year}'],
            'Lifetime income tax': base['Lifetime income tax'],
        })
        if mc:
            row[f'Capital {plan.end_year} P10'] = s10[f'Capital {plan.end_year}']
            row[f'Capital {plan.end_year} P90'] = s90[f'Capital {plan.end_year}']
        rows.append(row)
    return pd.DataFrame(rows)


def property_bands(plan: Plan, horizon: int, n_paths: int = 2000, seed: int = 2026) -> dict:
    """P10/P50/P90 value paths per asset for the fan charts."""
    sim = pm.simulate(plan, horizon, n_paths, seed)
    years = sim['years']
    out = {}
    for name, arr in sim.items():
        if name == 'years':
            continue
        out[name] = pd.DataFrame({'Year': years,
                                  'P10': np.percentile(arr, 10, axis=0),
                                  'P50': np.percentile(arr, 50, axis=0),
                                  'P90': np.percentile(arr, 90, axis=0)})
    return out


# ====================================================================== market risk
"""Investment-return Monte Carlo (sequence-of-returns risk).

Each path gets one market shock per calendar year, z[t] ~ N(0, 1), shared by every
retirement year being compared (common random numbers): retiring later means living
through the same markets, just working through more of them.

- Retirement portfolio: log(1 + r) = log(1 + return_rate) + return_vol * z. The plan's
  return_rate is the median (compound) return, so the median path lines up with the
  fixed-return plan and the volatility adds the spread around it.
- Accounts before retirement: each grows at its own rate with its own volatility,
  driven by the same shocks (an equity RRSP and a bond TFSA move together, by different
  amounts). Contributions are added at year end, as in Excel's FV.
- Property: in recovery mode, path i also uses property path i (independent of markets).

Success = total capital stays at or above one year of spending (and success_floor, if
higher) in every year to end_year. Capital can't reach $0 in this model: non-registered
money that can't cover a whole year's shortfall is never drawn (a rule inherited from
the original spreadsheet), so "below one year of spending" is the test for running out.
"""

MARKET_SEED = 1971
CAP_PCTS = (5, 10, 25, 50, 75, 90, 95)


def market_shocks(plan: Plan, n_paths: int, seed: int = MARKET_SEED) -> np.ndarray:
    """Standard-normal shocks, shape (n_paths, years from current_year to end_year)."""
    plan.sync_end_year()
    T = plan.end_year - plan.current_year + 1
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n_paths, max(T, 80)))[:, :T]


def _starts_for_year(plan: Plan, year: int, z: np.ndarray, surplus) -> tuple[Starts, np.ndarray]:
    n = z.shape[0]
    pre = year - plan.current_year
    tot = {(o, k): np.zeros(n) for o in ('P1', 'P2') for k in ('registered', 'tfsa')}
    for a in plan.accounts:
        pmt = plan.tfsa_limit if a.contribution_is_tfsa_limit else a.contribution
        bal = np.full(n, float(a.balance))
        for t in range(pre):
            if plan.mc_pre_retirement:
                g = np.exp(np.log1p(a.return_rate) + a.volatility * z[:, t]) - 1
            else:
                g = a.return_rate
            bal = bal * (1 + g) + pmt
        tot[(a.owner, a.kind)] += bal
    options = _engine.options_net_proceeds(plan)
    after = plan.base_nonreg_p2 + np.broadcast_to(np.asarray(surplus, dtype=float), (n,))
    st = Starts(nonreg_p1=options + np.minimum(0.0, after), nonreg_p2=np.maximum(0.0, after),
                reg_p1=tot[('P1', 'registered')], reg_p2=tot[('P2', 'registered')],
                tfsa_p1=tot[('P1', 'tfsa')], tfsa_p2=tot[('P2', 'tfsa')])
    return st, after


def _returns_for_year(plan: Plan, year: int, z: np.ndarray) -> np.ndarray:
    pre = year - plan.current_year
    r = np.exp(np.log1p(plan.return_rate) + plan.return_vol * z[:, pre:]) - 1
    if plan.first_year_shock:
        r = r.copy()
        r[:, 0] += plan.first_year_shock
    return r


@dataclass
class MarketOutcome:
    year: int
    years: np.ndarray
    capital: np.ndarray          # (paths, years)
    expenses: np.ndarray         # (years,)
    success: np.ndarray          # bool per path
    depleted_year: np.ndarray    # first year below the floor, 0 if never
    start_capital: np.ndarray
    surplus: np.ndarray

    @property
    def success_rate(self) -> float:
        return float(self.success.mean())

    def bands(self, pcts=CAP_PCTS) -> pd.DataFrame:
        d = {'Year': self.years}
        for q in pcts:
            d[f'P{q}'] = np.percentile(self.capital, q, axis=0)
        return pd.DataFrame(d)

    def end_capital(self, end_year: int) -> np.ndarray:
        return self.capital[:, list(self.years).index(end_year)]


def _run_year(plan: Plan, year: int, z: np.ndarray, surplus, expense_scale: float = 1.0) -> MarketOutcome:
    p = _plan_for_year(plan, year)
    starts, _ = _starts_for_year(p, year, z, surplus)
    out = project_many(p, starts, _returns_for_year(p, year, z), expense_scale)
    yrs = out['years']
    mask = yrs <= p.end_year
    cap = out['C'][:, mask]
    # "run out" = capital below one year of spending (or the floor, if higher)
    below = cap < np.maximum(p.success_floor, out['B'][:, mask])
    first = np.where(below.any(axis=1), yrs[mask][below.argmax(axis=1)], 0)
    n = z.shape[0]
    return MarketOutcome(year, yrs[mask], cap, out['B'][0, mask], ~below.any(axis=1), first,
                         cap[:, 0], np.broadcast_to(np.asarray(surplus, dtype=float), (n,)))


def _surpluses(plan: Plan, years: list[int], n_paths: int) -> dict:
    if plan.property_mode == 'recovery':
        return pm.surplus_distribution(plan, years, n_paths)['surplus']
    out = {}
    for y in years:
        p = _plan_for_year(plan, y)
        v, price = pm.sale_values(p, y)
        out[y] = pm.waterfall(p, y, v, price).surplus
    return out


def market_monte_carlo(plan: Plan, years: list[int], n_paths: int = 2000) -> dict:
    """{year: MarketOutcome} on shared market (and property) paths."""
    z = market_shocks(plan, n_paths)
    surp = _surpluses(plan, years, n_paths)
    return {y: _run_year(plan, y, z, surp[y]) for y in years}


def safe_spending(plan: Plan, year: int, target: float = 0.9, n_paths: int = 2000) -> float:
    """Largest multiple of planned spending (all years) with success >= target."""
    z = market_shocks(plan, n_paths)
    s = _surpluses(plan, [year], n_paths)[year]
    lo, hi = 0.3, 3.0
    if _run_year(plan, year, z, s, hi).success_rate >= target:
        return hi
    if _run_year(plan, year, z, s, lo).success_rate < target:
        return lo
    for _ in range(18):
        mid = (lo + hi) / 2
        if _run_year(plan, year, z, s, mid).success_rate >= target:
            lo = mid
        else:
            hi = mid
    return lo


def market_compare(plan: Plan, years: list[int], n_paths: int = 2000) -> pd.DataFrame:
    """Market-risk columns per retirement year, to merge into compare_years."""
    res = market_monte_carlo(plan, years, n_paths)
    rows = []
    for y, o in res.items():
        end = o.end_capital(plan.end_year)
        rows.append({'Retirement year': y, 'Success rate (markets)': o.success_rate,
                     f'Capital {plan.end_year} P10 (markets)': float(np.percentile(end, 10)),
                     f'Capital {plan.end_year} P50 (markets)': float(np.percentile(end, 50)),
                     f'Capital {plan.end_year} P90 (markets)': float(np.percentile(end, 90)),
                     'Lowest capital P10 (markets)': float(np.percentile(o.capital.min(axis=1), 10))})
    return pd.DataFrame(rows)


# ====================================================================== withdrawal strategy
"""Compare registered-withdrawal strategies on the same plan (same property path and,
when market risk is on, the same market histories).

Judged mainly on the after-tax estate at the end year: registered money still unspent is
taxed at the top rate on the second death, so a strategy that only defers tax is not
rewarded for it. Lifetime tax alone would favour leaving everything in the RRSP."""

BRACKET_TARGETS = tuple(range(50_000, 210_001, 10_000))
FILL_AGES = (64, 67, 71)


def _with(plan: Plan, **kw) -> Plan:
    p = plan.copy()
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def strategy_metrics(plan: Plan, sale=None) -> dict:
    df, st = project(plan, sale)
    s = summary(plan, df, st)
    e = df[df['A'] <= plan.end_year]
    real = (1 + plan.inflation) ** (plan.end_year - plan.current_year)
    return {
        'Lifetime income tax': s['Lifetime income tax'],
        'Lifetime OAS clawback': s['Lifetime OAS clawback'],
        f'Capital {plan.end_year}': s[f'Capital {plan.end_year}'],
        'Estate after tax': s['Estate after tax'],
        "Estate after tax (today's $)": s['Estate after tax'] / real,
        f'Registered left in {plan.end_year}': float((e['I'] + e['V']).iloc[-1]),
        f'TFSA in {plan.end_year}': float((e['BU'] + e['BX']).iloc[-1]),
        'Highest taxable income (one person)': float(max(e['Q'].max(), e['AD'].max())),
        'Years with OAS clawback': int(((e['CF'] + e['CM']) > 1).sum()),
        '_df': df,
    }


def optimize_bracket(plan: Plan, sale=None, targets=BRACKET_TARGETS, ages=FILL_AGES) -> pd.DataFrame:
    """Grid over bracket targets x fill-until ages; sorted best-first by after-tax estate."""
    rows = []
    for a in ages:
        for t in targets:
            m = strategy_metrics(_with(plan, withdrawal_strategy='bracket', bracket_target=float(t),
                                       fill_until_age=a), sale)
            rows.append({'Target income': t, 'Fill until age': a,
                         **{k: v for k, v in m.items() if not k.startswith('_')}})
    return pd.DataFrame(rows).sort_values('Estate after tax', ascending=False).reset_index(drop=True)


def compare_strategies(plan: Plan, sale=None, n_paths: int = 0) -> tuple[pd.DataFrame, dict, dict]:
    """Rows: minimums, defer to 71, the plan's bracket settings, and the best bracket target.
    Returns (table, {name: df}, best bracket params). n_paths > 0 adds a market success rate."""
    best = optimize_bracket(plan, sale).iloc[0]
    best_kw = dict(withdrawal_strategy='bracket', bracket_target=float(best['Target income']),
                   fill_until_age=int(best['Fill until age']))
    variants = [
        ('RRIF minimums from retirement', dict(withdrawal_strategy='minimums')),
        ('Defer RRSPs to 71, draw as needed', dict(withdrawal_strategy='defer')),
        (f'Fill to ${plan.bracket_target / 1000:,.0f}K until {plan.fill_until_age} (your setting)',
         dict(withdrawal_strategy='bracket')),
        (f'Best: fill to ${best_kw["bracket_target"] / 1000:,.0f}K until {best_kw["fill_until_age"]}', best_kw),
    ]
    rows, dfs = [], {}
    z = market_shocks(plan, n_paths) if n_paths else None
    surp = None
    if n_paths:
        surp = _surpluses(plan, [plan.start_year], n_paths)[plan.start_year]
    for name, kw in variants:
        p = _with(plan, **kw)
        m = strategy_metrics(p, sale)
        dfs[name] = m.pop('_df')
        row = {'Strategy': name, **m}
        if n_paths:
            row['Chance the money lasts (markets)'] = _run_year(p, p.start_year, z, surp).success_rate
        rows.append(row)
    t = pd.DataFrame(rows)
    base = t['Estate after tax'].iloc[0]
    t.insert(1, 'Estate vs minimums', t['Estate after tax'] - base)
    return t, dfs, best_kw


# ====================================================================== sustainable spending
"""How much can we spend each year and still (a) never run out and (b) leave a target estate
after tax at the end (second death), in today's dollars?

Spending is scaled as a whole (every item, every year, both phases) or only the
discretionary items. Without market risk the answer is exact for the plan as it stands;
with market risk it is the spending at which the chosen share of histories meets both tests.
More spending never leaves more money, so a bisection on the scale finds the answer."""


def scale_spending(plan: Plan, scale: float, mode: str = 'all') -> Plan:
    """Copy of the plan with spending scaled ('all' items or 'discretionary' only)."""
    p = plan.copy()
    for e in p.expenses:
        if mode == 'all' or e.discretionary:
            e.monthly *= scale
            if e.monthly_later is not None:
                e.monthly_later *= scale
    return p


def _real(plan: Plan) -> float:
    return (1 + plan.inflation) ** (plan.end_year - plan.current_year)


def spending_outcome(plan: Plan, scale: float, mode: str, sale=None) -> dict:
    """Deterministic outcome at a spending scale: lasts?, estate (today's $), first-year spend."""
    p = scale_spending(plan, scale, mode)
    df, st = project(p, sale)
    e = df[df['A'] <= p.end_year]
    return {'scale': scale, 'lasts': bool((e['C'] >= e['B']).all()),
            'estate_today': _engine.estate_after_tax(p, e.iloc[-1]) / _real(p),
            'first_year': float(e['B'].iloc[0]),
            'first_year_today': float(e['B'].iloc[0]) / (1 + p.inflation) ** (p.start_year - p.current_year),
            'low_capital': float(e['C'].min())}


def _market_success(plan: Plan, scale: float, mode: str, z, surplus, target_today: float,
                    return_estates: bool = False):
    p = _plan_for_year(scale_spending(plan, scale, mode), plan.start_year)
    starts, _ = _starts_for_year(p, p.start_year, z, surplus)
    out = project_many(p, starts, _returns_for_year(p, p.start_year, z))
    mask = out['years'] <= p.end_year
    cap, spend = out['C'][:, mask], out['B'][:, mask]
    lasts = (cap >= spend).all(axis=1)
    last = np.flatnonzero(mask)[-1]
    estate = (out['F'][:, last] + out['S'][:, last] + out['BU'][:, last] + out['BX'][:, last]
              + (out['I'][:, last] + out['V'][:, last]) * (1 - p.tax_rates[-1])
              + _engine.corp_after_tax(p, out['CORP'][:, last], out['RDTOH'][:, last])) / _real(p)
    rate = float((lasts & (estate >= target_today)).mean())
    return (rate, estate, lasts) if return_estates else rate


def solve_spending(plan: Plan, target_today: float = 0.0, mode: str = 'all', sale=None,
                   confidence: float | None = None, n_paths: int = 0) -> dict:
    """Largest spending scale meeting the goal. confidence + n_paths -> market-risk version."""
    z = surp = None
    if confidence and n_paths:
        z = market_shocks(plan, n_paths)
        surp = _surpluses(plan, [plan.start_year], n_paths)[plan.start_year]
        ok = lambda s: _market_success(plan, s, mode, z, surp, target_today) >= confidence
        metric = lambda s: _market_success(plan, s, mode, z, surp, target_today)
    else:
        ok = lambda s: (lambda o: o['lasts'] and o['estate_today'] >= target_today)(
            spending_outcome(plan, s, mode, sale))
        metric = None
    lo, hi = 0.0, 4.0
    feasible = ok(lo)
    if feasible:
        if ok(hi):
            lo = hi
        else:
            for _ in range(22):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    best = spending_outcome(plan, lo, mode, sale) if feasible else None
    # curve for the chart: deterministic estate, and the market success rate if requested
    grid = np.round(np.arange(0.5, 2.01, 0.05), 2)
    rows = []
    for s in grid:
        o = spending_outcome(plan, float(s), mode, sale)
        row = {'Spending scale': float(s), "First-year spending (today's $)": o['first_year_today'],
               "Estate after tax (today's $)": o['estate_today'], 'Money lasts (fixed return)': o['lasts']}
        if metric:
            row['Chance of meeting the goal (markets)'] = metric(float(s))
        rows.append(row)
    estates = None
    if metric and feasible:   # estate across market histories at the answer (today's $)
        _, est, _ = _market_success(plan, lo, mode, z, surp, target_today, return_estates=True)
        estates = {q: float(np.percentile(est, q)) for q in (10, 25, 50, 75, 90)}
    return {'feasible': feasible, 'scale': lo if feasible else None, 'outcome': best,
            'success_rate': metric(lo) if (metric and feasible) else None, 'curve': pd.DataFrame(rows),
            'estates': estates}


# ====================================================================== consulting corporation
DIVIDEND_TARGETS = tuple(range(40_000, 260_001, 10_000))


def best_dividend_target(plan: Plan, sale=None) -> pd.DataFrame:
    """Estate after tax for each dividend target (fill policy) and for 'pay everything out'."""
    rows = []
    for t in DIVIDEND_TARGETS:
        m = strategy_metrics(_with(plan, dividend_policy='target', dividend_target=float(t)), sale)
        rows.append({'Policy': 'target', 'Dividend target': t,
                     **{k: v for k, v in m.items() if not k.startswith('_')}})
    m = strategy_metrics(_with(plan, dividend_policy='all'), sale)
    rows.append({'Policy': 'all', 'Dividend target': None, **{k: v for k, v in m.items() if not k.startswith('_')}})
    return pd.DataFrame(rows).sort_values('Estate after tax', ascending=False).reset_index(drop=True)


def corp_vs_personal(plan: Plan, sale=None) -> pd.DataFrame:
    """The same consulting earned personally vs through the corporation (current dividend policy)."""
    rows = []
    for label, via in (('Personally (self-employed)', False), ('Through the corporation', True)):
        p = plan.copy()
        for c in p.consulting:
            c.via_corp = via
        m = strategy_metrics(p, sale)
        df = m.pop('_df')
        e = df[df['A'] <= p.end_year]
        rows.append({'Route': label, "Estate after tax (today's $)": m["Estate after tax (today's $)"],
                     'Lifetime income tax (personal)': m['Lifetime income tax'],
                     'Corporate tax': float(e['CORP_TAX'].sum()) if 'CORP_TAX' in e else 0.0,
                     'CPP contributions': float((e['CPP_P1'] + e['CPP_P2']).sum()),
                     'Lifetime OAS clawback': m['Lifetime OAS clawback'],
                     'Person 2 CPP at 65': float(df.loc[p.person('P2').birth_year + 65, 'CJ'])
                     if p.person('P2').birth_year + 65 in df.index else None})
    t = pd.DataFrame(rows)
    t.insert(2, 'Difference', t["Estate after tax (today's $)"] - t["Estate after tax (today's $)"].iloc[0])
    return t
