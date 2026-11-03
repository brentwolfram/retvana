"""Check the deployment files (Requirements 1.4 and 7.6). Static file checks only; no Docker.
  .venv/bin/python scripts/deploy_check.py

- docker-compose.yml: every service publishes its ports on 127.0.0.1 only (no port on all
  interfaces, no host networking), and port 8501 is published as 127.0.0.1:8501; read_only is
  true; cap_drop includes ALL; a volume mounts ${RETVANA_HOST_DATA_DIR:?...} at /data and the
  environment sets RETVANA_DATA_DIR=/data (7.6); the service, container and image are named
  retvana (1.4).
  The compose file is parsed with a small block-YAML parser (PyYAML is not a dependency); it
  stops with an error on syntax it does not understand rather than guessing.
- Dockerfile: the final stage is python:3.13-slim pinned by digest, installs the package with
  `pip install .`, and its last USER is retvana (not root or 0).
- .streamlit/config.toml (tomllib): server.address is "localhost".
- Makefile: has up, down, rebuild, logs, status and verify targets; PYTHON ?= .venv/bin/python;
  RETVANA_HOST_DATA_DIR defaults to the platformdirs path and is exported.
"""
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


def read(name):
    with open(os.path.join(ROOT, name), encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------- minimal block YAML ----------
def _strip_comment(line):
    """Remove a trailing # comment that is outside quotes."""
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
        elif ch == '#' and (i == 0 or line[i - 1] in ' \t'):
            break
        out.append(ch)
    return ''.join(out).rstrip()


def _scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in '"\'':
        return s[1:-1]
    if s in ('true', 'True', 'TRUE'):
        return True
    if s in ('false', 'False', 'FALSE'):
        return False
    if s.startswith(('[', '{', '|', '>', '&', '*', '!')):
        raise ValueError(f'unsupported YAML syntax: {s!r}')
    return s


def _split_key(text):
    """'key: value' -> (key, value or None); None if the text is not a mapping entry."""
    m = re.match(r'^("[^"]*"|\'[^\']*\'|[^\s:][^:]*?)\s*:(?:\s+(.*))?$', text)
    if not m:
        return None
    return _scalar(m.group(1)), (m.group(2) if m.group(2) not in (None, '') else None)


def parse_yaml(text):
    lines = []
    for raw in text.splitlines():
        if '\t' in raw[:len(raw) - len(raw.lstrip())]:
            raise ValueError('tab indentation')
        s = _strip_comment(raw)
        if s.strip() and s.strip() != '---':
            lines.append((len(s) - len(s.lstrip(' ')), s.strip()))
    pos = 0

    def block(indent):
        nonlocal pos
        if lines[pos][1].startswith('- ') or lines[pos][1] == '-':
            return seq(indent)
        return mapping(indent)

    def value_after(rest, indent):
        nonlocal pos
        if rest is not None:
            return _scalar(rest)
        if pos < len(lines) and (lines[pos][0] > indent or
                                 (lines[pos][0] == indent and lines[pos][1].startswith('-'))):
            return block(lines[pos][0])
        return None

    def mapping(indent):
        nonlocal pos
        out = {}
        while pos < len(lines) and lines[pos][0] == indent and not lines[pos][1].startswith('-'):
            kv = _split_key(lines[pos][1])
            if kv is None:
                raise ValueError(f'cannot parse line: {lines[pos][1]!r}')
            pos += 1
            out[kv[0]] = value_after(kv[1], indent)
        if pos < len(lines) and lines[pos][0] > indent:
            raise ValueError(f'unexpected indentation: {lines[pos][1]!r}')
        return out

    def seq(indent):
        nonlocal pos
        out = []
        while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith('-'):
            item = lines[pos][1][1:].strip()
            pos += 1
            if not item:
                out.append(value_after(None, indent))
                continue
            kv = _split_key(item)
            if kv is None:
                out.append(_scalar(item))
                continue
            # "- key: value" starts a mapping whose further keys sit at the item's indent
            child = indent + 2
            d = {kv[0]: value_after(kv[1], child)}
            if pos < len(lines) and lines[pos][0] > indent:
                d.update(mapping(lines[pos][0]))
            out.append(d)
        return out

    result = block(lines[0][0]) if lines else {}
    if pos != len(lines):
        raise ValueError(f'unparsed line: {lines[pos][1]!r}')
    return result


# ---------------------------------------------------------------- docker-compose.yml ----------
print('--- docker-compose.yml (1.4, 7.6)')
try:
    compose = parse_yaml(read('docker-compose.yml'))
    parse_err = ''
except (ValueError, OSError) as e:
    compose, parse_err = {}, str(e)
check('compose file parses', not parse_err, parse_err)
services = compose.get('services') or {}
check('compose defines at least one service', isinstance(services, dict) and services,
      f'services={list(services) if isinstance(services, dict) else services!r}')


def port_bindings(spec):
    """One published port entry -> (host_ip, host_port, container_port).
    host_ip is '' when the entry publishes on all interfaces."""
    if isinstance(spec, dict):                      # long syntax
        return (str(spec.get('host_ip', '')), str(spec.get('published', '')),
                str(spec.get('target', '')))
    s = str(spec).split('/')[0]                     # drop /tcp, /udp
    if s.startswith('['):                           # [ipv6]:host:container
        ip, rest = s[1:].split(']', 1)
        parts = rest.lstrip(':').split(':')
        return (ip, parts[0], parts[-1])
    parts = s.split(':')
    if len(parts) == 3:
        return tuple(parts)
    if len(parts) == 2:
        return ('', parts[0], parts[1])
    return ('', '', parts[0])                       # container port only: random host port


for name, svc in (services.items() if isinstance(services, dict) else []):
    svc = svc or {}
    tag = f'service {name}:'
    ports = svc.get('ports') or []
    binds = [port_bindings(p) for p in ports]
    check(f'{tag} no host networking', svc.get('network_mode') != 'host',
          f'network_mode={svc.get("network_mode")!r}')
    for spec, (ip, host, cont) in zip(ports, binds):
        check(f'{tag} port {spec!r} binds 127.0.0.1', ip == '127.0.0.1',
              f'host_ip={ip or "(all interfaces)"!r}')
    check(f'{tag} publishes 127.0.0.1:8501', ('127.0.0.1', '8501', '8501') in binds,
          f'bindings={binds}')
    check(f'{tag} read_only: true', svc.get('read_only') is True,
          f'read_only={svc.get("read_only")!r}')
    caps = svc.get('cap_drop') or []
    check(f'{tag} cap_drop includes ALL', isinstance(caps, list) and 'ALL' in caps,
          f'cap_drop={caps!r}')
    vols = svc.get('volumes') or []
    sources = []
    for v in vols:
        if isinstance(v, dict):
            sources.append((str(v.get('source', '')), str(v.get('target', ''))))
        else:
            # split source:target[:mode] on colons outside ${...} interpolations
            parts = re.findall(r'(?:\$\{[^}]*\}|[^:])+', str(v))
            sources.append((parts[0], parts[1] if len(parts) > 1 else ''))
    data = [(s, t) for s, t in sources
            if re.fullmatch(r'\$\{RETVANA_HOST_DATA_DIR:\?[^}]*\}', s) and t == '/data']
    check(f'{tag} mounts ${{RETVANA_HOST_DATA_DIR:?...}} at /data', bool(data),
          f'volumes={sources}')
    env = svc.get('environment') or {}
    if isinstance(env, list):                       # list form: - KEY=value
        env = dict(str(e).split('=', 1) if '=' in str(e) else (str(e), None) for e in env)
    check(f'{tag} sets RETVANA_DATA_DIR=/data', isinstance(env, dict)
          and env.get('RETVANA_DATA_DIR') == '/data', f'environment={env!r}')
    check(f'{tag} service, container and image are named retvana',
          name == 'retvana' and svc.get('container_name') == 'retvana'
          and str(svc.get('image', '')).split(':')[0] == 'retvana',
          f'service={name!r} container_name={svc.get("container_name")!r} '
          f'image={svc.get("image")!r}')

# ---------------------------------------------------------------- Dockerfile -------------------
print('--- Dockerfile (1.4)')
instrs, buf = [], ''
for raw in read('Dockerfile').splitlines():
    s = raw.strip()
    if not buf and (not s or s.startswith('#')):
        continue
    if buf and s.startswith('#'):                   # comment lines inside a continuation
        continue
    if s.endswith('\\'):
        buf += s[:-1] + ' '
        continue
    instrs.append((buf + s).strip())
    buf = ''
if buf:
    instrs.append(buf.strip())
stages = [i for i, s in enumerate(instrs) if s.split()[0].upper() == 'FROM']
final = instrs[stages[-1]:] if stages else instrs
users = [s.split(None, 1)[1].strip() for s in final
         if s.split()[0].upper() == 'USER' and len(s.split()) > 1]
last = users[-1] if users else None
name = last.split(':')[0] if last else None
check('final stage has a USER instruction', last is not None, f'users={users}')
check('last USER is not root or 0', name not in (None, 'root', '0'), f'USER {last}')
check('last USER is retvana', name == 'retvana', f'USER {last}')
base = instrs[stages[-1]].split()[1] if stages and len(instrs[stages[-1]].split()) > 1 else ''
check('final stage is python:3.13-slim pinned by digest',
      re.fullmatch(r'python:3\.13-slim@sha256:[0-9a-f]{64}', base) is not None, f'FROM {base}')
runs = [s.split(None, 1)[1] for s in final if s.split()[0].upper() == 'RUN' and len(s.split()) > 1]
check('installs the package with pip install . (not editable)',
      any(re.search(r'\bpip install \.(\s|$|&&)', r) for r in runs)
      and not any(re.search(r'\bpip install\b.*\s-e\b|--editable', r) for r in runs),
      f'RUN {runs}')

# ---------------------------------------------------------------- .streamlit/config.toml ------
print('--- .streamlit/config.toml')
with open(os.path.join(ROOT, '.streamlit', 'config.toml'), 'rb') as f:
    cfg = tomllib.load(f)
addr = cfg.get('server', {}).get('address')
check('server.address = "localhost"', addr == 'localhost', f'address={addr!r}')

# ---------------------------------------------------------------- Makefile ---------------------
print('--- Makefile (1.4)')
targets = set()
for line in read('Makefile').splitlines():
    m = re.match(r'^([A-Za-z0-9_.-]+(?:\s+[A-Za-z0-9_.-]+)*)\s*:(?!=)', line)
    if m and not line.startswith('\t'):
        targets.update(m.group(1).split())
for t in ('up', 'down', 'rebuild', 'logs', 'status', 'verify'):
    check(f'Makefile has target {t}', t in targets)
mk = read('Makefile')
check('Makefile sets PYTHON ?= .venv/bin/python',
      re.search(r'^PYTHON\s*\?=\s*\.venv/bin/python\s*$', mk, re.M) is not None)
check('Makefile defaults RETVANA_HOST_DATA_DIR from platformdirs and exports it',
      re.search(r'^RETVANA_HOST_DATA_DIR\s*:?=.*platformdirs\.user_data_dir\([\'"]retvana[\'"]', mk, re.M)
      is not None and re.search(r'^export RETVANA_HOST_DATA_DIR\s*$', mk, re.M) is not None)

print('\nDEPLOY CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
