"""App-level login throttling.

The app is a login proxy: if a family member fumbles their password a few times,
DSM's Auto Block can ban our Docker gateway IP and lock out *everyone*. We add
per-account and coarser per-client-IP limits here so repeated failures — even
with rotating account names — are rejected before they reach DSM. Attempts are
persisted in SQLite so the limits survive a container restart.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import connect


def _now() -> datetime:
    return datetime.now(timezone.utc)


def seconds_until_unblocked(
    sqlite_path: str, account: str, *, max_attempts: int, window_seconds: int
) -> int:
    """Return how many seconds the account is locked out, or 0 if it may try.

    Counts failures inside the trailing window; if they reach ``max_attempts``
    the account waits until the oldest counted failure ages out of the window.
    """
    window_start = _now() - timedelta(seconds=window_seconds)
    with connect(sqlite_path) as conn:
        rows = conn.execute(
            "SELECT attempted_at FROM login_attempt "
            "WHERE account = ? AND attempted_at >= ? "
            "ORDER BY attempted_at ASC",
            (account, window_start.isoformat()),
        ).fetchall()

    if len(rows) < max_attempts:
        return 0
    oldest = datetime.fromisoformat(rows[0]["attempted_at"])
    unblock_at = oldest + timedelta(seconds=window_seconds)
    remaining = (unblock_at - _now()).total_seconds()
    return max(0, int(remaining) + 1)


def seconds_until_ip_unblocked(
    sqlite_path: str, client_ip: str, *, max_attempts: int, window_seconds: int
) -> int:
    """Return the IP-wide retry delay, protecting against account rotation."""
    window_start = _now() - timedelta(seconds=window_seconds)
    with connect(sqlite_path) as conn:
        rows = conn.execute(
            "SELECT attempted_at FROM login_ip_attempt "
            "WHERE client_ip = ? AND attempted_at >= ? "
            "ORDER BY attempted_at ASC",
            (client_ip, window_start.isoformat()),
        ).fetchall()

    if len(rows) < max_attempts:
        return 0
    oldest = datetime.fromisoformat(rows[0]["attempted_at"])
    unblock_at = oldest + timedelta(seconds=window_seconds)
    remaining = (unblock_at - _now()).total_seconds()
    return max(0, int(remaining) + 1)


def record_failure(sqlite_path: str, account: str) -> None:
    """Record one failed login attempt for the account (also prunes old rows)."""
    now = _now()
    with connect(sqlite_path) as conn:
        conn.execute(
            "INSERT INTO login_attempt (account, attempted_at) VALUES (?, ?)",
            (account, now.isoformat()),
        )
        # Opportunistic cleanup: drop anything older than a day so the table
        # never grows unbounded.
        cutoff = (now - timedelta(days=1)).isoformat()
        conn.execute("DELETE FROM login_attempt WHERE attempted_at < ?", (cutoff,))
        conn.commit()


def record_ip_failure(sqlite_path: str, client_ip: str) -> None:
    """Record an attempted DSM login for the originating client address."""
    now = _now()
    with connect(sqlite_path) as conn:
        conn.execute(
            "INSERT INTO login_ip_attempt (client_ip, attempted_at) VALUES (?, ?)",
            (client_ip, now.isoformat()),
        )
        cutoff = (now - timedelta(days=1)).isoformat()
        conn.execute("DELETE FROM login_ip_attempt WHERE attempted_at < ?", (cutoff,))
        conn.commit()


def discard_latest_ip_attempt(sqlite_path: str, client_ip: str) -> None:
    """Remove the pre-recorded row after a successful DSM authentication.

    We remove one row rather than clearing the IP history: a valid family login
    must not erase earlier failed attempts made from the same public address.
    """
    with connect(sqlite_path) as conn:
        conn.execute(
            "DELETE FROM login_ip_attempt WHERE rowid = ("
            "SELECT rowid FROM login_ip_attempt WHERE client_ip = ? "
            "ORDER BY attempted_at DESC, rowid DESC LIMIT 1)",
            (client_ip,),
        )
        conn.commit()


def clear_failures(sqlite_path: str, account: str) -> None:
    """Clear an account's failure history after a successful login."""
    with connect(sqlite_path) as conn:
        conn.execute("DELETE FROM login_attempt WHERE account = ?", (account,))
        conn.commit()
