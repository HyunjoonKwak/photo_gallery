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
  path      TEXT,               -- filename (display)
  taken_at  TEXT,
  thumb_key TEXT,               -- thumbnail cache_key
  width     INTEGER,
  height    INTEGER,
  size      INTEGER,
  camera    TEXT,
  sha256    TEXT,               -- exact-duplicate hash (over thumbnail bytes)
  phash     TEXT                -- 64-bit perceptual hash, hex
);

CREATE INDEX IF NOT EXISTS idx_photo_cache_taken_at ON photo_cache (taken_at);
CREATE INDEX IF NOT EXISTS idx_photo_cache_space ON photo_cache (space);

-- Background jobs (dedup scan 등): SQLite에 영속화해 재시작에도 상태 유지.
CREATE TABLE IF NOT EXISTS job (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  type         TEXT NOT NULL,   -- dedup_scan
  space        TEXT NOT NULL,
  status       TEXT NOT NULL,   -- running | done | failed | cancelled
  processed    INTEGER NOT NULL DEFAULT 0,
  total        INTEGER NOT NULL DEFAULT 0,
  error        TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
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

    cache_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(photo_cache)")
    }
    for column in ("sha256", "phash"):
        if column not in cache_columns:
            conn.execute(f"ALTER TABLE photo_cache ADD COLUMN {column} TEXT")

    # A job left 'running' means the server died mid-scan; hashes are already
    # persisted per item, so a re-scan resumes cheaply from photo_cache.
    conn.execute(
        "UPDATE job SET status = 'failed', "
        "error = '서버 재시작으로 중단됨 — 재스캔하면 이어서 진행됩니다.' "
        "WHERE status = 'running'"
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
