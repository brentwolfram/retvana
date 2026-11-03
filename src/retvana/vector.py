"""Vectorized projection: the engine.project logic run for many paths at once with numpy.

Each path can have its own starting balances (property outcome, pre-retirement growth)
and its own yearly investment returns. engine.project stays the reference (it matches
the original spreadsheet); scripts/vector_check.py proves this module matches engine.project.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Plan
from .engine import (consulting_schedule, corp_pay, corp_start_balance, corp_step, dividend_shareholders,
                     expenses_at_start, plan_dividends, rrif_factor)

KEEP = ('B', 'C', 'F', 'I', 'S', 'V', 'BU', 'BX', 'N', 'AA', 'R', 'AE', 'Q', 'AD', 'BA',
        'BB', 'BC', 'BD', 'BH', 'BE', 'BI', 'BW', 'BZ', 'G', 'T', 'CF', 'CM', 'T_P1', 'T_P2', 'K', 'X',
        'CORP', 'RDTOH', 'D_P1', 'D_P2')


@dataclass
class Starts:
    """Starting balances per path (arrays of length n)."""
    nonreg_p1: np.ndarray
    nonreg_p2: np.ndarray
    reg_p1: np.ndarray
    reg_p2: np.ndarray
    tfsa_p1: np.ndarray
    tfsa_p2: np.ndarray
    corp: np.ndarray | None = None      # None = corp_start_balance (no market variation)


def _div(a, b):
    return np.divide(a, b, out=np.zeros_like(a, dtype=float), where=b != 0)


def project_many(plan: Plan, starts: Starts, returns: np.ndarray, expense_scale: float = 1.0) -> dict:
    """returns: array (n_paths, n_years) of yearly investment returns from start_year.
    Returns {column: array (n_paths, n_years)} for the KEEP columns plus 'years'."""
    plan.sync_end_year()
    p1, p2 = plan.person('P1'), plan.person('P2')
    dy = {'P1': plan.death_year('P1'), 'P2': plan.death_year('P2')}
    work, extra_years = consulting_schedule(plan)
    nil = {'W': 0.0, 'cpp': 0.0, 'ded': 0.0, 'credit': 0.0, 'rrsp': 0.0}
    has_corp = plan.corp_balance > 0 or any(c.via_corp for c in plan.consulting)
    gu, dtc = 1 + plan.ne_gross_up, plan.ne_dtc_rate * (1 + plan.ne_gross_up)
    years = np.arange(plan.start_year, plan.end_year + 1)
    n, ny = returns.shape[0], len(years)
    assert returns.shape[1] >= ny, 'returns must cover every projection year'
    infl, split = plan.inflation, plan.income_splitting
    rates = np.array(plan.tax_rates)
    top = rates[-1]
    k = (1 + infl) ** (plan.start_year - plan.current_year) if plan.index_brackets_to_start else 1.0
    thr = np.array(plan.tax_thresholds, dtype=float) * k
    bpa = plan.bpa * k
    rrif_start2 = max(plan.start_year, p2.birth_year + p2.rrif_min_age)
    gogo_exp, later_exp = expenses_at_start(plan)
    strategy, accurate = plan.withdrawal_strategy, plan.accurate_extra_tax
    min_age = plan.rrif_conversion_age + 1 if strategy in ('defer', 'bracket') else 0

    def planned_draw(person, year, bal, growth, factor, other_income):
        age = year - person.birth_year
        minimum = factor * bal if age >= min_age else np.zeros(n)
        if strategy == 'bracket' and age <= plan.fill_until_age:
            target = plan.bracket_target * (1 + infl) ** (year - plan.current_year)
            fill = np.minimum(bal + growth, np.maximum(0.0, target - other_income))
            return np.maximum(minimum, fill)
        return minimum

    def tfsa_room(year):
        return max(plan.tfsa_limit, 500 * round(plan.tfsa_limit * (1 + infl) ** (year - plan.current_year) / 500))

    def tax(income, thr, cum, bpa, credit=0.0, credit_dollars=0.0):
        idx = np.clip(np.searchsorted(thr, income, side='right') - 1, 0, len(thr) - 1)
        t = (income - thr[idx]) * rates[idx] + cum[idx] - (bpa + credit) * rates[0] - credit_dollars
        return np.where(income < thr[0], 0.0, np.maximum(t, 0.0))

    def cpp(p, year):
        age, s = year - p.birth_year, max(60, min(70, p.cpp_start_age))
        if age < s:
            return 0.0
        adj = 1 - 0.072 * (65 - s) if s < 65 else 1 + 0.084 * (s - 65)
        contrib = cpp_contrib(p)
        return p.cpp_monthly_at_65 * 12 * (1 + plan.cpp_inflation) ** (year - (p.birth_year + 65)) * adj * contrib

    def cpp_contrib(p):
        if not plan.cpp_proportional:
            return 1.0
        return min(1.0, (max(0, plan.start_year - (p.birth_year + 18)) + extra_years[p.key]) / plan.cpp_full_years)

    def with_survivor_cpp(survivor, deceased, year, own):
        contrib = cpp_contrib(deceased)
        dec65 = deceased.cpp_monthly_at_65 * 12 * (1 + plan.cpp_inflation) ** (year - (deceased.birth_year + 65)) * contrib
        rate = plan.cpp_survivor_rate if year - survivor.birth_year >= 65 else plan.cpp_survivor_rate_under65
        cap = plan.cpp_max_monthly_2026 * 12 * (1 + plan.cpp_inflation) ** (year - 2026)
        return max(own, min(own + rate * dec65, cap))

    def oas(p, year, prev_income):
        age, s = year - p.birth_year, max(65, min(70, p.oas_start_age))
        if age < s or year > dy[p.key]:
            return 0.0, np.zeros(n)
        thr_y = plan.oas_threshold * (1 + infl) ** (year - 1 - plan.oas_base_year)
        gross = (plan.oas_max_monthly * 12 * (1 + infl) ** (year - plan.oas_base_year)
                 * (1 + plan.oas_uplift_75 if age >= 75 else 1) * (1 + 0.072 * (s - 65)))
        return gross, np.minimum(plan.oas_clawback_rate * np.maximum(prev_income - thr_y, 0), gross)

    out = {c: np.zeros((n, ny)) for c in KEEP}
    p = None
    for t, year in enumerate(years):
        if t:
            thr = thr * (1 + infl)
            bpa *= 1 + infl
        cum = np.concatenate([[0.0], np.cumsum(np.diff(thr) * rates[:-1])])
        alive1, alive2 = year <= dy['P1'], year <= dy['P2']
        both = alive1 and alive2
        Bexp = ((gogo_exp if t < plan.gogo_years else later_exp) * (1 + infl) ** t * expense_scale
                * (1.0 if both else plan.survivor_spending))
        if p is None:
            F, I, S, V = starts.nonreg_p1.copy(), starts.reg_p1.copy(), starts.nonreg_p2.copy(), starts.reg_p2.copy()
            BU, BX = starts.tfsa_p1.copy(), starts.tfsa_p2.copy()
            Qp = ADp = np.zeros(n)
            CB0 = starts.corp.copy() if starts.corp is not None else np.full(n, corp_start_balance(plan))
            R0, ptinv = np.zeros(n), np.zeros(n)
        else:
            CB0, R0, ptinv = p['CORP_END'], p['RDTOH'], p['CORP_TINV']
            F = np.maximum(p['F'] - p['H'], 0)
            I = np.maximum(p['I'] + p['J'] - p['BD'] - p['BE']
                           - np.where(p['F'] + p['G'] - p['BB'] - p['BG'] < 0, p['BG'], 0) + p['K'], 0)
            S = np.maximum(p['S'] - p['U'], 0)
            V = np.maximum(p['V'] + p['W'] - p['BH'] - p['BI']
                           - np.where(p['S'] + p['T'] - p['BC'] - p['BK'] < 0, p['BK'], 0) + p['X'], 0)
            BU = np.maximum(p['BU'] + p['BV'] - p['BW'] + p['T_P1'], 0)
            BX = np.maximum(p['BX'] + p['BY'] - p['BZ'] + p['T_P2'], 0)
            Qp, ADp = p['Qc'], p['ADc']
        z0 = np.zeros(n)
        if not alive1:
            F, I, BU, S, V, BX = z0, z0, z0, S + F, V + I, BX + BU
        if not alive2:
            S, V, BX, F, I, BU = z0, z0, z0, F + S, I + V, BU + BX
        ret = returns[:, t]
        G, J, T, W, BV, BY = F * ret, I * ret, S * ret, V * ret, BU * ret, BX * ret
        Lf = rrif_factor(plan, year - p1.birth_year) if year >= plan.start_year else 0.0
        Yf = rrif_factor(plan, year - p2.birth_year) if year >= rrif_start2 else 0.0
        CD, CF = oas(p1, year, Qp)
        CK, CM = oas(p2, year, ADp)
        CC = cpp(p1, year) if alive1 else 0.0
        CJ = cpp(p2, year) if alive2 else 0.0
        if alive1 and not alive2:
            CC = with_survivor_cpp(p1, p2, year, CC)
        if alive2 and not alive1:
            CJ = with_survivor_cpp(p2, p1, year, CJ)
        w1, w2 = work.get(int(year), {}).get('P1', nil), work.get(int(year), {}).get('P2', nil)
        K, X, O, AB, P, AC = w1['rrsp'], w2['rrsp'], w1['ded'], w2['ded'], w1['credit'], w2['credit']
        N = CC + CD - CF + w1['W']
        AA = CJ + CK - CM + w2['W']
        if strategy == 'minimums':
            BD, BH = Lf * I, Yf * V
        else:
            BD = planned_draw(p1, year, I, J, Lf, G * p1.taxable_share + N - K - O)
            BH = (planned_draw(p2, year, V, W, Yf, T * p2.taxable_share + AA - X - AB) if year >= rrif_start2
                  else np.zeros(n))
        BL, BM = G * p1.taxable_share + N - K - O, T * p2.taxable_share + AA - X - AB
        if year - p1.birth_year >= 65:
            BN = np.where(BL > BM, BD / 2, np.where(BL + BD < BM, BD, (BL + BM + BD) / 2 - BL))
        else:
            BN = BD
        if year - p2.birth_year >= 65:
            BP = np.where(BM > BL, BH / 2, np.where(BM + BH < BL, BH, (BL + BM + BH) / 2 - BM))
        else:
            BP = BH
        BO, BQ = BD - BN, BH - BP
        BR, BS = (BN + BQ, BO + BP) if split and both else (BD, BH)
        Q = G * p1.taxable_share + N + BR - K - O
        AD = T * p2.taxable_share + AA + BS - X - AB
        D_P1 = D_P2 = CDA = z0
        if has_corp:
            cs = corp_step(plan, CB0, R0, ptinv, work.get(int(year), {}).get('corp', 0.0), ret, p2.taxable_share)
            ok1, ok2 = dividend_shareholders(plan, int(year), alive1, alive2)
            D_P1, D_P2 = plan_dividends(plan, int(year), cs['dmax'], Q, AD, ok1, ok2)
            D_P1, D_P2 = np.broadcast_to(D_P1, (n,)).astype(float), np.broadcast_to(D_P2, (n,)).astype(float)
            cp = corp_pay(plan, cs, D_P1 + D_P2)
            CDA = cs['cda']
            Q, AD = Q + gu * D_P1, AD + gu * D_P2
        BF = tax(Q, thr, cum, bpa, P, dtc * D_P1) if alive1 else z0
        BJ = tax(AD, thr, cum, bpa, AC, dtc * D_P2) if alive2 else z0
        BA = (Bexp + BF + BJ - N - G - AA - T - BD - BH + w1['cpp'] + w2['cpp'] + K + X
              - D_P1 - D_P2 - CDA)
        if plan.tfsa_topup:
            room, spare = tfsa_room(year), np.maximum(-BA, 0)
            room1, room2 = (room if alive1 else 0.0), (room if alive2 else 0.0)
            T_P1 = np.minimum(room1, spare / 2)
            T_P2 = np.minimum(room2, spare - T_P1)
            T_P1 = np.minimum(room1, spare - T_P2)
        else:
            T_P1 = T_P2 = np.zeros(n)
        BAr = BA + T_P1 + T_P2
        pos, FS = BA > 0, F + S
        tot, sv = F + I + S + V, (S + V) > 0
        if both:
            negB, negC = np.where(sv, _div(S + V, tot) * BAr, BAr), np.where(sv, _div(F + I, tot) * BAr, 0)
        else:                       # surplus goes to the survivor
            negB, negC = (BAr, z0) if alive1 else (z0, BAr)
        BB = np.where(pos, np.where(FS > BA, _div(F, FS) * BA, 0), negB)
        BC = np.where(pos, np.where(FS > BA, _div(S, FS) * BA, 0), negC)
        rem, tf = BAr - BB - BC, BU + BX
        c2 = (rem > 0.01) & (tf > 0)
        BW = np.where(c2, np.minimum(_div(BU, tf) * rem, BU + BV), 0)
        BZ = np.where(c2, np.minimum(_div(BX, tf) * rem, BX + BY), 0)
        rem2, IV = BAr - BB - BC - BW - BZ, I + V
        BE = np.where((I > 0) & (rem2 > 0), _div(I, IV) * rem2, 0)
        BI = np.where((V > 0) & (rem2 > 0), _div(V, IV) * rem2, 0)
        if accurate:
            BG = np.where(BE != 0, tax(Q + BE, thr, cum, bpa, P, dtc * D_P1) - BF, 0.0)
            BK = np.where(BI != 0, tax(AD + BI, thr, cum, bpa, AC, dtc * D_P2) - BJ, 0.0)
        else:
            BG, BK = BE * top, BI * top
        H = BB + np.where(F + G - BB - BG > 0, BG, 0)
        U = BC + np.where(S + T - BC - BK > 0, BK, 0)
        C = F + I + S + V + BU + BX + CB0
        if has_corp:
            corp = dict(CORP=CB0, CORP_END=cp['CB'], RDTOH=cp['R'], CORP_TINV=cs['tinv'], D_P1=D_P1, D_P2=D_P2)
        else:
            corp = dict(CORP=z0, CORP_END=z0, RDTOH=z0, CORP_TINV=z0, D_P1=z0, D_P2=z0)
        p = dict(**corp, F=F, G=G, H=H, I=I, J=J, S=S, T=T, U=U, V=V, W=W, BU=BU, BV=BV, BW=BW, BX=BX,
                 BY=BY, BZ=BZ, BB=BB, BC=BC, BD=BD, BE=BE, BG=BG, BH=BH, BI=BI, BK=BK, Q=Q, AD=AD,
                 T_P1=T_P1, T_P2=T_P2, Qc=Q + BE if accurate else Q, ADc=AD + BI if accurate else AD,
                 K=np.full(n, K), X=np.full(n, X))
        row = dict(p, B=np.full(n, Bexp), C=C, N=N, AA=AA, R=BF + BG, AE=BJ + BK, BA=BA,
                   CF=np.broadcast_to(CF, (n,)), CM=np.broadcast_to(CM, (n,)))
        for c in KEEP:
            out[c][:, t] = row[c]
    out['years'] = years
    return out
