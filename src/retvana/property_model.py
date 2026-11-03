"""Property values, mortgages and the sale/purchase waterfall.

Two ways to value the properties at the sale date (Jan 1 of the retirement year):

legacy    - the original spreadsheet scenarios (Bear/Base/Bull/Boom): one growth factor
            applied to every property and the townhouse.
recovery  - a per-segment mean-reversion model. Each property type has a fair value,
            anchored to its 2022 peak (recovery_target x peak), that grows at a
            long-run rate. Each year the price closes `recovery_speed` of the log gap
            to fair value, plus a shared market shock (rates, sentiment, supply;
            autocorrelated) scaled by the segment's beta and a property-specific shock:

              log V[t+1] = log V[t] + ln(1+g) + k * (log F[t] - log V[t]) + beta * m[t] + s * e[t]
              F[t]       = target * peak * (1 + g) ** t
              m[t]       = phi * m[t-1] + sigma_m * sqrt(1 - phi^2) * z[t]

            With no shocks this gives the median path; with shocks it gives Monte Carlo
            paths. The townhouse being bought is simulated in the same market, so a
            rising market raises its price too.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .config import Mortgage, Plan


# ---------------------------------------------------------------- mortgages
def mortgage_balance(m: Mortgage, year: int) -> float:
    """Balance on Jan 1 of `year`, monthly compounding, one renewal rate for all later
    terms (identical to the original spreadsheet formulas)."""
    if m.balance == 0:
        return 0.0
    i1, n, term = m.rate / 12, m.amort_years * 12, m.term_months
    i2 = (m.renewal_rate if m.renewal_rate is not None else m.rate) / 12
    pay = m.balance * i1 / (1 - (1 + i1) ** (-n))
    k = max(0, min(n, (year - m.first_payment_year) * 12 - (m.first_payment_month - 1)))
    if k >= n:
        return 0.0
    k1 = min(k, term)
    bal_term = m.balance * (1 + i1) ** k1 - pay * ((1 + i1) ** k1 - 1) / i1
    if k <= term:
        return bal_term
    pay2 = 0.0 if n <= term else bal_term * i2 / (1 - (1 + i2) ** (-(n - term)))
    k2 = k - term
    return bal_term * (1 + i2) ** k2 - pay2 * ((1 + i2) ** k2 - 1) / i2


def mortgage_payment(m: Mortgage) -> float:
    i1, n = m.rate / 12, m.amort_years * 12
    return m.balance * i1 / (1 - (1 + i1) ** (-n)) if m.balance else 0.0


# ---------------------------------------------------------------- transaction costs
def land_transfer_tax(plan: Plan, price: float) -> tuple[float, float]:
    """(provincial, municipal) land transfer tax. Each ltt_brackets row is
    [from, to, provincial rate, municipal rate]; the municipal rates model a city that levies
    its own land transfer tax on top of the provincial one."""
    prov = sum(max(min(price, hi) - lo, 0) * r_prov for lo, hi, r_prov, _ in plan.ltt_brackets)
    muni = sum(max(min(price, hi) - lo, 0) * r_muni for lo, hi, _, r_muni in plan.ltt_brackets)
    return prov, muni


@dataclass
class Waterfall:
    sale_values: dict
    total_sale: float
    mortgages: float
    principal: float
    commission: float
    capital_gains_tax: float
    ltt_provincial: float
    ltt_municipal: float
    purchase: float
    surplus: float
    cg_detail: dict

    @property
    def ltt(self) -> float:
        return self.ltt_provincial + self.ltt_municipal

    def rows(self) -> list[tuple[str, float]]:
        r = [(f'Sale: {k}', v) for k, v in self.sale_values.items()]
        r += [('Total sale value', self.total_sale), ('Less: mortgages at sale', -self.mortgages),
              ('Principal', self.principal),
              ('Less: real estate commission (incl. HST)', -self.commission),
              ('Less: capital gains tax', -self.capital_gains_tax),
              ('Less: land transfer tax (provincial + municipal)', -self.ltt),
              ('Less: townhouse purchase', -self.purchase),
              ('Surplus (+) / shortfall (-)', self.surplus)]
        return r


def waterfall(plan: Plan, year: int, sale_values: dict, purchase: float) -> Waterfall:
    total = sum(sale_values.values())
    morts = sum(mortgage_balance(m, year) for m in plan.mortgages)
    comm_rate = plan.commission_rate * (1 + plan.hst)
    top = plan.tax_rates[-1]
    cgt, detail = 0.0, {}
    for p in plan.properties:
        if p.principal_residence:
            continue
        sale = sale_values[p.name]
        acb = p.purchase_price if p.acb is None else p.acb
        gain = max(sale - acb - sale * comm_rate, 0)
        tax = gain * plan.cg_inclusion * top
        detail[p.name] = dict(sale=sale, acb=acb, selling_costs=sale * comm_rate, gain=gain, tax=tax)
        cgt += tax
    prov, muni = land_transfer_tax(plan, purchase)
    principal = total - morts
    commission = total * comm_rate
    surplus = principal - commission - cgt - prov - muni - purchase
    return Waterfall(sale_values, total, morts, principal, commission, cgt, prov, muni, purchase,
                     surplus, detail)


# ---------------------------------------------------------------- legacy scenarios
def legacy_factor(plan: Plan, year: int, scenario: str | None = None) -> float:
    s = next(x for x in plan.legacy_scenarios if x.name == (scenario or plan.legacy_scenario))
    n = year - plan.current_year
    return (1 + s.recovery_rate) ** min(n, s.recovery_years) * (1 + s.long_run_rate) ** max(n - s.recovery_years, 0)


def legacy_values(plan: Plan, year: int, scenario: str | None = None) -> tuple[dict, float]:
    f = legacy_factor(plan, year, scenario)
    values = {p.name: p.value_today * f for p in plan.properties}
    th = plan.townhouse
    return values, th.price_today * f if th.follows_market else th.price_today


# ---------------------------------------------------------------- recovery model
def _assets(plan: Plan):
    """(name, value_today, peak, segment) for each property, then the townhouse."""
    out = [(p.name, p.value_today, p.peak_value, plan.segment(p.segment)) for p in plan.properties]
    th = plan.townhouse
    out.append(('Townhouse', th.price_today, th.peak_value, plan.segment(th.segment)))
    return out


def simulate(plan: Plan, horizon_year: int, n_paths: int = 0, seed: int = 2026) -> dict:
    """Value paths from current_year to horizon_year.

    Returns {asset_name: array (paths, years+1)} plus 'years'. n_paths=0 gives the
    single median (no-shock) path."""
    T = max(horizon_year - plan.current_year, 0)
    assets = _assets(plan)
    paths = max(n_paths, 1)
    rng = np.random.default_rng(seed)
    if n_paths:
        # draw for a fixed 40-year window so every horizon sees the same random paths
        TD = max(T, 40)
        z = rng.standard_normal((paths, TD))[:, :T]
        phi, sm = plan.market_momentum, plan.market_vol
        m = np.zeros((paths, T))
        for t in range(T):
            m[:, t] = (sm * z[:, 0] if t == 0 else
                       phi * m[:, t - 1] + sm * math.sqrt(1 - phi ** 2) * z[:, t])
        e = rng.standard_normal((len(assets), paths, TD))[:, :, :T]
    out = {'years': np.arange(plan.current_year, plan.current_year + T + 1)}
    for a, (name, v0, peak, seg) in enumerate(assets):
        logv = np.full((paths, T + 1), math.log(v0))
        g, k = seg.long_run_growth, seg.recovery_speed
        log_f0 = math.log(seg.recovery_target * peak)
        for t in range(T):
            log_f = log_f0 + t * math.log1p(g)
            step = math.log1p(g) + k * (log_f - logv[:, t])
            if n_paths:
                step = step + seg.beta * m[:, t] + seg.idio_vol * e[a, :, t]
            logv[:, t + 1] = logv[:, t] + step
        out[name] = np.exp(logv)
    return out


def recovery_values(plan: Plan, year: int, sim: dict | None = None, path: int = 0) -> tuple[dict, float]:
    sim = sim or simulate(plan, year)
    t = year - plan.current_year
    vals = {}
    for p in plan.properties:
        disc = plan.segment(p.segment).sale_discount
        vals[p.name] = float(sim[p.name][path, t]) * (1 - disc)
    th = plan.townhouse
    price = float(sim['Townhouse'][path, t]) if th.follows_market else th.price_today
    return vals, price


def sale_values(plan: Plan, year: int) -> tuple[dict, float]:
    """Deterministic sale values and townhouse price for the plan's property mode."""
    if plan.property_mode == 'legacy':
        return legacy_values(plan, year)
    return recovery_values(plan, year)


def surplus_distribution(plan: Plan, years: list[int], n_paths: int = 2000, seed: int = 2026) -> dict:
    """Monte Carlo surplus by sale year on common random paths.
    Returns {year: np.array(paths)} and per-asset value arrays."""
    sim = simulate(plan, max(years), n_paths, seed)
    out = {}
    for y in years:
        t = y - plan.current_year
        s = np.empty(n_paths)
        morts = sum(mortgage_balance(m, y) for m in plan.mortgages)
        comm = plan.commission_rate * (1 + plan.hst)
        top = plan.tax_rates[-1]
        total = np.zeros(n_paths)
        cgt = np.zeros(n_paths)
        for p in plan.properties:
            v = sim[p.name][:, t] * (1 - plan.segment(p.segment).sale_discount)
            total += v
            if not p.principal_residence:
                acb = p.purchase_price if p.acb is None else p.acb
                cgt += np.maximum(v - acb - v * comm, 0) * plan.cg_inclusion * top
        th = plan.townhouse
        price = sim['Townhouse'][:, t] if th.follows_market else np.full(n_paths, th.price_today)
        ltt = np.zeros(n_paths)
        for lo, hi, r_prov, r_muni in plan.ltt_brackets:
            ltt += np.maximum(np.minimum(price, hi) - lo, 0) * (r_prov + r_muni)
        s = total - morts - total * comm - cgt - ltt - price
        out[y] = s
    return {'surplus': out, 'sim': sim}
