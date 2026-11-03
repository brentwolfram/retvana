"""Compare the engine with the Regression_Golden (Requirements 4.4, 4.6).
  .venv/bin/python scripts/regression_check.py [golden.json]
Runs engine.project on the Example_Plan for every case in scripts/regression_golden.json (or the
golden given as the argument) and compares every column of every year within the golden's stored
tolerances. Reports the first differing cells per case and checks the column set both ways.
The golden is opened read-only and this check writes no file (no bytecode either). It never
regenerates the golden: if the Example_Plan changed, it fails with the regeneration instruction.
"""
import sys
sys.dont_write_bytecode = True       # importing the generator and the package must write nothing

import json                                                  # noqa: E402
import math                                                  # noqa: E402
import os                                                    # noqa: E402

from retvana import engine                                   # noqa: E402
import make_regression_golden as gen                         # noqa: E402

FIRST = 5            # differing cells reported per case
REGEN = ('example plan changed: update the spec, then regenerate the golden deliberately '
         '(.venv/bin/python scripts/make_regression_golden.py)')

ok = True


def check(label, cond, detail=''):
    """Print one result; detail is shown only on failure."""
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail and not cond else ""}')


def close(kind, actual, stored, tol):
    """True when actual is within the stored tolerance of stored (format in the generator)."""
    a, s = float(actual), float(stored)
    if not (math.isfinite(a) and math.isfinite(s)):
        return False
    if kind == 'dollars':
        return abs(a - s) <= tol['dollars']
    return abs(a - s) <= tol['other'] * max(1.0, abs(s))


path = sys.argv[1] if len(sys.argv) > 1 else gen.GOLDEN
with open(path, 'r', encoding='utf-8') as f:
    golden = json.load(f)

# ---------------------------------------------------------------- header
check('schema', golden.get('schema') == gen.SCHEMA, f'{golden.get("schema")!r}')
check('generator', golden.get('generator') == gen.GENERATOR, f'{golden.get("generator")!r}')
sha = gen.plan_sha256()
same_plan = golden.get('example_plan_sha256') == sha
check('Example_Plan hash matches the golden', same_plan,
      '' if same_plan else f'{REGEN}; golden {str(golden.get("example_plan_sha256"))[:12]}, now {sha[:12]}')
tol = golden.get('tolerance', {})
check('tolerances stored', set(tol) == {'dollars', 'other'}
      and all(isinstance(tol[k], (int, float)) and tol[k] >= 0 for k in tol), f'{tol!r}')
check('dollar tolerance is at most $0.01', tol.get('dollars', 1) <= 0.01, f'{tol.get("dollars")!r}')

cols = golden.get('columns', {})
dollars, other = set(cols.get('dollars', [])), set(cols.get('other', []))
check('golden column groups are disjoint', not (dollars & other), f'{sorted(dollars & other)}')
check('golden "other" columns match the generator', other == set(gen.OTHER_COLUMNS),
      f'golden only {sorted(other - gen.OTHER_COLUMNS)}, generator only {sorted(gen.OTHER_COLUMNS - other)}')
kind_of = {c: 'dollars' for c in dollars} | {c: 'other' for c in other}
golden_cols = set(kind_of)

cases = golden.get('cases', [])
check('golden cases match CASES (names and overrides, in order)',
      [(c.get('name'), c.get('overrides')) for c in cases]
      == [(c['name'], json.loads(json.dumps(c['overrides']))) for c in gen.CASES],
      f'{len(cases)} golden cases, {len(gen.CASES)} in CASES')

# ---------------------------------------------------------------- cases
for case in cases:
    name = case.get('name')
    print(f'\n--- {name} ---')
    df, _ = engine.project(gen.case_plan(case))       # the golden's stored overrides
    engine_cols = set(df.columns)
    check('column set: every engine column is in the golden', engine_cols <= golden_cols,
          f'missing from golden {sorted(engine_cols - golden_cols)}')
    check('column set: every golden column comes from the engine', golden_cols <= engine_cols,
          f'not produced by engine {sorted(golden_cols - engine_cols)}')
    rows = case.get('rows', {})
    engine_rows = {str(int(y)): r for y, r in zip(df['A'], df.to_dict('records'))}
    check('year set matches', set(rows) == set(engine_rows),
          f'golden only {sorted(set(rows) - set(engine_rows))}, '
          f'engine only {sorted(set(engine_rows) - set(rows))}')
    diffs, cells = [], 0
    for year in sorted(set(rows) & set(engine_rows), key=int):
        stored, actual = rows[year], engine_rows[year]
        row_cols = set(stored)
        if row_cols != golden_cols:
            diffs.append(f'{year}: row columns differ from the golden column list '
                         f'(row only {sorted(row_cols - golden_cols)}, '
                         f'list only {sorted(golden_cols - row_cols)})')
        for c in sorted(row_cols & engine_cols & golden_cols):
            cells += 1
            if not close(kind_of[c], actual[c], stored[c], tol):
                diffs.append(f'{year} {c}: engine {float(actual[c])!r}, golden {stored[c]!r}')
    check(f'{cells} cells within tolerance', not diffs and cells > 0,
          f'{len(diffs)} differ' if diffs else '')
    for d in diffs[:FIRST]:
        print(f'      {d}')
    if len(diffs) > FIRST:
        print(f'      ... and {len(diffs) - FIRST} more')

print('\nREGRESSION CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
