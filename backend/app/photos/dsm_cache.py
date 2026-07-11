"""Process-wide caches + invalidation for the DSM photo source.

dsm_source.py 분할(Phase C 잔여, 2026-07-12): 전역 캐시/무효화를 한 모듈로.
브라우즈(dsm_browse)·파일작업(dsm_fileops) 믹스인이 모두 여기서 import한다.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time

from ..schemas import PersonInfo, PhotoBucket, PhotoFolder, PhotoItem, PlaceInfo

logger = logging.getLogger(__name__)

# Bucket cache: scope -> (monotonic_ts, buckets). scope = "team"(공유 라이브러리는
# 전 계정 공통 — 사용자마다 따로 풀스캔하지 않는다) 또는 "personal:<account>".
# L1(메모리) 뒤에 L2(SQLite bucket_cache)가 있어 재시작·타 세션에도 즉시 서빙되고,
# 쓰기 후에는 stale 데이터를 먼저 내주고 백그라운드로 재스캔한다(SWR).
_BUCKET_CACHE: dict[str, tuple[float, list[PhotoBucket]]] = {}
# sid -> account: invalidate 훅(세션만 아는 호출부)에서 scope를 만들 때 사용.
_SID_ACCOUNT: dict[str, str] = {}
# 백그라운드 재스캔 중복 방지.
_BUCKET_SCANNING: set[str] = set()


def _bucket_scope(account: str, space: str) -> str:
    return "team" if space == "team" else f"personal:{account}"
# Folder metadata cache: sid -> {folder_id: (space, name)}. The folder tree is
# huge (1500+) and hierarchical, so we load it lazily (one level per request)
# and remember id→(space,path) as levels are browsed. File-op helpers resolve a
# folder's space/path from here; cleared on folder create/remove.
_FOLDER_META: dict[str, dict[str, tuple[str, str]]] = {}
# Top-level folders are the one slow level (DSM scans all top folders); cache
# them per sid. Deeper levels are fast and fetched live.
_TOP_FOLDER_CACHE: dict[str, tuple[float, list[PhotoFolder]]] = {}
# App-trash item ids: 공유 휴지통은 전 계정 공통이므로 프로세스 전역 1개.
# 대량 폴더 삭제 후 #trash 서브트리가 커지면(폴더 150+) 전체 재스캔이 분 단위라,
# 쓰기마다 비우지 않고 삭제/복원 훅이 증분 갱신한다(TTL은 외부 변경 수렴용).
_TRASH_IDS: tuple[float, frozenset[str]] | None = None
_TRASH_TTL = 600.0
# 재구축 single-flight: 캐시가 빈 순간(재시작 직후) 동시 유입되는 items/buckets
# 호출들이 각자 158-폴더 병렬 재구축을 발사하면 DSM 세마포어(24)가 포화되어
# 로그인·폴더 목록까지 굶는다(2026-07-09 장애). 한 명만 재구축, 나머지는 대기.
_TRASH_LOCK = asyncio.Lock()
# 재구축 내부 동시성 상한 — 세마포어 24 중 상당수를 인터랙티브 요청 몫으로 남긴다.
_TRASH_CONCURRENCY = 6
# 백그라운드 재스캔 태스크 강한 참조(참조 없는 create_task는 GC로 중단될 수 있음).
_BG_TASKS: set["asyncio.Task"] = set()


async def _bounded_gather(coros: list, limit: int) -> list:
    """gather with a concurrency cap (DSM 세마포어를 독점하지 않기 위함)."""
    gate = asyncio.Semaphore(limit)

    async def run(coro):
        async with gate:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros))


def _trash_cache_add(item_ids: list[str]) -> None:
    global _TRASH_IDS
    if _TRASH_IDS is not None:
        _TRASH_IDS = (_TRASH_IDS[0], _TRASH_IDS[1] | frozenset(item_ids))


def _trash_cache_remove(item_ids: list[str]) -> None:
    global _TRASH_IDS
    if _TRASH_IDS is not None:
        _TRASH_IDS = (_TRASH_IDS[0], _TRASH_IDS[1] - frozenset(item_ids))


def trash_cache_clear() -> None:
    global _TRASH_IDS
    _TRASH_IDS = None
# Folder tombstones: sid -> {folder_id: removed_at}. FileStation deletes a
# folder instantly but Browse.Folder (Photos index) keeps returning it until
# reindexing (2026-07-04 실 NAS 보고: 삭제한 폴더가 트리에 계속 보임) — hide
# removed ids for a grace window. A same-named recreate gets a NEW Foto id,
# so tombstoning by id never hides a legitimate folder.
_REMOVED_FOLDERS: dict[str, dict[str, float]] = {}
_REMOVED_FOLDER_TTL = 600.0  # seconds — Photos reindex catches up well within
# Item tombstones: sid -> {item_id: removed_at}. Same reindex-lag problem as
# folders but for photos — a moved/deleted item keeps coming back from
# Browse.Item (both the folder_id filter and the timeline) until Photos
# reindexes (실 NAS: "삭제/이동했는데 폴더에 그대로 보임"). Hide these ids from
# every listing for a grace window; undo clears them. A moved item that comes
# back with a NEW id after reindex is unaffected (we tombstone the OLD id).
_REMOVED_ITEMS: dict[str, dict[str, float]] = {}
_BUCKET_TTL = 300.0  # seconds
_PAGE = 5000
# Video list cache: sid -> {space: (ts, items)}. videos()는 라이브러리 전체를
# 스캔해 type==video만 거르므로(무거움) 결과를 buckets와 같은 창으로 캐시.
_VIDEO_CACHE: dict[tuple[str, str], tuple[float, list["PhotoItem"]]] = {}
# 사람/장소 목록 캐시 — 전량 페이징(100~200/왕복)이라 렌즈를 열 때마다 풀스캔
# 하던 것을 캐시. 이름 지정/병합이 무효화한다.
_PERSON_CACHE: dict[tuple[str, str], tuple[float, list["PersonInfo"]]] = {}
_PLACE_CACHE: dict[tuple[str, str], tuple[float, list["PlaceInfo"]]] = {}
# 전량 스캔 페이지를 동시에 몇 개까지 조회할지(첫 조회 지연 단축; DsmClient
# 세마포어 24 안에서 여유 있게 — 69k 라이브러리 기준 2웨이브면 끝).
_SCAN_CONCURRENCY = 10


def _tombstoned_folders(sid: str) -> set[str]:
    """Live tombstone ids for this sid (expired entries pruned in place)."""
    entries = _REMOVED_FOLDERS.get(sid)
    if not entries:
        return set()
    now = _time.monotonic()
    for fid in [f for f, ts in entries.items() if now - ts > _REMOVED_FOLDER_TTL]:
        entries.pop(fid, None)
    return set(entries)


def _tombstoned_items(sid: str) -> set[str]:
    """Live item tombstones for this sid (expired entries pruned in place)."""
    entries = _REMOVED_ITEMS.get(sid)
    if not entries:
        return set()
    now = _time.monotonic()
    for iid in [i for i, ts in entries.items() if now - ts > _REMOVED_FOLDER_TTL]:
        entries.pop(iid, None)
    return set(entries)


def _tombstone_items(sid: str, item_ids: list[str]) -> None:
    entries = _REMOVED_ITEMS.setdefault(sid, {})
    now = _time.monotonic()
    for iid in item_ids:
        entries[iid] = now


def _untombstone_items(sid: str, item_ids: list[str]) -> None:
    entries = _REMOVED_ITEMS.get(sid)
    if not entries:
        return
    for iid in item_ids:
        entries.pop(iid, None)


def invalidate_bucket_cache(sid: str, space: str | None = None) -> None:
    """Mark bucket data stale after a write. L1을 비우면 다음 조회가 L2(SQLite)의
    지난 결과를 즉시 서빙하고 백그라운드 재스캔이 따라잡는다(SWR) — 쓰기마다
    전량 재스캔을 기다리게 하지 않는다. 휴지통 캐시는 삭제/복원 훅이 증분
    갱신하므로 여기서 건드리지 않는다."""
    account = _SID_ACCOUNT.get(sid, "")
    spaces = [space] if space else ["team", "personal"]
    for sp in spaces:
        scope = _bucket_scope(account, sp)
        _BUCKET_CACHE.pop(scope, None)
        try:
            from ..config import get_settings
            from ..db import mark_buckets_stale

            mark_buckets_stale(get_settings().sqlite_path, scope)
        except Exception:  # noqa: BLE001 - invalidation is best-effort
            pass
    for key in [k for k in _VIDEO_CACHE if k[0] == sid]:
        _VIDEO_CACHE.pop(key, None)


def drop_session_caches(sid: str) -> None:
    """만료/로그아웃 세션의 sid 키 캐시 회수(session_store가 호출) — 안 하면
    로그인마다 쌓여 영구 잔존한다. 팀 공유 캐시(_BUCKET_CACHE 'team',
    _TRASH_IDS)는 계정 무관이라 남긴다."""
    _SID_ACCOUNT.pop(sid, None)
    _FOLDER_META.pop(sid, None)
    _TOP_FOLDER_CACHE.pop(sid, None)
    _REMOVED_FOLDERS.pop(sid, None)
    _REMOVED_ITEMS.pop(sid, None)
    for cache in (_VIDEO_CACHE, _PERSON_CACHE, _PLACE_CACHE):
        for key in [k for k in cache if k[0] == sid]:
            cache.pop(key, None)


def invalidate_folder_cache(sid: str) -> None:
    # Only drop the top-level LISTING cache (its membership changed on a write).
    # _FOLDER_META (folder_id → (space, path)) is a stable path-resolution map:
    # nested folders(id) 조회가 여기에 의존하고, folders() 가 목록을 낼 때마다
    # 스스로 갱신한다. 이걸 통째로 지우면 쓰기 직후 프론트의 폴더 목록 재조회가
    # "경로 캐시 없음"으로 실패해 새 폴더/이동 결과가 새로고침 전엔 안 보였다
    # (2026-07-05 실 NAS 보고). 그래서 여기서 비우지 않는다.
    _TOP_FOLDER_CACHE.pop(sid, None)


def _ns(space: str, api: str) -> str:
    """Map an API name into the right namespace for the space.

    Personal space uses SYNO.Foto.*, shared (team) space uses SYNO.FotoTeam.*
    with an otherwise identical surface — the namespace split is the single
    biggest trap in the unofficial Photos API.
    """
    if space == "team":
        return api.replace("SYNO.Foto.", "SYNO.FotoTeam.")
    return api




def trash_cache_get() -> tuple[float, frozenset[str]] | None:
    """트래시 캐시 스냅샷 — 분할 후 타 모듈에서 전역 재바인딩 없이 읽는 액세서."""
    return _TRASH_IDS


def trash_cache_set(ids: frozenset[str]) -> None:
    global _TRASH_IDS
    _TRASH_IDS = (_time.monotonic(), ids)
