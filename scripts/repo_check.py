"""Check the repository layout and configuration rules that no other check covers.
  .venv/bin/python scripts/repo_check.py
Covers Requirements 1.2, 1.3, 3.3, 6.5, 8.4, 9.2, 9.3, 10.1 and 10.4:
  - no requirements*.txt files; pyproject.toml sets requires-python and pins every runtime,
    optional and build dependency with `==`
  - .gitignore excludes data directories, spreadsheets, plan JSON outside examples/, .venv/,
    .kiro/settings/ and tasks.meta.json in every spec directory
  - the Example_Plan uses exactly the person keys P1 and P2, and every owner is one of them
  - no file with a forbidden extension (the list in scripts/forbidden_files.py) is in the repo
  - the required docs, steering files, baseline spec and GitHub files are present
  - Dependabot covers pip, GitHub Actions and Docker
Inside a git work tree the file list is `git ls-files`; outside one (the Migration's staging tree)
it is a directory walk that skips .git/, .venv/, __pycache__/ and *.egg-info/. This check reads
only and writes no file. Standard library only, plus the installed retvana package."""
import importlib.util
import os
import re
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))

from retvana.config import example_plan   # noqa: E402

# Reuse the Forbidden_File_Check's extension list rather than keeping a second copy.
_spec = importlib.util.spec_from_file_location('forbidden_files', os.path.join(HERE, 'forbidden_files.py'))
forbidden_files = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(forbidden_files)
FORBIDDEN_EXTENSIONS = forbidden_files.FORBIDDEN_EXTENSIONS

REQUIRED_FILES = [
    'README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CODE_OF_CONDUCT.md', 'CHANGELOG.md', 'LICENSE',
    'pyproject.toml', '.gitignore',
    'docs/assumptions.md',
    'examples/example_household.json',
    '.kiro/steering/product.md', '.kiro/steering/tech.md', '.kiro/steering/structure.md',
    '.kiro/specs/engine-baseline/requirements.md',
    '.kiro/specs/engine-baseline/design.md',
    '.kiro/specs/engine-baseline/tasks.md',
    '.github/workflows/ci.yml', '.github/workflows/release.yml',
    '.github/dependabot.yml',
    '.github/ISSUE_TEMPLATE/bug_report.yml',
    '.github/ISSUE_TEMPLATE/feature_request.yml',
    '.github/ISSUE_TEMPLATE/config.yml',
    '.github/PULL_REQUEST_TEMPLATE.md',
    '.github/allowed-emails.txt',
    '.gitleaks.toml', '.binary-allow', '.pre-commit-config.yaml',
]

# Patterns .gitignore must contain, as written in the file (Requirements 6.5 and 10.4).
REQUIRED_IGNORES = [
    ('data directories', ['data/', '.data/', 'retvana-data/']),
    ('spreadsheets', ['*.xlsx', '*.xlsm', '*.xls', '*.ods', '*.csv']),
    ('the working plan', ['plan.json', 'plan.json.tmp']),
    ('plan JSON outside examples/', ['*[Pp]lan*.json', '!/examples/**/*.json']),
    ('virtual environment', ['.venv/']),
    ('Kiro local settings', ['.kiro/settings/']),
    ('tasks.meta.json in every spec directory', ['.kiro/specs/**/tasks.meta.json']),
]

# Behaviour probes for `git check-ignore --no-index`, run only inside a git work tree.
IGNORED_PROBES = [
    'data/plan.json', '.data/x.json', 'retvana-data/plan.json', 'plan.json', 'plan.json.tmp',
    'Book.xlsx', 'sub/Book.xlsx', 'my_plan.json', 'downloads/retvana-plan.json',
    '.venv/bin/python', '.kiro/settings/mcp.json',
    '.kiro/specs/engine-baseline/tasks.meta.json', '.kiro/specs/x/tasks.meta.json',
]
NOT_IGNORED_PROBES = [
    'examples/example_household.json', 'examples/example_plan.json', 'pyproject.toml',
    '.kiro/specs/engine-baseline/tasks.md',
]

PIN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9._,\s-]*\])?\s*==\s*[A-Za-z0-9.+!_-]+\s*(;.*)?$')
SKIP_DIRS = {'.git', '.venv', '__pycache__'}

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def in_git_work_tree():
    try:
        proc = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=ROOT,
                              capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return proc.returncode == 0 and proc.stdout.strip() == 'true'


def repo_files(git_mode):
    """Repository-relative '/'-separated paths: tracked files, or a directory walk."""
    if git_mode:
        out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True).stdout
        return sorted(p for p in out.decode('utf-8').split('\0') if p)
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith('.egg-info')]
        rel = os.path.relpath(dirpath, ROOT)
        for name in filenames:
            files.append(name if rel == '.' else f'{rel}/{name}'.replace(os.sep, '/'))
    return sorted(files)


def short(items, n=5):
    items = list(items)
    return ', '.join(items[:n]) + (f' (+{len(items) - n} more)' if len(items) > n else '')


git_mode = in_git_work_tree()
print(f'file list: {"git ls-files" if git_mode else "directory walk (not a git work tree)"}')
files = repo_files(git_mode)

# --- Required files (8.4, 9.2, 10.1; LICENSE and the docs the README points to) ---
missing = [p for p in REQUIRED_FILES if not os.path.isfile(os.path.join(ROOT, p))]
check(f'{len(REQUIRED_FILES)} required files present', not missing, f'missing: {short(missing, 10)}' if missing else '')
if git_mode:
    tracked = set(files)
    untracked = [p for p in REQUIRED_FILES if p not in missing and p not in tracked]
    check('required files are tracked by git', not untracked, f'untracked: {short(untracked, 10)}' if untracked else '')
lic = os.path.join(ROOT, 'LICENSE')
if os.path.isfile(lic):
    with open(lic, encoding='utf-8') as f:
        text = f.read()
    check('LICENSE is the Apache License 2.0', 'Apache License' in text and 'Version 2.0' in text)

# --- No requirements*.txt (1.3) ---
reqs = [p for p in files if re.fullmatch(r'requirements.*\.txt', p.rsplit('/', 1)[-1])]
check('no requirements*.txt files', not reqs, short(reqs) if reqs else '')

# --- pyproject.toml (1.2) ---
try:
    with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as f:
        pyproject = tomllib.load(f)
    err = ''
except (OSError, tomllib.TOMLDecodeError) as e:
    pyproject, err = None, f'{type(e).__name__}: {e}'
check('pyproject.toml parses', pyproject is not None, err)
if pyproject is not None:
    project = pyproject.get('project', {})
    check('project.name is retvana', project.get('name') == 'retvana', repr(project.get('name')))
    check('project.requires-python is set', bool(project.get('requires-python')))
    deps = project.get('dependencies', [])
    check('project.dependencies is not empty', bool(deps))
    groups = {'dependencies': deps}
    for name, group in project.get('optional-dependencies', {}).items():
        groups[f'optional-dependencies.{name}'] = group
    groups['build-system.requires'] = pyproject.get('build-system', {}).get('requires', [])
    for name, group in groups.items():
        loose = [d for d in group if not PIN.match(d.strip())]
        check(f'{name}: all {len(group)} pinned with ==', not loose, f'not pinned: {short(loose)}' if loose else '')

# --- .gitignore (6.5, 10.4) ---
gi_path = os.path.join(ROOT, '.gitignore')
if os.path.isfile(gi_path):
    with open(gi_path, encoding='utf-8') as f:
        lines = {line.strip() for line in f if line.strip() and not line.lstrip().startswith('#')}
    for label, patterns in REQUIRED_IGNORES:
        absent = [p for p in patterns if p not in lines]
        check(f'.gitignore excludes {label}', not absent, f'missing: {", ".join(absent)}' if absent else '')
    if git_mode:
        def ignored(path):
            return subprocess.run(['git', 'check-ignore', '--no-index', '-q', path], cwd=ROOT).returncode == 0
        wrong = [p for p in IGNORED_PROBES if not ignored(p)]
        check('git check-ignore: private paths are ignored', not wrong, f'not ignored: {short(wrong)}' if wrong else '')
        wrong = [p for p in NOT_IGNORED_PROBES if ignored(p)]
        check('git check-ignore: example and source paths are not ignored', not wrong,
              f'ignored: {short(wrong)}' if wrong else '')

# --- Example_Plan person keys (3.3) ---
plan = example_plan()
keys = [p.key for p in plan.people]
check('Example_Plan person keys are exactly P1, P2', sorted(keys) == ['P1', 'P2'], repr(keys))
owners = [('account', a.owner) for a in plan.accounts] + [('consulting', c.owner) for c in plan.consulting]
bad = [f'{kind}={owner!r}' for kind, owner in owners if owner not in ('P1', 'P2')]
check(f'all {len(owners)} account and consulting owners are P1 or P2', not bad, short(bad) if bad else '')

# --- Forbidden file types (2.2, 6.4) ---
found = [p for p in files if os.path.splitext(p)[1].lower() in FORBIDDEN_EXTENSIONS]
check(f'no forbidden file types among {len(files)} files', not found, short(found, 10) if found else '')

# --- Dependabot (9.3) ---
dep_path = os.path.join(ROOT, '.github', 'dependabot.yml')
if os.path.isfile(dep_path):
    with open(dep_path, encoding='utf-8') as f:
        ecosystems = set(re.findall(r'^\s*-?\s*package-ecosystem:\s*["\']?([\w-]+)', f.read(), re.M))
    need = {'pip', 'github-actions', 'docker'}
    check('Dependabot covers pip, github-actions and docker', need <= ecosystems,
          f'missing: {", ".join(sorted(need - ecosystems))}' if not need <= ecosystems else '')

print('\nREPO CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
