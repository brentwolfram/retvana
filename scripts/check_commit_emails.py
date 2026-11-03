"""Commit_Email_Check: every author and committer email must match the Allowed_Email_List.

  python scripts/check_commit_emails.py --pending   # pre-commit: the identity of the commit being made
  python scripts/check_commit_emails.py --all       # every commit reachable from any ref
  python scripts/check_commit_emails.py --all --allowed PATH

The list is `.github/allowed-emails.txt`: one fnmatch pattern per line, matched case-insensitively.
Blank lines and lines starting with `#` are ignored.

A failure prints `<hash>: author email not allowed` or `<hash>: committer email not allowed` (the hash is
`pending` in --pending mode) and never the email itself.

Exit codes: 0 every email allowed, 1 at least one email not allowed, 2 the list is missing or empty, or
git failed. Runs git in the current directory. Standard library only.
"""
import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_ALLOWED = Path(__file__).resolve().parent.parent / '.github' / 'allowed-emails.txt'
_IDENT_EMAIL = re.compile(r'<([^<>]*)>')


class GitError(Exception):
    pass


def load_patterns(path: Path) -> list[str]:
    """Lower-cased patterns from the list file; exits 2 naming the path if it is missing or empty."""
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        print(f'allowed email list not found: {path}', file=sys.stderr)
        sys.exit(2)
    patterns = [line.strip().lower() for line in text.splitlines()]
    patterns = [p for p in patterns if p and not p.startswith('#')]
    if not patterns:
        print(f'allowed email list is empty: {path}', file=sys.stderr)
        sys.exit(2)
    return patterns


def allowed(email: str, patterns: list[str]) -> bool:
    email = email.strip().lower()
    return bool(email) and any(fnmatch.fnmatchcase(email, p) for p in patterns)


def git(*args: str) -> str:
    try:
        res = subprocess.run(['git', *args], capture_output=True, text=True, check=False)
    except OSError as exc:
        raise GitError(f'git could not run: {exc.strerror}') from None
    if res.returncode != 0:
        # git's stderr can echo an identity; report only the command that failed.
        raise GitError(f'git {args[0]} failed with exit code {res.returncode}')
    return res.stdout


def ident_email(ident: str) -> str:
    """The email in a `Name <email> timestamp tz` ident, or '' if there is none."""
    m = _IDENT_EMAIL.search(ident)
    return m.group(1) if m else ''


def pending_identities() -> list[tuple[str, str, str]]:
    return [('pending',
             ident_email(git('var', 'GIT_AUTHOR_IDENT')),
             ident_email(git('var', 'GIT_COMMITTER_IDENT')))]


def all_identities() -> list[tuple[str, str, str]]:
    # %ae and %ce are the raw recorded emails (no mailmap). An empty repo has no commits: nothing to check.
    if not git('rev-parse', '--all').strip():
        return []
    out = git('log', '--all', '--format=%H%x00%ae%x00%ce')
    rows = []
    for line in out.splitlines():
        if line:
            commit, author, committer = line.split('\x00')
            rows.append((commit, author, committer))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Check commit author and committer emails.')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--pending', action='store_true', help='the identity of the commit being made')
    mode.add_argument('--all', action='store_true', help='every commit reachable from any ref')
    ap.add_argument('--allowed', type=Path, default=DEFAULT_ALLOWED, help='allowed email list file')
    args = ap.parse_args(argv)

    patterns = load_patterns(args.allowed)
    try:
        rows = pending_identities() if args.pending else all_identities()
    except GitError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    failures = 0
    for commit, author, committer in rows:
        if not allowed(author, patterns):
            print(f'{commit}: author email not allowed')
            failures += 1
        if not allowed(committer, patterns):
            print(f'{commit}: committer email not allowed')
            failures += 1
    if failures:
        print(f'commit email check: {failures} email(s) not allowed by {args.allowed}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
