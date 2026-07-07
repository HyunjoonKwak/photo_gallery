"""Unit tests for the on-disk thumbnail cache."""

import os
import time

from app.photos.thumb_cache import ThumbCache


def test_put_get_roundtrip(tmp_path):
    cache = ThumbCache(str(tmp_path / "tc"))
    k = ThumbCache.key("alice", "team", "42", "ck1", "sm")
    assert cache.get(k) is None  # miss
    cache.put(k, b"\xff\xd8jpegbytes")
    assert cache.get(k) == b"\xff\xd8jpegbytes"


def test_key_isolates_account_and_params(tmp_path):
    # 접근 제어: 계정이 다르면 키가 다르다(캐시 공유 안 됨).
    a = ThumbCache.key("alice", "personal", "42", "ck", "sm")
    b = ThumbCache.key("bob", "personal", "42", "ck", "sm")
    assert a != b
    # size/cache_key/space도 키에 반영.
    assert ThumbCache.key("a", "team", "1", "c", "sm") != ThumbCache.key(
        "a", "team", "1", "c", "xl"
    )
    assert ThumbCache.key("a", "team", "1", "c1", "sm") != ThumbCache.key(
        "a", "team", "1", "c2", "sm"
    )


def test_ttl_expiry(tmp_path):
    cache = ThumbCache(str(tmp_path / "tc"), ttl_seconds=1)
    k = ThumbCache.key("alice", "team", "9", "", "sm")
    cache.put(k, b"data")
    # 파일 mtime을 과거로 밀어 만료 상황을 만든다.
    path = cache._path(k)
    old = time.time() - 10
    os.utime(path, (old, old))
    assert cache.get(k) is None


def test_get_failure_is_silent(tmp_path):
    # 없는 루트/깨진 경로여도 예외 없이 None(라이브 페치로 폴백).
    cache = ThumbCache(str(tmp_path / "nope"))
    assert cache.get("deadbeef") is None
