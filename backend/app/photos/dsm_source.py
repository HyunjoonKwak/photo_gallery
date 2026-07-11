"""Synology Photos(DSM Web API) 소스 — 조립 모듈.

2,180줄 단일 파일을 Phase C에서 3분할(2026-07-12):
  dsm_cache   — 프로세스 전역 캐시·무효화·트래시 상태
  dsm_browse  — 읽기(타임라인/폴더/검색/렌즈/앨범/썸네일)
  dsm_fileops — 쓰기(이동/삭제/undo/폴더/트래시)
여기서는 둘을 DsmPhotoSource로 조합하고, 기존 import 경로 호환을 위해 캐시
심볼을 재수출한다(테스트 conftest가 dsm_source.* 로 접근).
"""

from __future__ import annotations

from ..dsm.client import DsmClient
from .dsm_browse import _DsmBrowseOps
from .dsm_fileops import _DsmFileOps

# 재수출(호환): 외부(api/session_store/tests)가 dsm_source 경로로 쓰는 이름들.
from .dsm_cache import (
    _BUCKET_CACHE,
    _SID_ACCOUNT,
    _BUCKET_SCANNING,
    _bucket_scope,
    _FOLDER_META,
    _TOP_FOLDER_CACHE,
    _TRASH_TTL,
    _TRASH_LOCK,
    _TRASH_CONCURRENCY,
    _BG_TASKS,
    _bounded_gather,
    _trash_cache_add,
    _trash_cache_remove,
    trash_cache_clear,
    trash_cache_get,
    trash_cache_set,
    _REMOVED_FOLDERS,
    _REMOVED_FOLDER_TTL,
    _REMOVED_ITEMS,
    _BUCKET_TTL,
    _PAGE,
    _VIDEO_CACHE,
    _PERSON_CACHE,
    _PLACE_CACHE,
    _SCAN_CONCURRENCY,
    _tombstoned_folders,
    _tombstoned_items,
    _tombstone_items,
    _untombstone_items,
    invalidate_bucket_cache,
    drop_session_caches,
    invalidate_folder_cache,
    _ns,
)


class DsmPhotoSource(_DsmBrowseOps, _DsmFileOps):
    """PhotoSource implementation talking to Synology Photos via the Web API."""

    def __init__(self, dsm: DsmClient, sid: str, account: str = ""):
        self._dsm = dsm
        self._sid = sid
        self._account = account
        if account:
            _SID_ACCOUNT[sid] = account
