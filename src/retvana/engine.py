"""Year-by-year retirement projection - a line-for-line port of the original spreadsheet's
Projections tab (column letters in comments). Person 1 (P1) is the first per-person block
(columns F-R), Person 2 (P2) the second (S-AE).

Withdrawal order each year: planned registered draws (RRIF minimums, or the withdrawal
strategy's target), then non-registered, then TFSA, then extra registered withdrawals (taxed
at the top marginal rate, or at the actual marginal rate with accurate_extra_tax). A surplus
is reinvested in non-registered, after filling TFSA room when tfsa_topup is on. OAS clawback
uses the previous year's taxable income. With the default settings this is exactly the
original spreadsheet's logic; scripts/regression_check.py guards it against the regression golden.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import property_model as pm
from .config import Plan, check_account_kind

# friendly names for the exported / displayed table
COLUMNS = {
    'A': 'Year', 'age_P1': 'Person 1 age', 'age_P2': 'Person 2 age',
    'B': 'Expenses', 'C': 'Total capital', 'D': 'Expense / capital', 'E': 'Return on capital',
    'F': 'Person 1 non-registered', 'G': 'Person 1 non-reg return', 'H': 'Person 1 non-reg withdrawal',
    'I': 'Person 1 registered', 'J': 'Person 1 registered return', 'L': 'Person 1 RRIF min %',
    'M': 'Person 1 registered withdrawal', 'N': 'Person 1 other income (CPP, OAS, consulting)',
    'Q': 'Person 1 taxable income',
    'R': 'Person 1 income tax',
    'S': 'Person 2 non-registered', 'T': 'Person 2 non-reg return', 'U': 'Person 2 non-reg withdrawal',
    'V': 'Person 2 registered', 'W': 'Person 2 registered return', 'Y': 'Person 2 RRIF min %',
    'Z': 'Person 2 registered withdrawal', 'AA': 'Person 2 other income (CPP, OAS, consulting)',
    'AD': 'Person 2 taxable income',
    'AE': 'Person 2 income tax',
    'BA': 'Shortfall before withdrawals', 'BB': 'Person 1 non-reg draw', 'BC': 'Person 2 non-reg draw',
    'BD': 'Person 1 planned registered draw', 'BE': 'Person 1 extra registered',
    'BG': 'Person 1 extra-withdrawal tax', 'BH': 'Person 2 planned registered draw',
    'BI': 'Person 2 extra registered', 'BK': 'Person 2 extra-withdrawal tax',
    'BU': 'Person 1 TFSA', 'BV': 'Person 1 TFSA return', 'BW': 'Person 1 TFSA withdrawal',
    'BX': 'Person 2 TFSA', 'BY': 'Person 2 TFSA return', 'BZ': 'Person 2 TFSA withdrawal',
    'CC': 'Person 1 CPP', 'CD': 'Person 1 OAS gross', 'CF': 'Person 1 OAS clawback',
    'CJ': 'Person 2 CPP', 'CK': 'Person 2 OAS gross', 'CM': 'Person 2 OAS clawback',
    'T_P1': 'Person 1 TFSA top-up', 'T_P2': 'Person 2 TFSA top-up',
    'W_P1': 'Person 1 consulting income', 'W_P2': 'Person 2 consulting income',
    'CPP_P1': 'Person 1 CPP contributions', 'CPP_P2': 'Person 2 CPP contributions',
    'K': 'Person 1 RRSP contribution', 'X': 'Person 2 RRSP contribution',
    'CORP': 'Corporation balance', 'CORP_ACTIVE': 'Corporate revenue', 'CORP_TAX': 'Corporate tax',
    'D_P1': 'Person 1 dividends', 'D_P2': 'Person 2 dividends', 'CDA': 'Capital dividends (tax-free)',
    'RDTOH': 'RDTOH (refundable tax)',
}

PERSON_LABELS = {'P1': 'Person 1', 'P2': 'Person 2'}


def column_label(key: str, plan: Plan | None = None) -> str:
    """Display label for a projection column, with the plan's person names in place of the
    generic "Person 1" / "Person 2".

    key is a column key from COLUMNS; any other string (a summary key such as
    "Person 2 CPP at 65", or a column without a friendly name) is used as the label itself.
    With no plan, or a person with an empty name, the generic label is kept."""
    label = COLUMNS.get(key, key)
    if plan is None:
        return label
    for pkey, generic in PERSON_LABELS.items():
        name = next((p.name for p in plan.people if p.key == pkey), '')
        if name:
            label = label.replace(generic, name)
    return label


@dataclass
class Start:
    """Balances and amounts at the start of retirement."""
    expense_gogo: float
    expense_later: float
    options_net: float
    waterfall: pm.Waterfall
    nonreg_p1: float
    nonreg_p2: float
    reg_p1: float
    reg_p2: float
    tfsa_p1: float
    tfsa_p2: float
    shortfall_from_p1: float
    nonreg_total_p1: float        # Non_Registered_Total(P1): Person 1's non-registered accounts at retirement
    nonreg_total_p2: float        # Non_Registered_Total(P2)
    account_fv: dict


def fv(rate: float, n: float, pmt: float, pv: float) -> float:
    """Excel FV(rate, n, -pmt, -pv, 0)."""
    g = (1 + rate) ** n
    return pv * g + (pmt * (g - 1) / rate if rate else pmt * n)


def options_net_proceeds(plan: Plan) -> float:
    """After-tax proceeds of exercising Person 1's employee stock options (50% of the
    benefit taxed at the marginal rate)."""
    total = 0.0
    for g in plan.option_grants:
        benefit = max(g.available * plan.options_share_price - g.available * g.grant_price, 0)
        total += benefit - benefit * 0.5 * plan.options_marginal_rate
    return total


def expenses_at_start(plan: Plan) -> tuple[float, float]:
    gogo = sum(e.monthly * 12 for e in plan.expenses)
    later = sum((e.monthly if e.monthly_later is None else e.monthly_later) * 12 for e in plan.expenses)
    f = (1 + plan.expense_cpi) ** (plan.start_year - plan.current_year)
    return gogo * f, later * f


def starting_position(plan: Plan, sale: tuple[dict, float] | None = None) -> Start:
    n = plan.start_year - plan.current_year
    acc = {}
    for a in plan.accounts:
        check_account_kind(a)
        pmt = plan.tfsa_limit if a.contribution_is_tfsa_limit else a.contribution
        acc[a.name] = fv(a.return_rate, n, pmt, a.balance)
    tot = lambda owner, kind: sum((acc[a.name] for a in plan.accounts if a.owner == owner and a.kind == kind), 0.0)
    values, price = sale if sale is not None else pm.sale_values(plan, plan.start_year)
    wf = pm.waterfall(plan, plan.start_year, values, price)
    options = options_net_proceeds(plan)
    n1, n2 = tot('P1', 'nonreg'), tot('P2', 'nonreg')
    after = n2 + wf.surplus
    gogo, later = expenses_at_start(plan)
    return Start(gogo, later, options, wf,
                 nonreg_p1=options + n1 + min(0.0, after), nonreg_p2=max(0.0, after),
                 reg_p1=tot('P1', 'registered'), reg_p2=tot('P2', 'registered'),
                 tfsa_p1=tot('P1', 'tfsa'), tfsa_p2=tot('P2', 'tfsa'),
                 shortfall_from_p1=-min(0.0, after),
                 nonreg_total_p1=n1, nonreg_total_p2=n2, account_fv=acc)


def consulting_schedule(plan: Plan) -> tuple[dict, dict]:
    """Per year and person: consulting income W, self-employed CPP contributions, the tax
    treatment of those contributions, and RRSP contributions from the new room.

    - Income is net of business expenses and in today's dollars, indexed if asked.
    - CPP: 11.9% between the basic exemption and the YMPE plus 8% (CPP2) up to the YAMPE.
      Paid until 65, or until CPP starts if later (to 70). Half is deducted from income (the
      "employer" share); the other half earns a credit at the lowest rate.
    - Years of consulting before 65 add CPP contributory years (pro rata to YMPE), which
      raises the CPP pension through the proportional reduction.
    - RRSP: if chosen, contribute 18% of last year's consulting income (up to the indexed
      dollar limit) through the year you turn 71; deducted from income, added to registered.
    Returns ({year: {'P1': {...}, 'P2': {...}}}, {'P1': extra contributory years, 'P2': ...})."""
    infl = plan.inflation
    sched, extra = {}, {'P1': 0.0, 'P2': 0.0}
    years = range(plan.current_year, max(plan.end_year, plan.current_year) + 1)
    income = {k: {} for k in ('P1', 'P2')}
    corp = {}
    for c in plan.consulting:
        for y in range(max(c.start_year, plan.start_year), c.end_year + 1):
            if y > plan.death_year(c.owner):
                continue
            amt = c.annual * ((1 + infl) ** (y - plan.current_year) if c.indexed else 1.0)
            if c.via_corp:                     # corporate revenue: no CPP, no RRSP room
                corp[y] = corp.get(y, 0.0) + amt
            else:
                income[c.owner][y] = income[c.owner].get(y, 0.0) + amt
    rrsp_on = {k: any(c.rrsp and not c.via_corp for c in plan.consulting if c.owner == k) for k in ('P1', 'P2')}
    for y in years:
        row = {}
        for k in ('P1', 'P2'):
            p = plan.person(k)
            age = y - p.birth_year
            alive = y <= plan.death_year(k)
            W = income[k].get(y, 0.0) if alive else 0.0
            ympe = plan.ympe_2026 * (1 + infl) ** (y - 2026)
            yampe = plan.yampe_2026 * (1 + infl) ** (y - 2026)
            pays = age < 70 and (age < 65 or age < p.cpp_start_age)
            cpp = 0.0
            if W > 0 and pays:
                cpp = (plan.cpp_se_rate * max(min(W, ympe) - plan.cpp_exemption, 0)
                       + plan.cpp2_se_rate * max(min(W, yampe) - ympe, 0))
                if age < 65:
                    extra[k] += min(1.0, W / ympe)
            prev_w = income[k].get(y - 1, 0.0) if alive else 0.0
            rrsp = (min(0.18 * prev_w, plan.rrsp_limit_2026 * (1 + infl) ** (y - 2026))
                    if rrsp_on[k] and alive and age <= 71 else 0.0)
            row[k] = {'W': W, 'cpp': cpp, 'ded': cpp / 2, 'credit': cpp / 2, 'rrsp': rrsp}
        row['corp'] = corp.get(y, 0.0)
        sched[y] = row
    return sched, extra


# ---------------------------------------------------------------- consulting corporation
"""Consulting through the corporation (a CCPC in Ontario). Each year:
1. Active income from via_corp contracts is taxed at the small-business rate (11.2%) up to the
   small-business limit, which shrinks by $5 per $1 of last year's taxable investment income over
   $50K; any excess is taxed at the general rate.
2. The corporate investments earn the plan's return. The taxable share (as for personal
   non-registered) is taxed at 50.17%, of which 30.67% goes into the refundable (RDTOH) pool. The
   rest (the untaxed half of capital gains) builds the capital dividend account and is paid out
   tax-free each year.
3. Non-eligible dividends are paid to the shareholders (policy below). Each dollar of dividend
   recovers 38.33 cents of RDTOH. Personally, the dividend is grossed up 15% and earns the
   dividend tax credit (federal 9.0301% + Ontario 1.99% of the grossed-up amount).
Dividends are not earned income: no CPP contributions, no CPP years, no RRSP room.
Shareholders: Person 2; Person 1 only if they hold shares and TOSI allows it, i.e. they are
working in the business that year, or Person 2 is 65+, or they inherited the shares.
At the end of the plan, the corporation is valued as if wound up with a final dividend taxed
at the top rate."""


def corp_start_balance(plan: Plan) -> float:
    n = plan.start_year - plan.current_year
    ts = plan.person('P2').taxable_share
    g = plan.return_rate * (1 - ts * (plan.corp_passive_rate - plan.corp_refundable_rate))
    return plan.corp_balance * (1 + g) ** n


def corp_step(plan: Plan, CB0, R0, prev_taxable_inv, active, ret, ts):
    """Corporate income and tax for the year, before dividends. Works on floats or arrays."""
    inv = CB0 * ret
    tinv = inv * ts
    ptax = tinv * plan.corp_passive_rate
    R = R0 + tinv * plan.corp_refundable_rate
    cda = inv - tinv                                   # untaxed part, paid out as a capital dividend
    limit = np.maximum(0.0, plan.corp_sbd_limit - 5 * np.maximum(0.0, prev_taxable_inv - 50_000))
    atax = plan.corp_sbd_rate * np.minimum(active, limit) + plan.corp_general_rate * np.maximum(active - limit, 0.0)
    avail = np.maximum(CB0 + inv - ptax - cda + active - atax, 0.0)
    rr = plan.corp_refund_rate
    dmax = np.minimum(avail / (1 - rr), avail + R)
    return dict(inv=inv, tinv=tinv, ptax=ptax, R=R, cda=cda, atax=atax, avail=avail, dmax=dmax)


def corp_pay(plan: Plan, step: dict, D):
    refund = np.minimum(step['R'], plan.corp_refund_rate * D)
    return dict(refund=refund, CB=np.maximum(step['avail'] - D + refund, 0.0), R=step['R'] - refund)


def corp_after_tax(plan: Plan, CB, R) -> float:
    """Value to the estate if wound up: final dividend (with refund) taxed at the top rate."""
    D = np.minimum(CB / (1 - plan.corp_refund_rate), CB + R)
    rate = (1 + plan.ne_gross_up) * (plan.tax_rates[-1] - plan.ne_dtc_rate)
    return D * (1 - rate)


def dividend_shareholders(plan: Plan, year: int, alive1: bool, alive2: bool) -> tuple[bool, bool]:
    """(Person 1 can receive, Person 2 can receive) dividends this year."""
    if not alive2:
        return alive1, False                          # Person 1 inherits the shares
    working1 = any(c.via_corp and c.owner == 'P1' and c.start_year <= year <= c.end_year
                   for c in plan.consulting)
    age2 = year - plan.person('P2').birth_year
    ok1 = plan.p1_shareholder and alive1 and (working1 or age2 >= 65)
    return ok1, True


def plan_dividends(plan: Plan, year: int, dmax, base1, base2, ok1: bool, ok2: bool):
    """Dividends to (Person 1, Person 2): fill each shareholder's taxable income to the target, or pay
    everything out; limited by what the corporation can pay. Floats or arrays. (Whatever is left
    at the end of the plan is valued as a wind-up dividend in the estate.)"""
    g = 1 + plan.ne_gross_up
    if plan.dividend_policy == 'all':
        want1 = dmax / 2 if ok1 and ok2 else (dmax if ok1 else 0.0 * dmax)
        want2 = dmax - want1 if ok2 else 0.0 * dmax
    else:
        target = plan.dividend_target * (1 + plan.inflation) ** (year - plan.current_year)
        want1 = np.maximum(0.0, (target - base1) / g) if ok1 else 0.0 * dmax
        want2 = np.maximum(0.0, (target - base2) / g) if ok2 else 0.0 * dmax
    tot = want1 + want2
    scale = np.where(tot > dmax, np.divide(dmax, tot, out=np.zeros_like(np.asarray(tot, dtype=float)),
                                           where=np.asarray(tot) > 0), 1.0)
    return want1 * scale, want2 * scale


def rrif_factor(plan: Plan, age: int) -> float:
    key = max((k for k in plan.rrif_factors if k <= age), default=0)
    return plan.rrif_factors[key]


def income_tax(income: float, thresholds: list, cum: list, rates: list, bpa: float,
               extra_credit: float = 0.0, credit_dollars: float = 0.0) -> float:
    """Excel BF: bracket tax less (BPA + additional personal amounts) at the lowest rate, less any
    dollar credits (the dividend tax credit). Non-refundable: never below zero."""
    if income < thresholds[0]:
        return 0.0
    i = max(j for j, t in enumerate(thresholds) if t <= income)
    return max((income - thresholds[i]) * rates[i] + cum[i] - (bpa + extra_credit) * rates[0]
               - credit_dollars, 0.0)


def project(plan: Plan, sale: tuple[dict, float] | None = None, start: Start | None = None,
            returns=None) -> tuple[pd.DataFrame, Start]:
    """returns: optional per-year investment returns from start_year (Monte Carlo);
    None = the plan's fixed return_rate every year."""
    plan.sync_end_year()
    st = start or starting_position(plan, sale)
    p1, p2 = plan.person('P1'), plan.person('P2')
    infl = plan.inflation
    dy = {'P1': plan.death_year('P1'), 'P2': plan.death_year('P2')}
    work, extra_years = consulting_schedule(plan)
    nil = {'W': 0.0, 'cpp': 0.0, 'ded': 0.0, 'credit': 0.0, 'rrsp': 0.0}
    has_corp = plan.corp_balance > 0 or any(c.via_corp for c in plan.consulting)
    gu, dtc = 1 + plan.ne_gross_up, plan.ne_dtc_rate * (1 + plan.ne_gross_up)
    split = plan.income_splitting
    rates, top = plan.tax_rates, plan.tax_rates[-1]
    k = (1 + infl) ** (plan.start_year - plan.current_year) if plan.index_brackets_to_start else 1.0
    thr = [t * k for t in plan.tax_thresholds]
    bpa = plan.bpa * k
    rrif_start1 = plan.start_year
    rrif_start2 = max(plan.start_year, p2.birth_year + p2.rrif_min_age)
    strategy = plan.withdrawal_strategy
    min_age = plan.rrif_conversion_age + 1 if strategy in ('defer', 'bracket') else 0
    accurate = plan.accurate_extra_tax

    def planned_draw(person, year, bal_growth, factor, other_income):
        """Registered withdrawal planned for the year (before any extra to cover a shortfall)."""
        age = year - person.birth_year
        minimum = factor * (bal_growth[0]) if age >= min_age else 0.0
        if strategy == 'bracket' and age <= plan.fill_until_age:
            target = plan.bracket_target * (1 + infl) ** (year - plan.current_year)
            fill = min(sum(bal_growth), max(0.0, target - other_income))
            return max(minimum, fill)
        return minimum

    def tfsa_room(year):
        """TFSA dollar limit, indexed to inflation in $500 steps (CRA rule)."""
        return max(plan.tfsa_limit, 500 * round(plan.tfsa_limit * (1 + infl) ** (year - plan.current_year) / 500))

    def cpp(p, year):
        age, s = year - p.birth_year, max(60, min(70, p.cpp_start_age))
        if age < s:
            return 0.0
        adj = 1 - 0.072 * (65 - s) if s < 65 else 1 + 0.084 * (s - 65)
        contrib = cpp_contrib(p)
        return p.cpp_monthly_at_65 * 12 * (1 + plan.cpp_inflation) ** (year - (p.birth_year + 65)) * adj * contrib

    def cpp_contrib(p):
        """Contributory factor: years from 18 to retirement plus consulting years (pro rata to
        the YMPE) before 65, over the full-benefit years."""
        if not plan.cpp_proportional:
            return 1.0
        yrs = max(0, plan.start_year - (p.birth_year + 18)) + extra_years[p.key]
        return min(1.0, yrs / plan.cpp_full_years)

    def with_survivor_cpp(survivor, deceased, year, own):
        """Survivor's own CPP plus the CPP survivor's pension, capped at the maximum retirement
        pension: 60% of the deceased's pension at 65 (37.5% if the survivor is under 65; the
        small flat-rate part is ignored)."""
        contrib = cpp_contrib(deceased)
        dec65 = deceased.cpp_monthly_at_65 * 12 * (1 + plan.cpp_inflation) ** (year - (deceased.birth_year + 65)) * contrib
        rate = plan.cpp_survivor_rate if year - survivor.birth_year >= 65 else plan.cpp_survivor_rate_under65
        cap = plan.cpp_max_monthly_2026 * 12 * (1 + plan.cpp_inflation) ** (year - 2026)
        return max(own, min(own + rate * dec65, cap))

    def oas(p, year, prev_income):
        age, s = year - p.birth_year, max(65, min(70, p.oas_start_age))
        thr_y = plan.oas_threshold * (1 + infl) ** (year - 1 - plan.oas_base_year)
        if age < s or year > dy[p.key]:
            return 0.0, 0.0, thr_y
        gross = (plan.oas_max_monthly * 12 * (1 + infl) ** (year - plan.oas_base_year)
                 * (1 + plan.oas_uplift_75 if age >= 75 else 1) * (1 + 0.072 * (s - 65)))
        claw = min(plan.oas_clawback_rate * max(prev_income - thr_y, 0), gross) if gross > 0 else 0.0
        return gross, claw, thr_y

    rows = []
    prev = None
    for year in range(plan.start_year, plan.end_year + 1):
        r = {'A': year, 'age_P1': year - p1.birth_year, 'age_P2': year - p2.birth_year}
        if year > plan.start_year:
            thr = [t * (1 + infl) for t in thr]
            bpa *= 1 + infl
        cum = [0.0]
        for j in range(1, len(thr)):
            cum.append(cum[-1] + (thr[j] - thr[j - 1]) * rates[j - 1])
        ret = plan.return_rate if returns is None else float(returns[year - plan.start_year])
        gogo = year - plan.start_year < plan.gogo_years
        alive1, alive2 = year <= dy['P1'], year <= dy['P2']
        r['alive_P1'], r['alive_P2'] = alive1, alive2
        r['B'] = ((st.expense_gogo if gogo else st.expense_later) * (1 + infl) ** (year - plan.start_year)
                  * (1.0 if alive1 and alive2 else plan.survivor_spending))
        if prev is None:
            F, I, S, V, BU, BX = st.nonreg_p1, st.reg_p1, st.nonreg_p2, st.reg_p2, st.tfsa_p1, st.tfsa_p2
            CB0, R0, ptinv = corp_start_balance(plan), 0.0, 0.0
        else:
            CB0, R0, ptinv = prev['CORP_END'], prev['RDTOH'], prev['CORP_TINV']
            p = prev
            F = max(p['F'] - p['H'], 0)
            I = max(p['I'] + p['J'] - p['BD'] - p['BE'] - (p['BG'] if p['F'] + p['G'] - p['BB'] - p['BG'] < 0 else 0)
                    + p['K'], 0)
            S = max(p['S'] - p['U'], 0)
            V = max(p['V'] + p['W'] - p['BH'] - p['BI'] - (p['BK'] if p['S'] + p['T'] - p['BC'] - p['BK'] < 0 else 0)
                    + p['X'], 0)
            BU = max(p['BU'] + p['BV'] - p['BW'] + p['T_P1'], 0)
            BX = max(p['BX'] + p['BY'] - p['BZ'] + p['T_P2'], 0)
        # first death: everything rolls over to the survivor tax-free (spousal rollover,
        # TFSA successor holder); the deceased's columns stay at zero from then on
        if not alive1:
            F, I, BU, S, V, BX = 0.0, 0.0, 0.0, S + F, V + I, BX + BU
        if not alive2:
            S, V, BX, F, I, BU = 0.0, 0.0, 0.0, F + S, I + V, BU + BX
        G, J, T, W, BV, BY = F * ret, I * ret, S * ret, V * ret, BU * ret, BX * ret
        Lf = rrif_factor(plan, year - p1.birth_year) if year >= rrif_start1 else 0.0
        Yf = rrif_factor(plan, year - p2.birth_year) if year >= rrif_start2 else 0.0
        # CPP + OAS (clawback on previous year's taxable income)
        CC = cpp(p1, year) if alive1 else 0.0
        CJ = cpp(p2, year) if alive2 else 0.0
        if alive1 and not alive2:
            CC = with_survivor_cpp(p1, p2, year, CC)
        if alive2 and not alive1:
            CJ = with_survivor_cpp(p2, p1, year, CJ)
        CD, CF, CE = oas(p1, year, prev['Qc'] if prev else 0.0)
        CK, CM, CL = oas(p2, year, prev['ADc'] if prev else 0.0)
        # consulting: income in N/AA ("other income"), RRSP contributions K/X, deduction for
        # half the CPP O/AB, credit for the other half P/AC (the spreadsheet's own columns)
        w1, w2 = work.get(year, {}).get('P1', nil), work.get(year, {}).get('P2', nil)
        W_P1, W_P2 = w1['W'], w2['W']
        K, X, O, AB, P, AC = w1['rrsp'], w2['rrsp'], w1['ded'], w2['ded'], w1['credit'], w2['credit']
        N, AA = CC + CD - CF + W_P1, CJ + CK - CM + W_P2
        if strategy == 'minimums':
            BD, BH = Lf * I, Yf * V
        else:
            BD = (planned_draw(p1, year, (I, J), Lf, G * p1.taxable_share + N - K - O)
                  if year >= rrif_start1 else 0.0)
            BH = (planned_draw(p2, year, (V, W), Yf, T * p2.taxable_share + AA - X - AB)
                  if year >= rrif_start2 else 0.0)
        # pension income splitting (RRIF), only from 65
        BL, BM = G * p1.taxable_share + N - K - O, T * p2.taxable_share + AA - X - AB
        if year - p1.birth_year >= 65:
            BN = BD / 2 if BL > BM else (BD if BL + BD < BM else (BL + BM + BD) / 2 - BL)
        else:
            BN = BD
        BO = BD - BN
        if year - p2.birth_year >= 65:
            BP = BH / 2 if BM > BL else (BH if BM + BH < BL else (BL + BM + BH) / 2 - BM)
        else:
            BP = BH
        BQ = BH - BP
        both = alive1 and alive2                # income splitting needs a living spouse
        BR, BS = (BN + BQ, BO + BP) if split and both else (BD, BH)
        Q = G * p1.taxable_share + N + BR - K - O
        AD = T * p2.taxable_share + AA + BS - X - AB
        # consulting corporation: corporate tax, then dividends to fill the shareholders' incomes
        D_P1 = D_P2 = cda1 = cda2 = 0.0
        if has_corp:
            cs = corp_step(plan, CB0, R0, ptinv, work.get(year, {}).get('corp', 0.0), ret, p2.taxable_share)
            ok1, ok2 = dividend_shareholders(plan, year, alive1, alive2)
            D_P1, D_P2 = (float(v) for v in plan_dividends(plan, year, cs['dmax'], Q, AD, ok1, ok2))
            cp = corp_pay(plan, cs, D_P1 + D_P2)
            cda1, cda2 = (0.0, float(cs['cda'])) if alive2 else (float(cs['cda']), 0.0)
            Q, AD = Q + gu * D_P1, AD + gu * D_P2
        BF = income_tax(Q, thr, cum, rates, bpa, P, dtc * D_P1) if alive1 else 0.0
        BJ = income_tax(AD, thr, cum, rates, bpa, AC, dtc * D_P2) if alive2 else 0.0
        # withdrawals (consulting cash also pays the CPP contributions and RRSP contributions;
        # dividends and capital dividends from the corporation are cash in)
        BA = (r['B'] + BF + BJ - N - G - AA - T - BD - BH
              + w1['cpp'] + w2['cpp'] + K + X - D_P1 - D_P2 - cda1 - cda2)
        T_P1 = T_P2 = 0.0
        if BA < 0 and plan.tfsa_topup:          # surplus: fill TFSA room first, rest to non-registered
            room, spare = tfsa_room(year), -BA
            room1, room2 = (room if alive1 else 0.0), (room if alive2 else 0.0)
            T_P1 = min(room1, spare / 2)
            T_P2 = min(room2, spare - T_P1)
            T_P1 = min(room1, spare - T_P2)
        BAr = BA + T_P1 + T_P2                  # surplus left for non-registered (<= 0)
        if BA > 0:
            BB = F / (F + S) * BA if F + S > BA else 0.0
            BC = S / (F + S) * BA if F + S > BA else 0.0
        elif not both:                          # surplus goes to the survivor
            BB, BC = (BAr, 0.0) if alive1 else (0.0, BAr)
        else:
            tot = F + I + S + V
            BB = (S + V) / tot * BAr if S + V > 0 else BAr
            BC = (F + I) / tot * BAr if S + V > 0 else 0.0
        rem = BAr - BB - BC
        if rem > 0.01 and BU + BX > 0:
            BW = min(BU / (BU + BX) * rem, BU + BV)
            BZ = min(BX / (BU + BX) * rem, BX + BY)
        else:
            BW = BZ = 0.0
        rem2 = BAr - BB - BC - BW - BZ
        BE = I / (I + V) * rem2 if I > 0 and rem2 > 0 else 0.0
        BI = V / (I + V) * rem2 if V > 0 and rem2 > 0 else 0.0
        if accurate:   # incremental tax at each person's own brackets
            BG = income_tax(Q + BE, thr, cum, rates, bpa, P, dtc * D_P1) - BF if BE else 0.0
            BK = income_tax(AD + BI, thr, cum, rates, bpa, AC, dtc * D_P2) - BJ if BI else 0.0
        else:
            BG, BK = BE * top, BI * top
        H = BB + (BG if F + G - BB - BG > 0 else 0)
        U = BC + (BK if S + T - BC - BK > 0 else 0)
        C = F + I + S + V + BU + BX + CB0
        if has_corp:
            corp_row = dict(CORP=CB0, CORP_END=float(cp['CB']), RDTOH=float(cp['R']), CORP_TINV=float(cs['tinv']),
                            CORP_ACTIVE=work.get(year, {}).get('corp', 0.0), CORP_TAX=float(cs['atax'] + cs['ptax']),
                            CORP_REFUND=float(cp['refund']), D_P1=D_P1, D_P2=D_P2, CDA=cda1 + cda2)
        else:
            corp_row = dict(CORP=0.0, CORP_END=0.0, RDTOH=0.0, CORP_TINV=0.0, CORP_ACTIVE=0.0, CORP_TAX=0.0,
                            CORP_REFUND=0.0, D_P1=0.0, D_P2=0.0, CDA=0.0)
        r.update(corp_row)
        r.update(dict(
            C=C, D=(r['B'] / C if C > 0 else float('inf')),
            E=((G + J + T + W + BV + BY) / C if C > 0 else 0.0),
            F=F, G=G, H=H, I=I, J=J, L=Lf, M=BD + BE + BG, N=N, Q=Q, R=BF + BG,
            S=S, T=T, U=U, V=V, W=W, Y=Yf, Z=BH + BI + BK, AA=AA, AD=AD, AE=BJ + BK,
            BA=BA, BB=BB, BC=BC, BD=BD, BE=BE, BF=BF, BG=BG, BH=BH, BI=BI, BJ=BJ, BK=BK,
            BL=BL, BM=BM, BN=BN, BO=BO, BP=BP, BQ=BQ, BR=BR, BS=BS,
            BU=BU, BV=BV, BW=BW, BX=BX, BY=BY, BZ=BZ, T_P1=T_P1, T_P2=T_P2,
            K=K, X=X, O=O, AB=AB, P=P, AC=AC, W_P1=W_P1, W_P2=W_P2, CPP_P1=w1['cpp'], CPP_P2=w2['cpp'],
            Qc=Q + BE if accurate else Q, ADc=AD + BI if accurate else AD,
            CC=CC, CD=CD, CE=CE, CF=CF, CG=CD - CF, CJ=CJ, CK=CK, CL=CL, CM=CM, CN=CK - CM,
            AG=bpa, **{f'thr{j}': t for j, t in enumerate(thr)}))
        rows.append(r)
        prev = r
    return pd.DataFrame(rows).set_index('A', drop=False), st


def estate_after_tax(plan: Plan, row) -> float:
    """Rough after-tax value at the end year: registered balances are fully taxable on the
    second death (taken at the top rate), non-registered and TFSA pass as-is (the model
    already taxes non-registered returns every year)."""
    reg = row['I'] + row['V']
    corp = float(corp_after_tax(plan, row['CORP'], row['RDTOH'])) if 'CORP' in row and row['CORP'] else 0.0
    return float(row['F'] + row['S'] + row['BU'] + row['BX'] + reg * (1 - plan.tax_rates[-1]) + corp)


def summary(plan: Plan, df: pd.DataFrame, st: Start) -> dict:
    end = df[df['A'] <= plan.end_year]
    at = lambda y: float(df.loc[y, 'C']) if y in df.index else None
    worst = end['D'].idxmax()
    depleted = end.index[end['C'] <= 0]
    return {
        'Retirement year': plan.start_year,
        'Capital at retirement': float(df['C'].iloc[0]),
        'First-year expenses': float(df['B'].iloc[0]),
        'First-year expense / capital': float(df['D'].iloc[0]),
        'Property surplus': st.waterfall.surplus,
        'Shortfall funded by Person 1': st.shortfall_from_p1,
        'Capital 2050': at(2050), 'Capital 2065': at(2065),
        f'Capital {plan.end_year}': at(plan.end_year),
        'Worst expense / capital': float(end['D'].max()), 'Worst year': int(worst),
        'Capital depleted in': int(depleted[0]) if len(depleted) else None,
        'Estate after tax': estate_after_tax(plan, end.iloc[-1]),
        'First death': (min(plan.death_year('P1'), plan.death_year('P2')) if plan.use_death_ages else None),
        'Second death': (plan.second_death_year() if plan.use_death_ages else None),
        'Lifetime income tax': float((end['R'] + end['AE']).sum()),
        'Lifetime CPP + OAS': float((end['N'] + end['AA']).sum()),
        'Lifetime OAS clawback': float((end['CF'] + end['CM']).sum()),
    }


def run(plan: Plan, sale=None):
    df, st = project(plan, sale)
    return df, st, summary(plan, df, st)
