"""Unit tests for app-level login throttling."""

import pytest

from app import rate_limit
from app.db import init_db


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "app.db")
    init_db(path)
    return path


def test_fresh_account_is_allowed(db_path):
    assert (
        rate_limit.seconds_until_unblocked(
            db_path, "alice", max_attempts=5, window_seconds=600
        )
        == 0
    )


def test_below_limit_still_allowed(db_path):
    for _ in range(4):
        rate_limit.record_failure(db_path, "alice")
    assert (
        rate_limit.seconds_until_unblocked(
            db_path, "alice", max_attempts=5, window_seconds=600
        )
        == 0
    )


def test_at_limit_blocks_with_positive_retry(db_path):
    for _ in range(5):
        rate_limit.record_failure(db_path, "alice")
    retry = rate_limit.seconds_until_unblocked(
        db_path, "alice", max_attempts=5, window_seconds=600
    )
    assert retry > 0


def test_limit_is_per_account(db_path):
    for _ in range(5):
        rate_limit.record_failure(db_path, "alice")
    # bob is unaffected by alice's failures
    assert (
        rate_limit.seconds_until_unblocked(
            db_path, "bob", max_attempts=5, window_seconds=600
        )
        == 0
    )


def test_clear_failures_unblocks(db_path):
    for _ in range(5):
        rate_limit.record_failure(db_path, "alice")
    rate_limit.clear_failures(db_path, "alice")
    assert (
        rate_limit.seconds_until_unblocked(
            db_path, "alice", max_attempts=5, window_seconds=600
        )
        == 0
    )


def test_expired_failures_do_not_count(db_path):
    # A zero-length window means every past failure is already outside it.
    for _ in range(5):
        rate_limit.record_failure(db_path, "alice")
    assert (
        rate_limit.seconds_until_unblocked(
            db_path, "alice", max_attempts=5, window_seconds=0
        )
        == 0
    )


def test_ip_limit_stops_account_rotation(db_path):
    for _ in range(20):
        rate_limit.record_ip_failure(db_path, "203.0.113.7")
    assert (
        rate_limit.seconds_until_ip_unblocked(
            db_path, "203.0.113.7", max_attempts=20, window_seconds=600
        )
        > 0
    )
    # A different household/public address is unaffected.
    assert (
        rate_limit.seconds_until_ip_unblocked(
            db_path, "203.0.113.8", max_attempts=20, window_seconds=600
        )
        == 0
    )


def test_success_discards_only_one_ip_attempt(db_path):
    for _ in range(2):
        rate_limit.record_ip_failure(db_path, "203.0.113.9")
    rate_limit.discard_latest_ip_attempt(db_path, "203.0.113.9")
    assert (
        rate_limit.seconds_until_ip_unblocked(
            db_path, "203.0.113.9", max_attempts=2, window_seconds=600
        )
        == 0
    )
    # One older failure remains; a second new failure reaches the threshold.
    rate_limit.record_ip_failure(db_path, "203.0.113.9")
    assert (
        rate_limit.seconds_until_ip_unblocked(
            db_path, "203.0.113.9", max_attempts=2, window_seconds=600
        )
        > 0
    )


def test_login_client_ip_only_trusts_proxy_header_when_enabled():
    from starlette.requests import Request

    from app.api.auth import _login_client_ip
    from app.config import Settings

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/auth/login",
            "raw_path": b"/api/auth/login",
            "query_string": b"",
            "headers": [(b"x-real-ip", b"198.51.100.12")],
            "client": ("172.18.0.1", 43210),
            "server": ("app", 9800),
        }
    )
    assert (
        _login_client_ip(request, Settings(login_trust_proxy_headers=True))
        == "198.51.100.12"
    )
    assert (
        _login_client_ip(request, Settings(login_trust_proxy_headers=False))
        == "172.18.0.1"
    )
