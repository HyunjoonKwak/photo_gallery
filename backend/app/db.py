"""SQLite initialization for app state (sessions, operation log, photo cache).

The schema follows spec ch.8. Only the ``session`` table is exercised by the
login step; ``operation`` and ``photo_cache`` are created now so later steps
(Undo, timeline cache) can build on a stable schema.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS session (
  token        TEXT PRIMARY KEY,   -- opaque cookie value (never the DSM sid)
  sid          TEXT NOT NULL,      -- DSM session id (server-side only)
  account      TEXT NOT NULL,
  role         TEXT NOT NULL,      -- admin | member
  created_at   TEXT NOT NULL,
  expires_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user          TEXT,
  target_user   TEXT,
  type          TEXT,              -- move | copy | delete | mkdir | rename
  space_from    TEXT,              -- personal | team
  space_to      TEXT,
  payload_json  TEXT,
  status        TEXT,              -- pending | done | undone | failed
  created_at    TEXT,
  undo_deadline TEXT
);

CREATE TABLE IF NOT EXISTS photo_cache (
  file_id   TEXT PRIMARY KEY,
  space     TEXT,
  path      TEXT,
  taken_at  TEXT,
  thumb_key TEXT,
  width     INTEGER,
  height    INTEGER,
  size      INTEGER,
  camera    TEXT
);
"""


def init_db(sqlite_path: str) -> None:
    """Create the SQLite file and tables if they do not yet exist."""
    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(sqlite_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def connect(sqlite_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
