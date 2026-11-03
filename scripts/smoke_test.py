"""Headless smoke test of the Streamlit app and the Excel export.

  .venv/bin/python scripts/smoke_test.py

Names, the retirement year and the end year the app shows are read from the example plan.
RETVANA_DATA_DIR points at a fresh temporary directory for every App run, so the test never
reads or writes the real Data_Dir.
"""
import io
import os
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
os.chdir(ROOT)

TMP = tempfile.TemporaryDirectory(prefix='retvana-smoke-')
_n = 0


def temp_data_dir() -> Path:
    """A new, empty, not yet created Data_Dir under TMP, set as RETVANA_DATA_DIR."""
    global _n
    _n += 1
    d = Path(TMP.name) / f'data{_n}'
    os.environ['RETVANA_DATA_DIR'] = str(d)
    return d


temp_data_dir()                                   # before the App or plan_io is first used

import openpyxl                                   # noqa: E402
from streamlit.testing.v1 import AppTest          # noqa: E402

from retvana import analysis, export              # noqa: E402
from retvana.config import example_plan           # noqa: E402


def check(at, label):
    errs = [e.value for e in at.exception]
    assert not errs, f'{label}: {errs}'
    metrics = {m.label: m.value for m in at.metric}
    print(f'{label:<34} ok  ' + ' | '.join(f'{k}: {v}' for k, v in list(metrics.items())[:4]))
    return metrics


EX = example_plan()
P1_NAME, P2_NAME = EX.person('P1').name, EX.person('P2').name
EX.use_death_ages = True                          # the app defaults plan to the second death
EX.sync_end_year()
END = EX.end_year

at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120)
at.run()
check(at, f'default (recovery, {EX.start_year})')

at.slider(key='w_start').set_value(2030).run()
m = check(at, 'retirement year -> 2030')
assert at.title[0].value == 'Retiring in 2030'

at.radio(key='w_mode').set_value('Simple scenarios').run()
check(at, 'simple scenarios (Base)')
at.selectbox(key='w_legacy').set_value('Bear').run()
check(at, 'simple scenarios (Bear)')

at.radio(key='w_mode').set_value('Recovery model').run()
at.slider(key='w_studio_tgt').set_value(0.7).run()
check(at, 'studio recovery target 0.70')
at.toggle(key='w_split').set_value(True).run()
check(at, 'income splitting on')
at.number_input(key='w_th_price').set_value(1_300_000).run()
check(at, 'townhouse 1.3M')
at.toggle(key='w_rmc').set_value(True).run()
m = check(at, 'market risk on')
assert any('money lasts' in k for k in m), m
at.slider(key='w_rvol').set_value(15.0).run()
check(at, 'market risk 15% volatility')
at.slider(key='w_shock').set_value(-30).run()
check(at, 'market risk -30% first-year crash')
at.radio(key='w_mode').set_value('Simple scenarios').run()
check(at, 'market risk + simple scenarios')
at.toggle(key='w_rmc').set_value(False).run()
at.radio(key='w_wd_strategy').set_value('Defer RRSPs to 71, draw only as needed').run()
check(at, 'withdrawals: defer to 71')
at.radio(key='w_wd_strategy').set_value('Fill tax brackets to a target income').run()
at.slider(key='w_wd_target').set_value(120_000).run()
at.slider(key='w_wd_until').set_value(67).run()
check(at, 'withdrawals: fill to 120K until 67')
best = [b for b in at.button if b.label == 'Use the best setting']
assert best, 'expected the "Use the best setting" button'
best[0].click().run()
check(at, 'withdrawals: use the best setting')
assert at.radio(key='w_wd_strategy').value == 'Fill tax brackets to a target income'
print('   best applied ->', at.slider(key='w_wd_target').value, 'until', at.slider(key='w_wd_until').value)
at.toggle(key='w_wd_topup').set_value(False).run()
at.toggle(key='w_wd_acctax').set_value(False).run()
check(at, 'withdrawals: spreadsheet rules')
m = check(AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120).run(), 'fresh: death ages on')
assert any(k.startswith('Estate at second death') for k in m), m
at.number_input(key='w_deathP1').set_value(85).run()
at.number_input(key='w_deathP2').set_value(90).run()
m = check(at, 'death ages P1 85 / P2 90')
assert f'Planning to {P1_NAME} 85' in at.caption[0].value, at.caption[0].value
at.slider(key='w_surv_spend').set_value(60).run()
at.toggle(key='w_rmc').set_value(True).run()
check(at, 'survivor 60% + market risk')
at.toggle(key='w_death_on').set_value(False).run()
m = check(at, 'death ages off (fixed end year)')
assert any('2080' in k for k in m), m

# sustainable spending solver
at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120).run()
m = check(at, 'spending: defaults ($1M estate)')
assert any(k.startswith('Sustainable spending') for k in m), m
# $2M, tuned for the example household: with discretionary-only cuts and market risk at 75%
# confidence the solver still finds a feasible spending level (at $3M it does not).
at.slider(key='w_sp_target').set_value(2_000_000).run()
check(at, 'spending: $2M estate')
at.radio(key='w_sp_mode').set_value(
    'Discretionary only (items marked discretionary)').run()
check(at, 'spending: discretionary only')
at.toggle(key='w_rmc').set_value(True).run()
at.slider(key='w_sp_conf').set_value(75).run()
m = check(at, 'spending: market risk 75%')
assert "Estate left, typical market (today's $)" in m, m
btn = [b for b in at.button if b.label == 'Apply to my plan']
assert btn, 'expected "Apply to my plan"'
btn[0].click().run()
m = check(at, 'spending: applied to plan')
assert any('applied' in s.value for s in at.success), [s.value for s in at.success]
assert m["Sustainable spending (today's $)"], m

# consulting income via the Inputs editor
at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120).run()
m0 = check(at, 'consulting: none')
at.session_state['ed_cons'] = {'edited_rows': {}, 'added_rows': [
    {'Who': P2_NAME, 'Description': 'Advisory', "Per year (today's $)": 80000, 'From': 2033,
     'To (last year)': 2040, 'Grows with inflation': True, 'Contribute RRSP room': True}], 'deleted_rows': []}
at.run()
m1 = check(at, 'consulting: Person 2 $80K 2033-2040')
assert m1['Capital at retirement'] == m0['Capital at retirement']
assert m1[f'Capital in {END} (median)'] != m0[f'Capital in {END} (median)'], (m0, m1)
assert any('CPP contributory years' in c.value for c in at.caption), 'expected the consulting summary caption'

# the same contract through the corporation
at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120).run()
at.session_state['ed_cons'] = {'edited_rows': {}, 'added_rows': [
    {'Who': P2_NAME, 'Description': 'Advisory', "Per year (today's $)": 150000, 'From': 2033,
     'To (last year)': 2040, 'Grows with inflation': True, 'Through my corporation': True,
     'Contribute RRSP room': False}], 'deleted_rows': []}
at.run()
m2 = check(at, 'corporation: Person 2 $150K via corp')
assert any('Through the corporation vs personally' in x.value for x in at.markdown), 'expected the comparison'
b = [x for x in at.button if x.label == 'Use best dividend policy']
if b:
    b[0].click().run()
    check(at, 'corporation: best dividend policy applied')
at.radio(key='w_div_policy').set_value('Pay everything out each year').run()
check(at, 'corporation: pay everything out')
at.toggle(key='w_corp_p1').set_value(True).run()
at.toggle(key='w_rmc').set_value(True).run()
check(at, 'corporation: Person 1 shareholder + market risk')

# export
p = example_plan()
p.property_mode = 'recovery'
mc = analysis.monte_carlo(p, [p.start_year], 500)
df, st_, summ = mc['years'][p.start_year].runs[50]
cmp = analysis.compare_years(p, list(range(2029, 2036)), 500)
p.returns_mc = True
mk = {'outcome': analysis.market_monte_carlo(p, [p.start_year], 500)[p.start_year],
      'safe90': analysis.safe_spending(p, p.start_year, 0.9, 500),
      'safe75': analysis.safe_spending(p, p.start_year, 0.75, 500)}
data = export.to_excel(p, df, st_, summ, cmp, None, 'smoke test', mk)
wb = openpyxl.load_workbook(io.BytesIO(data))
assert 'Market risk' in wb.sheetnames
print('excel sheets:', wb.sheetnames, '| cash flow rows:', wb['Cash flow'].max_row,
      '| compare rows:', wb['Compare years'].max_row)
assert wb['Summary']['A1'].value.startswith('retvana retirement model')
# plan file: missing, save, reload, unreadable at start, broken after start, save error
from retvana.config import Plan                   # noqa: E402

d = temp_data_dir()
at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120).run()
check(at, 'plan file: missing -> example plan')
assert not at.warning, [w.value for w in at.warning]
save = at.button(key='save_default')
assert not save.disabled and str(d / 'plan.json') in save.help, save.help
at.slider(key='w_start').set_value(2031).run()
at.button(key='save_default').click().run()
check(at, 'plan file: save as default')
assert not at.error, [e.value for e in at.error]
saved = Plan.from_json((d / 'plan.json').read_text(encoding='utf-8'))
assert saved.start_year == 2031, saved.start_year
assert not (d / 'plan.json.tmp').exists()
at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120).run()
check(at, 'plan file: reload saved plan')
assert at.title[0].value == 'Retiring in 2031', at.title[0].value

d = temp_data_dir()
d.mkdir()
broken = b'{"not": "a plan"'
(d / 'plan.json').write_bytes(broken)
at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120).run()
check(at, 'plan file: unreadable at start')
warn = ' '.join(w.value for w in at.warning)
assert str(d / 'plan.json') in warn and 'JSONDecodeError' in warn, warn
assert at.title[0].value == f'Retiring in {EX.start_year}', at.title[0].value
save = at.button(key='save_default')
assert save.disabled and 'JSONDecodeError' in save.help, (save.disabled, save.help)
assert (d / 'plan.json').read_bytes() == broken

d = temp_data_dir()
at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120).run()
d.mkdir()
(d / 'plan.json').write_bytes(broken)             # the file breaks after the App started
at.button(key='save_default').click().run()
check(at, 'plan file: broken after start')
err = ' '.join(e.value for e in at.error)
assert 'Not saved' in err and str(d / 'plan.json') in err, err
assert (d / 'plan.json').read_bytes() == broken
assert at.run().button(key='save_default').disabled   # stays off on the next rerun

d = temp_data_dir()
at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=120).run()
d.write_text('a file where the Data_Dir should be', encoding='utf-8')
at.button(key='save_default').click().run()
check(at, 'plan file: save error (OSError)')
err = ' '.join(e.value for e in at.error)
assert 'Not saved' in err and 'Error' in err, err

TMP.cleanup()
print('SMOKE TEST PASS')
