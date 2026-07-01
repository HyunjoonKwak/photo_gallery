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
    return Session(
        token=row["token"],
        sid=row["sid"],
        account=row["account"],
        role=row["role"],
        can_browse_homes=bool(row["can_browse_homes"]),
    )


def delete_session(sqlite_path: str, token: str) -> str | None:
    """Remove a session, returning its sid so the caller can DSM-logout."""
    with connect(sqlite_path) as conn:
        row = conn.execute(
            "SELECT sid FROM session WHERE token = ?", (token,)
        ).fetchone()
        conn.execute("DELETE FROM session WHERE token = ?", (token,))
        conn.commit()
    return row["sid"] if row else None


def purge_expired(sqlite_path: str) -> None:
    with connect(sqlite_path) as conn:
        conn.execute("DELETE FROM session WHERE expires_at <= ?", (_now().isoformat(),))
        conn.commit()
