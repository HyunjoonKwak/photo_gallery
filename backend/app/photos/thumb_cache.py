"""On-disk cache for proxied DSM thumbnails.

A thumbnail is the same image for a given (item, cache_key, size), so serving
repeats from local disk avoids a DSM round-trip. This matters most for **1차
구역(FileStation) 썸네일**, which DSM often has to read/generate on demand and
are noticeably slow, and for cold browser caches across devices.

접근 제어 보존: the cache key includes the **requesting account**, so a cached
thumbnail is only ever handed back to the same user who was already authorized
to fetch it from DSM. We never let one user read another's cached thumbnail by
id alone (personal/1차 구역 항목은 소유자 전용).

Best-effort: every filesystem error is swallowed — a cache miss/failure simply
falls through to the live DSM fetch. Synology thumbnails are JPEG, so hits are
served as ``image/jpeg``.
"""

from __future__ import annotations

import hashlib
import os
import time

# Synology 썸네일(SYNO.Foto.Thumbnail / SYNO.FileStation.Thumb)은 항상 JPEG.
THUMB_MEDIA_TYPE = "image/jpeg"

# 캐시 키 버전 — 썸네일 획득 로직이 바뀌면 올려 옛 캐시를 무효화한다.
# v2: 1차 구역/homes 썸네일을 @eaDir SYNOPHOTO_THUMB(고해상·동영상 지원)로 전환.
_CACHE_VERSION = "v2"

# 기본 신선도 상한(주로 cache_key 없는 1차 구역 파일이 교체됐을 때의 안전장치).
# Foto 항목은 cache_key가 내용 버전이라 바뀌면 키 자체가 달라져 stale이 불가능.
_DEFAULT_TTL = 30 * 24 * 3600


class ThumbCache:
    def __init__(self, root: str, ttl_seconds: float = _DEFAULT_TTL) -> None:
        self._root = root
        self._ttl = ttl_seconds

    @staticmethod
    def key(
        account: str, space: str, item_id: str, cache_key: str, size: str
    ) -> str:
        raw = "\x00".join([_CACHE_VERSION, account, space, item_id, cache_key, size])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> str:
        # 앞 2 hex로 샤딩 — 한 디렉터리에 파일이 몰리지 않게.
        return os.path.join(self._root, key[:2], key)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            if self._ttl and (time.time() - os.stat(path).st_mtime) > self._ttl:
                return None
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # 원자적 교체 — 동시 요청이 반쪽 파일을 읽지 않게.
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except OSError:
            pass  # best-effort — 실패해도 라이브 페치로 폴백
