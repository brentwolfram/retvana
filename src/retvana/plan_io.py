"""Plan file loading and saving. The only code that touches the plan file.

The Data_Dir is ``RETVANA_DATA_DIR`` if set and non-empty, otherwise the platform user data
directory for ``retvana`` (``~/Library/Application Support/retvana`` on macOS). The working plan
is ``<Data_Dir>/plan.json``; a save writes ``plan.json.tmp`` first and replaces the file atomically.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from retvana.config import Plan

ENV_VAR = 'RETVANA_DATA_DIR'
PLAN_FILE = 'plan.json'
TEMP_FILE = 'plan.json.tmp'
PERSON_KEYS = ('P1', 'P2')


class PlanFileUnreadable(Exception):
    """The existing plan file cannot be read or parsed, so it must not be overwritten."""

    def __init__(self, path: Path, error: str):
        super().__init__(f'{path}: {error}')
        self.path = path
        self.error = error


@dataclass
class LoadResult:
    path: Path
    plan: Plan | None        # None when missing or unreadable
    error: str | None        # "<ExceptionType>: <message>" when unreadable


def data_dir() -> Path:
    """RETVANA_DATA_DIR if set and non-empty, else platformdirs.user_data_dir('retvana', appauthor=False)."""
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env)
    return Path(platformdirs.user_data_dir('retvana', appauthor=False))


def _parse(text: str) -> Plan:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError(f'plan file must hold a JSON object, not {type(data).__name__}')
    plan = Plan.from_dict(data)
    keys = sorted(p.key for p in plan.people)
    if keys != list(PERSON_KEYS):
        raise ValueError(f'person keys must be exactly P1 and P2, found {keys}')
    return plan


def _read(path: Path) -> tuple[Plan | None, str | None]:
    """(plan, None) when readable, (None, error) when unreadable. The file must exist."""
    try:
        return _parse(path.read_text(encoding='utf-8')), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as e:
        return None, f'{type(e).__name__}: {e}'


def load_saved_plan(directory: Path) -> LoadResult:
    """Load ``plan.json`` from the directory. A missing file gives plan=None and error=None."""
    path = Path(directory) / PLAN_FILE
    if not path.exists():
        return LoadResult(path=path, plan=None, error=None)
    plan, error = _read(path)
    return LoadResult(path=path, plan=plan, error=error)


def save_plan(plan: Plan, directory: Path) -> Path:
    """Write the plan to ``plan.json`` in the directory, creating it if needed.

    Raises PlanFileUnreadable and writes nothing if an existing ``plan.json`` is unreadable.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / PLAN_FILE
    if path.exists():
        _, error = _read(path)
        if error is not None:
            raise PlanFileUnreadable(path, error)
    tmp = directory / TEMP_FILE
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(plan.to_json())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path
