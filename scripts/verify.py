"""Run every verification check in turn and report the overall result.
  .venv/bin/python scripts/verify.py     (or: make verify)
Runs every scripts/*_check.py in name order, then smoke_test.py. Each check runs in its own
process with this interpreter, so one failure does not stop the rest. Exits 0 only if all pass.
The pattern is a strict `_check.py` suffix, so it never runs the golden generator
(make_regression_golden.py), the release gate (release_gate.py) or its helpers
(forbidden_files.py, check_commit_emails.py)."""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TAIL = 15        # lines of output shown for a failing check

checks = sorted(glob.glob(os.path.join(HERE, '*_check.py')))
smoke = os.path.join(HERE, 'smoke_test.py')
if os.path.exists(smoke):
    checks.append(smoke)

results = []
total0 = time.perf_counter()
for path in checks:
    name = os.path.basename(path)
    print(f'running {name} ...', flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, path], capture_output=True, text=True)
    secs = time.perf_counter() - t0
    ok = proc.returncode == 0
    results.append((name, ok, secs, proc.returncode))
    if not ok:
        out = (proc.stdout + proc.stderr).rstrip().splitlines()
        print(f'  {name} FAILED (exit {proc.returncode}), last {min(TAIL, len(out))} lines:')
        for line in out[-TAIL:]:
            print('    ' + line)
total = time.perf_counter() - total0

print()
print(f'{"check":<24} {"result":<7} {"time":>8}')
print('-' * 41)
for name, ok, secs, _ in results:
    print(f'{name:<24} {"PASS" if ok else "FAIL":<7} {secs:>7.1f}s')
print('-' * 41)
passed = sum(ok for _, ok, _, _ in results)
all_ok = bool(results) and passed == len(results)
print(f'{f"{passed}/{len(results)} passed":<32} {total:>7.1f}s')
print('VERIFY', 'PASS' if all_ok else 'FAIL')
sys.exit(0 if all_ok else 1)
