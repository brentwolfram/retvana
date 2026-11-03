"""Excel export of a scenario for sharing: values only (not a live model), formatted,
with native Excel charts."""
from __future__ import annotations

import datetime
import io

import numpy as np
import pandas as pd

from .config import Plan
from .engine import column_label

MONEY = '$#,##0;[Red]-$#,##0'
PCT = '0.0%'

CASHFLOW_COLS = ['A', 'age_P1', 'age_P2', 'B', 'C', 'D', 'F', 'I', 'BU', 'S', 'V', 'BX',
                 'N', 'AA', 'W_P1', 'W_P2', 'CPP_P1', 'CPP_P2', 'K', 'X',
                 'CORP', 'CORP_ACTIVE', 'CORP_TAX', 'D_P1', 'D_P2', 'CDA', 'RDTOH',
                 'BD', 'BH', 'BB', 'BC', 'BW', 'BZ', 'T_P1', 'T_P2', 'BE', 'BI', 'Q', 'AD', 'R', 'AE',
                 'CF', 'CM']


def cashflow_table(df: pd.DataFrame, end_year: int, plan: Plan | None = None) -> pd.DataFrame:
    """The cash flow columns up to end_year, headed by column_label (the plan's person names
    in place of "Person 1" / "Person 2" when a plan is given)."""
    t = df[df['A'] <= end_year][CASHFLOW_COLS]
    t = t.rename(columns={k: column_label(k, plan) for k in CASHFLOW_COLS})
    return t.reset_index(drop=True)


def _fmt_for(name: str) -> str | None:
    n = name.lower()
    if n in ('year', 'retirement year', 'worst year', 'capital depleted in', 'purchase year') \
            or n.endswith(' age'):
        return '0'
    if '/' in n or '%' in n or 'chance' in n or 'rate' in n or 'share' in n:
        return PCT
    return MONEY


def _write_table(wb, ws, df: pd.DataFrame, row: int, col: int = 0, title: str | None = None):
    hdr = wb.add_format({'bold': True, 'bg_color': '#1F3A5F', 'font_color': 'white',
                         'text_wrap': True, 'valign': 'top', 'border': 1})
    ttl = wb.add_format({'bold': True, 'font_size': 12, 'font_color': '#1F3A5F'})
    fmts = {}
    if title:
        ws.write(row, col, title, ttl)
        row += 1
    for j, name in enumerate(df.columns):
        ws.write(row, col + j, name, hdr)
        f = _fmt_for(str(name))
        fmts[j] = wb.add_format({'num_format': f}) if f else None
    for i, rec in enumerate(df.itertuples(index=False), start=1):
        for j, v in enumerate(rec):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                ws.write_blank(row + i, col + j, None)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                ws.write_number(row + i, col + j, float(v) if v != float('inf') else 9.99, fmts[j])
            else:
                ws.write(row + i, col + j, str(v))
    return row + len(df) + 2


def _kv_table(wb, ws, pairs: list[tuple[str, object]], row: int, col: int, title: str):
    ttl = wb.add_format({'bold': True, 'font_size': 12, 'font_color': '#1F3A5F'})
    lab = wb.add_format({'bold': True})
    ws.write(row, col, title, ttl)
    for i, (k, v) in enumerate(pairs, start=1):
        ws.write(row + i, col, k, lab)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            ws.write_number(row + i, col + 1, v, wb.add_format({'num_format': _fmt_for(k) or MONEY}))
        else:
            ws.write(row + i, col + 1, '' if v is None else str(v))
    return row + len(pairs) + 2


def to_excel(plan: Plan, df: pd.DataFrame, start, summ: dict, compare: pd.DataFrame | None = None,
             property_table: pd.DataFrame | None = None, scenario_name: str = 'Scenario',
             market: dict | None = None, strategies: pd.DataFrame | None = None,
             spending: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as xw:
        wb = xw.book
        title = wb.add_format({'bold': True, 'font_size': 16, 'font_color': '#1F3A5F'})
        note = wb.add_format({'italic': True, 'font_color': '#666666'})

        # ---- Summary
        ws = wb.add_worksheet('Summary')
        ws.set_column(0, 0, 38)
        ws.set_column(1, 1, 18)
        ws.set_column(3, 3, 40)
        ws.set_column(4, 4, 18)
        ws.write(0, 0, f'retvana retirement model - {scenario_name}', title)
        ws.write(1, 0, f'Exported {datetime.date.today():%B %d, %Y}. Values only; '
                       f'the live model is the retvana app.', note)
        mode = ('Recovery model (per property type)' if plan.property_mode == 'recovery'
                else f'Simple scenario: {plan.legacy_scenario}')
        p1, p2 = plan.person('P1'), plan.person('P2')
        inputs = [('Retirement year', plan.start_year), ('Projection end year', plan.end_year),
                  ('Investment return', plan.return_rate), ('Inflation', plan.inflation),
                  ('Go-go years', plan.gogo_years), ('Property model', mode),
                  ('Townhouse price today', plan.townhouse.price_today),
                  ('Income splitting', 'yes' if plan.income_splitting else 'no'),
                  (f'{p1.name} CPP / OAS start age', f'{p1.cpp_start_age} / {p1.oas_start_age}'),
                  (f'{p2.name} CPP / OAS start age', f'{p2.cpp_start_age} / {p2.oas_start_age}')]
        wd = {'minimums': 'RRIF minimums from retirement', 'defer': 'Defer RRSPs to 71, draw as needed',
              'bracket': f'Fill to ${plan.bracket_target:,.0f} (today\'s $) until {plan.fill_until_age}'}
        if plan.use_death_ages:
            inputs += [(f'{p1.name} planned to age', f'{p1.death_age} ({plan.death_year("P1")})'),
                       (f'{p2.name} planned to age', f'{p2.death_age} ({plan.death_year("P2")})'),
                       ('Survivor spending share %', plan.survivor_spending)]
        else:
            inputs += [('Life expectancy', f'off (both alive to {plan.end_year})')]
        inputs += [('Withdrawal strategy', wd[plan.withdrawal_strategy]),
                   ('Top up TFSAs with surplus', 'yes' if plan.tfsa_topup else 'no'),
                   ('Extra withdrawals taxed at', 'actual marginal rate' if plan.accurate_extra_tax else 'top rate')]
        if market:
            inputs += [('Market risk', 'on'), ('Portfolio volatility rate', plan.return_vol),
                       ('First-year stress test rate', plan.first_year_shock)]
        else:
            inputs += [('Market risk', f'off (fixed {plan.return_rate:.2%} return)')]
        r = _kv_table(wb, ws, inputs, 3, 0, 'Key inputs')
        res = [(column_label(k, plan), v) for k, v in summ.items() if k != 'Retirement year']
        if market:
            o = market['outcome']
            e = o.end_capital(plan.end_year)
            s1 = float(o.expenses[0])
            res += [('Chance the money lasts (markets) %', o.success_rate),
                    (f'Capital {plan.end_year} P10 (markets)', float(np.percentile(e, 10))),
                    (f'Capital {plan.end_year} P50 (markets)', float(np.percentile(e, 50))),
                    ('First-year spending with 90% success', s1 * market['safe90']),
                    ('First-year spending with 75% success', s1 * market['safe75'])]
        if spending and spending.get('feasible'):
            o = spending['outcome']
            res += [("Estate target after tax (today's $)", plan.spend_target_estate),
                    ('Spending solver adjusts', 'all spending' if plan.spend_mode == 'all' else 'discretionary only'),
                    ("Sustainable first-year spending (today's $)", o['first_year_today']),
                    ('Sustainable vs planned spending %', spending['scale'] - 1)]
            if spending.get('success_rate') is not None:
                res += [('Spending solver confidence (markets) %', spending['success_rate'])]
        rr = _kv_table(wb, ws, res, 3, 3, 'Results')
        r = max(r, rr)
        wfp = [(k, v) for k, v in start.waterfall.rows()]
        r = _kv_table(wb, ws, wfp, max(r, 22), 0, f'Property sale and purchase ({plan.start_year})')

        # ---- Cash flow
        cf = cashflow_table(df, plan.end_year, plan)
        wsc = wb.add_worksheet('Cash flow')
        _write_table(wb, wsc, cf, 0)
        wsc.set_column(0, 2, 8)
        wsc.set_column(3, len(cf.columns), 14)
        wsc.freeze_panes(1, 1)
        chart = wb.add_chart({'type': 'line'})
        n = len(cf)
        for name in ('Total capital', 'Expenses'):
            j = list(cf.columns).index(name)
            chart.add_series({'name': name, 'categories': ['Cash flow', 1, 0, n, 0],
                              'values': ['Cash flow', 1, j, n, j]})
        chart.set_title({'name': 'Total capital and expenses'})
        chart.set_y_axis({'num_format': '$#,##0,,"M"'})
        chart.set_size({'width': 760, 'height': 360})
        ws.insert_chart(r, 0, chart)

        # ---- Market risk
        if market:
            o = market['outcome']
            bands = o.bands()
            dep = o.depleted_year
            bands['Chance run out by year %'] = [float(((dep > 0) & (dep <= y)).mean()) for y in o.years]
            wsm = wb.add_worksheet('Market risk')
            wsm.set_column(0, len(bands.columns), 15)
            wsm.write(0, 0, f'Total capital across {len(dep):,} market histories (percentiles), '
                            f'{plan.return_vol:.0%} volatility', title)
            _write_table(wb, wsm, bands, 2)
            wsm.freeze_panes(3, 1)
            ch = wb.add_chart({'type': 'line'})
            n = len(bands)
            for name in ('P10', 'P50', 'P90'):
                j = list(bands.columns).index(name)
                ch.add_series({'name': name, 'categories': ['Market risk', 3, 0, 2 + n, 0],
                               'values': ['Market risk', 3, j, 2 + n, j]})
            ch.set_title({'name': 'Total capital: P10 / median / P90'})
            ch.set_y_axis({'num_format': '$#,##0,,"M"'})
            ch.set_size({'width': 760, 'height': 360})
            wsm.insert_chart(2, len(bands.columns) + 1, ch)

        # ---- Withdrawal strategies
        if strategies is not None and len(strategies):
            wsw = wb.add_worksheet('Withdrawals')
            wsw.set_column(0, 0, 44)
            wsw.set_column(1, len(strategies.columns), 17)
            _write_table(wb, wsw, strategies, 0, title='Withdrawal strategies compared '
                                                       '(estate: registered left is taxed at the top rate)')

        # ---- Compare years
        if compare is not None and len(compare):
            wsg = wb.add_worksheet('Compare years')
            wsg.set_column(0, len(compare.columns), 16)
            _write_table(wb, wsg, compare, 0, title='Retirement year comparison')
            wsg.freeze_panes(2, 1)

        # ---- Property
        wsp = wb.add_worksheet('Property')
        wsp.set_column(0, 0, 30)
        wsp.set_column(1, 12, 16)
        rr = 0
        if property_table is not None:
            rr = _write_table(wb, wsp, property_table, rr, title='Properties')
        props = pd.DataFrame([{'Property': p.name, 'Segment': plan.segment(p.segment).label,
                               'Value today': p.value_today, '2022 peak': p.peak_value,
                               'Purchase price': p.purchase_price, 'Purchase year': p.purchase_year,
                               'Principal residence': 'yes' if p.principal_residence else 'no',
                               'Description': p.description} for p in plan.properties])
        rr = _write_table(wb, wsp, props, rr, title='Property details')
        segs = pd.DataFrame([{'Segment': s.label, 'Recovery target (share of peak)': s.recovery_target,
                              'Recovery speed (share of gap / yr)': s.recovery_speed,
                              'Long-run growth rate': s.long_run_growth, 'Market beta': s.beta,
                              'Property volatility rate': s.idio_vol, 'Sale discount rate': s.sale_discount,
                              'Rationale': s.rationale} for s in plan.segments])
        _write_table(wb, wsp, segs, rr, title='Recovery model parameters')

        # ---- Inputs
        wsi = wb.add_worksheet('Inputs')
        wsi.set_column(0, 0, 40)
        wsi.set_column(1, 6, 16)
        acc = pd.DataFrame([{'Account': a.name, 'Owner': plan.person(a.owner).name, 'Type': a.kind,
                             f'Balance {plan.current_year}': a.balance, 'Growth rate': a.return_rate,
                             'Yearly contribution': plan.tfsa_limit if a.contribution_is_tfsa_limit else a.contribution,
                             f'Value at {plan.start_year}': start.account_fv[a.name]}
                            for a in plan.accounts])
        rr = _write_table(wb, wsi, acc, 0, title='Registered and TFSA accounts')
        exp = pd.DataFrame([{'Expense': e.name, 'Monthly (go-go)': e.monthly,
                             'Monthly (later)': e.monthly if e.monthly_later is None else e.monthly_later,
                             'Discretionary': 'yes' if e.discretionary else 'no'} for e in plan.expenses])
        _write_table(wb, wsi, exp, rr, title='Living expenses (today\'s dollars)')
    return buf.getvalue()
