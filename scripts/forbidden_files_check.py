"""Check the Forbidden_File_Check, scripts/forbidden_files.py (Requirement 6.2-6.4).
  .venv/bin/python scripts/forbidden_files_check.py
Runs the script as a subprocess against temporary directories and git repositories: every forbidden
extension, non-UTF-8 and NUL files, Binary_Allowlist patterns, PNGs with and without each metadata
chunk, the --files, --tree, --dir and --history modes (a forbidden file committed and then deleted is
still reported), that output never contains file content, and the exit codes.
git runs with global and system config disabled and a throwaway identity. Everything is created under
a temporary directory that is removed afterwards; nothing in the repository is read or written.
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'forbidden_files.py'
MARKER = 'MARKER-CONTENT-q7Zx'           # planted in every file; must never appear in any output
EXTENSIONS = ['.xlsx', '.xls', '.xlsm', '.xlsb', '.ods', '.csv', '.ipynb', '.pdf', '.doc', '.docx',
              '.ppt', '.pptx', '.zip', '.pkl', '.parquet', '.db', '.sqlite']
METADATA_CHUNKS = [b'tEXt', b'iTXt', b'zTXt', b'eXIf']
ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def chunk(ctype, data):
    return struct.pack('>I', len(data)) + ctype + data + struct.pack('>I', zlib.crc32(ctype + data))


def png(extra=b''):
    """A 1x1 greyscale PNG; `extra` chunks go between IHDR and IDAT."""
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 0, 0, 0, 0))
    idat = chunk(b'IDAT', zlib.compress(b'\x00\x00'))
    return b'\x89PNG\r\n\x1a\n' + ihdr + extra + idat + chunk(b'IEND', b'')


def metadata_chunk(ctype):
    payload = {b'tEXt': b'Author\x00' + MARKER.encode(),
               b'iTXt': b'Author\x00\x00\x00\x00\x00' + MARKER.encode(),
               b'zTXt': b'Author\x00\x00' + zlib.compress(MARKER.encode()),
               b'eXIf': b'MM\x00\x2a\x00\x00\x00\x08' + MARKER.encode()}[ctype]
    return chunk(ctype, payload)


def write(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())


ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
           GIT_AUTHOR_NAME='Test Author', GIT_AUTHOR_EMAIL='test@users.noreply.github.com',
           GIT_COMMITTER_NAME='Test Author', GIT_COMMITTER_EMAIL='test@users.noreply.github.com')
outputs = []                             # every stdout+stderr, for the no-content check


def run(args, cwd):
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, env=ENV,
                          capture_output=True, text=True)
    outputs.append(proc.stdout + proc.stderr)
    return proc.returncode, set(proc.stdout.splitlines())


def git(cwd, *args):
    subprocess.run(['git', *args], cwd=cwd, env=ENV, check=True, capture_output=True)


def git_out(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, env=ENV, check=True, capture_output=True,
                          text=True).stdout.strip()


def finding(path, rule):
    return f'{path}: forbidden file ({rule})'


ALLOW = '# test allowlist\n\ndocs/images/*.png\n'
CLEAN_PNG = png()

with tempfile.TemporaryDirectory() as tmp:
    base = Path(os.path.realpath(tmp))
    ENV['GIT_CEILING_DIRECTORIES'] = str(base)

    # ---- --dir: extensions, binary, allowlist, PNG metadata --------------------------------------
    d = base / 'dir'
    expected = set()
    for ext in EXTENSIONS:
        write(d, f'data/file{ext}', MARKER)
        expected.add(finding(f'data/file{ext}', 'extension'))
    write(d, 'data/UPPER.XLSX', MARKER)
    expected.add(finding('data/UPPER.XLSX', 'extension'))
    write(d, 'notes.md', f'plain UTF-8 text {MARKER} caf\u00e9\n')
    write(d, 'nul.txt', f'{MARKER}\x00tail')
    expected.add(finding('nul.txt', 'binary'))
    write(d, 'latin1.txt', MARKER.encode() + b' caf\xe9')
    expected.add(finding('latin1.txt', 'binary'))
    write(d, '.binary-allow', ALLOW)
    write(d, 'docs/images/clean.png', CLEAN_PNG)
    write(d, 'docs/clean.png', CLEAN_PNG)                     # outside the pattern
    expected.add(finding('docs/clean.png', 'binary'))
    write(d, 'docs/images/sub/clean.png', CLEAN_PNG)          # '*' does not cross '/'
    expected.add(finding('docs/images/sub/clean.png', 'binary'))
    for ctype in METADATA_CHUNKS:
        name = f'docs/images/meta_{ctype.decode()}.png'
        write(d, name, png(metadata_chunk(ctype)))
        expected.add(finding(name, 'png metadata'))
    write(d, 'docs/images/private_chunk.png', png(chunk(b'prVt', b'\x00\x01')))   # not metadata
    write(d, 'docs/images/no_iend.png', CLEAN_PNG[:-12])
    expected.add(finding('docs/images/no_iend.png', 'png metadata'))
    write(d, 'docs/images/trailing.png', CLEAN_PNG + MARKER.encode() + b'\x00')
    expected.add(finding('docs/images/trailing.png', 'png metadata'))
    write(d, 'docs/images/renamed.png', b'\xff\xd8\xff\xe0\x00\x10JFIF\x00' + MARKER.encode())
    expected.add(finding('docs/images/renamed.png', 'png metadata'))
    write(d, 'docs/images/sheet.xlsx', MARKER)                 # extension wins over the allowlist
    expected.add(finding('docs/images/sheet.xlsx', 'extension'))
    write(d, '.venv/lib/x.xlsx', MARKER)                       # skipped directories
    write(d, '.git/objects/x.pkl', MARKER)
    code, lines = run(['--dir', str(d)], base)
    check('--dir: exit 1 on findings', code == 1, f'exit {code}')
    check('--dir: exactly the expected findings', lines == expected,
          f'missing {sorted(expected - lines)} extra {sorted(lines - expected)}')
    for ext in EXTENSIONS:
        if finding(f'data/file{ext}', 'extension') not in lines:
            check(f'--dir: {ext} reported as extension', False)
    check('--dir: clean PNG under docs/images/ is allowed',
          not any('docs/images/clean.png' in s for s in lines))
    check('--dir: PNG with a non-metadata chunk is allowed',
          not any('private_chunk' in s for s in lines))
    check('--dir: .venv/ and .git/ are skipped', not any('.venv' in s or '.git/' in s for s in lines))

    c = base / 'clean'
    write(c, 'README.md', 'hello\n')
    write(c, '.binary-allow', ALLOW)
    write(c, 'docs/images/ok.png', CLEAN_PNG)
    code, lines = run(['--dir', str(c)], base)
    check('--dir: clean directory exits 0 with no findings', code == 0 and not lines,
          f'exit {code} {sorted(lines)}')
    na = base / 'noallow'
    write(na, 'docs/images/ok.png', CLEAN_PNG)
    code, lines = run(['--dir', str(na)], base)
    check('--dir: with no .binary-allow every binary file is forbidden',
          code == 1 and lines == {finding('docs/images/ok.png', 'binary')}, f'exit {code} {sorted(lines)}')

    # ---- usage and git errors --------------------------------------------------------------------
    code, _ = run([], base)
    check('no mode: exit 2', code == 2, f'exit {code}')
    code, _ = run(['--tree', '--history'], base)
    check('two modes: exit 2', code == 2, f'exit {code}')
    code, _ = run(['--dir', str(base / 'does-not-exist')], base)
    check('--dir on a missing directory: exit 2', code == 2, f'exit {code}')
    code, _ = run(['--tree'], c)
    check('--tree outside a git repo: exit 2', code == 2, f'exit {code}')
    code, _ = run(['--history'], c)
    check('--history outside a git repo: exit 2', code == 2, f'exit {code}')

    # ---- git repo: --files, --tree, --history ----------------------------------------------------
    r = base / 'repo'
    r.mkdir()
    git(r, 'init', '-q', '-b', 'main')
    write(r, '.binary-allow', ALLOW)
    write(r, '.gitignore', 'ignored/\n')
    write(r, 'README.md', 'hello\n')
    write(r, 'docs/images/ok.png', CLEAN_PNG)
    write(r, 'old.xlsx', MARKER)
    git(r, 'add', '-A')
    git(r, 'commit', '-q', '-m', 'first')
    first = git_out(r, 'rev-parse', 'HEAD')[:12]
    git(r, 'rm', '-q', 'old.xlsx')
    git(r, 'commit', '-q', '-m', 'delete the spreadsheet')
    git(r, 'checkout', '-q', '-b', 'side')
    write(r, 'side/blob.bin', f'{MARKER}\x00'.encode())
    git(r, 'add', '-A')
    git(r, 'commit', '-q', '-m', 'side branch binary')
    side = git_out(r, 'rev-parse', 'HEAD')[:12]
    git(r, 'checkout', '-q', 'main')                          # removes side/ from the work tree

    code, lines = run(['--tree'], r)
    check('--tree: clean committed tree exits 0 (deleted file not in the tree)',
          code == 0 and not lines, f'exit {code} {sorted(lines)}')
    code, lines = run(['--history'], r)
    expected = {finding(f'{first}:old.xlsx', 'extension'), finding(f'{side}:side/blob.bin', 'binary')}
    check('--history: committed-then-deleted file and a binary on another ref are reported',
          code == 1 and lines == expected, f'exit {code} {sorted(lines)}')

    write(r, 'tracked.csv', MARKER)
    git(r, 'add', 'tracked.csv')
    write(r, 'untracked.docx', MARKER)
    write(r, 'untracked_nul.txt', f'{MARKER}\x00')
    write(r, 'ignored/hidden.xlsx', MARKER)
    write(r, 'docs/images/meta.png', png(metadata_chunk(b'tEXt')))
    code, lines = run(['--tree'], r)
    expected = {finding('tracked.csv', 'extension'), finding('untracked.docx', 'extension'),
                finding('untracked_nul.txt', 'binary'), finding('docs/images/meta.png', 'png metadata')}
    check('--tree: tracked and untracked findings, ignored files skipped',
          code == 1 and lines == expected, f'exit {code} {sorted(lines)}')

    code, lines = run(['--files', 'tracked.csv', 'README.md', 'docs/images/ok.png'], r)
    check('--files: only the given files are checked',
          code == 1 and lines == {finding('tracked.csv', 'extension')}, f'exit {code} {sorted(lines)}')
    code, lines = run(['--files', 'README.md', 'docs/images/ok.png'], r)
    check('--files: clean files exit 0', code == 0 and not lines, f'exit {code} {sorted(lines)}')
    code, lines = run(['--files', 'images/meta.png'], r / 'docs')
    check('--files: paths given from a subdirectory are made repo-relative',
          code == 1 and lines == {finding('docs/images/meta.png', 'png metadata')},
          f'exit {code} {sorted(lines)}')
    code, lines = run(['--files', 'gone.txt'], r)
    check('--files: a deleted (missing) file is skipped', code == 0 and not lines, f'exit {code}')

    # ---- no content in any output ----------------------------------------------------------------
    leaked = [o for o in outputs if MARKER in o]
    check(f'no output of {len(outputs)} runs contains file content', not leaked)

print('ALL PASS' if ok else 'SOME CHECKS FAILED')
sys.exit(0 if ok else 1)
