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
  phash     TEXT,               -- 64-bit perceptual hash, hex
  thumbhash TEXT                -- blur placeholder, base64 (B-2)
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

-- A second, coarser throttle stops account-name rotation from bypassing the
-- per-account limit. NPM supplies the real client address to the login route.
CREATE TABLE IF NOT EXISTS login_ip_attempt (
  client_ip    TEXT NOT NULL,
  attempted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_ip_attempt_ip
  ON login_ip_attempt (client_ip, attempted_at);

-- 1차 구역(기기 백업 zone): 로그인 사용자별로 등록한, Synology Photos 인덱스
-- 밖의 폴더. 여기 사진은 타임라인에 안 나오고, 앱이 FileStation으로 탐색해
-- 이벤트별로 개인 Photos(2차)로 옮기는 워크플로의 소스가 된다.
CREATE TABLE IF NOT EXISTS zone_config (
  account    TEXT NOT NULL,
  id         TEXT NOT NULL,      -- 앱 생성 id (secrets)
  root_path  TEXT NOT NULL,      -- 절대경로 (/homes/<account>/… 또는 /photo/…)
  label      TEXT NOT NULL,      -- 표시 이름
  created_at TEXT NOT NULL,
  PRIMARY KEY (account, id)
);

-- 정리 마법사: 공용으로 복사한 개인 아이템(클러스터 재구성돼도 아이템 단위로
-- 안정적으로 "이미 복사됨"을 판정). undo로 복사를 되돌려도 남는다(v2 한계).
CREATE TABLE IF NOT EXISTS organize_copied (
  user      TEXT NOT NULL,
  file_id   TEXT NOT NULL,
  copied_at TEXT NOT NULL,
  PRIMARY KEY (user, file_id)
);

-- 타임라인 일자 버킷 L2 캐시 (scope = "team" | "personal:<account>").
-- 전량 스캔(69k 기준 수십 초)을 재시작·세션마다 반복하지 않기 위한 영속층.
-- updated_at=0 은 "stale" 표식(쓰기 후) — 조회는 즉시 서빙 + 백그라운드 재스캔.
-- 정리 마법사 세션(이어하기): 사용자당 1행, step과 단계별 처리 통계.
CREATE TABLE IF NOT EXISTS workflow_session (
  user       TEXT PRIMARY KEY,
  step       INTEGER NOT NULL DEFAULT 1,   -- 1 중복 | 2 잡동사니 | 3 이벤트 | 4 요약
  stats_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bucket_cache (
  scope  TEXT NOT NULL,
  day    TEXT NOT NULL,
  count  INTEGER NOT NULL,
  PRIMARY KEY (scope, day)
);
CREATE TABLE IF NOT EXISTS bucket_meta (
  scope      TEXT PRIMARY KEY,
  updated_at REAL NOT NULL
);
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
    for column in ("sha256", "phash", "thumbhash"):
        if column not in cache_columns:
            conn.execute(f"ALTER TABLE photo_cache ADD COLUMN {column} TEXT")

    zone_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(zone_config)")
    }
    if "last_seen_at" not in zone_columns:
        # 신규 유입 뱃지 기준 시각 — 기존 행은 지금부터 센다(과거분 폭탄 방지).
        conn.execute("ALTER TABLE zone_config ADD COLUMN last_seen_at TEXT")
        conn.execute(
            "UPDATE zone_config SET last_seen_at = datetime('now') "
            "WHERE last_seen_at IS NULL"
        )

    # A job left 'running' means the server died mid-scan; hashes are already
    # persisted per item, so a re-scan resumes cheaply from photo_cache.
    conn.execute(
        "UPDATE job SET status = 'failed', "
        "error = '서버 재시작으로 중단됨 — 재스캔하면 이어서 진행됩니다.' "
        "WHERE status = 'running'"
    )


def load_buckets(
    sqlite_path: str, scope: str, ttl: float
) -> tuple[list[tuple[str, int]], bool]:
    """(rows, fresh) — rows는 day 내림차순 (day, count), fresh는 TTL 이내 여부."""
    import time as _t

    with connect(sqlite_path) as conn:
        meta = conn.execute(
            "SELECT updated_at FROM bucket_meta WHERE scope = ?", (scope,)
        ).fetchone()
        if meta is None:
            return [], False
        rows = [
            (r["day"], r["count"])
            for r in conn.execute(
                "SELECT day, count FROM bucket_cache WHERE scope = ? "
                "ORDER BY day DESC",
                (scope,),
            )
        ]
    fresh = (_t.time() - meta["updated_at"]) < ttl
    return rows, fresh


def save_buckets(
    sqlite_path: str, scope: str, rows: list[tuple[str, int]]
) -> None:
    import time as _t

    with connect(sqlite_path) as conn:
        conn.execute("DELETE FROM bucket_cache WHERE scope = ?", (scope,))
        conn.executemany(
            "INSERT INTO bucket_cache (scope, day, count) VALUES (?, ?, ?)",
            [(scope, d, c) for d, c in rows],
        )
        conn.execute(
            "INSERT INTO bucket_meta (scope, updated_at) VALUES (?, ?) "
            "ON CONFLICT(scope) DO UPDATE SET updated_at = excluded.updated_at",
            (scope, _t.time()),
        )
        conn.commit()


def mark_buckets_stale(sqlite_path: str, scope: str) -> None:
    with connect(sqlite_path) as conn:
        conn.execute(
            "UPDATE bucket_meta SET updated_at = 0 WHERE scope = ?", (scope,)
        )
        conn.commit()


def connect(sqlite_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets readers and a writer proceed concurrently — a better fit for the
    # async server (and the coming background scan/hash jobs) than the default
    # rollback journal, which serializes everything.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
