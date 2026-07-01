"""Unit tests for the server-side session store."""

from datetime import datetime, timedelta, timezone

import pytest

from app import session_store
from app.db import connect, init_db


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "app.db")
    init_db(path)
    return path


def test_create_and_get_roundtrip(db_path):
    created = session_store.create_session(
        db_path,
        sid="SID123",
        account="alice",
        role="admin",
        can_browse_homes=True,
        ttl_seconds=3600,
    )
    fetched = session_store.get_session(db_path, created.token)
    assert fetched is not None
    assert fetched.sid == "SID123"
    assert fetched.account == "alice"
    assert fetched.role == "admin"
    assert fetched.can_browse_homes is True


def test_member_can_browse_homes_false(db_path):
    created = session_store.create_session(
        db_path,
        sid="s",
        account="bob",
        role="member",
        can_browse_homes=False,
        ttl_seconds=3600,
    )
    fetched = session_store.get_session(db_path, created.token)
    assert fetched is not None
    assert fetched.can_browse_homes is False


def test_get_unknown_token_returns_none(db_path):
    assert session_store.get_session(db_path, "nope") is None


def test_delete_returns_sid_and_removes(db_path):
    created = session_store.create_session(
        db_path,
        sid="SIDX",
        account="a",
        role="member",
        can_browse_homes=False,
        ttl_seconds=3600,
    )
    assert session_store.delete_session(db_path, created.token) == "SIDX"
    assert session_store.get_session(db_path, created.token) is None
    # Deleting again returns None (already gone).
    assert session_store.delete_session(db_path, created.token) is None


def test_expired_session_is_pruned_on_get(db_path):
    created = session_store.create_session(
        db_path,
        sid="s",
        account="a",
        role="member",
        can_browse_homes=False,
        ttl_seconds=3600,
    )
    # Force expiry into the past.
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE session SET expires_at = ? WHERE token = ?", (past, created.token)
        )
        conn.commit()

    assert session_store.get_session(db_path, created.token) is None
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM session WHERE token = ?", (created.token,)
        ).fetchone()
    assert row is None  # pruned, not just hidden


def test_purge_expired_removes_only_expired(db_path):
    live = session_store.create_session(
        db_path, sid="s", account="live", role="member",
        can_browse_homes=False, ttl_seconds=3600,
    )
    dead = session_store.create_session(
        db_path, sid="s", account="dead", role="member",
        can_browse_homes=False, ttl_seconds=3600,
    )
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE session SET expires_at = ? WHERE token = ?", (past, dead.token)
        )
        conn.commit()

    session_store.purge_expired(db_path)
    assert session_store.get_session(db_path, live.token) is not None
    assert session_store.get_session(db_path, dead.token) is None
