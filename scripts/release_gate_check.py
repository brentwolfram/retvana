"""Check the Release_Gate, scripts/release_gate.py (Requirements 6.6-6.9).
  .venv/bin/python scripts/release_gate_check.py
Builds throwaway git repos in a temp dir and runs the real scripts/release_gate.py in them, with a stub
`gitleaks` on a controlled PATH (the directory holding git plus the stub's directory; the real gitleaks,
if installed, is never on it, so this check does not depend on gitleaks being installed):
- a clean repo passes with three PASS summary lines, and the stub ran `git --log-opts=--all` and `dir`,
  both with `--redact` (6.6);
- a stub finding, a forbidden file committed then deleted, and a disallowed author email each exit
  non-zero and fail their own step only;
- a missing gitleaks binary fails the gitleaks step;
- `--pre-push` without the Maintainer_Flag prints exactly the skip notice, exits 0 and never runs the
  stub (6.8); with the flag every step runs (6.7) and a failing step exits non-zero, which blocks the
  push (6.9).
git is isolated from the user's config (GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM=1,
GIT_CEILING_DIRECTORIES) and every identity comes from the environment. Only @example.invalid and
noreply addresses are used. The temp dir is removed afterwards.
"""
import os
import shutil
import subprocess
import sys
import tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, 'release_gate.py')
SKIP_NOTICE = 'release gate skipped: not a maintainer clone'
GOOD = '12345+someone@users.noreply.github.com'
BAD = 'private.person@example.invalid'
STEPS = ['gitleaks', 'forbidden files', 'commit emails']
STUB = '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$STUB_LOG"\nexit "${STUB_EXIT:-0}"\n'
ok = True
def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')
base = tempfile.mkdtemp(prefix='release_gate_check_')
STUB_LOG = os.path.join(base, 'stub.log')
def git_only_dir():
    """A PATH entry that holds git but no gitleaks: git's own dir, or a dir with just a git symlink."""
    git_exe = shutil.which('git')
    if git_exe is None:
        raise RuntimeError('git not found on PATH')
    git_dir = os.path.dirname(git_exe)
    if shutil.which('gitleaks', path=git_dir) is None:
        return git_dir
    link_dir = os.path.join(base, 'gitbin')
    os.makedirs(link_dir)
    os.symlink(os.path.realpath(git_exe), os.path.join(link_dir, 'git'))
    return link_dir
def env_for(path, stub_exit=0, author=GOOD):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(PATH=path, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
               GIT_CEILING_DIRECTORIES=base,
               GIT_AUTHOR_NAME='Test Author', GIT_AUTHOR_EMAIL=author,
               GIT_COMMITTER_NAME='Test Committer', GIT_COMMITTER_EMAIL=GOOD,
               STUB_LOG=STUB_LOG, STUB_EXIT=str(stub_exit))
    return env
def git(repo, *args, author=GOOD):
    res = subprocess.run(['git', *args], cwd=repo, env=env_for(os.environ['PATH'], author=author),
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f'git {args[0]} failed: {res.stderr.strip()}')
    return res.stdout.strip()
def write(repo, rel, data):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb' if isinstance(data, bytes) else 'w') as f:
        f.write(data)
def new_repo(name):
    """A repo whose history and tree pass every step: config files and one text file."""
    repo = os.path.join(base, name)
    os.makedirs(repo)
    git(repo, 'init', '-q', '-b', 'main')
    write(repo, '.gitleaks.toml', '[extend]\nuseDefault = true\n')
    write(repo, '.github/allowed-emails.txt', '*@users.noreply.github.com\nnoreply@github.com\n')
    write(repo, '.binary-allow', 'docs/images/*.png\n')
    write(repo, 'README.md', 'test repo\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', 'initial')
    return repo
def run_gate(repo, path, *args, stub_exit=0):
    if os.path.exists(STUB_LOG):
        os.remove(STUB_LOG)
    res = subprocess.run([sys.executable, GATE, *args], cwd=repo, env=env_for(path, stub_exit),
                         capture_output=True, text=True)
    calls = []
    if os.path.exists(STUB_LOG):
        with open(STUB_LOG, encoding='utf-8') as f:
            calls = f.read().splitlines()
    return res.returncode, res.stdout, res.stdout + res.stderr, calls
def summary(out):
    """{step: 'PASS'|'FAIL'} from the lines after `release gate summary:`."""
    lines = out.split('release gate summary:', 1)
    if len(lines) < 2:
        return {}
    result = {}
    for line in lines[1].strip().splitlines():
        status, _, name = line.strip().partition('  ')
        result[name.strip()] = status
    return result
def expect(label, code, out, failing):
    """Exit and stdout summary match: only the steps in `failing` fail."""
    want = {s: 'FAIL' if s in failing else 'PASS' for s in STEPS}
    got = summary(out)
    exit_ok = code == 0 if not failing else code != 0
    check(label, exit_ok and got == want, f'exit {code}, summary {got}')
try:
    git_dir = git_only_dir()
    stub_dir = os.path.join(base, 'stubbin')
    os.makedirs(stub_dir)
    stub = os.path.join(stub_dir, 'gitleaks')
    write(stub_dir, 'gitleaks', STUB)
    os.chmod(stub, 0o755)
    with_stub = os.pathsep.join([stub_dir, git_dir])
    check('controlled PATH resolves gitleaks to the stub',
          shutil.which('gitleaks', path=with_stub) == stub)
    check('PATH without the stub has no gitleaks', shutil.which('gitleaks', path=git_dir) is None)
    # ------------------------------------------------------------ by hand -------------------------
    repo = new_repo('clean')
    code, stdout, out, calls = run_gate(repo, with_stub)
    expect('clean repo exits 0 with three PASS lines', code, stdout, [])
    hist = [c for c in calls if c.startswith('git ')]
    tree = [c for c in calls if c.startswith('dir ')]
    check('stub ran gitleaks git --log-opts=--all with --redact',
          len(hist) == 1 and '--log-opts=--all' in hist[0].split() and '--redact' in hist[0].split(),
          repr(hist))
    check('stub ran gitleaks dir with --redact',
          len(tree) == 1 and '--redact' in tree[0].split(), repr(tree))
    check('stub got the repo .gitleaks.toml as --config',
          all(os.path.join(os.path.realpath(repo), '.gitleaks.toml') in c for c in calls), repr(calls))
    code, stdout, out, calls = run_gate(repo, with_stub, stub_exit=1)
    expect('stub gitleaks finding exits non-zero, gitleaks FAIL only', code, stdout, ['gitleaks'])
    code, stdout, out, calls = run_gate(repo, git_dir)
    expect('missing gitleaks exits non-zero, gitleaks FAIL only', code, stdout, ['gitleaks'])
    check('missing gitleaks is named', 'gitleaks not found on PATH' in out)
    repo = new_repo('no_config')
    git(repo, 'rm', '-q', '.gitleaks.toml')
    git(repo, 'commit', '-q', '-m', 'drop gitleaks config')
    code, stdout, out, calls = run_gate(repo, with_stub)
    expect('missing .gitleaks.toml exits non-zero, gitleaks FAIL only', code, stdout, ['gitleaks'])
    check('missing .gitleaks.toml never runs the stub', calls == [], repr(calls))
    repo = new_repo('forbidden')
    write(repo, 'data/plan.xlsx', 'not really a spreadsheet\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', 'add file')
    git(repo, 'rm', '-q', 'data/plan.xlsx')
    git(repo, 'commit', '-q', '-m', 'remove file')
    code, stdout, out, calls = run_gate(repo, with_stub)
    expect('forbidden file in history exits non-zero, forbidden files FAIL only', code, stdout,
           ['forbidden files'])
    repo = new_repo('bad_email')
    git(repo, 'commit', '-q', '--allow-empty', '-m', 'bad author', author=BAD)
    code, stdout, out, calls = run_gate(repo, with_stub)
    expect('disallowed author email exits non-zero, commit emails FAIL only', code, stdout,
           ['commit emails'])
    check('gate output never holds the disallowed email', BAD.lower() not in out.lower())
    # ------------------------------------------------------------ --pre-push ----------------------
    repo = new_repo('contributor')
    code, stdout, out, calls = run_gate(repo, with_stub, '--pre-push')
    check('--pre-push without the flag exits 0 with exactly the skip notice',
          code == 0 and stdout.strip() == SKIP_NOTICE and out.strip() == SKIP_NOTICE,
          f'exit {code}, {stdout.strip()!r}')
    check('--pre-push without the flag never runs gitleaks', calls == [], repr(calls))
    git(repo, 'config', '--local', 'retvana.maintainer', 'false')
    code, stdout, out, calls = run_gate(repo, with_stub, '--pre-push')
    check('--pre-push with the flag false skips',
          code == 0 and stdout.strip() == SKIP_NOTICE and calls == [], f'exit {code}')
    git(repo, 'config', '--local', 'retvana.maintainer', 'true')
    code, stdout, out, calls = run_gate(repo, with_stub, '--pre-push')
    expect('--pre-push with the flag runs every step and passes', code, stdout, [])
    check('--pre-push with the flag runs gitleaks git and dir',
          sorted(c.split()[0] for c in calls) == ['dir', 'git'], repr(calls))
    check('--pre-push with the flag prints no skip notice', SKIP_NOTICE not in out)
    code, stdout, out, calls = run_gate(repo, with_stub, '--pre-push', stub_exit=1)
    expect('--pre-push with the flag and a finding exits non-zero', code, stdout, ['gitleaks'])
    git(repo, 'config', '--local', 'retvana.maintainer', 'maybe')
    code, stdout, out, calls = run_gate(repo, with_stub, '--pre-push')
    check('--pre-push with an invalid flag exits 2', code == 2 and calls == [], f'exit {code}')
    # ------------------------------------------------------------ not a repo ----------------------
    outside = os.path.join(base, 'not_a_repo')
    os.makedirs(outside)
    code, stdout, out, calls = run_gate(outside, with_stub)
    check('outside a git repo exits 2', code == 2 and 'not inside a git repository' in out,
          f'exit {code}')
finally:
    shutil.rmtree(base, ignore_errors=True)
check('temp dir removed', not os.path.exists(base))
print('\nRELEASE GATE CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
