"""Check that examples/example_household.json is example_plan() serialized (Requirement 8.7).

  .venv/bin/python scripts/examples_check.py

The file is example_plan().to_json() followed by one newline. This check reads it and never writes.
If example_plan() changes, regenerate the file deliberately with:

  .venv/bin/python -c "from retvana.config import example_plan; open('examples/example_household.json', 'w').write(example_plan().to_json() + '\\n')"
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, '..', 'examples', 'example_household.json')
REGEN = ('.venv/bin/python -c "from retvana.config import example_plan; '
         "open('examples/example_household.json', 'w').write(example_plan().to_json() + '\\n')\"")

from retvana.config import Plan, example_plan   # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


exists = os.path.isfile(PATH)
check('examples/example_household.json exists', exists, '' if exists else f'regenerate with: {REGEN}')

if exists:
    with open(PATH, encoding='utf-8', newline='') as f:
        text = f.read()
    expected = example_plan().to_json() + '\n'

    same = text == expected
    detail = ''
    if not same:
        a, b = text.splitlines(), expected.splitlines()
        if a == b:
            where = 'content matches but line endings or the single trailing newline differ'
        else:
            line = next((i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)) + 1)
            where = f'first difference at line {line} ({len(a)} lines in file, {len(b)} expected)'
        detail = f'{where}; if example_plan() changed on purpose, regenerate with: {REGEN}'
    check('file equals example_plan().to_json() plus one trailing newline', same, detail)

    try:
        loaded = Plan.from_json(text)
        err = ''
    except Exception as e:   # report, do not crash: the check must print its verdict
        loaded, err = None, f'{type(e).__name__}: {e}'
    check('file loads with Plan.from_json', loaded is not None, err)
    if loaded is not None:
        check('loaded plan equals example_plan()', loaded == example_plan())
        check('loaded plan round-trips through to_json', loaded.to_json() + '\n' == text)

print('\nEXAMPLES CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
