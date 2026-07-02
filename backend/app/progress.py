"""In-memory bulk-operation progress registry (IMPROVEMENTS B-6 진행 바).

A move/delete/undo request may carry a client-generated ``progress_key``; the
sources report count-based progress ("34/120") through a callback bound to
that key, and the frontend polls ``GET /api/ops/progress`` while its mutation
is pending. This is transient UI feedback for a single-process server, so a
plain dict suffices — entries are TTL-pruned in case a request dies before
clearing its key.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

ProgressFn = Callable[[int, int], None]  # (done, total)

_TTL_SECONDS = 600.0


@dataclass
class ProgressEntry:
    done: int
    total: int
    label: str
    updated: float


_entries: dict[str, ProgressEntry] = {}


def _prune() -> None:
    cutoff = time.monotonic() - _TTL_SECONDS
    for key in [k for k, e in _entries.items() if e.updated < cutoff]:
        _entries.pop(key, None)


def update(key: str, done: int, total: int, label: str) -> None:
    _prune()
    _entries[key] = ProgressEntry(
        done=done, total=total, label=label, updated=time.monotonic()
    )


def clear(key: str | None) -> None:
    if key:
        _entries.pop(key, None)


def get(key: str) -> ProgressEntry | None:
    _prune()
    return _entries.get(key)


def callback(key: str | None, label: str) -> ProgressFn | None:
    """Progress callback bound to a key, or None when no key was sent."""
    if not key:
        return None

    def report(done: int, total: int) -> None:
        update(key, done, total, label)

    return report
