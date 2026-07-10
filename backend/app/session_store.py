"""Server-side session store mapping our opaque cookie token -> DSM sid.

The DSM sid is sensitive (it authorizes file operations) so it must never be
exposed to the browser. We hand the browser only an opaque random token via an
HttpOnly cookie and keep the sid <-> token mapping in SQLite.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db import connect

# In-process TTL cache: get_session은 인증된 '모든' 요청에서 불려 요청당 SQLite
# 왕복(이벤트 루프 블로킹)을 만들었다. 30초 캐시로 흡수하고 삭제 시 즉시 비운다.
_SESSION_TTL = 30.0
_session_cache: dict[str, tuple[float, "Session"]] = {}


@dataclass(frozen=True)
class Session:
    token: str
    sid: str
    account: str
    role: str
    can_browse_homes: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(
    sqlite_path: str,
    *,
    sid: str,
    account: str,
    role: str,
    can_browse_homes: bool,
    ttl_seconds: int,
) -> Session:
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(seconds=ttl_seconds)
    with connect(sqlite_path) as conn:
        conn.execute(
            "INSERT INTO session "
            "(token, sid, account, role, can_browse_homes, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                sid,
                account,
                role,
                int(can_browse_homes),
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        conn.commit()
    return Session(
        token=token,
        sid=sid,
        account=account,
        role=role,
        can_browse_homes=can_browse_homes,
    )


def get_session(sqlite_path: str, token: str) -> Session | None:
    """Return a live session, or None if missing/expired (expired rows pruned)."""
    import time as _t

    hit = _session_cache.get(token)
    if hit and (_t.monotonic() - hit[0]) < _SESSION_TTL:
        return hit[1]
    with connect(sqlite_path) as conn:
        row = conn.execute(
            "SELECT token, sid, account, role, can_browse_homes, expires_at "
            "FROM session WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            conn.execute("DELETE FROM session WHERE token = ?", (token,))
            conn.commit()
            return None
    session = Session(
        token=row["token"],
        sid=row["sid"],
        account=row["account"],
        role=row["role"],
        can_browse_homes=bool(row["can_browse_homes"]),
    )
    _session_cache[token] = (_t.monotonic(), session)
    return session


def delete_session(sqlite_path: str, token: str) -> str | None:
    """Remove a session, returning its sid so the caller can DSM-logout."""
    with connect(sqlite_path) as conn:
        row = conn.execute(
            "SELECT sid FROM session WHERE token = ?", (token,)
        ).fetchone()
        conn.execute("DELETE FROM session WHERE token = ?", (token,))
        conn.commit()
    _session_cache.pop(token, None)
    if row:
        _drop_sid_caches(row["sid"])
    return row["sid"] if row else None


def purge_expired(sqlite_path: str) -> None:
    with connect(sqlite_path) as conn:
        expired = [
            r["sid"]
            for r in conn.execute(
                "SELECT sid FROM session WHERE expires_at <= ?",
                (_now().isoformat(),),
            )
        ]
        conn.execute("DELETE FROM session WHERE expires_at <= ?", (_now().isoformat(),))
        conn.commit()
    _session_cache.clear()
    for sid in expired:
        _drop_sid_caches(sid)


def _drop_sid_caches(sid: str) -> None:
    """만료/로그아웃된 세션의 프로세스 캐시 회수 — 예전엔 sid 키 캐시들이
    로그인마다 쌓이기만 하고 영구 잔존했다(메모리 누수)."""
    try:
        from .photos.dsm_source import drop_session_caches

        drop_session_caches(sid)
    except Exception:  # noqa: BLE001 - 회수는 best-effort
        pass
