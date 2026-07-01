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
