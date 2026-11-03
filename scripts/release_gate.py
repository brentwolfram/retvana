"""Release_Gate: the full leak scan and commit email check over a clone, before a push.

  python scripts/release_gate.py              # run by hand: always runs every step
  python scripts/release_gate.py --pre-push   # the pre-push hook: runs only in a Maintainer_Clone

Steps, run from the clone's root (`git rev-parse --show-toplevel`):

1. gitleaks: `gitleaks git --log-opts=--all` (every commit) and `gitleaks dir .` (working tree), with the
   repo's `.gitleaks.toml` and `--redact`, so no secret value is ever printed. `gitleaks` is found on PATH;
   a missing binary or a missing `.gitleaks.toml` fails the step.
2. forbidden files: `forbidden_files.py --tree` and `forbidden_files.py --history`.
3. commit emails: `check_commit_emails.py --all`.

Every step runs even if an earlier one fails, then one summary line per step is printed, PASS or FAIL.

A Maintainer_Clone has `retvana.maintainer=true` in its own git config. With `--pre-push` in a clone
without it, the gate prints `release gate skipped: not a maintainer clone` and exits 0; contributors are
covered by the pre-commit hooks and CI.

Exit codes: 0 every step passed or the gate was skipped, 1 a step failed, 2 not in a git repo or the
Maintainer_Flag is not a valid boolean. Standard library only.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKIP_NOTICE = 'release gate skipped: not a maintainer clone'
FLAG_KEY = 'retvana.maintainer'


class GateError(Exception):
    pass


def repo_root() -> Path:
    try:
        res = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True, check=False)
    except OSError as exc:
        raise GateError(f'git could not run: {exc.strerror}') from None
    if res.returncode != 0 or not res.stdout.strip():
        raise GateError('not inside a git repository')
    return Path(res.stdout.strip()).resolve()


def is_maintainer_clone(root: Path) -> bool:
    """True when the clone's git config has the Maintainer_Flag set to true."""
    res = subprocess.run(['git', 'config', '--type=bool', '--get', FLAG_KEY],
                         cwd=root, capture_output=True, text=True, check=False)
    if res.returncode == 1:  # key not set
        return False
    if res.returncode != 0:
        raise GateError(f'{FLAG_KEY} is not a valid boolean; fix it with git config or unset it')
    return res.stdout.strip() == 'true'


def display(cmd: list[str], root: Path) -> str:
    """The command as echoed: tool names instead of full paths, files relative to the root."""
    shown = ['python' if cmd[0] == sys.executable else Path(cmd[0]).name]
    for arg in cmd[1:]:
        p = Path(arg)
        shown.append(str(p.relative_to(root)) if p.is_absolute() and p.is_relative_to(root) else arg)
    return ' '.join(shown)


def run(cmd: list[str], root: Path) -> bool:
    """Run one command in the clone root with output passed through; True on exit 0."""
    print(f'$ {display(cmd, root)}', flush=True)
    try:
        res = subprocess.run(cmd, cwd=root, check=False)
    except OSError as exc:
        print(f'could not run {cmd[0]}: {exc.strerror}', file=sys.stderr)
        return False
    return res.returncode == 0


def step_gitleaks(root: Path) -> bool:
    exe = shutil.which('gitleaks')
    if exe is None:
        print('gitleaks not found on PATH; install the pinned version named in CONTRIBUTING',
              file=sys.stderr)
        return False
    config = root / '.gitleaks.toml'
    if not config.is_file():
        print('.gitleaks.toml not found at the repo root', file=sys.stderr)
        return False
    common = ['--config', str(config), '--redact', '--no-banner']
    history = run([exe, 'git', '--log-opts=--all', *common, '.'], root)
    tree = run([exe, 'dir', *common, '.'], root)
    return history and tree


def step_forbidden_files(root: Path) -> bool:
    script = str(SCRIPTS / 'forbidden_files.py')
    tree = run([sys.executable, script, '--tree'], root)
    history = run([sys.executable, script, '--history'], root)
    return tree and history


def step_commit_emails(root: Path) -> bool:
    return run([sys.executable, str(SCRIPTS / 'check_commit_emails.py'), '--all'], root)


STEPS = [
    ('gitleaks', step_gitleaks),
    ('forbidden files', step_forbidden_files),
    ('commit emails', step_commit_emails),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Run the Release_Gate over this clone.')
    ap.add_argument('--pre-push', action='store_true',
                    help='run as the pre-push hook: skip unless this is a Maintainer_Clone')
    args = ap.parse_args(argv)

    try:
        root = repo_root()
        if args.pre_push and not is_maintainer_clone(root):
            print(SKIP_NOTICE)
            return 0
    except GateError as exc:
        print(f'release gate: {exc}', file=sys.stderr)
        return 2

    results = []
    for name, step in STEPS:
        print(f'== {name}', flush=True)
        results.append((name, step(root)))

    print('release gate summary:')
    for name, ok in results:
        print(f'  {"PASS" if ok else "FAIL"}  {name}')
    return 0 if all(ok for _, ok in results) else 1


if __name__ == '__main__':
    sys.exit(main())
