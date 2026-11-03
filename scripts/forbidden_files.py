"""Forbidden_File_Check: reject forbidden file types, unexpected binary files and image metadata.
  python scripts/forbidden_files.py --files F [F ...]   the given files (pre-commit)
  python scripts/forbidden_files.py --tree              tracked + untracked, not-ignored files
  python scripts/forbidden_files.py --dir PATH          every file under PATH (not a git repo),
                                                        skipping .git/ and .venv/
  python scripts/forbidden_files.py --history           every blob reachable from any ref, with
                                                        the path it was committed under
Rules, checked in this order, one finding per file:
  extension     a spreadsheet, notebook, document, archive, pickle or database extension
  binary        not valid UTF-8 or contains a NUL byte, and the path matches no pattern in
                .binary-allow (the Binary_Allowlist)
  png metadata  an allowed PNG that carries tEXt, iTXt, zTXt or eXIf chunks, or cannot be parsed
A finding prints `path: forbidden file (<rule>)`, or `commit:path: forbidden file (<rule>)` in
history mode. Paths are relative to the repository root (or to PATH in --dir mode). File content is
never printed and nothing is written to disk. Exits 1 on any finding, 2 on a usage or git error.
Standard library only; it reads no private data, so it behaves the same in every clone."""
import argparse
import fnmatch
import os
import struct
import subprocess
import sys

FORBIDDEN_EXTENSIONS = frozenset({
    '.xlsx', '.xls', '.xlsm', '.xlsb', '.ods', '.csv', '.ipynb', '.pdf', '.doc', '.docx',
    '.ppt', '.pptx', '.zip', '.pkl', '.parquet', '.db', '.sqlite',
})
ALLOW_FILE = '.binary-allow'
SKIP_DIRS = frozenset({'.git', '.venv'})
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
PNG_METADATA_CHUNKS = frozenset({b'tEXt', b'iTXt', b'zTXt', b'eXIf'})


class GitError(Exception):
    pass


def git(args, cwd=None):
    """Run a read-only git command and return its stdout as bytes."""
    proc = subprocess.run(['git', *args], cwd=cwd, capture_output=True)
    if proc.returncode != 0:
        raise GitError(f'git {args[0]} failed (exit {proc.returncode})')
    return proc.stdout


def load_allowlist(root):
    """Patterns from <root>/.binary-allow; blank lines and # comments ignored. Missing = none."""
    try:
        with open(os.path.join(root, ALLOW_FILE), encoding='utf-8') as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []
    return [s for s in (line.strip() for line in lines) if s and not s.startswith('#')]


def path_allowed(path, patterns):
    """True if the '/'-separated relative path matches a pattern segment by segment,
    so `*` never crosses a '/' (docs/images/*.png does not match docs/images/a/b.png)."""
    parts = path.split('/')
    for pattern in patterns:
        pparts = pattern.strip('/').split('/')
        if len(pparts) == len(parts) and all(
                fnmatch.fnmatchcase(p, q) for p, q in zip(parts, pparts)):
            return True
    return False


def is_binary(data):
    if b'\x00' in data:
        return True
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        return True
    return False


def png_has_metadata(data):
    """True if the PNG carries a metadata chunk, or is not a well-formed chunk stream (fail closed)."""
    if not data.startswith(PNG_SIGNATURE):
        return True
    pos = len(PNG_SIGNATURE)
    while pos + 8 <= len(data):
        length, ctype = struct.unpack('>I4s', data[pos:pos + 8])
        if ctype in PNG_METADATA_CHUNKS:
            return True
        pos += 12 + length               # length, type, data, crc
        if pos > len(data):
            return True                  # truncated chunk
        if ctype == b'IEND':
            return pos != len(data)      # trailing bytes after IEND could hide anything
    return True                          # no IEND


def content_verdict(data):
    """(is binary, PNG metadata or unparseable) for a blob; independent of its path."""
    binary = is_binary(data)
    return binary, binary and png_has_metadata(data)


def content_rule(path, verdict, patterns):
    """The rule broken by content with this verdict at this path, or None. A binary file at an
    allowed .png path must be a clean PNG (a renamed JPEG fails as 'png metadata')."""
    binary, png_bad = verdict
    if not binary:
        return None
    if not path_allowed(path, patterns):
        return 'binary'
    if path.lower().endswith('.png') and png_bad:
        return 'png metadata'
    return None


def extension_rule(path):
    return 'extension' if os.path.splitext(path)[1].lower() in FORBIDDEN_EXTENSIONS else None


def read_local(abspath):
    """File bytes, or the link target for a symlink (what git would store). None if unreadable."""
    try:
        if os.path.islink(abspath):
            return os.fsencode(os.readlink(abspath))
        if not os.path.isfile(abspath):
            return None
        with open(abspath, 'rb') as f:
            return f.read()
    except OSError:
        return None


def check_local(root, relpaths, patterns):
    """Check files on disk. Returns (files checked, findings as (path, rule))."""
    findings, checked = [], 0
    for rel in relpaths:
        rule = extension_rule(rel)
        if rule is None:
            data = read_local(os.path.join(root, rel))
            if data is None:
                continue                 # deleted or not a regular file: nothing to commit
            rule = content_rule(rel, content_verdict(data), patterns)
        checked += 1
        if rule:
            findings.append((rel, rule))
    return checked, findings


def repo_root():
    return os.fsdecode(git(['rev-parse', '--show-toplevel']).rstrip(b'\n'))


def mode_files(files):
    root = repo_root()
    rels = []
    for f in files:
        rel = os.path.relpath(os.path.abspath(f), root)
        rels.append(rel.replace(os.sep, '/'))
    return check_local(root, rels, load_allowlist(root))


def mode_tree():
    root = repo_root()
    out = git(['ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root)
    rels = sorted({os.fsdecode(p) for p in out.split(b'\0') if p})
    return check_local(root, rels, load_allowlist(root))


def mode_dir(path):
    if not os.path.isdir(path):
        raise GitError('--dir: not a directory')
    root = os.path.abspath(path)
    rels = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            rels.append(rel.replace(os.sep, '/'))
    return check_local(root, rels, load_allowlist(root))


class BlobReader:
    """Reads blobs through one `git cat-file --batch` process."""

    def __init__(self, root):
        self.proc = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=root,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def read(self, sha):
        self.proc.stdin.write(sha.encode() + b'\n')
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3:
            raise GitError('git cat-file: unexpected reply')
        data = self.proc.stdout.read(int(header[2]))
        self.proc.stdout.read(1)         # trailing newline
        return data

    def close(self):
        self.proc.stdin.close()
        self.proc.wait()


def mode_history():
    """Every (path, blob) in every commit reachable from any ref, oldest commit first. Each
    (path, rule) is reported once, under the first commit that has it."""
    root = repo_root()
    patterns = load_allowlist(root)
    commits = git(['rev-list', '--all', '--reverse'], cwd=root).decode().split()
    reader = BlobReader(root)
    seen, reported, findings = set(), set(), []
    verdicts = {}                        # blob sha -> content_verdict
    try:
        for commit in commits:
            out = git(['ls-tree', '-r', '-z', '--full-tree', commit], cwd=root)
            for entry in out.split(b'\0'):
                if not entry:
                    continue
                meta, path = entry.split(b'\t', 1)
                _mode, otype, sha = meta.decode().split()
                if otype != 'blob':
                    continue             # submodule commit entries
                path = os.fsdecode(path)
                if (path, sha) in seen:
                    continue
                seen.add((path, sha))
                rule = extension_rule(path)
                if rule is None:
                    if sha not in verdicts:
                        verdicts[sha] = content_verdict(reader.read(sha))
                    rule = content_rule(path, verdicts[sha], patterns)
                if rule and (path, rule) not in reported:
                    reported.add((path, rule))
                    findings.append((f'{commit[:12]}:{path}', rule))
    finally:
        reader.close()
    return len(seen), findings


def main(argv=None):
    ap = argparse.ArgumentParser(description='Reject forbidden file types, unexpected binary '
                                             'files and PNG metadata.')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--files', nargs='+', metavar='F', help='check the given files')
    mode.add_argument('--tree', action='store_true', help='tracked and untracked, not-ignored files')
    mode.add_argument('--dir', metavar='PATH', help='every file under a directory that is not a repo')
    mode.add_argument('--history', action='store_true', help='every blob reachable from any ref')
    args = ap.parse_args(argv)
    try:
        if args.files:
            checked, findings = mode_files(args.files)
        elif args.tree:
            checked, findings = mode_tree()
        elif args.dir:
            checked, findings = mode_dir(args.dir)
        else:
            checked, findings = mode_history()
    except (GitError, OSError) as e:
        print(f'forbidden_files: error: {e}', file=sys.stderr)
        return 2
    for path, rule in findings:
        print(f'{path}: forbidden file ({rule})')
    print(f'forbidden_files: {checked} files checked, {len(findings)} findings', file=sys.stderr)
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
