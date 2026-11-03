"""Check the property sale, legacy scenarios and the recovery model (Requirements 2, 3, 4, 5;
design P5 and the rules-coded-twice table).
  .venv/bin/python scripts/property_check.py

Hand calculations are written out from the rules in requirements.md, not by calling the function
under test. Property values, ACBs, mortgages and the townhouse price are read from the example plan;
commission, HST, LTT brackets, segment parameters and tax rates are the public rules, written out.
Monte Carlo runs use at most 200 paths.
"""
import math
import sys
import numpy as np                                                    # noqa: E402
from retvana import property_model as pm                              # noqa: E402
from retvana.analysis import monte_carlo                              # noqa: E402
from retvana.config import Mortgage, example_plan                     # noqa: E402
from retvana.engine import starting_position                          # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def close(a, b, tol=0.005):
    return abs(a - b) <= tol


def fresh_plan():
    """The app defaults (mirror of app.fresh_plan(); plan_check.py keeps the mirror honest)."""
    p = example_plan()
    p.property_mode = 'recovery'
    p.tfsa_topup = True
    p.accurate_extra_tax = True
    p.use_death_ages = True
    p.sync_end_year()
    return p


# ------------------------------------------------------------------ 3.1 mortgage balance
def hand_balance(balance, rate, amort_years, fp_year, fp_month, term, renewal, year):
    """Month-by-month amortization: payment fixed for the current term, recomputed at renewal
    on the remaining amortization at the renewal rate. Balance on Jan 1 of `year`."""
    n = int(round(amort_years * 12))
    i = rate / 12
    pay = balance * i / (1 - (1 + i) ** -n)
    made = (year - fp_year) * 12 - (fp_month - 1)          # payments made before Jan 1 of `year`
    made = max(0, min(n, made))
    bal = balance
    for k in range(made):
        if k == term:                                       # renewal: new rate, new payment
            i = (rate if renewal is None else renewal) / 12
            pay = bal * i / (1 - (1 + i) ** -(n - term))
        bal = bal * (1 + i) - pay
    return 0.0 if made >= n else bal


p = example_plan()
bad = []
for m in p.mortgages:
    for renewal in (None, 0.045, 0.06):
        mm = Mortgage(m.name, m.secured_on, m.balance, m.rate, m.amort_years, m.first_payment_year,
                      m.first_payment_month, m.term_months, renewal)
        for y in (2025, 2026, 2028, 2029, 2030, 2033, 2040):
            got = pm.mortgage_balance(mm, y)
            want = hand_balance(m.balance, m.rate, m.amort_years, m.first_payment_year,
                                m.first_payment_month, m.term_months, renewal, y)
            if not close(got, want, 0.01):
                bad.append(f'{m.name} renewal {renewal} {y}: {got:,.2f} vs {want:,.2f}')
check('mortgage balances match a month-by-month hand amortization (term rate, then renewal rate), '
      '2 mortgages x 3 renewal rates x 7 years', not bad, '; '.join(bad[:3]))
m = p.mortgages[1]                                          # the shorter amortization
paid_off = m.first_payment_year + math.ceil((m.amort_years * 12 + m.first_payment_month - 1) / 12)
check('mortgage balance before the first payment is the starting balance',
      pm.mortgage_balance(m, m.first_payment_year) == m.balance)
check(f'mortgage balance after full amortization is 0 (Jan 1 {paid_off}), and not before',
      pm.mortgage_balance(m, paid_off) == 0.0
      and hand_balance(m.balance, m.rate, m.amort_years, m.first_payment_year, m.first_payment_month,
                       m.term_months, None, paid_off) == 0.0
      and pm.mortgage_balance(m, paid_off - 1) > 0)
check('renewal at a higher rate leaves a higher balance after the term',
      pm.mortgage_balance(Mortgage('x', 'y', 500_000, 0.04, 25, 2025, 1, 36, 0.06), 2033)
      > pm.mortgage_balance(Mortgage('x', 'y', 500_000, 0.04, 25, 2025, 1, 36, None), 2033))

# ------------------------------------------------------------------ 3.2 waterfall by hand
COMM = 0.05 * 1.13                                          # 5% commission + 13% HST
TOP = 0.5353


def hand_ltt_one(price):
    """Provincial (= municipal) LTT from the 2026 brackets: 0.5% to 55K, 1% to 250K, 1.5% to 400K,
    2% to 2M, 2.5% to 3M. Cumulative tax at each edge written out."""
    if price <= 55_000:
        return price * 0.005
    if price <= 250_000:
        return 275 + (price - 55_000) * 0.01
    if price <= 400_000:
        return 2_225 + (price - 250_000) * 0.015
    if price <= 2_000_000:
        return 4_475 + (price - 400_000) * 0.02
    if price <= 3_000_000:
        return 36_475 + (price - 2_000_000) * 0.025
    return 61_475                                          # brackets end at $3M (see finding below)


p = example_plan()
bad = []
for edge in (55_000, 250_000, 400_000, 2_000_000, 3_000_000):
    for price in (edge - 1, edge, edge + 1):
        prov, muni = pm.land_transfer_tax(p, price)
        want = hand_ltt_one(price)
        if not (close(prov, want, 1e-6) and close(muni, want, 1e-6)):
            bad.append(f'{price}: {prov:.4f}/{muni:.4f} vs {want:.4f}')
for price in (0, 1_000_000, 1_500_000):
    prov, muni = pm.land_transfer_tax(p, price)
    if not (close(prov, hand_ltt_one(price), 1e-6) and close(muni, hand_ltt_one(price), 1e-6)):
        bad.append(f'{price}: {prov:.4f}/{muni:.4f} vs {hand_ltt_one(price):.4f}')
check('LTT (provincial and municipal) matches hand values at $0, $1.0M, $1.5M and each bracket edge -1/0/+1',
      not bad, '; '.join(bad))
on1, _ = pm.land_transfer_tax(p, 3_000_000)
on2, _ = pm.land_transfer_tax(p, 3_500_000)
check('(finding) LTT stops at $3M: no tax on the price above $3M (Req 3.5 does not say what applies '
      'above $3M; real Ontario LTT continues at 2.5%)', on2 == on1, f'{on1:,.0f} at 3M, {on2:,.0f} at 3.5M')

# Waterfall: Property 1 is the principal residence, Property 2 a rental with its ACB set,
# Property 3 a rental with the ACB left as the purchase price. Two cases with opposite surplus
# signs: every property sold at 1.5x today's value with the townhouse at today's price, and
# every property at today's value with the townhouse at 1.5x today's price.
y = p.start_year
morts_hand = sum(hand_balance(m.balance, m.rate, m.amort_years, m.first_payment_year, m.first_payment_month,
                              m.term_months, m.renewal_rate, y) for m in p.mortgages)
PR = [q.name for q in p.properties if q.principal_residence]
RENTALS = {q.name: (q.purchase_price if q.acb is None else q.acb) for q in p.properties if not q.principal_residence}
check('example plan: Property 1 is the principal residence; Property 2 has its ACB set, Property 3 does not',
      PR == ['Property 1'] and p.properties[1].acb is not None and p.properties[2].acb is None)


def hand_cgt(sales):
    """Req 3.3: each rental's gain = sale - ACB - selling costs (floored at 0), 50% included, top rate."""
    return sum(max(sales[k] - acb - sales[k] * COMM, 0) * 0.5 * TOP for k, acb in RENTALS.items())


today = {q.name: q.value_today for q in p.properties}
th_today = p.townhouse.price_today
for tag, sales, purchase, sign in (
        ('positive surplus', {k: v * 1.5 for k, v in today.items()}, th_today, 1),
        ('negative surplus', dict(today), th_today * 1.5, -1)):
    wf = pm.waterfall(p, y, sales, purchase)
    total = sum(sales.values())
    commission = total * COMM
    cgt = hand_cgt(sales)
    ltt = 2 * hand_ltt_one(purchase)
    surplus = total - morts_hand - commission - cgt - ltt - purchase
    check(f'waterfall ({tag}): commission = total x 5% x 1.13', close(wf.commission, commission),
          f'{wf.commission:,.2f} vs {commission:,.2f}')
    check(f'waterfall ({tag}): CGT on each rental from its ACB (set, or the purchase price); '
          f'principal residence untaxed', close(wf.capital_gains_tax, cgt) and set(wf.cg_detail) == set(RENTALS)
          and all(wf.cg_detail[k]['acb'] == acb for k, acb in RENTALS.items()),
          f'{wf.capital_gains_tax:,.2f} vs {cgt:,.2f}')
    check(f'waterfall ({tag}): mortgages, LTT and surplus match hand values',
          close(wf.mortgages, morts_hand, 0.01) and close(wf.ltt, ltt) and close(wf.surplus, surplus, 0.01),
          f'surplus {wf.surplus:,.2f} vs {surplus:,.2f}')
    check(f'waterfall ({tag}): surplus sign', (wf.surplus > 0) == (sign > 0), f'{wf.surplus:,.0f}')
check('waterfall (positive surplus): both rentals have a taxable gain (the CGT test above is not trivial)',
      all(today[k] * 1.5 - acb - today[k] * 1.5 * COMM > 0 for k, acb in RENTALS.items()))
# each rental sold 1% above its ACB: the selling costs (5.65%) exceed the gain
wf = pm.waterfall(p, y, {**today, **{k: acb * 1.01 for k, acb in RENTALS.items()}}, th_today)
check('waterfall: CGT is 0 when sale - ACB - selling costs < 0', wf.capital_gains_tax == 0.0)
q3 = p.properties[2]
sale3 = q3.purchase_price * 1.25
wf = pm.waterfall(p, y, {**today, 'Property 2': p.properties[1].acb, 'Property 3': sale3}, th_today)
check(f'waterfall: ACB defaults to the purchase price (${q3.purchase_price / 1000:,.0f}K) when not set',
      wf.cg_detail['Property 3']['acb'] == q3.purchase_price
      and close(wf.capital_gains_tax, (sale3 - q3.purchase_price - sale3 * COMM) * 0.5 * TOP))

# ------------------------------------------------------------------ 3.3 legacy scenarios
# Req 4.2, written out: (recovery years, recovery rate, long-run rate)
SCEN = {'Bear': (3, 0.0, 0.025), 'Base': (3, 0.06, 0.035), 'Bull': (3, 0.10, 0.045), 'Boom': (99, 0.115, 0.115)}
p = example_plan()
check('legacy scenarios are Bear/Base/Bull/Boom with the Req 4.2 rates',
      {s.name: (s.recovery_years, s.recovery_rate, s.long_run_rate) for s in p.legacy_scenarios} == SCEN)
bad = []
for name, (R, rr, lr) in SCEN.items():
    for year in (2026, 2027, 2029, 2030, 2033, 2045):
        n = year - 2026
        want = (1 + rr) ** min(n, R) * (1 + lr) ** max(n - R, 0)
        got = pm.legacy_factor(p, year, name)
        if not math.isclose(got, want, rel_tol=1e-12):
            bad.append(f'{name} {year}: {got} vs {want}')
check('legacy factor matches (1+r)^min(n,R) x (1+g)^max(n-R,0) for all four scenarios', not bad, '; '.join(bad))
n = p.start_year - p.current_year
f = (1.06) ** min(n, 3) * (1.035) ** max(n - 3, 0)          # Base, retirement year
vals, th = pm.legacy_values(p, p.start_year)
check('legacy values: every property and the townhouse grow by the factor',
      all(math.isclose(vals[q.name], q.value_today * f, rel_tol=1e-12) for q in p.properties)
      and math.isclose(th, p.townhouse.price_today * f, rel_tol=1e-12))
p.townhouse.follows_market = False
_, th = pm.legacy_values(p, p.start_year)
check('legacy: townhouse stays at today\'s price when "follows the market" is off', th == p.townhouse.price_today,
      f'{th:,.0f}')

# ------------------------------------------------------------------ 3.4 recovery model, no shocks
p = example_plan()
# Req 5.5, written out: target, speed, growth, beta, sigma, discount
SEG = {'condo_townhouse': (1.00, 0.30, 0.035, 0.9, 0.05, 0.0),
       'condo_apartment': (0.90, 0.20, 0.030, 1.1, 0.07, 0.0),
       'studio': (0.85, 0.15, 0.025, 1.2, 0.09, 0.03),
       'freehold_townhouse': (1.00, 0.30, 0.040, 1.0, 0.05, 0.0)}
check('default segments match Req 5.5',
      {s.key: (s.recovery_target, s.recovery_speed, s.long_run_growth, s.beta, s.idio_vol, s.sale_discount)
       for s in p.segments} == SEG)
check('default market shock: sigma_m 7%, phi 0.5', p.market_vol == 0.07 and p.market_momentum == 0.5)

ASSETS = ([(q.name, q.segment, q.value_today, q.peak_value) for q in p.properties]
          + [('Townhouse', p.townhouse.segment, p.townhouse.price_today, p.townhouse.peak_value)])
STUDIO = next(q.name for q in p.properties if q.segment == 'studio')


def hand_median(v0, peak, seg, T):
    """Req 5.1 with no shocks: log V[t+1] = log V[t] + ln(1+g) + k (log F[t] - log V[t]),
    F[t] = target x peak x (1+g)^t. The drift ln(1+g) grows value at the fair-value rate."""
    target, k, g = SEG[seg][:3]
    logv = [math.log(v0)]
    for t in range(T):
        log_f = math.log(target * peak * (1 + g) ** t)
        logv.append(logv[-1] + math.log1p(g) + k * (log_f - logv[-1]))
    return [math.exp(x) for x in logv]


sim = pm.simulate(p, 2045)
T = 2045 - 2026
check('no-shock simulate returns one path per asset, years 2026..2045',
      list(sim['years']) == list(range(2026, 2046)) and all(sim[a].shape == (1, T + 1) for a, *_ in ASSETS))
worst = ''
rec_ok = True
for name, seg, v0, peak in ASSETS:
    want = hand_median(v0, peak, seg, T)
    got = sim[name][0]
    rel = max(abs(a / b - 1) for a, b in zip(got, want))
    if rel > 1e-9:
        rec_ok = False
        worst += f'{name} 2045 {got[-1]:,.0f} vs {want[-1]:,.0f} (max rel diff {rel:.2%}); '
check('recovery model with no shocks matches the Req 5.1 recurrence', rec_ok, worst)

vals, th = pm.recovery_values(p, 2033)
t = 2033 - 2026
check(f'sale discount applies to the studio only ({STUDIO} x 0.97, others undiscounted)',
      all(math.isclose(vals[q.name], sim[q.name][0, t] * (0.97 if q.name == STUDIO else 1.0), rel_tol=1e-12)
          for q in p.properties)
      and math.isclose(th, sim['Townhouse'][0, t], rel_tol=1e-12))
p.townhouse.follows_market = False
_, th = pm.recovery_values(p, 2033)
check('recovery: townhouse stays at today\'s price when "follows the market" is off', th == p.townhouse.price_today)

# ------------------------------------------------------------------ 3.5 common random numbers (P5)
p = example_plan()
a = pm.simulate(p, 2030, 150)
b = pm.simulate(p, 2045, 150)
n = 2030 - 2026 + 1
check('CRN: simulate gives identical values for shared years at horizon 2030 and 2045 (150 paths)',
      all(np.array_equal(a[name], b[name][:, :n]) for name, *_ in ASSETS))
c = pm.simulate(p, 2030, 150, seed=7)
check('CRN: a different seed gives different paths', not np.array_equal(a['Property 1'], c['Property 1']))
# Req 5.2 / 5.6: seed 2026, a 40-year window of market draws z, then per-asset draws e.
# Year 1 for Property 1: log(V1 / median V1) = beta x sigma_m x z[0] + sigma x e[0].
rng = np.random.default_rng(2026)
z = rng.standard_normal((150, 40))
e = rng.standard_normal((4, 150, 40))
med1 = pm.simulate(p, 2027)['Property 1'][0, 1]
check('first-year shock = beta x sigma_m x z[0] + sigma x e[0] from seed 2026 with a 40-year window',
      np.allclose(np.log(a['Property 1'][:, 1] / med1),
                  SEG[ASSETS[0][1]][3] * 0.07 * z[:, 0] + SEG[ASSETS[0][1]][4] * e[0, :, 0], atol=1e-12))
# m[1] = phi m[0] + sigma_m sqrt(1 - phi^2) z[1]; year-2 shock for Property 2 (its segment's beta and sigma)
m0 = 0.07 * z[:, 0]
m1 = 0.5 * m0 + 0.07 * math.sqrt(1 - 0.25) * z[:, 1]
lv1 = np.log(a['Property 2'][:, 1])
tgt_, k_, g_, beta_, sig_ = SEG[ASSETS[1][1]][:5]
# what is left after removing the mean reversion and the shocks is the drift, the same on every path
# (the drift itself is checked in 3.4)
log_f1 = math.log(tgt_ * ASSETS[1][3] * (1 + g_))
resid = np.log(a['Property 2'][:, 2]) - lv1 - k_ * (log_f1 - lv1) - beta_ * m1 - sig_ * e[1, :, 1]
check('second-year shock follows the autocorrelated market recurrence (Req 5.2)',
      np.ptp(resid) < 1e-10, f'spread {np.ptp(resid):.2e}')

# ------------------------------------------------------------------ 3.6 waterfall = surplus_distribution
for tag, setup in (('default', lambda q: None),
                   ('ACB set, townhouse fixed', lambda q: (setattr(q.properties[2], 'acb', 550_000),
                                                           setattr(q.townhouse, 'follows_market', False)))):
    p = example_plan()
    setup(p)
    years = [2030, 2033, 2040]
    dist = pm.surplus_distribution(p, years, 50)
    worst = 0.0
    for y in years:
        for i in range(50):
            v, price = pm.recovery_values(p, y, dist['sim'], i)
            worst = max(worst, abs(pm.waterfall(p, y, v, price).surplus - dist['surplus'][y][i]))
    check(f'{tag}: waterfall surplus = surplus_distribution path by path (50 paths, 3 years)',
          worst < 0.01, f'max diff ${worst:.6f}')
    med = pm.waterfall(p, 2033, *pm.recovery_values(p, 2033)).surplus
    p0 = p.copy()
    p0.market_vol = 0.0
    for s in p0.segments:
        s.idio_vol = 0.0
    d0 = pm.surplus_distribution(p0, [2033], 3)['surplus'][2033]
    check(f'{tag}: median-path waterfall surplus = surplus_distribution with every shock at zero volatility',
          np.allclose(d0, med, atol=0.01), f'{med:,.2f} vs {d0[0]:,.2f}')

# ------------------------------------------------------------------ 3.7 monte_carlo percentile paths
p = fresh_plan()
N = 101                                                     # q/100 x (N-1) is a whole index for 10/50/90
mc = monte_carlo(p, [2033], N)
o = mc['years'][2033]
srt = np.sort(o.surplus)
for q in (10, 50, 90):
    want = srt[q]                                           # q/100 x 100
    _, st, _ = o.runs[q]
    got = st.waterfall.surplus
    check(f'monte_carlo P{q}: the run uses the path at the P{q} surplus ({N} paths)',
          close(got, want, 0.01) and close(float(np.percentile(o.surplus, q)), want, 0.01),
          f'{got:,.2f} vs {want:,.2f}')
check('monte_carlo: P10 <= P50 <= P90 surplus and the shortfall share is the share of negative surpluses',
      o.runs[10][1].waterfall.surplus <= o.runs[50][1].waterfall.surplus <= o.runs[90][1].waterfall.surplus
      and o.p_shortfall == sum(1 for s in o.surplus if s < 0) / N)

# ------------------------------------------------------------------ Req 2 with the app defaults
p = fresh_plan()
st = starting_position(p)
n = p.start_year - p.current_year
acc = {}
for a_ in p.accounts:                                       # FV with contributions at year end, by hand
    bal = a_.balance
    pmt = 7000 if a_.contribution_is_tfsa_limit else a_.contribution
    for _ in range(n):
        bal = bal * (1 + a_.return_rate) + pmt
    acc[a_.name] = bal
tot = lambda o_, k: sum(acc[x.name] for x in p.accounts if x.owner == o_ and x.kind == k)
check('app defaults: registered and TFSA balances at retirement = year-by-year FV',
      all(close(getattr(st, f), tot(o_, k), 0.01) for f, o_, k in
          (('reg_p1', 'P1', 'registered'), ('reg_p2', 'P2', 'registered'),
           ('tfsa_p1', 'P1', 'tfsa'), ('tfsa_p2', 'P2', 'tfsa'))))
options = sum(max(g.available * (p.options_share_price - g.grant_price), 0) * (1 - 0.5 * p.options_marginal_rate)
              for g in p.option_grants)
check('app defaults: employee stock option net proceeds by hand', close(st.options_net, options, 0.01),
      f'{st.options_net:,.2f} vs {options:,.2f}')
vals, price = pm.recovery_values(p, p.start_year)          # recovery mode uses the median path
total = sum(vals.values())
surplus = (total - sum(hand_balance(m.balance, m.rate, m.amort_years, m.first_payment_year,
                                    m.first_payment_month, m.term_months, m.renewal_rate, p.start_year)
                       for m in p.mortgages)
           - total * COMM - hand_cgt(vals) - 2 * hand_ltt_one(price) - price)
n1 = tot('P1', 'nonreg')                                    # Non_Registered_Total by hand FV
n2 = tot('P2', 'nonreg')
after = n2 + surplus
check('app defaults: the waterfall uses the recovery median path', close(st.waterfall.surplus, surplus, 0.01),
      f'{st.waterfall.surplus:,.2f} vs {surplus:,.2f}')
check('app defaults: non-registered totals at retirement = year-by-year FV of each person\'s nonreg accounts',
      close(st.nonreg_total_p1, n1, 0.01) and close(st.nonreg_total_p2, n2, 0.01),
      f'P1 {st.nonreg_total_p1:,.2f} vs {n1:,.2f}, P2 {st.nonreg_total_p2:,.2f} vs {n2:,.2f}')
check('app defaults: Person 2 non-reg = max(0, N2 + surplus), Person 1 = options + N1 + min(0, N2 + surplus), '
      'shortfall from Person 1 = -min(0, N2 + surplus)',
      close(st.nonreg_p2, max(0.0, after), 0.01) and close(st.nonreg_p1, options + n1 + min(0.0, after), 0.01)
      and close(st.shortfall_from_p1, -min(0.0, after), 0.01),
      f'P2 {st.nonreg_p2:,.0f} P1 {st.nonreg_p1:,.0f} shortfall {st.shortfall_from_p1:,.0f}')
gogo = sum(e.monthly * 12 for e in p.expenses) * (1 + p.expense_cpi) ** n
later = sum((e.monthly if e.monthly_later is None else e.monthly_later) * 12 for e in p.expenses) * (1 + p.expense_cpi) ** n
check(f'app defaults: go-go and later expenses inflated at {p.expense_cpi:.1%} to the retirement year',
      close(st.expense_gogo, gogo, 0.01) and close(st.expense_later, later, 0.01))
check('app defaults: starting position is the same with the median sale supplied explicitly',
      starting_position(p, (vals, price)).nonreg_p2 == st.nonreg_p2)

print('\nPROPERTY CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
