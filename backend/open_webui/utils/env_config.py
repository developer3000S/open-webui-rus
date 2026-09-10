"""Tracks which settings were declared in the .env file.

The config table in SQLite outranks everything else at read time, so a value that
an operator pins in .env silently loses to a stale row seeded on a previous
deploy. Recording the names that .env itself declares lets Config treat exactly
those keys as authoritative while the table keeps working for everything else.

Only names coming from the file count. Values the process happens to inherit (the
image's own ENV, a shell export) are not a deployment's declared intent and must
not take over settings the admin UI owns.

Depends on nothing but the stdlib so it stays importable from models/ and testable
without booting the application.
"""

from __future__ import annotations

import re
from pathlib import Path

_LINE = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$')
_UNQUOTED_COMMENT = re.compile(r'\s+#')

_declared: set[str] = set()


def unquote(value: str) -> str:
    """Strip the shell-style quoting a dotenv value carries.

    `docker run --env-file` keeps surrounding quotes inside the value while
    python-dotenv and docker compose remove them, so the same .env yields
    different settings depending on how the container was started. Values are
    normalised on read instead of forcing one quoting style on the file.
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return _UNQUOTED_COMMENT.split(value, maxsplit=1)[0].strip()


def parse_env_file(text: str) -> dict[str, str]:
    """Parse dotenv-style text into {name: value}.

    A name counts as declared even when assigned an empty value, because
    `KEY=` is an explicit statement that the setting is empty. Later lines win,
    matching dotenv.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        match = _LINE.match(line)
        if match:
            values[match.group(1)] = unquote(match.group(2))
    return values


def parse_env_names(text: str) -> set[str]:
    """Return the variable names a dotenv-style file declares."""
    return set(parse_env_file(text))


def record_declared(names: set[str]) -> None:
    """Remember the names read from .env. Called once, from env.py, at import."""
    _declared.update(names)


def declared_names() -> frozenset[str]:
    return frozenset(_declared)


def reset_declared() -> None:
    """Drop the recorded names. For tests."""
    _declared.clear()


def env_name_for(key: str) -> str:
    """The .env name a dotted config key is configured by.

    `rag.embedding_batch_size` -> `RAG_EMBEDDING_BATCH_SIZE`, which is the name
    config.py reads to build the key's default.
    """
    return key.upper().replace('.', '_')


def is_declared_in_env(key: str) -> bool:
    """True when .env pins this config key, so .env outranks the stored row."""
    return env_name_for(key) in _declared


def read_env_file(path: Path) -> set[str]:
    """Parse a .env file if present and record its names. Returns what was found."""
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return set()
    names = parse_env_names(text)
    record_declared(names)
    return names
