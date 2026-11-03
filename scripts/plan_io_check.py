"""Check plan file loading and saving (Requirement 7.1-7.5, 7.7-7.9).
  .venv/bin/python scripts/plan_io_check.py
Every case runs in a temporary directory, and RETVANA_DATA_DIR is restored afterwards, so the real
Data_Dir is never read or written. The platformdirs default is compared by path only; nothing is created.
Req 7.4 and 7.9 are App-level: here they are covered by what plan_io gives the App (a missing file
loads as plan None with no error; an unreadable file loads as plan None with an error string).
"""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import platformdirs

from retvana.config import example_plan                                         # noqa: E402
from retvana.plan_io import (ENV_VAR, PLAN_FILE, TEMP_FILE, LoadResult,         # noqa: E402
                             PlanFileUnreadable, data_dir, load_saved_plan, save_plan)

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


saved_env = os.environ.get(ENV_VAR)


def set_env(value):
    if value is None:
        os.environ.pop(ENV_VAR, None)
    else:
        os.environ[ENV_VAR] = value


try:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # Req 7.1: env set
        set_env(str(root / 'custom'))
        check('RETVANA_DATA_DIR set: data_dir() is that directory', data_dir() == root / 'custom',
              str(data_dir()))
        check('data_dir() does not create the directory', not (root / 'custom').exists())

        # Req 7.2: env empty and unset fall back to platformdirs
        default = Path(platformdirs.user_data_dir('retvana', appauthor=False))
        set_env('')
        check('RETVANA_DATA_DIR empty: data_dir() is the platformdirs default', data_dir() == default,
              str(data_dir()))
        set_env(None)
        check('RETVANA_DATA_DIR unset: data_dir() is the platformdirs default', data_dir() == default,
              str(data_dir()))
        if sys.platform == 'darwin':
            check('macOS default is ~/Library/Application Support/retvana',
                  default == Path.home() / 'Library' / 'Application Support' / 'retvana', str(default))

        # Req 7.4: missing file
        missing = root / 'missing'
        r = load_saved_plan(missing)
        check('missing plan.json: plan None, error None, path is <dir>/plan.json',
              isinstance(r, LoadResult) and r.plan is None and r.error is None
              and r.path == missing / PLAN_FILE)
        check('loading a missing file creates nothing', not missing.exists())

        # Req 7.5 + 7.3: save creates the directory, then the file loads back equal
        plan = example_plan()
        target = root / 'new' / 'nested'
        path = save_plan(plan, target)
        check('save creates the Data_Dir and writes plan.json', target.is_dir() and path == target / PLAN_FILE
              and path.is_file())
        check('atomic write leaves no plan.json.tmp', not (target / TEMP_FILE).exists(),
              str(sorted(p.name for p in target.iterdir())))
        r = load_saved_plan(target)
        check('valid plan.json loads with no error and equals the saved plan',
              r.error is None and r.plan is not None and r.plan.to_json() == plan.to_json(), str(r.error))

        # save over a valid existing file replaces it
        plan.start_year += 1
        save_plan(plan, target)
        r = load_saved_plan(target)
        check('save over a valid plan.json replaces it, still no temp file',
              r.plan is not None and r.plan.start_year == plan.start_year and not (target / TEMP_FILE).exists())

        # Req 7.7: unreadable files (bad JSON, non-object, wrong person keys, bad bytes, no permission)
        def write_case(name, content: bytes):
            d = root / name
            d.mkdir()
            (d / PLAN_FILE).write_bytes(content)
            return d

        good = json.loads(example_plan().to_json())
        wrong_keys = json.loads(example_plan().to_json())
        wrong_keys['people'][0]['key'] = 'XX'
        cases = {
            'bad_json': (b'{"start_year": 2033,', 'JSONDecodeError'),
            'not_object': (b'[1, 2, 3]', 'TypeError'),
            'wrong_keys': (json.dumps(wrong_keys).encode(), 'ValueError'),
            'bad_utf8': (b'\xff\xfe\x00garbage', 'UnicodeDecodeError'),
        }
        check('wrong-keys fixture differs from the valid plan only in a person key',
              good['people'][0]['key'] in ('P1', 'P2') and wrong_keys['people'][0]['key'] == 'XX')
        unreadable_dirs = []
        for name, (content, exc) in cases.items():
            d = write_case(name, content)
            unreadable_dirs.append((name, d, content))
            r = load_saved_plan(d)
            check(f'{name}: plan None and error "{exc}: ..." (usable as the disabled-save reason)',
                  r.plan is None and isinstance(r.error, str) and r.error.startswith(f'{exc}: '), str(r.error))

        no_perm = write_case('no_permission', json.dumps(good).encode())
        os.chmod(no_perm / PLAN_FILE, 0)
        perm_effective = not os.access(no_perm / PLAN_FILE, os.R_OK)
        if perm_effective:
            r = load_saved_plan(no_perm)
            check('no read permission: plan None and error "PermissionError: ..."',
                  r.plan is None and isinstance(r.error, str) and r.error.startswith('PermissionError: '),
                  str(r.error))
            unreadable_dirs.append(('no_permission', no_perm, None))
        else:
            print('SKIP  no read permission case (running as a user that ignores file modes)')

        # Req 7.8: save refuses over an unreadable file, leaves it untouched, writes no temp file
        for name, d, content in unreadable_dirs:
            st = (d / PLAN_FILE).stat()
            raised = None
            try:
                save_plan(example_plan(), d)
            except PlanFileUnreadable as e:
                raised = e
            unchanged = (d / PLAN_FILE).stat().st_mtime_ns == st.st_mtime_ns
            if content is not None:
                unchanged &= (d / PLAN_FILE).read_bytes() == content
            check(f'{name}: save raises PlanFileUnreadable, file untouched, no temp file',
                  raised is not None and raised.path == d / PLAN_FILE and raised.error
                  and unchanged and not (d / TEMP_FILE).exists(), str(raised))

        os.chmod(no_perm / PLAN_FILE, stat.S_IRUSR | stat.S_IWUSR)   # so the temp dir can be removed
finally:
    set_env(saved_env)

check('RETVANA_DATA_DIR restored to its value before the check', os.environ.get(ENV_VAR) == saved_env)

print('\nPLAN IO CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
