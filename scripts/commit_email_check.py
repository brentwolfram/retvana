"""Check the Commit_Email_Check (Requirements 6.10 and 6.11).
  .venv/bin/python scripts/commit_email_check.py
Builds throwaway git repos in a temp dir and runs scripts/check_commit_emails.py against them:
- --all: an allowed history passes; an author-only and a committer-only disallowed email each fail
  with `<hash>: author/committer email not allowed` for that commit and that email only; matching is
  case-insensitive; noreply@github.com (GitHub's own commits) is allowed; an empty repo passes.
- --pending: the identity of the commit being made, from GIT_AUTHOR_* and GIT_COMMITTER_*.
- The output never contains a disallowed email (6.11).
- A missing or empty --allowed list exits 2 and names the path.
- The committed .github/allowed-emails.txt holds exactly the two patterns (6.10).
git is isolated from the user's config (GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM=1) and every
identity comes from the environment. Only @example.invalid and noreply addresses are used.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
SCRIPT = os.path.join(HERE, 'check_commit_emails.py')
LIST = os.path.join(ROOT, '.github', 'allowed-emails.txt')

GOOD = '12345+someone@users.noreply.github.com'
GOOD_MIXED = '12345+Someone@Users.NoReply.GitHub.COM'
GITHUB = 'noreply@github.com'
BAD = 'private.person@example.invalid'
BAD2 = 'other.person@example.invalid'

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def env_for(author, committer):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
               GIT_AUTHOR_NAME='Test Author', GIT_AUTHOR_EMAIL=author,
               GIT_COMMITTER_NAME='Test Committer', GIT_COMMITTER_EMAIL=committer)
    return env


def git(repo, *args, author=GOOD, committer=GOOD):
    res = subprocess.run(['git', *args], cwd=repo, env=env_for(author, committer),
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f'git {args[0]} failed: {res.stderr.strip()}')
    return res.stdout.strip()


def new_repo(base, name):
    repo = os.path.join(base, name)
    os.makedirs(repo)
    git(repo, 'init', '-q', '-b', 'main')
    return repo


def commit(repo, msg, author=GOOD, committer=GOOD):
    git(repo, 'commit', '-q', '--allow-empty', '-m', msg, author=author, committer=committer)
    return git(repo, 'rev-parse', 'HEAD')


def run(repo, *args, author=GOOD, committer=GOOD):
    res = subprocess.run([sys.executable, SCRIPT, *args], cwd=repo, env=env_for(author, committer),
                         capture_output=True, text=True)
    return res.returncode, res.stdout + res.stderr


def no_email(out, *emails):
    low = out.lower()
    return not any(e.lower() in low for e in emails)


# ---------------------------------------------------------------- committed list (6.10) -------
with open(LIST, encoding='utf-8') as f:
    lines = [ln.strip() for ln in f.read().splitlines()]
patterns = [ln for ln in lines if ln and not ln.startswith('#')]
check('allowed-emails.txt holds exactly the two patterns',
      sorted(patterns) == sorted(['*@users.noreply.github.com', 'noreply@github.com']), repr(patterns))

base = tempfile.mkdtemp(prefix='commit_email_check_')
try:
    # ------------------------------------------------------------ --all --------------------------
    repo = new_repo(base, 'empty')
    code, out = run(repo, '--all')
    check('--all on an empty repo exits 0', code == 0, f'exit {code}')

    repo = new_repo(base, 'clean')
    commit(repo, 'noreply', GOOD, GOOD)
    commit(repo, 'mixed case', GOOD_MIXED, GOOD_MIXED.upper())
    commit(repo, 'web-flow', GOOD, GITHUB)
    commit(repo, 'github both', GITHUB.upper(), GITHUB)
    code, out = run(repo, '--all')
    check('--all on an allowed history exits 0 (case-insensitive, noreply@github.com)',
          code == 0 and out.strip() == '', f'exit {code}')

    repo = new_repo(base, 'author_bad')
    commit(repo, 'ok', GOOD, GOOD)
    h = commit(repo, 'bad author', BAD, GOOD)
    code, out = run(repo, '--all')
    check('--all author-only disallowed exits 1', code == 1, f'exit {code}')
    check('--all author-only reports the hash and author', f'{h}: author email not allowed' in out)
    check('--all author-only does not report committer', 'committer email not allowed' not in out)
    check('--all author-only output never holds the email', no_email(out, BAD))

    repo = new_repo(base, 'committer_bad')
    commit(repo, 'ok', GOOD, GOOD)
    h = commit(repo, 'bad committer', GOOD, BAD)
    code, out = run(repo, '--all')
    check('--all committer-only disallowed exits 1', code == 1, f'exit {code}')
    check('--all committer-only reports the hash and committer', f'{h}: committer email not allowed' in out)
    check('--all committer-only does not report author', 'author email not allowed' not in out)
    check('--all committer-only output never holds the email', no_email(out, BAD))

    repo = new_repo(base, 'other_ref')
    commit(repo, 'ok', GOOD, GOOD)
    git(repo, 'checkout', '-q', '-b', 'side')
    h = commit(repo, 'bad on side branch', BAD, BAD2)
    git(repo, 'checkout', '-q', 'main')
    code, out = run(repo, '--all')
    check('--all checks commits on every ref, both emails',
          code == 1 and f'{h}: author email not allowed' in out
          and f'{h}: committer email not allowed' in out, f'exit {code}')
    check('--all both-bad output never holds either email', no_email(out, BAD, BAD2))

    # ------------------------------------------------------------ --pending ----------------------
    repo = new_repo(base, 'pending')
    code, out = run(repo, '--pending', author=GOOD_MIXED, committer=GITHUB)
    check('--pending with allowed identities exits 0', code == 0, f'exit {code}')
    code, out = run(repo, '--pending', author=BAD, committer=GOOD)
    check('--pending author-only disallowed exits 1 naming author',
          code == 1 and 'pending: author email not allowed' in out
          and 'committer email not allowed' not in out, f'exit {code}')
    check('--pending author-only output never holds the email', no_email(out, BAD))
    code, out = run(repo, '--pending', author=GOOD, committer=BAD)
    check('--pending committer-only disallowed exits 1 naming committer',
          code == 1 and 'pending: committer email not allowed' in out
          and 'author email not allowed' not in out, f'exit {code}')
    check('--pending committer-only output never holds the email', no_email(out, BAD))

    # ------------------------------------------------------------ --allowed list errors ----------
    missing = os.path.join(base, 'no-such-list.txt')
    code, out = run(repo, '--all', '--allowed', missing)
    check('missing --allowed list exits 2 naming the path', code == 2 and missing in out, f'exit {code}')
    empty = os.path.join(base, 'empty-list.txt')
    with open(empty, 'w', encoding='utf-8') as f:
        f.write('\n# only a comment\n\n')
    code, out = run(repo, '--pending', '--allowed', empty)
    check('empty --allowed list exits 2 naming the path', code == 2 and empty in out, f'exit {code}')

    custom = os.path.join(base, 'custom-list.txt')
    with open(custom, 'w', encoding='utf-8') as f:
        f.write('*@example.invalid\n')
    code, out = run(new_repo(base, 'custom'), '--pending', '--allowed', custom, author=BAD, committer=BAD2)
    check('--allowed PATH overrides the committed list', code == 0, f'exit {code}')
finally:
    shutil.rmtree(base, ignore_errors=True)

check('temp dir removed', not os.path.exists(base))
print('\nCOMMIT EMAIL CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
