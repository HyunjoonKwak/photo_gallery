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
  token            TEXT PRIMARY KEY,   -- opaque cookie value (never the DSM sid)
  sid              TEXT NOT NULL,      -- DSM session id (server-side only)
  account          TEXT NOT NULL,
  role             TEXT NOT NULL,      -- admin | member
  can_browse_homes INTEGER NOT NULL DEFAULT 0,  -- may list /homes (admin feature gate)
  created_at       TEXT NOT NULL,
  expires_at       TEXT NOT NULL
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

-- Failed login attempts, used to throttle brute-force tries at the app layer
-- before DSM's own Auto Block can lock out our whole container IP.
CREATE TABLE IF NOT EXISTS login_attempt (
  account      TEXT NOT NULL,
  attempted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_attempt_account
  ON login_attempt (account, attempted_at);
"""


def init_db(sqlite_path: str) -> None:
    """Create the SQLite file and tables if they do not yet exist."""
    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(sqlite_path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created by an earlier schema.

    SQLite cannot ``ADD COLUMN IF NOT EXISTS``, so we probe ``PRAGMA table_info``
    and add only what is missing. Kept additive (never drops/renames) so an
    older DB upgrades in place without data loss.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(session)")}
    if "can_browse_homes" not in columns:
        conn.execute(
            "ALTER TABLE session ADD COLUMN can_browse_homes INTEGER NOT NULL DEFAULT 0"
        )


def connect(sqlite_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets readers and a writer proceed concurrently — a better fit for the
    # async server (and the coming background scan/hash jobs) than the default
    # rollback journal, which serializes everything.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
