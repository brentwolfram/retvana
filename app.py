"""retvana retirement model - Streamlit app (local only).

Run from the repository root:
    .venv/bin/streamlit run app.py
then open http://localhost:8501

Layout rule: every input widget is rendered (and applied to the plan) before the model
runs, and results are drawn into containers created earlier on the page. That keeps
results in step with every edit.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from retvana import analysis, engine, export
from retvana.engine import column_label
from retvana import property_model as pm
from retvana.config import ACCOUNT_KINDS, Account, ConsultingIncome, ExpenseItem, OptionGrant, Plan, example_plan
from retvana.plan_io import PlanFileUnreadable, data_dir, load_saved_plan, save_plan

st.set_page_config(page_title='retvana - Retirement Model', page_icon='🌅', layout='wide')

# ------------------------------------------------------------------ theme (light / dark)
# Follows the OS appearance or the Settings menu choice; Streamlit reruns the script
# when it changes, so charts and custom CSS are re-coloured to match.
DARK = (getattr(st.context.theme, 'type', None) or 'light') == 'dark'
if DARK:
    NAVY, TEAL, GOLD, RED, GREY = '#6FA3E0', '#3CC4B2', '#F2CF6B', '#E8735C', '#8D99AE'
    INK, MUTED, CARD, ACCENT = '#E6EAF0', '#A3AEBD', '#18222F', '#6FA3E0'
    PALETTE = ['#2F5D8F', '#5B8DC9', '#2A9D8F', '#7CC6B5', '#E9C46A', '#F4A261', '#E8735C', '#8D99AE']
    BAND_ALPHA, GRID, PLOT_TEMPLATE = 0.16, 'rgba(255,255,255,0.08)', 'plotly_dark'
else:
    NAVY, TEAL, GOLD, RED, GREY = '#1F3A5F', '#2A9D8F', '#E9C46A', '#C8553D', '#8D99AE'
    INK, MUTED, CARD, ACCENT = '#1B2430', '#4A5568', '#F3F6FA', '#1F3A5F'
    PALETTE = ['#1F3A5F', '#3D6A9E', '#2A9D8F', '#7CC6B5', '#E9C46A', '#F4A261', '#C8553D', '#8D99AE']
    BAND_ALPHA, GRID, PLOT_TEMPLATE = 0.13, 'rgba(0,0,0,0.07)', 'plotly_white'
ASSET_COLORS = {'Property 1': NAVY, 'Property 2': RED, 'Property 3': TEAL, 'Townhouse': GOLD}

st.markdown(f"""
<style>
  .block-container {{padding-top: 2.2rem; padding-bottom: 2rem;}}
  div[data-testid="stMetric"] {{background: {CARD}; border-radius: 10px; padding: 12px 16px;
                               border-left: 4px solid {ACCENT};}}
  div[data-testid="stMetricLabel"] p {{font-size: 0.85rem; color: {MUTED};}}
  h1, h2, h3 {{color: {ACCENT};}}
  .muted {{color: {MUTED};}}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def money(x, short=True) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 'n/a'
    sign = '-' if x < 0 else ''
    a = abs(x)
    if short and a >= 999_500:
        return f'{sign}${a / 1e6:,.2f}M'
    if short and a >= 1e4:
        return f'{sign}${a / 1e3:,.0f}K'
    return f'{sign}${a:,.0f}'


def md(s: str) -> str:
    """Escape $ so Streamlit markdown doesn't render dollar amounts as LaTeX."""
    return s.replace('$', '\\$')


def pct(x) -> str:
    return 'n/a' if x is None else f'{x:.1%}'


def style_table(df: pd.DataFrame):
    fmt = {}
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        n = str(c).lower()
        if n in ('year', 'retirement year', 'worst year') or n.endswith(' age'):
            fmt[c] = '{:.0f}'
        elif '/' in n or 'chance' in n or '%' in n or 'rate' in n:
            fmt[c] = '{:.1%}'
        else:
            fmt[c] = lambda x: f'-${-x:,.0f}' if x < 0 else f'${x:,.0f}'
    return df.style.format(fmt, na_rep='')


def chart_layout(fig, title=None, height=380, yfmt='$,.2s'):
    fig.update_layout(title=title, height=height, margin=dict(l=10, r=10, t=50 if title else 20, b=10),
                      template=PLOT_TEMPLATE, legend=dict(orientation='h', y=-0.18),
                      hovermode='x unified', font=dict(family='Inter, Helvetica, Arial', color=INK),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID)
    fig.update_yaxes(tickformat=yfmt, gridcolor=GRID, zerolinecolor=GRID)
    return fig


def band(fig, x, lo, hi, color, name=None):
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    fig.add_trace(go.Scatter(x=list(x) + list(x)[::-1], y=list(hi) + list(lo)[::-1], fill='toself', mode='lines',
                             fillcolor=f'rgba({rgb[0]},{rgb[1]},{rgb[2]},{BAND_ALPHA})', line=dict(width=0),
                             hoverinfo='skip', name=name, showlegend=name is not None))


def reset_widgets():
    for k in list(st.session_state.keys()):
        if k.startswith(('w_', 'ed_', 'base_')):
            del st.session_state[k]


def load_plan(p: Plan):
    st.session_state.plan = p
    reset_widgets()


def fresh_plan() -> Plan:
    p = example_plan()
    p.property_mode = 'recovery'
    # realism settings the original spreadsheet didn't have (example_plan keeps the model defaults)
    p.tfsa_topup = True
    p.accurate_extra_tax = True
    p.use_death_ages = True            # plan to FP Canada life-expectancy ages, not a fixed 2080
    p.sync_end_year()
    return p


if 'plan' not in st.session_state:
    # the Data_Dir is resolved once per session; plan_io is the only code that touches plan.json
    st.session_state.data_dir = data_dir()
    loaded = load_saved_plan(st.session_state.data_dir)
    st.session_state.plan_path = loaded.path
    st.session_state.plan_error = loaded.error      # set while plan.json cannot be read or parsed
    st.session_state.plan = loaded.plan if loaded.plan is not None else fresh_plan()
if st.session_state.plan_error:
    st.warning(f'Could not read the saved plan {st.session_state.plan_path} '
               f'({st.session_state.plan_error}). Starting from the example plan; the file is left '
               'untouched and "Save as default" is off until it is fixed or removed.')
plan: Plan = st.session_state.plan
p1, p2 = plan.person('P1'), plan.person('P2')

# ================================================================== SIDEBAR INPUTS
with st.sidebar:
    st.markdown('## 🌅 retvana')
    st.caption(f'Retirement model for {p1.name} & {p2.name}')
    plan.start_year = st.slider('Retirement year', 2027, 2040, plan.start_year, key='w_start')
    mode = st.radio('Property values', ['Recovery model', 'Simple scenarios'],
                    index=0 if plan.property_mode == 'recovery' else 1, key='w_mode',
                    help='Recovery model: each property type recovers toward its own fair value, with '
                         'Monte Carlo ranges. Simple scenarios: one growth path for everything (the '
                         'original spreadsheet scenarios).')
    plan.property_mode = 'recovery' if mode == 'Recovery model' else 'legacy'
    if plan.property_mode == 'legacy':
        names = [s.name for s in plan.legacy_scenarios]
        plan.legacy_scenario = st.selectbox('Market scenario', names, names.index(plan.legacy_scenario),
                                            key='w_legacy')
        n_paths = 0
    else:
        n_paths = st.select_slider('Property Monte Carlo paths', [500, 1000, 2000, 5000], 2000, key='w_paths')
    st.markdown('---')
    plan.return_rate = st.slider('Investment return (retirement)', 3.0, 8.0, plan.return_rate * 100, 0.25,
                                 format='%.2f%%', key='w_ret') / 100
    plan.inflation = st.slider('Inflation', 1.0, 4.5, plan.inflation * 100, 0.1, format='%.1f%%',
                               key='w_infl') / 100
    plan.gogo_years = st.slider('Go-go years (higher travel spending)', 0, 30, plan.gogo_years, key='w_gogo')
    plan.income_splitting = st.toggle('Pension income splitting (from 65)', plan.income_splitting,
                                      key='w_split')
    with st.expander('CPP / OAS start ages'):
        c1, c2 = st.columns(2)
        p1.cpp_start_age = c1.slider(f'{p1.name} CPP', 60, 70, p1.cpp_start_age, key='w_cppP1')
        p2.cpp_start_age = c2.slider(f'{p2.name} CPP', 60, 70, p2.cpp_start_age, key='w_cppP2')
        p1.oas_start_age = c1.slider(f'{p1.name} OAS', 65, 70, p1.oas_start_age, key='w_oasP1')
        p2.oas_start_age = c2.slider(f'{p2.name} OAS', 65, 70, p2.oas_start_age, key='w_oasP2')
        plan.cpp_proportional = st.toggle('Reduce CPP for fewer contribution years', plan.cpp_proportional,
                                          key='w_cppprop')
    with st.expander('Life expectancy', expanded=False):
        plan.use_death_ages = st.toggle('Plan to these ages (survivor rules after the first death)',
                                        plan.use_death_ages, key='w_death_on',
                                        help='Off = run both of you to a fixed end year (Inputs tab).')
        c1, c2 = st.columns(2)
        p1.death_age = c1.number_input(f'{p1.name} to age', 70, 110, int(p1.death_age), 1, key='w_deathP1',
                                       disabled=not plan.use_death_ages)
        p2.death_age = c2.number_input(f'{p2.name} to age', 70, 110, int(p2.death_age), 1, key='w_deathP2',
                                       disabled=not plan.use_death_ages)
        plan.survivor_spending = st.slider('Survivor spending (share of the couple\'s)', 50, 100,
                                           int(round(plan.survivor_spending * 100)), 5, format='%d%%',
                                           key='w_surv_spend', disabled=not plan.use_death_ages) / 100
        st.caption('Defaults are FP Canada\'s 2026 planning ages: a 25% chance of living longer '
                   '(female 97, male 94).')
    plan.sync_end_year()
    st.markdown('---')
    plan.returns_mc = st.toggle('📈 Market risk (vary yearly returns)', plan.returns_mc, key='w_rmc',
                                help='Runs thousands of market histories around your return assumption, '
                                     'including bad years early in retirement (sequence risk).')
    if plan.returns_mc:
        plan.return_vol = st.slider('Portfolio volatility (yearly)', 4.0, 20.0, plan.return_vol * 100, 0.5,
                                    format='%.1f%%', key='w_rvol',
                                    help='~6% conservative (mostly bonds), ~10% balanced 60/40, ~15% all-equity.') / 100
        plan.first_year_shock = st.slider('Stress test: first-year market move', -40, 0,
                                          int(round(plan.first_year_shock * 100)), 5, format='%d%%',
                                          key='w_shock',
                                          help='Added to every path in the first year of retirement, e.g. -30% '
                                               'for a 2008-style crash right after you retire.') / 100
        plan.mc_pre_retirement = st.toggle('Also vary growth until retirement', plan.mc_pre_retirement,
                                           key='w_mcpre')
    side_out = st.container()          # export / save, filled after the model runs

# ================================================================== PAGE SKELETON
title_box = st.container()
tab_over, tab_prop, tab_cmp, tab_wd, tab_sp, tab_cf, tab_in, tab_about = st.tabs(
    ['Overview', 'Property', 'Compare retirement years', 'Withdrawals', 'Spending', 'Cash flow', 'Inputs',
     'How it works'])
with tab_sp:
    sp_in = st.container()
    sp_out = st.container()
with tab_prop:
    prop_out = st.container()
    prop_in = st.container()
with tab_cmp:
    cmp_in = st.container()
    cmp_out = st.container()
with tab_wd:
    wd_in = st.container()
    wd_out = st.container()

STRATEGY_LABELS = {'minimums': 'RRIF minimums from retirement',
                   'defer': 'Defer RRSPs to 71, draw only as needed',
                   'bracket': 'Fill tax brackets to a target income'}


def apply_spending(scale: float, mode: str):
    """Button callback: scale the plan's expense items, then rebuild the expenses editor."""
    p = st.session_state.plan
    for e in p.expenses:
        if mode == 'all' or e.discretionary:
            e.monthly = round(e.monthly * scale, 2)
            if e.monthly_later is not None:
                e.monthly_later = round(e.monthly_later * scale, 2)
    for k in ('base_exp', 'ed_exp'):
        st.session_state.pop(k, None)
    st.session_state.spend_applied = scale


def apply_strategy(strategy: str, target: float, until: int):
    """Button callback: runs before the next rerun, so the widgets pick these up."""
    st.session_state.w_wd_strategy = STRATEGY_LABELS[strategy]
    st.session_state.w_wd_target = int(target)
    st.session_state.w_wd_until = int(until)

# ================================================================== TAB INPUTS
sale_year = plan.start_year
th = plan.townhouse
with prop_in:
    st.markdown('#### Properties')
    base = st.session_state.setdefault('base_props', pd.DataFrame([{
        'Property': p.name, 'Type': p.segment, 'Value today': p.value_today, '2022 peak': p.peak_value,
        'Purchase price': p.purchase_price, 'Purchase year': p.purchase_year,
        'Principal residence': p.principal_residence,
        'ACB (blank = purchase price)': p.acb} for p in plan.properties]))
    ed = st.data_editor(base, key='ed_props', hide_index=True, width='stretch', num_rows='fixed',
                        column_config={
                            'Property': st.column_config.TextColumn(disabled=True),
                            'Type': st.column_config.SelectboxColumn(options=[s.key for s in plan.segments]),
                            'Value today': st.column_config.NumberColumn(format='$%d', step=5000),
                            '2022 peak': st.column_config.NumberColumn(format='$%d', step=5000),
                            'Purchase price': st.column_config.NumberColumn(format='$%d', step=1000),
                            'Purchase year': st.column_config.NumberColumn(format='%d'),
                            'ACB (blank = purchase price)': st.column_config.NumberColumn(format='$%d')})
    for p, (_, r) in zip(plan.properties, ed.iterrows()):
        p.segment, p.value_today, p.peak_value = r['Type'], float(r['Value today']), float(r['2022 peak'])
        p.purchase_price, p.purchase_year = float(r['Purchase price']), int(r['Purchase year'])
        p.principal_residence = bool(r['Principal residence'])
        acb = r['ACB (blank = purchase price)']
        p.acb = None if acb is None or pd.isna(acb) else float(acb)
    c1, c2, c3, c4 = st.columns(4)
    th.price_today = c1.number_input('Townhouse price today', 500_000, 4_000_000, int(th.price_today), 25_000,
                                     key='w_th_price')
    c1.caption(f'Areas: {th.areas}')
    th.peak_value = c2.number_input('Townhouse 2022 peak', 500_000, 4_000_000, int(th.peak_value), 25_000,
                                    key='w_th_peak', help='The 2022 peak price of a comparable freehold townhouse.')
    th.follows_market = c3.toggle('Townhouse price moves with the market', th.follows_market,
                                  key='w_th_follow')
    plan.commission_rate = c4.slider('Commission (before HST)', 2.0, 6.0, plan.commission_rate * 100, 0.25,
                                     format='%.2f%%', key='w_comm') / 100

    with st.expander('Recovery model settings (per property type)'):
        st.caption('Fair value = recovery target x 2022 peak, growing at the long-run rate. Each year the '
                   'price closes the recovery-speed share of the gap, plus a shared market shock (rates, '
                   'sentiment, supply) scaled by beta and a property-specific shock.')
        c1, c2 = st.columns(2)
        plan.market_vol = c1.slider('Market shock volatility (yearly)', 0.0, 20.0, plan.market_vol * 100, 0.5,
                                    format='%.1f%%', key='w_mvol') / 100
        plan.market_momentum = c2.slider('Market momentum (autocorrelation)', 0.0, 0.9, plan.market_momentum,
                                         0.05, key='w_mmom')
        for s in plan.segments:
            st.markdown(f'**{s.label}**  \n<span class="muted">{s.rationale}</span>',
                        unsafe_allow_html=True)
            c = st.columns(6)
            s.recovery_target = c[0].slider('Target (x peak)', 0.6, 1.3, s.recovery_target, 0.01,
                                            key=f'w_{s.key}_tgt')
            s.recovery_speed = c[1].slider('Speed (gap / yr)', 0.0, 1.0, s.recovery_speed, 0.05,
                                           key=f'w_{s.key}_spd')
            s.long_run_growth = c[2].slider('Long-run growth', 0.0, 8.0, s.long_run_growth * 100, 0.25,
                                            format='%.2f%%', key=f'w_{s.key}_g') / 100
            s.beta = c[3].slider('Market beta', 0.0, 2.0, s.beta, 0.05, key=f'w_{s.key}_beta')
            s.idio_vol = c[4].slider('Own volatility', 0.0, 20.0, s.idio_vol * 100, 0.5, format='%.1f%%',
                                     key=f'w_{s.key}_vol') / 100
            s.sale_discount = c[5].slider('Sale discount', 0.0, 10.0, s.sale_discount * 100, 0.5,
                                          format='%.1f%%', key=f'w_{s.key}_disc') / 100

    with st.expander('Mortgages'):
        cols = st.columns(len(plan.mortgages))
        for c, m in zip(cols, plan.mortgages):
            cur = m.renewal_rate if m.renewal_rate is not None else m.rate
            m.renewal_rate = c.slider(f'{m.name}: renewal rate', 2.0, 8.0, cur * 100, 0.05, format='%.2f%%',
                                      key=f'w_ren_{m.name}') / 100
        mort_box = st.container()

with wd_in:
    st.subheader('How to draw down the RRSPs and RRIFs')
    c1, c2, c3 = st.columns([2, 1, 1])
    labels = list(STRATEGY_LABELS.values())
    pick = c1.radio('Strategy', labels, labels.index(STRATEGY_LABELS[plan.withdrawal_strategy]),
                    key='w_wd_strategy', horizontal=False)
    plan.withdrawal_strategy = next(k for k, v in STRATEGY_LABELS.items() if v == pick)
    plan.bracket_target = float(c2.slider('Target taxable income per person (today\'s $)', 40_000, 250_000,
                                          int(plan.bracket_target), 5_000, format='$%d', key='w_wd_target',
                                          disabled=plan.withdrawal_strategy != 'bracket',
                                          help='Each year, draw from registered until each person\'s taxable '
                                               'income reaches this (indexed to inflation). $95K is about '
                                               'where the OAS clawback starts.'))
    plan.fill_until_age = int(c2.slider('Fill until age', 60, 71, int(plan.fill_until_age), 1, key='w_wd_until',
                                        disabled=plan.withdrawal_strategy != 'bracket'))
    plan.tfsa_topup = c3.toggle('Top up TFSAs with surplus', plan.tfsa_topup, key='w_wd_topup',
                                help='Surplus cash goes into each person\'s TFSA room (indexed limit) before '
                                     'non-registered. Tax-free growth instead of taxable.')
    plan.accurate_extra_tax = c3.toggle('Tax extra withdrawals at the actual marginal rate',
                                        plan.accurate_extra_tax, key='w_wd_acctax',
                                        help='Off = the spreadsheet rule (always the top rate, 53.53%).')
    st.caption('"Defer" and "Fill" keep RRSPs unconverted until the end of the year you turn 71; RRIF minimums '
               f'start the year after. {p2.name}\'s LIRA stays locked until 55 under every strategy.')

SPEND_MODES = {'all': 'All spending', 'discretionary': 'Discretionary only (items marked discretionary)'}
with sp_in:
    st.subheader('How much can we spend?')
    st.caption('Finds the most you can spend every year, in both spending phases, so the money never runs out '
               'and you still leave the estate you choose. Spending stays in proportion: scaling up or down keeps '
               'the go-go and later-years mix.')
    c1, c2, c3 = st.columns([1.2, 1.4, 1])
    plan.spend_target_estate = float(c1.slider("Estate to leave, after tax (today's $)", 0, 6_000_000,
                                               int(plan.spend_target_estate), 250_000, format='$%d',
                                               key='w_sp_target',
                                               help='Measured at the end of the plan (the second death, if '
                                                    'life expectancy is on).'))
    mlabels = list(SPEND_MODES.values())
    pickm = c2.radio('Adjust', mlabels, mlabels.index(SPEND_MODES[plan.spend_mode]), key='w_sp_mode')
    plan.spend_mode = next(k for k, v in SPEND_MODES.items() if v == pickm)
    plan.spend_confidence = c3.slider('Confidence (market risk)', 50, 95, int(round(plan.spend_confidence * 100)),
                                      5, format='%d%%', key='w_sp_conf', disabled=not plan.returns_mc,
                                      help='Share of market histories that must meet the goal. Turn on market '
                                           'risk in the sidebar to use it.') / 100

with cmp_in:
    st.subheader('Which retirement year?')
    cmp_lo, cmp_hi = st.slider('Years to compare', 2027, 2040, (2029, 2035), key='w_cmp')
cmp_years = tuple(range(min(cmp_lo, plan.start_year), max(cmp_hi, plan.start_year) + 1))

with tab_in:
    st.subheader('Inputs')
    st.caption(f'Balances are as of {plan.current_year} and grow at their own rates until retirement. '
               'Edits apply immediately; use "Save as default" in the sidebar to keep them.')
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('**Investment accounts**')
        base = st.session_state.setdefault('base_acc', pd.DataFrame([{
            'Account': a.name, 'Owner': a.owner, 'Type': a.kind, 'Balance': a.balance,
            'Growth %': a.return_rate * 100, 'Volatility %': a.volatility * 100,
            'Yearly contribution': a.contribution,
            'Contribute TFSA limit': a.contribution_is_tfsa_limit} for a in plan.accounts]))
        ed = st.data_editor(base, key='ed_acc', hide_index=True, width='stretch', num_rows='dynamic',
                            column_config={
                                'Owner': st.column_config.SelectboxColumn(options=['P1', 'P2']),
                                'Type': st.column_config.SelectboxColumn(options=list(ACCOUNT_KINDS)),
                                'Balance': st.column_config.NumberColumn(format='$%.0f'),
                                'Growth %': st.column_config.NumberColumn(format='%.2f'),
                                'Volatility %': st.column_config.NumberColumn(
                                    format='%.1f', help='Yearly swing before retirement (market risk only).'),
                                'Yearly contribution': st.column_config.NumberColumn(format='$%.0f')})
        plan.accounts = [Account(str(r['Account']), r['Owner'] or 'P1', r['Type'] or 'registered',
                                 float(r['Balance'] or 0), float(r['Growth %'] or 0) / 100,
                                 float(r['Yearly contribution'] or 0), bool(r['Contribute TFSA limit']),
                                 float(r['Volatility %'] if pd.notna(r['Volatility %']) else 12) / 100)
                         for _, r in ed.iterrows() if isinstance(r['Account'], str) and r['Account']]
        cc = st.columns(2)
        plan.tfsa_limit = cc[0].number_input('TFSA annual limit', 0, 20_000, int(plan.tfsa_limit), 500,
                                             key='w_tfsa')
        st.markdown(f'**Employee stock options ({p1.name})**')
        cc = st.columns(2)
        plan.options_share_price = cc[0].number_input('Share price', 0.0, 200.0, float(plan.options_share_price),
                                                      0.25, key='w_optprice')
        plan.options_marginal_rate = cc[1].number_input('Marginal tax rate on exercise', 0.0, 0.6,
                                                        float(plan.options_marginal_rate), 0.005, key='w_optrate')
        base = st.session_state.setdefault('base_opt', pd.DataFrame([vars(g) for g in plan.option_grants]).rename(
            columns={'grant_date': 'Grant date', 'expiry': 'Expiry', 'grant_price': 'Grant price',
                     'granted': 'Granted', 'available': 'Available'}))
        ed = st.data_editor(base, key='ed_opt', hide_index=True, width='stretch', num_rows='dynamic',
                            column_config={'Grant price': st.column_config.NumberColumn(format='$%.3f')})
        plan.option_grants = [OptionGrant(str(r['Grant date']), str(r['Expiry']), float(r['Grant price'] or 0),
                                          int(r['Granted'] or 0), int(r['Available'] or 0))
                              for _, r in ed.iterrows() if isinstance(r['Grant date'], str) and r['Grant date']]
        st.caption(md(f'Net proceeds after tax, all grants exercised: '
                      f'**{money(engine.options_net_proceeds(plan), False)}**'))
    with c2:
        st.markdown("**Living expenses (monthly, today's dollars)**")
        base = st.session_state.setdefault('base_exp', pd.DataFrame([{
            'Expense': e.name, 'Monthly (go-go)': e.monthly,
            'Monthly (later)': e.monthly if e.monthly_later is None else e.monthly_later,
            'Discretionary': e.discretionary} for e in plan.expenses]))
        ed = st.data_editor(base, key='ed_exp', hide_index=True, width='stretch', num_rows='dynamic',
                            height=600,
                            column_config={'Monthly (go-go)': st.column_config.NumberColumn(format='$%.0f'),
                                           'Monthly (later)': st.column_config.NumberColumn(format='$%.0f')})
        plan.expenses = [ExpenseItem(str(r['Expense']), float(r['Monthly (go-go)'] or 0),
                                     bool(r['Discretionary']),
                                     float(r['Monthly (later)']) if pd.notna(r['Monthly (later)']) else None)
                         for _, r in ed.iterrows() if isinstance(r['Expense'], str) and r['Expense']]
        g, lt = engine.expenses_at_start(plan)
        f = (1 + plan.expense_cpi) ** (plan.start_year - plan.current_year)
        st.caption(md(f'Yearly: **{money(g / f, False)}** go-go, **{money(lt / f, False)}** later in today\'s '
                      f'dollars; {money(g, False)} / {money(lt, False)} in {plan.start_year} dollars.'))
    st.markdown('**Consulting income in retirement (self-employed)**')
    st.caption('Net business income (after expenses) per year, in today\'s dollars. Taxable, so it can raise the '
               'OAS clawback after 65. You pay both halves of CPP (11.9%, plus 8% CPP2) until 65, or until CPP '
               'starts if later; consulting years before 65 also raise your CPP pension. With "Contribute RRSP '
               'room" on, the new room (18% of last year\'s income) goes into the RRSP each year through 71. HST '
               'registration is required above $30,000 a year (not modelled: it is collected from clients and '
               'passed through). Click the empty row to add a contract; add as many as you like.')
    base = st.session_state.setdefault('base_cons', pd.DataFrame(
        [{'Who': plan.person(c.owner).name, 'Description': c.label, 'Per year (today\'s $)': c.annual,
          'From': c.start_year, 'To (last year)': c.end_year, 'Grows with inflation': c.indexed,
          'Through my corporation': c.via_corp, 'Contribute RRSP room': c.rrsp} for c in plan.consulting],
        columns=['Who', 'Description', "Per year (today's $)", 'From', 'To (last year)', 'Grows with inflation',
                 'Through my corporation', 'Contribute RRSP room']))
    names_map = {p1.name: 'P1', p2.name: 'P2'}
    ed = st.data_editor(base, key='ed_cons', hide_index=True, width='stretch', num_rows='dynamic',
                        column_config={
                            'Who': st.column_config.SelectboxColumn(options=[p1.name, p2.name], required=True),
                            "Per year (today's $)": st.column_config.NumberColumn(format='$%.0f', min_value=0,
                                                                                  step=5000),
                            'From': st.column_config.NumberColumn(format='%d', min_value=2026, max_value=2090),
                            'To (last year)': st.column_config.NumberColumn(format='%d', min_value=2026,
                                                                            max_value=2090),
                            'Grows with inflation': st.column_config.CheckboxColumn(default=True),
                            'Through my corporation': st.column_config.CheckboxColumn(
                                default=False, help='Earned by the consulting corporation and paid out as '
                                                    'dividends (no CPP, no RRSP room).'),
                            'Contribute RRSP room': st.column_config.CheckboxColumn(
                                default=True, help='Personal consulting only; dividends create no RRSP room.')})
    plan.consulting = [ConsultingIncome(names_map.get(r['Who'], 'P2'), float(r["Per year (today's $)"] or 0),
                                        int(r['From'] if pd.notna(r['From']) else plan.start_year),
                                        int(r['To (last year)'] if pd.notna(r['To (last year)']) else plan.start_year),
                                        bool(r['Grows with inflation']) if pd.notna(r['Grows with inflation']) else True,
                                        bool(r['Contribute RRSP room']) if pd.notna(r['Contribute RRSP room']) else True,
                                        str(r['Description'] or 'Consulting'),
                                        bool(r['Through my corporation']) if pd.notna(r['Through my corporation'])
                                        else False)
                       for _, r in ed.iterrows() if pd.notna(r["Per year (today's $)"]) and r["Per year (today's $)"]]
    if plan.consulting:
        sched, extra = engine.consulting_schedule(plan)
        tot = {k: sum(v[k]['W'] for v in sched.values()) for k in ('P1', 'P2')}
        ctot = sum(v['corp'] for v in sched.values())
        bits = [f'{plan.person(k).name}: {money(tot[k])} personally' +
                (f', +{extra[k]:.1f} CPP contributory years' if extra[k] else '') for k in ('P1', 'P2') if tot[k]]
        if ctot:
            bits.append(f'Corporation: {money(ctot)} of revenue')
        st.caption(md(' · '.join(bits) + ' (nominal dollars).'))

    with st.expander('Consulting corporation', expanded=any(c.via_corp for c in plan.consulting)):
        st.caption('For contracts marked "Through my corporation": the corporation pays the small-business rate '
                   '(11.2% in Ontario from July 2026), invests what it keeps, and pays you non-eligible dividends. '
                   'Dividends are grossed up 15% and get the dividend tax credit; they carry no CPP and no RRSP '
                   'room. Money left in the corporation compounds and is taxed as a final dividend in the estate.')
        c1, c2, c3 = st.columns(3)
        pol = c1.radio('Dividends', ['Fill each shareholder to a target income', 'Pay everything out each year'],
                       0 if plan.dividend_policy == 'target' else 1, key='w_div_policy',
                       help='Keeping money in the corporation and paying it out in lower-income years is the '
                            'main advantage of a corporation.')
        plan.dividend_policy = 'target' if pol.startswith('Fill') else 'all'
        plan.dividend_target = float(c2.slider("Target taxable income per shareholder (today's $)", 30_000,
                                               260_000, int(plan.dividend_target), 5_000, format='$%d',
                                               key='w_div_target', disabled=plan.dividend_policy != 'target'))
        plan.corp_balance = float(c2.number_input('Corporate investments today', 0, 10_000_000,
                                                  int(plan.corp_balance), 10_000, key='w_corp_bal',
                                                  help='Investments held in the corporation today ($0 if none).'))
        plan.p1_shareholder = c3.toggle(f'{p1.name} holds shares', plan.p1_shareholder, key='w_corp_p1',
                                        help=f'TOSI rules: {p1.name} can receive dividends at regular rates '
                                             f'only in years {p1.name} works in the business, or once {p2.name} '
                                             f'is 65. Confirm the share structure with your accountant.')
        c3.caption(f'Off: {p2.name} is the only shareholder.')
        corp_out = st.container()


def apply_dividends(policy: str, target):
    st.session_state.w_div_policy = ('Fill each shareholder to a target income' if policy == 'target'
                                     else 'Pay everything out each year')
    if target is not None:
        st.session_state.w_div_target = int(target)
    with st.expander('Tax, CPP and projection settings'):
        c = st.columns(4)
        p1.cpp_monthly_at_65 = c[0].number_input(f'{p1.name} CPP at 65 (monthly)', 0, 3000,
                                                 int(p1.cpp_monthly_at_65), 10, key='w_cpp65P1')
        p2.cpp_monthly_at_65 = c[1].number_input(f'{p2.name} CPP at 65 (monthly)', 0, 3000,
                                                 int(p2.cpp_monthly_at_65), 10, key='w_cpp65P2')
        if plan.use_death_ages:
            c[2].metric('Projection ends (second death)', str(plan.end_year))
        else:
            plan.fixed_end_year = int(c[2].number_input('Projection end year', 2060, 2110, plan.fixed_end_year, 1,
                                                        key='w_end'))
            plan.sync_end_year()
        plan.index_brackets_to_start = c[3].toggle('Index tax brackets to retirement year',
                                                   plan.index_brackets_to_start, key='w_idx')
        st.caption('Combined federal + Ontario brackets in 2026 dollars, indexed with inflation.')
        tb = st.session_state.setdefault('base_tax', pd.DataFrame({
            'From (2026 $)': plan.tax_thresholds, 'Marginal rate': plan.tax_rates}))
        ed = st.data_editor(tb, key='ed_tax', hide_index=True, num_rows='fixed')
        plan.tax_thresholds = [float(x) for x in ed['From (2026 $)']]
        plan.tax_rates = [float(x) for x in ed['Marginal rate']]


# ================================================================== RUN THE MODEL
@st.cache_data(show_spinner='Running the model...', max_entries=64)
def compute(plan_json: str, n_paths: int, years: tuple):
    p = Plan.from_json(plan_json)
    mc = bands = None
    if p.property_mode == 'recovery':
        mc = analysis.monte_carlo(p, [p.start_year], n_paths)
        df, stt, summ = mc['years'][p.start_year].runs[50]
        bands = analysis.property_bands(p, max(years[-1], p.start_year), n_paths)
    else:
        df, stt, summ = analysis.deterministic(p)
    cmp = analysis.compare_years(p, list(years), max(n_paths, 500))
    mkt = None
    if p.returns_mc:
        n_mkt = n_paths or 2000
        res = analysis.market_monte_carlo(p, sorted(set(years) | {p.start_year}), n_mkt)
        mkt = {'outcome': res[p.start_year],
               'safe90': analysis.safe_spending(p, p.start_year, 0.90, n_mkt),
               'safe75': analysis.safe_spending(p, p.start_year, 0.75, n_mkt)}
        rows = []
        for y in years:
            o = res[y]
            e = o.end_capital(p.end_year)
            rows.append({'Retirement year': y, 'Success rate (markets)': o.success_rate,
                         f'Capital {p.end_year} P10 (markets)': float(np.percentile(e, 10)),
                         f'Capital {p.end_year} P50 (markets)': float(np.percentile(e, 50))})
        cmp = cmp.merge(pd.DataFrame(rows), on='Retirement year')
    return df, stt, summ, mc, bands, cmp, mkt


df, start, summ, mc, bands, compare, mkt = compute(plan.to_json(), n_paths, cmp_years)


@st.cache_data(show_spinner='Comparing withdrawal strategies...', max_entries=32)
def compute_strategies(plan_json: str, sale_values: tuple, purchase: float, n_mkt: int):
    p = Plan.from_json(plan_json)
    table, dfs, best = analysis.compare_strategies(p, (dict(sale_values), purchase), n_mkt)
    grid = analysis.optimize_bracket(p, (dict(sale_values), purchase))
    return table, dfs, best, grid


@st.cache_data(show_spinner='Solving for sustainable spending...', max_entries=32)
def compute_spending(plan_json: str, sale_values: tuple, purchase: float, n_mkt: int):
    p = Plan.from_json(plan_json)
    sale = (dict(sale_values), purchase)
    fixed = analysis.solve_spending(p, p.spend_target_estate, p.spend_mode, sale)
    mkt_res = (analysis.solve_spending(p, p.spend_target_estate, p.spend_mode, sale,
                                       p.spend_confidence, n_mkt) if n_mkt else None)
    return fixed, mkt_res


sp_fixed, sp_mkt = compute_spending(plan.to_json(), tuple(start.waterfall.sale_values.items()),
                                    start.waterfall.purchase, (n_paths or 2000) if plan.returns_mc else 0)

@st.cache_data(show_spinner='Comparing personal vs corporate consulting...', max_entries=32)
def compute_corp(plan_json: str, sale_values: tuple, purchase: float):
    p = Plan.from_json(plan_json)
    sale = (dict(sale_values), purchase)
    return analysis.corp_vs_personal(p, sale), analysis.best_dividend_target(p, sale)


corp_cmp = corp_grid = None
if any(c.via_corp for c in plan.consulting):
    corp_cmp, corp_grid = compute_corp(plan.to_json(), tuple(start.waterfall.sale_values.items()),
                                       start.waterfall.purchase)

wd_table, wd_dfs, wd_best, wd_grid = compute_strategies(
    plan.to_json(), tuple(start.waterfall.sale_values.items()), start.waterfall.purchase,
    (n_paths or 2000) if plan.returns_mc else 0)
yo = mc['years'][plan.start_year] if mc else None
end = plan.end_year
t_sale = sale_year - plan.current_year

# ================================================================== SIDEBAR OUTPUTS
with side_out:
    st.markdown('---')
    st.markdown('**Share & save**')
    prop_tbl = None
    if bands:
        prop_tbl = pd.DataFrame([{
            'Property': n, 'Value today': b['P50'].iloc[0], f'P10 at {sale_year}': b['P10'].iloc[t_sale],
            f'Median at {sale_year}': b['P50'].iloc[t_sale], f'P90 at {sale_year}': b['P90'].iloc[t_sale]}
            for n, b in bands.items()])
    label = (f'{plan.start_year} retirement - ' +
             ('recovery model' if plan.property_mode == 'recovery' else f'{plan.legacy_scenario} scenario'))
    st.download_button('⬇️ Export scenario to Excel',
                       export.to_excel(plan, df, start, summ, compare, prop_tbl, label, mkt,
                                       wd_table.drop(columns=[c for c in wd_table.columns
                                                              if c.startswith('Years with')]),
                                       sp_mkt or sp_fixed),
                       width='stretch', type='primary',
                       file_name=f'retvana_{plan.start_year}_{datetime.date.today():%Y%m%d}.xlsx',
                       mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    st.download_button('Download plan (JSON)', plan.to_json(), file_name='retvana_plan.json',
                       mime='application/json', width='stretch')
    c1, c2 = st.columns(2)
    plan_error = st.session_state.plan_error
    save_help = (f'Off: the saved plan {st.session_state.plan_path} cannot be read ({plan_error}). '
                 'Fix or remove the file, then reload the app.' if plan_error else
                 f'Saves these inputs to {st.session_state.plan_path} so the app opens with them.')
    save_error = None
    if c1.button('Save as default', width='stretch', disabled=bool(plan_error), help=save_help,
                 key='save_default'):
        try:
            saved = save_plan(plan, st.session_state.data_dir)
            st.toast(f'Saved to {saved}')
        except PlanFileUnreadable as e:
            st.session_state.plan_error = e.error   # the file broke after start: keep save off
            save_error = (f'Not saved: {e.path} cannot be read ({e.error}). '
                          'The file was left untouched.')
        except OSError as e:
            save_error = f'Not saved to {st.session_state.plan_path}: {type(e).__name__}: {e}'
    if save_error:
        st.error(save_error)
    if c2.button('Reset', width='stretch', help='Back to the example plan.'):
        load_plan(fresh_plan())
        st.rerun()
    up = st.file_uploader('Load plan (JSON)', type='json', key='w_upload')
    if up is not None and st.session_state.get('loaded_id') != up.file_id:
        st.session_state.loaded_id = up.file_id
        load_plan(Plan.from_json(up.getvalue().decode()))
        st.rerun()

# ================================================================== HEADER
with title_box:
    st.title(f'Retiring in {plan.start_year}')
    mode_txt = (f'Property values: recovery model, median of {n_paths:,} Monte Carlo paths' if mc else
                f'Property values: "{plan.legacy_scenario}" scenario')
    mode_txt += (f'. Market risk on: {plan.return_vol:.0%} volatility, {mkt["outcome"].success_rate:.0%} chance '
                 f'the money lasts' if mkt else f'. Fixed {plan.return_rate:.2%} return')
    mode_txt += '. Withdrawals: ' + (STRATEGY_LABELS[plan.withdrawal_strategy] if plan.withdrawal_strategy != 'bracket'
                                     else f'fill to ${plan.bracket_target / 1000:,.0f}K until {plan.fill_until_age}')
    life = (f'Planning to {p1.name} {p1.death_age} ({plan.death_year("P1")}) and {p2.name} {p2.death_age} '
            f'({plan.death_year("P2")}); estate measured at the second death' if plan.use_death_ages
            else f'Projection to {end} (both alive)')
    st.caption(f'{mode_txt}. {p1.name} {plan.start_year - p1.birth_year} and {p2.name} '
               f'{plan.start_year - p2.birth_year} at retirement. {life}.')

# ================================================================== OVERVIEW
real_end = (1 + plan.inflation) ** (end - plan.current_year)    # today's $ -> end-year $
with tab_over:
    m = st.columns(5)
    m[0].metric('Capital at retirement', money(summ['Capital at retirement']))
    m[1].metric('First-year draw', pct(summ['First-year expense / capital']),
                help='Spending / total capital in the first year of retirement.')
    if yo:
        m[2].metric('Property surplus (median)', money(summ['Property surplus']),
                    f'{yo.p_shortfall:.0%} chance of shortfall', delta_color='off', delta_arrow='off')
        c10, c90 = yo.runs[10][2][f'Capital {end}'], yo.runs[90][2][f'Capital {end}']
        m[3].metric(f'Capital in {end} (median)', money(summ[f'Capital {end}']),
                    md(f"{money(summ[f'Capital {end}'] / real_end)} in today's $ · P10-P90 "
                       f'{money(c10)} to {money(c90)}'), delta_color='off', delta_arrow='off',
                    help=f'In {end} dollars, before tax. Prices rise {real_end:.2f}x from {plan.current_year} '
                         f'to {end}.')
    else:
        m[2].metric('Property surplus', money(summ['Property surplus']))
        m[3].metric(f'Capital in {end}', money(summ[f'Capital {end}']),
                    md(f"{money(summ[f'Capital {end}'] / real_end)} in today's $"), delta_color='off',
                    delta_arrow='off', help=f'In {end} dollars, before tax.')
    if plan.use_death_ages:
        m[4].metric("Estate at second death (today's $)", money(summ['Estate after tax'] / real_end),
                    md(f"{money(summ['Estate after tax'])} in {end} dollars"), delta_color='off',
                    delta_arrow='off',
                    help=f'At the second death ({end}): registered balances taxed at the top rate; non-registered '
                         'and TFSA pass as-is. Shown in today\'s dollars, like the Spending tab\'s estate target. '
                         + (f'This is the typical path with a fixed {plan.return_rate:.1%} return; see Market risk '
                            'below for the range.' if plan.returns_mc else ''))
    else:
        m[4].metric('Lifetime income tax', money(summ['Lifetime income tax']))
    if start.shortfall_from_p1 > 0:
        st.info(md(f'The property sales leave a shortfall of **{money(start.shortfall_from_p1, False)}** after '
                   f"{p2.name}'s non-registered accounts ({money(start.nonreg_total_p2, False)} at retirement). "
                   f"It is funded from {p1.name}'s non-registered money (employee stock option proceeds and "
                   f"{p1.name}'s non-registered accounts)."))
    d = df[df['A'] <= end]
    left, right = st.columns([3, 2])
    with left:
        fig = go.Figure()
        stack = [(k, column_label(k, plan)) for k in ('F', 'S', 'I', 'V', 'BU', 'BX')]
        if d['CORP'].any():
            stack.append(('CORP', 'Corporation'))
        for (col, name), color in zip(stack, PALETTE + ['#9B5DE5']):
            fig.add_trace(go.Scatter(x=d['A'], y=d[col], name=name, stackgroup='cap', mode='none',
                                     fillcolor=color, hovertemplate='%{y:$,.0f}'))
        if yo:
            for q in (10, 90):
                dq = yo.runs[q][0]
                dq = dq[dq['A'] <= end]
                fig.add_trace(go.Scatter(x=dq['A'], y=dq['C'], name=f'Total capital P{q}',
                                         line=dict(color=RED if q == 10 else TEAL, dash='dot', width=2),
                                         hovertemplate='%{y:$,.0f}'))
        if plan.use_death_ages:
            first_key = 'P1' if plan.death_year('P1') <= plan.death_year('P2') else 'P2'
            fd = plan.death_year(first_key)
            if fd < end:
                fig.add_vline(x=fd + 0.5, line_dash='dash', line_color=GREY,
                              annotation_text=f'{plan.person(first_key).name} dies ({fd})',
                              annotation_position='top left')
        chart_layout(fig, 'Capital by account', 430)
        st.plotly_chart(fig, width='stretch')
    with right:
        fig = go.Figure()
        work_y = d['W_P1'] + d['W_P2']
        divs = d['D_P1'] + d['D_P2'] + d['CDA']
        srcs = [('CPP + OAS', d['N'] + d['AA'] - work_y), ('Consulting (after CPP + RRSP)',
                                                           work_y - d['CPP_P1'] - d['CPP_P2'] - d['K'] - d['X']),
                ('Dividends from the corporation', divs),
                ('Non-reg investment income', d['G'] + d['T']),
                ('Planned registered draws', d['BD'] + d['BH']), ('Non-registered draws', d['BB'] + d['BC']),
                ('TFSA withdrawals', d['BW'] + d['BZ']), ('Extra registered', d['BE'] + d['BI'])]
        colors = [TEAL, '#9B5DE5', '#C77DFF', PALETTE[3], PALETTE[1], PALETTE[0], GOLD, RED]
        keep = [i for i, (_, y) in enumerate(srcs) if i not in (1, 2) or y.any()]
        srcs, colors = [srcs[i] for i in keep], [colors[i] for i in keep]
        for (name, y), color in zip(srcs, colors):
            fig.add_trace(go.Bar(x=d['A'], y=y, name=name, marker_color=color, hovertemplate='%{y:$,.0f}'))
        fig.add_trace(go.Scatter(x=d['A'], y=d['B'] + d['R'] + d['AE'], name='Spending + income tax',
                                 line=dict(color=INK, width=2), hovertemplate='%{y:$,.0f}'))
        fig.update_layout(barmode='relative')
        chart_layout(fig, "Where each year's spending comes from", 430)
        st.plotly_chart(fig, width='stretch')
    st.caption('Negative non-registered draws are surpluses being reinvested. Extra registered withdrawals '
               'are taxed at the top marginal rate.')

    # ---------------------------------------------------------- market risk
    st.markdown('### Market risk')
    if not mkt:
        st.caption(f'Investment returns are a fixed {plan.return_rate:.2%} every year. Turn on '
                   '"📈 Market risk" in the sidebar to see how good and bad market years, especially '
                   'early in retirement, change the outcome.')
    else:
        o = mkt['outcome']
        e = o.end_capital(end)
        low = o.capital.min(axis=1)
        spend1 = float(o.expenses[0])
        defl = (1 + plan.inflation) ** (plan.start_year - plan.current_year)
        m = st.columns(5)
        m[0].metric('Chance the money lasts', f'{o.success_rate:.0%}',
                    help=f'Share of {len(e):,} market histories where capital never falls below one year '
                         f'of spending, through {end}.')
        m[1].metric(f'Capital in {end}: typical', money(float(np.median(e))),
                    md(f'bad case (P10) {money(float(np.percentile(e, 10)))}'), delta_color='off', delta_arrow='off')
        m[2].metric('Low point (P10)', money(float(np.percentile(low, 10))),
                    help='The lowest total capital reaches along the way, in the worst 10% of histories.')
        for col, key, lbl in ((m[3], 'safe90', '90%'), (m[4], 'safe75', '75%')):
            sp = spend1 * mkt[key]
            col.metric(f"Spend at {lbl} success (today's $)", money(sp / defl),
                       md(f'{mkt[key] - 1:+.0%} vs plan · leaving $0'), delta_color='off', delta_arrow='off',
                       help='Yearly spending (all years scaled the same way) at which this share of market '
                            'histories never runs out, with nothing required to be left over. The Spending tab '
                            'answers the same question with an estate target.')
        c1, c2 = st.columns([3, 2])
        with c1:
            bnd = o.bands()
            fig = go.Figure()
            band(fig, bnd['Year'], bnd['P5'], bnd['P95'], NAVY, 'P5-P95')
            band(fig, bnd['Year'], bnd['P25'], bnd['P75'], NAVY, 'P25-P75')
            fig.add_trace(go.Scatter(x=bnd['Year'], y=bnd['P50'], name='Median', line=dict(color=NAVY, width=3),
                                     hovertemplate='%{y:$,.0f}'))
            fig.add_trace(go.Scatter(x=bnd['Year'], y=bnd['P10'], name='Bad case (P10)',
                                     line=dict(color=RED, width=2, dash='dot'), hovertemplate='%{y:$,.0f}'))
            fig.add_trace(go.Scatter(x=d['A'], y=d['C'], name=f'Plan at fixed {plan.return_rate:.1%}',
                                     line=dict(color=GOLD, width=2, dash='dash'), hovertemplate='%{y:$,.0f}'))
            chart_layout(fig, f'Total capital across {len(e):,} market histories', 430)
            ticks = [v * 10 ** k for k in range(4, 9) for v in (1, 2, 5)]
            fig.update_yaxes(type='log', tickvals=ticks, ticktext=[money(v) for v in ticks])
            st.plotly_chart(fig, width='stretch')
        with c2:
            yrs = o.years
            dep = o.depleted_year
            cum = [(float(((dep > 0) & (dep <= y)).mean())) for y in yrs]
            ages = np.stack([yrs - p1.birth_year, yrs - p2.birth_year], axis=1)
            fig = go.Figure(go.Scatter(x=yrs, y=cum, fill='tozeroy', line=dict(color=RED, width=2),
                                       name='Ran out by this year', customdata=ages,
                                       hovertemplate=f'%{{y:.1%}} ({p1.name} %{{customdata[0]}}, '
                                                     f'{p2.name} %{{customdata[1]}})<extra></extra>'))
            chart_layout(fig, 'Chance of running out, by year', 430, yfmt='.0%')
            fig.update_layout(yaxis=dict(range=[0, max(0.2, max(cum) * 1.3)]), showlegend=False)
            st.plotly_chart(fig, width='stretch')
        shock = f' Stress test: {plan.first_year_shock:+.0%} in the first retirement year.' if plan.first_year_shock else ''
        st.caption(md(
            f'Each history has its own sequence of yearly returns: a median of {plan.return_rate:.1%} with '
            f'{plan.return_vol:.0%} volatility after retirement'
            + (', and each account\'s own rate and volatility before it' if plan.mc_pre_retirement else '')
            + ('. Property outcomes vary too (recovery model).' if mc else '.') + shock
            + ' "Running out" means capital drops below one year of spending. The chart uses a log scale so the '
              'bad cases stay visible.'))

# ================================================================== PROPERTY (outputs)
with prop_out:
    st.subheader('Selling the properties, buying the townhouse')
    rows = []
    vcol = f'Median {sale_year}' if bands else f'Value {sale_year}'
    for p in plan.properties:
        r = {'Property': p.name, 'Type': plan.segment(p.segment).label, 'Today': p.value_today,
             '2022 peak': p.peak_value, 'vs peak %': p.value_today / p.peak_value - 1}
        if bands:   # each asset's own percentiles (before any sale discount)
            b = bands[p.name]
            r['P10'], r[vcol], r['P90'] = b['P10'].iloc[t_sale], b['P50'].iloc[t_sale], b['P90'].iloc[t_sale]
        else:
            r[vcol] = start.waterfall.sale_values[p.name]
        r['Mortgage at sale'] = sum(pm.mortgage_balance(mg, sale_year) for mg in plan.mortgages
                                    if mg.secured_on == p.name)
        rows.append(r)
    r = {'Property': 'Townhouse (buy)', 'Type': plan.segment(th.segment).label, 'Today': th.price_today,
         '2022 peak': th.peak_value, 'vs peak %': th.price_today / th.peak_value - 1}
    if bands and th.follows_market:
        b = bands['Townhouse']
        r['P10'], r[vcol], r['P90'] = b['P10'].iloc[t_sale], b['P50'].iloc[t_sale], b['P90'].iloc[t_sale]
    else:
        r[vcol] = start.waterfall.purchase
    r['Mortgage at sale'] = 0.0
    rows.append(r)
    st.dataframe(style_table(pd.DataFrame(rows)), width='stretch', hide_index=True)
    note = []
    if bands:
        note.append('Each property\'s own median and P10/P90. Because all four move with the same market, '
                    'the waterfall below uses one whole path: the one with the median surplus.')
    for k, v in start.waterfall.cg_detail.items():
        note.append(f"Capital gains on {k}: sale {money(v['sale'])} - ACB {money(v['acb'])} - selling costs "
                    f"{money(v['selling_costs'])} = gain {money(v['gain'])}, tax {money(v['tax'])}.")
    st.caption(md(' '.join(note)))

    c1, c2 = st.columns([3, 2])
    with c1:
        if bands:
            fig = go.Figure()
            for name, b in bands.items():
                col = ASSET_COLORS.get(name, GREY)
                band(fig, b['Year'], b['P10'], b['P90'], col)
                fig.add_trace(go.Scatter(x=b['Year'], y=b['P50'], name=name, line=dict(color=col, width=2.5),
                                         hovertemplate='%{y:$,.0f}'))
            fig.add_vline(x=sale_year, line_dash='dash', line_color=GREY, annotation_text='sale',
                          annotation_position='top')
            chart_layout(fig, 'Value paths: median with P10-P90 band', 430)
            st.plotly_chart(fig, width='stretch')
        else:
            st.info('Switch to the recovery model in the sidebar for per-property paths and ranges.')
    with c2:
        wf = start.waterfall
        items = list(wf.sale_values.items()) + [
            ('Mortgages', -wf.mortgages), ('Commission', -wf.commission),
            ('Capital gains tax', -wf.capital_gains_tax), ('Land transfer tax', -wf.ltt),
            ('Townhouse', -wf.purchase)]
        labels = [money(v) for _, v in items] + [money(wf.surplus)]
        fig = go.Figure(go.Waterfall(
            x=[i[0] for i in items] + ['Surplus'], y=[i[1] for i in items] + [0],
            measure=['relative'] * len(items) + ['total'], text=labels, textposition='outside',
            increasing=dict(marker_color=TEAL), decreasing=dict(marker_color=RED),
            totals=dict(marker_color=NAVY if wf.surplus >= 0 else RED), cliponaxis=False,
            hovertemplate='%{x}: %{text}<extra></extra>'))
        chart_layout(fig, f'Proceeds waterfall, {sale_year}' + (' (median-surplus path)' if bands else ''), 430)
        fig.update_layout(showlegend=False, hovermode='closest')
        fig.update_xaxes(tickangle=-35)
        st.plotly_chart(fig, width='stretch')

    if yo:
        c1, c2 = st.columns([2, 3])
        with c1:
            fig = go.Figure(go.Histogram(x=yo.surplus, nbinsx=60, marker_color=NAVY, opacity=0.85))
            fig.add_vline(x=0, line_color=RED, line_width=2)
            chart_layout(fig, f'Surplus / shortfall across paths, {sale_year}', 340, yfmt=',')
            fig.update_xaxes(tickformat='$,.2s')
            fig.update_layout(hovermode='closest', bargap=0.02)
            st.plotly_chart(fig, width='stretch')
        with c2:
            fig = go.Figure()
            band(fig, compare['Retirement year'], compare['Property surplus P10'],
                 compare['Property surplus P90'], NAVY, 'P10-P90')
            fig.add_trace(go.Scatter(x=compare['Retirement year'], y=compare['Property surplus P50'],
                                     name='Median', line=dict(color=NAVY, width=3), hovertemplate='%{y:$,.0f}'))
            fig.add_trace(go.Bar(x=compare['Retirement year'], y=compare['Chance of property shortfall'],
                                 name='Chance of shortfall', yaxis='y2', marker_color=RED, opacity=0.35,
                                 hovertemplate='%{y:.0%}'))
            fig.add_hline(y=0, line_color=GREY)
            chart_layout(fig, 'Surplus by sale year', 340)
            fig.update_layout(yaxis2=dict(overlaying='y', side='right', tickformat='.0%', range=[0, 1],
                                          showgrid=False))
            st.plotly_chart(fig, width='stretch')

with mort_box:
    mt = pd.DataFrame([{'Mortgage': m.name, 'Secured on': m.secured_on,
                        f'Balance at sale ({sale_year})': pm.mortgage_balance(m, sale_year),
                        'Monthly payment': pm.mortgage_payment(m), 'Rate': m.rate,
                        'Renewal rate': m.renewal_rate if m.renewal_rate is not None else m.rate}
                       for m in plan.mortgages])
    st.dataframe(style_table(mt), width='stretch', hide_index=True)

# ================================================================== COMPARE (outputs)
with cmp_out:
    endc = f'Capital {end}'
    fig = go.Figure()
    fig.add_trace(go.Bar(x=compare['Retirement year'], y=compare['First-year expense / capital'],
                         name='First-year draw (right axis)', yaxis='y2', marker_color=GOLD, opacity=0.3,
                         width=0.5, hovertemplate='%{y:.1%}'))
    if mc:
        band(fig, compare['Retirement year'], compare[f'{endc} P10'], compare[f'{endc} P90'], TEAL,
             f'{endc} P10-P90 (property)')
    fig.add_trace(go.Scatter(x=compare['Retirement year'], y=compare[endc],
                             name=f'{endc}' + (' (median)' if mc else ''), line=dict(color=TEAL, width=3),
                             mode='lines+markers', hovertemplate='%{y:$,.0f}'))
    fig.add_trace(go.Scatter(x=compare['Retirement year'], y=compare['Capital at retirement'],
                             name='Capital at retirement', line=dict(color=NAVY, width=3), mode='lines+markers',
                             hovertemplate='%{y:$,.0f}'))
    chart_layout(fig, None, 430)
    top = max(0.06, float(compare['First-year expense / capital'].max()) * 1.3)
    fig.update_layout(yaxis=dict(rangemode='tozero'),
                      yaxis2=dict(overlaying='y', side='right', tickformat='.1%', showgrid=False,
                                  range=[0, top * 2.2]))   # keep the bars in the lower half
    st.plotly_chart(fig, width='stretch')
    if mkt:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=compare['Retirement year'], y=compare['Success rate (markets)'],
                             marker_color=[TEAL if v >= 0.9 else GOLD if v >= 0.75 else RED
                                           for v in compare['Success rate (markets)']],
                             text=[f'{v:.0%}' for v in compare['Success rate (markets)']], textposition='outside',
                             hovertemplate='%{y:.1%}', name='Chance the money lasts'))
        fig.add_hline(y=0.9, line_dash='dot', line_color=GREY, annotation_text='90% target',
                      annotation_position='bottom left')
        chart_layout(fig, f'Chance the money lasts to {end} (market risk)', 320, yfmt='.0%')
        fig.update_layout(yaxis=dict(range=[0, 1.08]), showlegend=False, hovermode='closest')
        st.plotly_chart(fig, width='stretch')
    st.dataframe(style_table(compare), width='stretch', hide_index=True)
    st.caption('First-year draw = spending / capital; under ~4% is the usual comfort zone. '
               + ('"(markets)" columns vary yearly returns (and property, in recovery mode); other P10/P90 columns '
                  'vary property only.' if mkt else
                  'P10/P90 columns reflect property-market uncertainty only (investment returns are fixed). '
                  'Turn on market risk in the sidebar to add a success rate.'))

# ================================================================== WITHDRAWALS (outputs)
with wd_out:
    names = list(wd_dfs)
    cur_name = {'minimums': names[0], 'defer': names[1], 'bracket': names[2]}[plan.withdrawal_strategy]
    cur = wd_table.set_index('Strategy').loc[cur_name]
    best_row = wd_table.iloc[3]
    m = st.columns(5)
    m[0].metric('Estate after tax (today\'s $)', money(cur["Estate after tax (today's $)"]),
                md(f'{money(cur["Estate vs minimums"])} vs minimums (nominal)'), delta_color='off',
                delta_arrow='off',
                help=f'Capital in {end} with registered money taxed at the top rate on the second death.')
    m[1].metric('Lifetime income tax', money(cur['Lifetime income tax']))
    m[2].metric('Lifetime OAS clawback', money(cur['Lifetime OAS clawback']),
                f'{int(cur["Years with OAS clawback"])} years with a clawback', delta_color='off', delta_arrow='off')
    m[3].metric('Peak taxable income', money(cur['Highest taxable income (one person)']))
    if 'Chance the money lasts (markets)' in wd_table:
        m[4].metric('Chance the money lasts', f"{cur['Chance the money lasts (markets)']:.0%}")
    else:
        m[4].metric(f'Registered left in {end}', money(cur[f'Registered left in {end}']))

    is_best = (plan.withdrawal_strategy == 'bracket' and plan.bracket_target == wd_best['bracket_target']
               and plan.fill_until_age == wd_best['fill_until_age'])
    gain = best_row['Estate after tax'] - cur['Estate after tax']
    c1, c2 = st.columns([3, 1])
    if is_best:
        c1.success(f'You are using the best bracket-fill setting found: ${wd_best["bracket_target"]:,.0f} '
                   f'until {wd_best["fill_until_age"]}.')
    else:
        c1.info(md(f'Best setting found: fill to **${wd_best["bracket_target"]:,.0f}** per person until '
                   f'**{wd_best["fill_until_age"]}**, worth about **{money(gain)}** more estate after tax '
                   f'({money(gain / (1 + plan.inflation) ** (end - plan.current_year))} in today\'s dollars) than '
                   'your current choice.'))
        c2.button('Use the best setting', type='primary', width='stretch', on_click=apply_strategy,
                  args=('bracket', wd_best['bracket_target'], wd_best['fill_until_age']))

    show = wd_table.drop(columns=[c for c in wd_table.columns if c.startswith('Years with')])
    st.dataframe(style_table(show), width='stretch', hide_index=True)

    left, right = st.columns(2)
    base_df = wd_dfs[names[0]]
    cur_df = wd_dfs[cur_name]
    with left:
        fig = go.Figure()
        d0, d1 = base_df[base_df['A'] <= end], cur_df[cur_df['A'] <= end]
        for d_, lbl, dash in ((d0, 'minimums', 'dot'), (d1, 'your strategy', 'solid')):
            fig.add_trace(go.Scatter(x=d_['A'], y=d_['Q'], name=f'{p1.name}, {lbl}',
                                     line=dict(color=NAVY, dash=dash, width=2.5 if dash == 'solid' else 1.5),
                                     hovertemplate='%{y:$,.0f}'))
            fig.add_trace(go.Scatter(x=d_['A'], y=d_['AD'], name=f'{p2.name}, {lbl}',
                                     line=dict(color=TEAL, dash=dash, width=2.5 if dash == 'solid' else 1.5),
                                     hovertemplate='%{y:$,.0f}'))
        yrs = d1['A']
        claw = plan.oas_threshold * (1 + plan.inflation) ** (yrs - 1 - plan.oas_base_year)
        fig.add_trace(go.Scatter(x=yrs, y=claw, name='OAS clawback starts', line=dict(color=RED, dash='dash', width=1),
                                 hovertemplate='%{y:$,.0f}'))
        chart_layout(fig, 'Taxable income per person', 420)
        st.plotly_chart(fig, width='stretch')
    with right:
        fig = go.Figure()
        palette = [GREY, GOLD, TEAL, NAVY]
        for (name, d_), col in zip(wd_dfs.items(), palette):
            d_ = d_[d_['A'] <= end]
            short = name.split(' (')[0].split(',')[0]
            fig.add_trace(go.Scatter(x=d_['A'], y=d_['I'] + d_['V'], name=f'Registered: {short}',
                                     line=dict(color=col, width=2.5 if name == cur_name else 1.5),
                                     hovertemplate='%{y:$,.0f}'))
        chart_layout(fig, 'Registered balances (RRSP/RRIF/LIRA) by strategy', 420)
        st.plotly_chart(fig, width='stretch')

    with st.expander('All bracket-fill settings tried'):
        piv = wd_grid.pivot(index='Target income', columns='Fill until age', values='Estate after tax')
        real = (1 + plan.inflation) ** (end - plan.current_year)
        fig = go.Figure(go.Heatmap(z=piv.values / real, x=[f'until {a}' for a in piv.columns],
                                   y=[money(v) for v in piv.index], colorscale='Teal',
                                   hovertemplate='target %{y}, %{x}: estate %{z:$,.3s} today\'s $<extra></extra>',
                                   colorbar=dict(tickformat='$,.2s')))
        chart_layout(fig, 'Estate after tax (today\'s $) by target income and fill-until age', 460, yfmt='')
        fig.update_layout(hovermode='closest')
        st.plotly_chart(fig, width='stretch')

    st.caption(md(
        'Why it works: RRIF money is taxed when it comes out, and anything left at the second death is taxed at '
        'the top rate. Drawing it in the low-income years before CPP and OAS (and below the OAS clawback) fills '
        'the cheaper brackets, then the surplus grows tax-free in the TFSAs. Deferring everything to 71 does the '
        'opposite: bigger forced withdrawals later, at higher rates, with more OAS clawed back. The estate figure is '
        f'approximate: registered balances left in {end} are taxed at the top rate; non-registered and TFSA pass '
        'as-is. The comparison uses the median property path' + (' and the same market histories.' if plan.returns_mc
                                                                  else ' and the fixed return.')))

# ================================================================== SPENDING (outputs)
with sp_out:
    if st.session_state.pop('spend_applied', None):
        st.success('Spending applied to your plan. The expense items on the Inputs tab have been updated; use '
                   '"Save as default" in the sidebar to keep them.')
    defl0 = (1 + plan.inflation) ** (plan.start_year - plan.current_year)
    now_today = float(df['B'].iloc[0]) / defl0
    goal = f"never run out and leave {money(plan.spend_target_estate)} (today's $)"
    answer = sp_mkt if sp_mkt else sp_fixed
    if not answer['feasible']:
        st.error(md(f'Even with {"no discretionary" if plan.spend_mode == "discretionary" else "minimal"} '
                    f'spending the plan can\'t {goal}. Lower the estate target, or switch to adjusting all '
                    'spending.'))
    else:
        o, s = answer['outcome'], answer['scale']
        m = st.columns(4)
        m[0].metric("Sustainable spending (today's $)", money(o['first_year_today'], False),
                    md(f'{s - 1:+.0%} vs your plan ({money(now_today, False)})'), delta_color='off', delta_arrow='off')
        m[1].metric('Per month (today\'s $)', money(o['first_year_today'] / 12, False))
        m[2].metric(f'In {plan.start_year} dollars', money(o['first_year'], False))
        if sp_mkt:
            est = answer['estates']
            m[3].metric("Estate left, typical market (today's $)", money(est[50]),
                        md(f"bad case (P10) {money(est[10])}"), delta_color='off', delta_arrow='off',
                        help=f'At this spending, half of market histories leave more than the typical amount. '
                             f'Only {1 - answer["success_rate"]:.0%} leave less than '
                             f'{money(plan.spend_target_estate)}.')
        else:
            m[3].metric("Estate left (today's $)", money(o['estate_today']))
        if sp_mkt and sp_fixed['feasible']:
            st.caption(md(f'With the fixed {plan.return_rate:.1%} return (no market risk) the answer would be '
                          f'{money(sp_fixed["outcome"]["first_year_today"], False)} a year '
                          f'({sp_fixed["scale"] - 1:+.0%}). The gap is the price of a '
                          f'{plan.spend_confidence:.0%} confidence level.'))
        # reconcile with the Overview: what the plan leaves now vs at the sustainable level
        cur_estate = summ['Estate after tax'] / real_end
        cap_end = summ[f'Capital {end}']
        with st.expander('How this ties to the Overview numbers'):
            st.markdown(md(
                f'- At your current spending ({money(now_today, False)} a year), the plan leaves '
                f'**{money(cap_end)}** of capital in {end}. That is in {end} dollars, before tax. In today\'s '
                f'dollars it is **{money(cap_end / real_end)}** (prices rise {real_end:.2f}x by {end}). After '
                f'the tax on registered money at the second death, the estate is **{money(cur_estate)}** in '
                f'today\'s dollars.\n'
                f'- The surplus over your {money(plan.spend_target_estate)} target is about '
                f'**{money(cur_estate - plan.spend_target_estate)}** (today\'s $). Spread over '
                f'{end - plan.start_year + 1} years, and allowing for the growth it would have earned, it pays for '
                f'the extra {money(sp_fixed["outcome"]["first_year_today"] - now_today if sp_fixed["feasible"] else 0, False)} '
                f'a year with the fixed return.\n'
                f'- The Overview\'s "Spend at 90% success" leaves **$0**. This tab adds your estate target, so its '
                f'answer is lower when the target is above zero.'))
        c1, c2 = st.columns([3, 1])
        msg = (f'To {goal}' + (f' in {plan.spend_confidence:.0%} of market histories' if sp_mkt else '') +
               f', you can spend **{money(o["first_year_today"], False)} a year** in today\'s dollars '
               f'(adjusting {"all spending" if plan.spend_mode == "all" else "discretionary items only"}).')
        if sp_mkt:
            msg += (f' That {money(plan.spend_target_estate)} is the **bad case**: in a typical market history '
                    f'you would leave about **{money(answer["estates"][50])}** (today\'s $). The Overview shows '
                    f'that typical (fixed {plan.return_rate:.1%} return) path, which is why its estate stays high '
                    f'after you apply this. Turn market risk off here to solve for exactly '
                    f'{money(plan.spend_target_estate)} on the typical path.')
        c1.info(md(msg))
        c2.button('Apply to my plan', type='primary', width='stretch', on_click=apply_spending,
                  args=(s, plan.spend_mode), disabled=abs(s - 1) < 0.005,
                  help='Scales the expense items on the Inputs tab by this factor.')

        rows = []
        for e in plan.expenses:
            f_ = s if (plan.spend_mode == 'all' or e.discretionary) else 1.0
            later = e.monthly if e.monthly_later is None else e.monthly_later
            rows.append({'Expense': e.name, 'Discretionary': 'yes' if e.discretionary else '',
                         'Monthly now (go-go)': e.monthly, 'Sustainable (go-go)': e.monthly * f_,
                         'Monthly now (later)': later, 'Sustainable (later)': later * f_})
        tbl = pd.DataFrame(rows)
        tot = {'Expense': 'Total per month', 'Discretionary': ''}
        tot.update({c: tbl[c].sum() for c in tbl.columns[2:]})
        tbl = pd.concat([tbl, pd.DataFrame([tot])], ignore_index=True)

    curve = answer['curve']
    left, right = st.columns(2)
    with left:
        fig = go.Figure()
        x = curve["First-year spending (today's $)"]
        fig.add_trace(go.Scatter(x=x, y=curve["Estate after tax (today's $)"], name='Estate left (fixed return)',
                                 line=dict(color=NAVY, width=3), hovertemplate='%{y:$,.0f}<extra></extra>'))
        fig.add_hline(y=plan.spend_target_estate, line_dash='dot', line_color=GOLD,
                      annotation_text='estate target', annotation_position='top right')
        fig.add_vline(x=now_today, line_dash='dash', line_color=GREY, annotation_text='your plan',
                      annotation_position='top left')
        if sp_fixed['feasible']:
            fig.add_vline(x=sp_fixed['outcome']['first_year_today'], line_color=TEAL, line_width=2,
                          annotation_text='sustainable (fixed return)' if sp_mkt else 'sustainable',
                          annotation_position='bottom right')
        chart_layout(fig, f"Estate left vs spending, fixed {plan.return_rate:.1%} return (today's $)", 400)
        fig.update_xaxes(tickformat='$,.3s', title="First-year spending (today's $)")
        fig.update_layout(hovermode='x', showlegend=False)
        st.plotly_chart(fig, width='stretch')
    with right:
        if 'Chance of meeting the goal (markets)' in curve:
            fig = go.Figure(go.Scatter(x=x, y=curve['Chance of meeting the goal (markets)'], fill='tozeroy',
                                       line=dict(color=TEAL, width=3), hovertemplate='%{y:.0%}<extra></extra>'))
            fig.add_hline(y=plan.spend_confidence, line_dash='dot', line_color=GOLD,
                          annotation_text=f'{plan.spend_confidence:.0%} target', annotation_position='bottom left')
            fig.add_vline(x=now_today, line_dash='dash', line_color=GREY, annotation_text='your plan',
                          annotation_position='top left')
            if answer['feasible']:
                fig.add_vline(x=answer['outcome']['first_year_today'], line_color=NAVY, line_width=2,
                              annotation_text=f'sustainable at {plan.spend_confidence:.0%}',
                              annotation_position='bottom right')
            chart_layout(fig, 'Chance of meeting the goal vs spending (market risk)', 400, yfmt='.0%')
            fig.update_xaxes(tickformat='$,.3s', title="First-year spending (today's $)")
            fig.update_layout(yaxis=dict(range=[0, 1.02]), hovermode='x', showlegend=False)
            st.plotly_chart(fig, width='stretch')
        elif answer['feasible']:
            st.markdown('**Monthly budget at the sustainable level (today\'s $)**')
            st.dataframe(style_table(tbl.drop(columns=['Discretionary'])), width='stretch', hide_index=True,
                         height=420)
        else:
            st.caption('Turn on market risk in the sidebar to see the chance of meeting the goal at each level.')
    if sp_mkt and answer['feasible']:
        with st.expander("Monthly budget at the sustainable level (today's $)"):
            st.dataframe(style_table(tbl.drop(columns=['Discretionary'])), width='stretch', hide_index=True)
    st.caption(md('Uses everything else in your plan as it stands: retirement year, property, withdrawal strategy, '
                  'CPP/OAS, life expectancy and the survivor drop in spending. The estate is after tax: registered '
                  'money left is taxed at the top rate. "Never run out" means capital stays above one year of '
                  'spending.'))

# ================================================================== CONSULTING CORPORATION (outputs)
with corp_out:
    if corp_cmp is None:
        st.caption('Mark a consulting contract "Through my corporation" to compare it with consulting personally.')
    else:
        EST = "Estate after tax (today's $)"
        diff = corp_cmp['Difference'].iloc[1]
        st.markdown(md(f'**Through the corporation vs personally:** {money(diff)} '
                       f'{"more" if diff >= 0 else "less"} estate after tax (today\'s $), with the dividend policy '
                       'above.'))
        st.dataframe(style_table(corp_cmp.rename(columns=lambda c: column_label(c, plan))), width='stretch',
                     hide_index=True)
        best = corp_grid.iloc[0]
        cur_is_best = (plan.dividend_policy == best['Policy'] and
                       (best['Policy'] == 'all' or abs(plan.dividend_target - best['Dividend target']) < 1))
        label = ('pay everything out each year' if best['Policy'] == 'all'
                 else f'fill to {money(best["Dividend target"])}')
        cc1, cc2 = st.columns([3, 1])
        cc1.caption(md(f'Best dividend policy found: **{label}** per shareholder '
                       f'({money(best[EST])} estate after tax, today\'s $).' +
                       ('' if not cur_is_best else ' You are using it.')))
        if not cur_is_best:
            cc2.button('Use best dividend policy', width='stretch', on_click=apply_dividends,
                       args=(best['Policy'], best['Dividend target'] if best['Policy'] == 'target' else None))

# ================================================================== CASH FLOW
with tab_cf:
    st.subheader('Year by year')
    cf = export.cashflow_table(df, end, plan)
    groups = {   # column keys; the table headers come from column_label
        'Overview': ['age_P1', 'age_P2', 'B', 'C', 'D'],
        'Balances': ['F', 'I', 'BU', 'S', 'V', 'BX'],
        'Income': ['N', 'AA', 'BD', 'BH'],
        'Consulting': ['W_P1', 'W_P2', 'CPP_P1', 'CPP_P2', 'K', 'X'],
        'Corporation': ['CORP', 'CORP_ACTIVE', 'CORP_TAX', 'D_P1', 'D_P2', 'CDA', 'RDTOH'],
        'Withdrawals': ['BB', 'BC', 'BW', 'BZ', 'BE', 'BI'],
        'Tax': ['Q', 'AD', 'R', 'AE', 'CF', 'CM'],
        'TFSA top-ups': ['T_P1', 'T_P2'],
    }
    pick = st.multiselect('Show', list(groups), ['Overview', 'Balances', 'Tax'], key='w_cfgroups')
    cols = [column_label('A', plan)] + [column_label(c, plan) for g in pick for c in groups[g]]
    st.dataframe(style_table(cf[cols]), width='stretch', hide_index=True, height=560)

# ================================================================== ABOUT
with tab_about:
    st.subheader('How the model works')
    st.markdown(f"""
**Engine.** A line-for-line Python port of an original spreadsheet model's projection, checked
against that spreadsheet when it was ported and guarded by regression checks since. Each year, in order:
planned registered draws, then non-registered, then TFSA, then extra registered withdrawals.
Planned draws are the RRIF minimums, or the target of the withdrawal strategy you pick on the
Withdrawals tab. Surpluses go to TFSA room first (if "Top up TFSAs" is on), then non-registered.
OAS clawback uses the previous year's taxable income. CPP is reduced for fewer contribution years
(years from 18 to retirement / 39).

**Life expectancy and the survivor.** By default the plan runs to FP Canada's 2026 planning ages (a
25% chance of living longer: female 97, male 94), set in the sidebar. Each person is alive through
the end of the year they reach that age. After the first death:
- the deceased's CPP and OAS stop;
- the survivor adds the **CPP survivor's pension**: 60% of the deceased's pension at 65 (37.5% if
  under 65), with the combined CPP capped at the maximum retirement pension;
- all accounts **roll over to the survivor tax-free** (spousal rollover, TFSA successor holder);
- **income splitting ends**, so the survivor is taxed alone on everything;
- spending drops to the survivor share (70% by default).

The plan ends at the second death, which is where the **estate after tax** is measured.

**Consulting income (Inputs tab).** Self-employed income for either of you, in today's dollars, over
any span of years. It is added to taxable income, so it raises tax and, after 65, the OAS clawback.
- **CPP:** self-employed contributions (both halves: 11.9% up to the YMPE, plus 8% CPP2 up to the
  YAMPE, using 2026 ceilings indexed to inflation) are paid until 65, or until CPP starts if later.
  Half is deducted from income; the other half is a credit at the lowest rate.
- **CPP pension:** consulting years before 65 count toward your CPP, pro rata to the YMPE.
- **RRSP (optional):** contributes the new room, 18% of the previous year's consulting income up to
  the indexed dollar limit, each year through 71. It is deducted from income and added to registered.
- Consulting stops at death. HST is not modelled; it is collected from clients and passed through.

**Through the consulting corporation.** Contracts marked "Through my corporation" are earned by the
corporation (Ontario CCPC):
- **Corporate tax:** 11.2% small-business rate (federal 9% + Ontario 2.2% from July 2026). The
  small-business limit shrinks once investment income passes $50K a year.
- **Corporate investments:** what the corporation keeps is invested at your return. The taxable
  part is taxed at 50.17%, with 30.67% refundable (RDTOH) when dividends are paid, at 38.33 cents
  per dollar. The untaxed half of capital gains is paid out tax-free as a capital dividend.
- **Dividends to you:** non-eligible, grossed up 15%, with a dividend tax credit of 9.0301% federal
  + 1.99% Ontario of the grossed-up amount (2026). There are no CPP contributions, no CPP years and
  no RRSP room.
- **Dividend policy:** fill each shareholder's taxable income up to a target (the main advantage:
  pay out in low-income years), or pay everything out each year. The app searches for the best
  target.
- **{p1.name} as a shareholder (optional):** under the TOSI rules {p1.name} can only be paid at
  regular rates in years of working in the business, or once {p2.name} is 65. If {p2.name} dies
  first, {p1.name} inherits the shares.
- **Estate:** whatever is left in the corporation is valued as a final dividend taxed at the top
  rate.

This is a planning model, not tax advice. Confirm the structure with your accountant.

**Two fixes the original spreadsheet didn't have,** both on by default and both on the Withdrawals tab:
- **TFSA top-up:** surplus cash fills each person's yearly TFSA room (indexed in $500 steps).
- **Extra withdrawals taxed at the person's actual marginal rate,** not a flat 53.53%.

Switch both off to reproduce the original spreadsheet exactly.

**Property: recovery model.** A housing market doesn't move at a steady yearly rate, and each property
type behaves differently. Each property gets a *fair value* anchored to its 2022 peak (a recovery
target x peak) that grows at a long-run rate. Each year the price closes part of the gap to fair
value (recovery speed), plus:
- a **shared market shock** for rates, sentiment and supply, which persists from year to year
  (momentum) and hits each type by its beta;
- a **property-specific shock**.

Thousands of paths give the range of sale values and the chance that the proceeds don't cover the
townhouse. The townhouse is simulated in the same market, so a rising market raises its price too.

**Market risk (optional).** With "📈 Market risk" on, each of thousands of histories gets its own
sequence of yearly returns: a median of {plan.return_rate:.2%} with the volatility you set. The
median history lines up with the fixed-return plan; the spread shows what good and bad sequences
do. A crash early in retirement hurts far more than the same crash 20 years later, because you are
withdrawing from a smaller pot (sequence-of-returns risk).
- **Before retirement,** each account grows at its own rate and volatility. An equity RRSP and a
  bond TFSA move together, by different amounts.
- **The same market history is used for every retirement year** being compared, so the comparison
  is fair.
- **"Chance the money lasts"** is the share of histories where capital never drops below one year
  of spending.
- **"Spending with 90% success"** scales all planned spending up or down until 90% of histories
  last.
- **Returns are bell-shaped,** with no fat tails or regime changes. The first-year stress test lets
  you force a crash.

**Default property-type settings.** These are judgment calls, not fitted to data:
- **Condo townhouse (Property 1):** full recovery to the 2022 peak. Family-sized condo townhouses
  have fallen far less since the 2022 peak than condo apartments.
- **Condo apartment (Property 3):** recovers 90% of the peak.
- **Studio (Property 2):** recovers 85% of the peak, slowly, with a 3% sale haircut. Studios are
  investor-driven, have the most supply coming and are hard to finance.
- **Freehold townhouse (purchase):** full recovery, with 4% long-run growth.

You can adjust all of them on the Property tab.

**Not modelled.** Share price risk on the employee stock options, rental income before the sale, and
municipal luxury land transfer tax tiers above $3M.
""".replace('$', '\\$'))
