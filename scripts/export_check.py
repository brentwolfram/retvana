"""Check the Excel export (Requirement 18).
  .venv/bin/python scripts/export_check.py

Builds the to_excel inputs the way app.py does (compute, compute_strategies, compute_spending),
calling the analysis functions directly, because importing app.py runs the Streamlit page.
Four cases: legacy mode, recovery mode, a strategy table present, and market risk on.
Monte Carlo runs use 200 paths.

- 18.1 sheet names per case, written out by hand from the requirement: Summary, Cash flow,
  Compare years, Property, Inputs, plus Market risk and Withdrawals when they apply.
  Names only: the requirement does not fix the sheet order.
  The Summary sheet carries the "Total capital and expenses" chart, and every series in it
  references the 'Cash flow' sheet. The Market risk sheet carries its own chart.
- 18.2 the Summary holds the life expectancy, withdrawal strategy, market risk and spending
  solver settings and results.
- values only: no formula cells (openpyxl data type 'f' or a string starting with '='), and no
  <f> element in any worksheet XML. Chart series references live in the chart parts, not in
  the worksheets, so they are allowed.
- nonreg-accounts Req 8.1, 8.2, 10.9: the Inputs sheet's A1 is "Investment accounts", its rows are
  exactly the plan's account names, the "Sam non-registered" row is Type nonreg, owner Sam, value
  150,000 at 2032, and no cell reads "Registered and TFSA accounts".
"""
import io
import posixpath
import re
import sys
import zipfile
import numpy as np                                  # noqa: E402
import openpyxl                                     # noqa: E402
import pandas as pd                                 # noqa: E402
from retvana import analysis, export                # noqa: E402
from retvana.config import Plan, example_plan       # noqa: E402

N = 200
ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def fresh_plan() -> Plan:
    """Mirror of app.fresh_plan() (plan_check.py verifies the mirror against app.py)."""
    p = example_plan()
    p.property_mode = 'recovery'
    p.tfsa_topup = True
    p.accurate_extra_tax = True
    p.use_death_ages = True
    p.sync_end_year()
    return p


def build(p: Plan, years: list[int], strategies: bool):
    """The to_excel inputs, built as app.py builds them."""
    bands = None
    if p.property_mode == 'recovery':
        mc = analysis.monte_carlo(p, [p.start_year], N)
        df, st, summ = mc['years'][p.start_year].runs[50]
        bands = analysis.property_bands(p, max(years[-1], p.start_year), N)
    else:
        df, st, summ = analysis.deterministic(p)
    cmp = analysis.compare_years(p, years, N)
    mkt = None
    if p.returns_mc:
        res = analysis.market_monte_carlo(p, sorted(set(years) | {p.start_year}), N)
        mkt = {'outcome': res[p.start_year],
               'safe90': analysis.safe_spending(p, p.start_year, 0.90, N),
               'safe75': analysis.safe_spending(p, p.start_year, 0.75, N)}
        cmp = cmp.merge(analysis.market_compare(p, years, N)[
            ['Retirement year', 'Success rate (markets)', f'Capital {p.end_year} P10 (markets)',
             f'Capital {p.end_year} P50 (markets)']], on='Retirement year')
    sale = (dict(st.waterfall.sale_values), st.waterfall.purchase)
    prop_tbl = None
    if bands:
        t = p.start_year - p.current_year
        prop_tbl = pd.DataFrame([{'Property': n, 'Value today': b['P50'].iloc[0],
                                  f'Median at {p.start_year}': b['P50'].iloc[t]} for n, b in bands.items()])
    wd = None
    if strategies:
        wd, _, _ = analysis.compare_strategies(p, sale, N if p.returns_mc else 0)
        wd = wd.drop(columns=[c for c in wd.columns if c.startswith('Years with')])
    if p.returns_mc:
        sp = analysis.solve_spending(p, p.spend_target_estate, p.spend_mode, sale, p.spend_confidence, N)
    else:
        sp = analysis.solve_spending(p, p.spend_target_estate, p.spend_mode, sale)
    data = export.to_excel(p, df, st, summ, cmp, prop_tbl, 'export check', mkt, wd, sp)
    return data, sp, mkt


def chart_sheets(data: bytes) -> dict:
    """worksheet name -> list of chart XML texts it holds (sheet -> drawing -> chart relationships)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())

    def rels(part):
        rp = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
        if rp not in names:
            return []
        xml = z.read(rp).decode()
        out = []
        for m in re.finditer(r'<Relationship [^>]*>', xml):
            tag = m.group(0)
            typ = re.search(r'Type="([^"]+)"', tag).group(1)
            tgt = re.search(r'Target="([^"]+)"', tag).group(1)
            rid = re.search(r'Id="([^"]+)"', tag).group(1)
            out.append((rid, typ.rsplit('/', 1)[-1],
                        posixpath.normpath(posixpath.join(posixpath.dirname(part), tgt))))
        return out

    wbx = z.read('xl/workbook.xml').decode()
    rid_to_part = {rid: tgt for rid, _, tgt in rels('xl/workbook.xml')}
    out = {}
    for m in re.finditer(r'<sheet [^>]*>', wbx):
        tag = m.group(0)
        name = re.search(r'name="([^"]+)"', tag).group(1).replace('&amp;', '&')
        rid = re.search(r'r:id="([^"]+)"', tag).group(1)
        for _, typ, drawing in rels(rid_to_part[rid]):
            if typ == 'drawing':
                for _, t, chart in rels(drawing):
                    if t == 'chart':
                        out.setdefault(name, []).append(z.read(chart).decode())
    return out


def has_chart(cs: dict, sheet: str, title: str, source: str) -> bool:
    """`sheet` holds a chart titled `title` whose series all reference the `source` sheet."""
    for xml in cs.get(sheet, []):
        refs = re.findall(r'<c:f>([^<]+)</c:f>', xml)
        if title in xml and refs and all(r.startswith(f"'{source}'!") for r in refs):
            return True
    return False


def worksheet_formula_tags(data: bytes) -> int:
    z = zipfile.ZipFile(io.BytesIO(data))
    return sum(len(re.findall(r'<f[ >]', z.read(n).decode()))
               for n in z.namelist() if n.startswith('xl/worksheets/') and n.endswith('.xml'))


def summary_pairs(ws) -> dict:
    """label -> value from the Summary's two key/value tables (columns A:B and D:E)."""
    out = {}
    for row in ws.iter_rows(min_row=4):
        for k, v in ((row[0], row[1]), (row[3], row[4])):
            if isinstance(k.value, str) and k.value:
                out[k.value] = v.value
    return out


BASE = ['Summary', 'Cash flow', 'Compare years', 'Property', 'Inputs']   # Req 18.1, always present

legacy = example_plan()
recovery = fresh_plan()
market = fresh_plan()
market.returns_mc = True
years = [2032, 2033]
cases = [  # tag, plan, strategy table?, expected sheets (by hand from Req 18.1)
    ('legacy', legacy, False, BASE),
    ('recovery', recovery, False, BASE),
    ('legacy + strategy table', example_plan(), True, BASE + ['Withdrawals']),
    ('recovery + market risk + strategy table', market, True, BASE + ['Market risk', 'Withdrawals']),
]

for tag, p, strat, expect in cases:
    data, sp, mkt = build(p, years, strat)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    check(f'{tag}: sheet names', sorted(wb.sheetnames) == sorted(expect),
          f'got {wb.sheetnames}, expected {expect}')
    cs = chart_sheets(data)
    check(f'{tag}: the Summary sheet has the capital and expenses chart (Cash flow data)',
          has_chart(cs, 'Summary', 'Total capital and expenses', 'Cash flow'), f'charts on {sorted(cs)}')
    if mkt:
        check(f'{tag}: the Market risk sheet has a chart', 'Market risk' in cs, f'charts on {sorted(cs)}')

    # values only
    bad = [f'{ws.title}!{c.coordinate}' for ws in wb.worksheets for r in ws.iter_rows() for c in r
           if c.data_type == 'f' or (isinstance(c.value, str) and c.value.startswith('='))]
    check(f'{tag}: no formula cells', not bad, f'{bad[:5]}')
    nf = worksheet_formula_tags(data)
    check(f'{tag}: no <f> elements in the worksheet XML', nf == 0, f'{nf} found')

    # Summary entries (Req 18.2), expected values from the plan settings
    s = summary_pairs(wb['Summary'])
    p1, p2 = p.person('P1'), p.person('P2')
    if p.use_death_ages:
        exp_le = {f'{p1.name} planned to age': f'{p1.death_age} ({p1.birth_year + p1.death_age})',
                  f'{p2.name} planned to age': f'{p2.death_age} ({p2.birth_year + p2.death_age})',
                  'Survivor spending share %': p.survivor_spending}
    else:
        exp_le = {'Life expectancy': f'off (both alive to {p.fixed_end_year})'}
    got_le = {k: s.get(k) for k in exp_le}
    check(f'{tag}: Summary life expectancy entries', got_le == exp_le, f'got {got_le}, expected {exp_le}')

    exp_wd = {'minimums': 'RRIF minimums from retirement'}[p.withdrawal_strategy]
    check(f'{tag}: Summary withdrawal strategy', s.get('Withdrawal strategy') == exp_wd,
          f'{s.get("Withdrawal strategy")!r}')

    if p.returns_mc:
        o = mkt['outcome']
        e = o.end_capital(p.end_year)
        exp_mk = {'Market risk': 'on', 'Portfolio volatility rate': p.return_vol,
                  'First-year stress test rate': p.first_year_shock,
                  'Chance the money lasts (markets) %': o.success_rate,
                  f'Capital {p.end_year} P10 (markets)': float(np.percentile(e, 10)),
                  f'Capital {p.end_year} P50 (markets)': float(np.percentile(e, 50)),
                  'First-year spending with 90% success': float(o.expenses[0]) * mkt['safe90'],
                  'First-year spending with 75% success': float(o.expenses[0]) * mkt['safe75']}
    else:
        exp_mk = {'Market risk': f'off (fixed {p.return_rate * 100:.2f}% return)'}
    got_mk = {k: s.get(k) for k in exp_mk}
    check(f'{tag}: Summary market risk entries',
          all(isinstance(got_mk[k], (int, float)) and np.isclose(got_mk[k], v) if isinstance(v, float)
              else got_mk[k] == v for k, v in exp_mk.items()), f'got {got_mk}')

    check(f'{tag}: spending solver found an answer', sp['feasible'], f'scale {sp["scale"]}')
    exp_sp = {"Estate target after tax (today's $)": p.spend_target_estate,
              'Spending solver adjusts': 'all spending' if p.spend_mode == 'all' else 'discretionary only',
              "Sustainable first-year spending (today's $)": sp['outcome']['first_year_today'],
              'Sustainable vs planned spending %': sp['scale'] - 1}
    if p.returns_mc:
        exp_sp['Spending solver confidence (markets) %'] = sp['success_rate']
    got_sp = {k: s.get(k) for k in exp_sp}
    check(f'{tag}: Summary spending solver entries',
          all(isinstance(got_sp[k], (int, float)) and np.isclose(got_sp[k], v) if isinstance(v, (int, float))
              else got_sp[k] == v for k, v in exp_sp.items()), f'got {got_sp}')
    if not p.returns_mc:
        check(f'{tag}: no market solver confidence without market risk',
              'Spending solver confidence (markets) %' not in s)

    # Inputs sheet accounts table (Req 8.1, 8.2, 10.9): title in A1, header in row 2,
    # one row per account from row 3 until the blank row after the table.
    wsi = wb['Inputs']
    check(f'{tag}: Inputs A1 is "Investment accounts"', wsi['A1'].value == 'Investment accounts',
          f'{wsi["A1"].value!r}')
    hdr = [c.value for c in wsi[2]]
    rows = []
    for r in wsi.iter_rows(min_row=3, values_only=True):
        if r[0] is None:
            break
        rows.append(dict(zip(hdr, r)))
    want_names = [a.name for a in p.accounts]
    got_names = [r['Account'] for r in rows]
    check(f'{tag}: Inputs account rows are exactly the plan accounts', got_names == want_names,
          f'got {got_names}, expected {want_names}')
    # Example_Plan: "Sam non-registered" is $150,000 at 0% growth with no contribution, so its value
    # at retirement (2032) is the balance unchanged.
    check(f'{tag}: retirement year is 2032', p.start_year == 2032, f'{p.start_year}')
    sam = next((r for r in rows if r.get('Account') == 'Sam non-registered'), None)
    got_sam = None if sam is None else (sam.get('Type'), sam.get('Owner'), sam.get('Value at 2032'))
    check(f'{tag}: "Sam non-registered" row is nonreg, owner Sam, 150,000 at 2032',
          got_sam is not None and got_sam[:2] == ('nonreg', 'Sam') and got_sam[2] == 150_000,
          f'got {got_sam}')
    old = [f'{ws.title}!{c.coordinate}' for ws in wb.worksheets for r in ws.iter_rows() for c in r
           if c.value == 'Registered and TFSA accounts']
    check(f'{tag}: no cell reads "Registered and TFSA accounts"', not old, f'{old[:5]}')

print('\nEXPORT CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
