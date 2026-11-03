"""Generate scripts/regression_golden.json, the Regression_Golden (Requirements 4.4, 4.5).

  .venv/bin/python scripts/make_regression_golden.py

Runs engine.project on the Example_Plan for the 12 cases in CASES and stores every projection
column of every year. This is the only script that writes the golden; scripts/verify.py does not
run it (its name does not end in _check.py), and scripts/regression_check.py only reads it.
Regenerate it only after a deliberate, spec-approved behaviour or example change, never to make
a check pass.

Before writing, the generator asserts that every feature path the design lists is reached
(FEATURE_PATHS below). If any assertion fails it prints the failures, exits 1 and writes nothing.

Golden format (JSON, sorted keys at every level, one projection year per line):
  schema               1
  generator            "scripts/make_regression_golden.py"
  example_plan_sha256  hex SHA-256 of example_plan().to_json() encoded as UTF-8 (see plan_sha256)
  tolerance            {"dollars": 0.01, "other": 1e-9}
                       dollars: |actual - stored| <= 0.01 (the stored value is rounded to cents)
                       other:   |actual - stored| <= 1e-9 * max(1, |stored|), for the unrounded
                                ratio, rate, age, year and flag columns (flags and ints compare
                                exactly in practice)
  columns              {"dollars": [...], "other": [...]}: every column of engine.project, split
                       by how it is stored and compared
  cases                [{"name", "overrides", "rows": {"<year>": {column: value}}}]

Overrides are applied to a fresh example_plan() by apply_overrides(): top-level keys set Plan
fields; "people" sets Person fields by person key; "townhouse" sets Townhouse fields;
"consulting" replaces the consulting list with ConsultingIncome(**item) for each item.
regression_check.py imports CASES, apply_overrides, case_plan, plan_sha256 and OTHER_COLUMNS from
this module, so the two cannot drift apart.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys

import numpy as np

from retvana import engine
from retvana.config import ConsultingIncome, Plan, example_plan

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, 'regression_golden.json')
SCHEMA = 1
GENERATOR = 'scripts/make_regression_golden.py'
TOLERANCE = {'dollars': 0.01, 'other': 1e-9}

# Columns stored unrounded: the year, ages, alive flags, ratios and rates. Every other column of
# engine.project is a dollar amount and is stored rounded to cents.
OTHER_COLUMNS = frozenset({'A', 'age_P1', 'age_P2', 'alive_P1', 'alive_P2', 'D', 'E', 'L', 'Y'})

# The first 8 keep the shape of the original spreadsheet parity cases (retirement year x property
# scenario x switches); the other 4 cover the switches the parity cases leave at their defaults.
CASES = [
    {'name': '2032 Base',
     'overrides': {'start_year': 2032, 'legacy_scenario': 'Base'}},
    {'name': '2029 Base',
     'overrides': {'start_year': 2029, 'legacy_scenario': 'Base'}},
    {'name': '2031 Bear',
     'overrides': {'start_year': 2031, 'legacy_scenario': 'Bear'}},
    {'name': '2035 Boom',
     'overrides': {'start_year': 2035, 'legacy_scenario': 'Boom'}},
    {'name': '2030 Bull, income splitting',
     'overrides': {'start_year': 2030, 'legacy_scenario': 'Bull', 'income_splitting': True}},
    {'name': '2032 Base, CPP 60/70 and OAS 70/67',
     'overrides': {'start_year': 2032, 'legacy_scenario': 'Base',
                   'people': {'P1': {'cpp_start_age': 60, 'oas_start_age': 70},
                              'P2': {'cpp_start_age': 70, 'oas_start_age': 67}}}},
    {'name': '2029 Bull, fixed townhouse',
     'overrides': {'start_year': 2029, 'legacy_scenario': 'Bull',
                   'townhouse': {'follows_market': False}}},
    {'name': '2027 Base',
     'overrides': {'start_year': 2027, 'legacy_scenario': 'Base'}},
    {'name': '2032 defer, death ages on',
     'overrides': {'start_year': 2032, 'legacy_scenario': 'Base', 'withdrawal_strategy': 'defer',
                   'use_death_ages': True}},
    {'name': '2032 bracket above the OAS threshold, TFSA top-up, accurate extra tax',
     'overrides': {'start_year': 2032, 'legacy_scenario': 'Base', 'withdrawal_strategy': 'bracket',
                   'bracket_target': 120_000, 'tfsa_topup': True, 'accurate_extra_tax': True}},
    # the App's fresh_plan() settings: recovery model (median path), TFSA top-up, accurate extra
    # tax, death ages on
    {'name': '2032 recovery mode, median path, app defaults',
     'overrides': {'start_year': 2032, 'property_mode': 'recovery', 'tfsa_topup': True,
                   'accurate_extra_tax': True, 'use_death_ages': True}},
    {'name': '2032 consulting: P1 direct, P2 through the corporation',
     'overrides': {'start_year': 2032, 'legacy_scenario': 'Base',
                   'consulting': [
                       {'owner': 'P1', 'annual': 50_000, 'start_year': 2032, 'end_year': 2036},
                       {'owner': 'P2', 'annual': 80_000, 'start_year': 2032, 'end_year': 2036,
                        'via_corp': True}]}},
]


def plan_sha256() -> str:
    """Hex SHA-256 of example_plan().to_json() encoded as UTF-8: the Example_Plan the golden was
    generated from. regression_check.py fails when this no longer matches the golden."""
    return hashlib.sha256(example_plan().to_json().encode('utf-8')).hexdigest()


def apply_overrides(plan: Plan, overrides: dict) -> Plan:
    """Apply a case's overrides to plan in place and return it (format in the module docstring)."""
    for key, value in overrides.items():
        if key == 'people':
            for pkey, attrs in value.items():
                person = plan.person(pkey)
                for name, v in attrs.items():
                    if not hasattr(person, name):
                        raise KeyError(f'unknown Person field: {name}')
                    setattr(person, name, v)
        elif key == 'townhouse':
            for name, v in value.items():
                if not hasattr(plan.townhouse, name):
                    raise KeyError(f'unknown Townhouse field: {name}')
                setattr(plan.townhouse, name, v)
        elif key == 'consulting':
            plan.consulting = [ConsultingIncome(**item) for item in value]
        else:
            if not hasattr(plan, key):
                raise KeyError(f'unknown Plan field: {key}')
            setattr(plan, key, value)
    return plan


def case_plan(case: dict) -> Plan:
    """A fresh Example_Plan with the case's overrides applied."""
    return apply_overrides(example_plan(), case['overrides'])


def _cell(column: str, value):
    """Stored form of one cell: dollars rounded to cents, everything else unrounded."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f'column {column}: non-finite value {x!r} cannot be stored')
    return (round(x, 2) if column not in OTHER_COLUMNS else x) + 0.0   # + 0.0 turns -0.0 into 0.0


def case_rows(df) -> dict:
    """{"<year>": {column: stored value}} for every year and every column of a projection."""
    return {str(int(year)): {c: _cell(c, row[c]) for c in df.columns}
            for year, row in zip(df['A'], df.to_dict('records'))}


# ------------------------------------------------------------------ feature coverage
def _feature_checks(runs: dict) -> list[tuple[str, bool]]:
    """(description, reached) for every feature path the design lists. runs maps a case name to
    (plan, df, start). Expected values are written out from the plan's rules."""
    out = []
    by = lambda name: runs[name]

    # both RRIF start rules
    plan, df, _ = by('2032 Base')
    first = df.iloc[0]
    out.append(("RRIF 'minimums' from retirement: P1 minimum factor and planned draw > 0 in the "
                "first retirement year (2032 Base)",
                plan.withdrawal_strategy == 'minimums' and first['L'] > 0 and first['BD'] > 0
                and abs(first['BD'] - first['L'] * first['I']) <= 1e-6))
    plan, df, _ = by('2032 defer, death ages on')
    conv = plan.rrif_conversion_age
    ok = plan.withdrawal_strategy == 'defer'
    for pkey, col in (('P1', 'BD'), ('P2', 'BH')):
        age = df[f'age_{pkey}']
        alive = df[f'alive_{pkey}']
        before, first_min = df[age <= conv], df[(age == conv + 1) & alive]
        ok = ok and len(before) > 0 and bool((before[col] == 0).all()) \
            and len(first_min) == 1 and float(first_min[col].iloc[0]) > 0
    out.append((f"RRIF 'defer': no planned registered draw through age {conv}, minimum from "
                f"{conv + 1} for both people (2032 defer)", ok))

    # LIRA unlock: P2 is 52 at a 2032 retirement and reaches the RRIF/LIF minimum age (55) in 2035
    plan, df, _ = by('2032 Base')
    p2 = plan.person('P2')
    unlock = p2.birth_year + p2.rrif_min_age
    pre = df[df['A'] < unlock]
    out.append((f"LIRA unlock: P2 aged 52 at retirement, no P2 minimum before {unlock}, minimum "
                f"from {unlock} (2032 Base)",
                int(df.iloc[0]['age_P2']) == 52 and unlock == 2035 and len(pre) == 3
                and bool((pre['Y'] == 0).all()) and bool((pre['BH'] == 0).all())
                and df.loc[unlock, 'Y'] > 0 and df.loc[unlock, 'BH'] > 0))

    # survivor rules (death ages on)
    plan, df, _ = by('2032 defer, death ages on')
    first_death = min(plan.death_year('P1'), plan.death_year('P2'))
    surv = df[df['A'] > first_death]
    ok = (plan.use_death_ages and int(df['A'].iloc[-1]) == plan.second_death_year()
          and len(surv) > 0 and plan.death_year('P1') == first_death
          and bool((~surv['alive_P1']).all()) and bool(surv['alive_P2'].all()))
    if ok:
        ok = all(bool((surv[c] == 0).all()) for c in ('F', 'I', 'BU', 'CC', 'CD'))
        y0, y1 = df.loc[first_death], df.loc[first_death + 1]
        later = first_death - plan.start_year >= plan.gogo_years    # both years in the later phase
        b_expected = y0['B'] * (1 + plan.inflation) * plan.survivor_spending
        ok = (ok and later and abs(y1['B'] - b_expected) <= 1e-6
              and y1['CJ'] > y0['CJ'] * (1 + plan.cpp_inflation) + 1.0)        # CPP survivor pension
    out.append(('Survivor rules: P1 dies first, P1 balances and benefits zero after, survivor '
                'spending share and CPP survivor pension applied, plan ends at the second death '
                '(2032 defer)', ok))

    # OAS clawback
    plan, df, _ = by('2032 bracket above the OAS threshold, TFSA top-up, accurate extra tax')
    out.append(('OAS clawback: rows with a non-zero clawback, bracket target above the OAS '
                'threshold (2032 bracket)',
                plan.bracket_target > plan.oas_threshold and bool(((df['CF'] > 0) | (df['CM'] > 0)).any())))

    # property surplus: negative (Bear) and positive (Bull with a fixed townhouse)
    plan, df, st = by('2031 Bear')
    out.append(('Negative property surplus (2031 Bear)',
                plan.legacy_scenario == 'Bear' and st.waterfall.surplus < 0))
    plan, df, st = by('2029 Bull, fixed townhouse')
    out.append(('Positive property surplus (2029 Bull, fixed townhouse)',
                plan.legacy_scenario == 'Bull' and not plan.townhouse.follows_market
                and st.waterfall.surplus > 0))

    # withdrawal cascade: extra registered draws and TFSA draws
    extra = [n for n, (_, df, _) in runs.items() if ((df['BE'] > 0) | (df['BI'] > 0)).any()]
    tfsa = [n for n, (_, df, _) in runs.items() if ((df['BW'] > 0) | (df['BZ'] > 0)).any()]
    out.append((f'Extra registered draw in the cascade ({len(extra)} cases)', len(extra) > 0))
    out.append((f'TFSA draw in the cascade ({len(tfsa)} cases)', len(tfsa) > 0))
    return out


# ------------------------------------------------------------------ output
def render(golden: dict) -> str:
    """JSON text with sorted keys at every level and one projection year per line."""
    d = lambda x: json.dumps(x, sort_keys=True, allow_nan=False)
    lines = ['{', '  "cases": [']
    for i, case in enumerate(golden['cases']):
        lines.append('    {')
        lines.append(f'      "name": {d(case["name"])},')
        lines.append(f'      "overrides": {d(case["overrides"])},')
        lines.append('      "rows": {')
        years = sorted(case['rows'])
        for j, y in enumerate(years):
            lines.append(f'        {d(y)}: {d(case["rows"][y])}' + (',' if j < len(years) - 1 else ''))
        lines.append('      }')
        lines.append('    }' + (',' if i < len(golden['cases']) - 1 else ''))
    lines.append('  ],')
    rest = sorted(k for k in golden if k != 'cases')
    for i, k in enumerate(rest):
        lines.append(f'  {d(k)}: {d(golden[k])}' + (',' if i < len(rest) - 1 else ''))
    lines.append('}')
    return '\n'.join(lines) + '\n'


def build() -> tuple[dict, list[tuple[str, bool]]]:
    runs, cases, columns = {}, [], None
    for case in CASES:
        plan = case_plan(case)
        df, st = engine.project(plan)
        runs[case['name']] = (plan, df, st)
        cols = set(df.columns)
        if columns is None:
            columns = cols
        elif cols != columns:
            raise ValueError(f'{case["name"]}: column set differs from the first case')
        cases.append({'name': case['name'], 'overrides': case['overrides'], 'rows': case_rows(df)})
    missing = OTHER_COLUMNS - columns
    if missing:
        raise ValueError(f'OTHER_COLUMNS not produced by engine.project: {sorted(missing)}')
    golden = {
        'schema': SCHEMA,
        'generator': GENERATOR,
        'example_plan_sha256': plan_sha256(),
        'tolerance': TOLERANCE,
        'columns': {'dollars': sorted(columns - OTHER_COLUMNS), 'other': sorted(OTHER_COLUMNS)},
        'cases': cases,
    }
    return golden, _feature_checks(runs)


def main() -> int:
    if len({c['name'] for c in CASES}) != len(CASES) or len(CASES) != 12:
        print('FAIL: CASES must hold 12 uniquely named cases')
        return 1
    golden, checks = build()
    for desc, ok in checks:
        print(f'{"PASS" if ok else "FAIL"}: {desc}')
    failed = [desc for desc, ok in checks if not ok]
    if failed:
        print(f'{len(failed)} feature path(s) not reached; {os.path.basename(GOLDEN)} not written')
        return 1
    text = render(golden)
    if json.loads(text) != golden:                     # the hand layout must be the same data
        print(f'FAIL: rendered JSON does not round-trip; {os.path.basename(GOLDEN)} not written')
        return 1
    tmp = GOLDEN + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(tmp, GOLDEN)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    n_rows = sum(len(c['rows']) for c in golden['cases'])
    n_cols = len(golden['columns']['dollars']) + len(golden['columns']['other'])
    print(f'{os.path.basename(GOLDEN)} written: {len(golden["cases"])} cases, {n_rows} rows, '
          f'{n_cols} columns, example plan {golden["example_plan_sha256"][:12]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
