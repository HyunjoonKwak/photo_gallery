"""Read-side of the DSM photo source (browse/list/search/AI lenses/albums).

dsm_source.py 분할(2026-07-12): DsmPhotoSource = _DsmBrowseOps + _DsmFileOps.
믹스인은 self 속성(_dsm/_sid/_account)과 상대 믹스인 메서드를 런타임에 공유
한다 — 단독 사용 금지, 반드시 DsmPhotoSource로 조합해 쓸 것.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time
from collections import Counter
from datetime import date
from typing import Callable

from ..dsm.client import DsmClient
from ..dsm.errors import DsmError
from ..progress import ProgressFn
from ..schemas import (
    AlbumInfo,
    ItemDetail,
    MemberInfo,
    PersonInfo,
    PhotoBucket,
    PhotoFolder,
    PhotoItem,
    PlaceInfo,
    PlacedItem,
)
from .dsm_time import date_from_epoch, day_range, decode_wall_clock
from .hashing import compute_hashes
from .source import Affected, DeleteOutcome, MoveOutcome

logger = logging.getLogger(__name__)

# A normal day fits in one 5,000-item DSM page. Exceptionally large import days
# continue in a small parallel wave so they do not pay one NAS RTT per page or
# monopolize the app-wide DSM semaphore.
_DAY_PAGE_CONCURRENCY = 4

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


class _DsmBrowseOps:
    async def buckets(self, space: str) -> list[PhotoBucket]:
        """Day buckets grouped in local (KST) time by paging the whole library.

        실 NAS 검증(DSM 7.2, 2026-07): SYNO.Foto.Browse.Timeline 의 일별 count 는
        UTC 계열로 그룹핑되어 우리가 쓰는 로컬(KST) 자정 경계 items() 와 날짜별
        개수가 어긋난다(사진 표시는 정확하나 헤더 count 불일치). 정확도를 위해
        Timeline 을 쓰지 않고 Browse.Item 을 전량 페이징하며 taken time 을 서버
        로컬 타임존으로 그룹핑한다 — buckets 와 items 가 동일 소스·동일 TZ 라
        개수가 정확히 일치한다. (배포 컨테이너 TZ=Asia/Seoul 전제 — docker 설정)

        비용: 69k 라이브러리 기준 수십 초 → 그래서 3계층:
        L1 메모리(scope) → L2 SQLite(재시작·타 세션에도 즉시) → 실스캔.
        쓰기 후에는 stale L2를 먼저 내주고 백그라운드로 재스캔한다(SWR).
        """
        scope = _bucket_scope(self._account, space)
        cached = _BUCKET_CACHE.get(scope)
        if cached and (_time.monotonic() - cached[0]) < _BUCKET_TTL:
            return cached[1]

        from ..config import get_settings
        from ..db import load_buckets

        sqlite_path = get_settings().sqlite_path
        try:
            rows, fresh = await asyncio.to_thread(
                load_buckets, sqlite_path, scope, _BUCKET_TTL
            )
        except Exception:  # noqa: BLE001 - L2 장애는 스캔 폴백으로 흡수
            rows, fresh = [], False
        if rows:
            out = [PhotoBucket(day=d, count=c) for d, c in rows]
            _BUCKET_CACHE[scope] = (_time.monotonic(), out)
            if not fresh and scope not in _BUCKET_SCANNING:
                # Stale-while-revalidate: 지난 결과를 즉시 내주고 뒤에서 재스캔.
                # 태스크는 강한 참조로 보관 — 참조 없는 create_task는 GC가
                # 중간에 회수할 수 있어 재스캔이 소리 없이 사라진다.
                _BUCKET_SCANNING.add(scope)
                task = asyncio.create_task(
                    self._rescan_buckets(scope, space, sqlite_path)
                )
                _BG_TASKS.add(task)
                task.add_done_callback(_BG_TASKS.discard)
            return out
        # 첫 스캔(스코프에 데이터 자체가 없음) — 동기로 한 번 채운다.
        return await self._rescan_buckets(scope, space, sqlite_path, register=False)

    async def _rescan_buckets(
        self, scope: str, space: str, sqlite_path: str, register: bool = True
    ) -> list[PhotoBucket]:
        """Full-library scan → counter → L1/L2 갱신. 백그라운드 태스크로도 돎."""
        try:
            trash_ids = await self._trash_item_ids(space)
            tomb = _tombstoned_items(self._sid)
            counter: Counter[str] = Counter()
            # additional 생략 → time 만 받아 페이로드 최소화.
            for page in await self._scan_item_pages(space):
                for it in page:
                    ts = it.get("time")
                    iid = str(it.get("id"))
                    if ts and iid not in trash_ids and iid not in tomb:
                        counter[date_from_epoch(ts).isoformat()] += 1
            out = [
                PhotoBucket(day=day, count=count)
                for day, count in sorted(counter.items(), reverse=True)
            ]
            _BUCKET_CACHE[scope] = (_time.monotonic(), out)
            try:
                from ..db import save_buckets

                await asyncio.to_thread(
                    save_buckets, sqlite_path, scope, [(b.day, b.count) for b in out]
                )
            except Exception:  # noqa: BLE001 - L2 저장 실패해도 결과는 서빙
                logger.exception("bucket save failed (scope=%s)", scope)
            return out
        except Exception:
            logger.exception("bucket rescan failed (scope=%s)", scope)
            return []
        finally:
            if register:
                _BUCKET_SCANNING.discard(scope)

    async def _scan_item_pages(
        self, space: str, additional: list[str] | None = None
    ) -> list[list[dict]]:
        """라이브러리 전체 Browse.Item를 병렬 "물결"로 스캔해 raw 페이지들을
        반환. total을 미리 못 믿으므로(필터 없는 count 동작 불확실)
        _SCAN_CONCURRENCY 페이지씩 동시에 받고, 짧은 페이지(< _PAGE)가 나오면
        끝에 도달한 것 → 종료. 순차 페이징 대비 첫 조회 지연을 줄인다
        (buckets/videos 공용)."""
        extra_add = {"additional": json.dumps(additional)} if additional else {}

        async def fetch(offset: int) -> list[dict]:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Item"),
                "list",
                version=1,
                sid=self._sid,
                extra={"offset": offset, "limit": _PAGE, **extra_add},
            )
            return data.get("list", [])

        pages: list[list[dict]] = []
        offset = 0
        done = False
        while not done:
            offsets = [offset + i * _PAGE for i in range(_SCAN_CONCURRENCY)]
            wave = await asyncio.gather(*(fetch(o) for o in offsets))
            for page in wave:
                pages.append(page)
                if len(page) < _PAGE:
                    done = True
            offset += _SCAN_CONCURRENCY * _PAGE
        return pages

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        d = date.fromisoformat(day)
        start, end = day_range(d)
        trash_ids = await self._trash_item_ids(space)
        tomb = _tombstoned_items(self._sid)
        # Page through the whole day — a single mobile-backup/import day can
        # exceed DSM's page limit. The common case stays one request; only a
        # full first page fans the remaining offsets out in bounded waves.
        async def fetch(offset: int) -> list[dict]:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Item"),
                "list",
                version=1,
                sid=self._sid,
                extra={
                    "offset": offset,
                    "limit": _PAGE,
                    "start_time": start,
                    "end_time": end,
                    "sort_by": "takentime",
                    "sort_direction": "desc",
                    "additional": json.dumps(["thumbnail", "resolution", "video_meta"]),
                },
            )
            return data.get("list", [])

        pages = [await fetch(0)]
        offset = _PAGE
        while len(pages[-1]) == _PAGE:
            offsets = [offset + i * _PAGE for i in range(_DAY_PAGE_CONCURRENCY)]
            wave = await asyncio.gather(*(fetch(o) for o in offsets))
            pages.extend(wave)
            if any(len(page) < _PAGE for page in wave):
                break
            offset += _DAY_PAGE_CONCURRENCY * _PAGE

        out: list[PhotoItem] = []
        for page in pages:
            out.extend(
                self._to_item(it)
                for it in page
                if str(it.get("id")) not in trash_ids
                and str(it.get("id")) not in tomb
            )
        # Timeline buckets are newest-first, and every grid consumer assumes the
        # items inside a bucket follow the same direction.  Sort again after the
        # bounded parallel page fetch so response completion order and DSM page
        # ties cannot make the visible grid jump between reloads.
        out.sort(key=lambda item: (item.taken_at, item.id), reverse=True)
        return out

    async def _trash_item_ids(self, space: str = "team") -> frozenset[str]:
        """Foto item ids currently in the app trash (/photo/#trash).

        Synology Photos indexes the trash folder like any other folder, so
        space-wide listings (timeline/search/classify) must subtract these
        (2026-07-04 실 NAS 사용자 보고: 삭제 사진이 공용 타임라인에 노출).
        The trash only holds pending deletes, so one small fetch per cache
        window keeps the full-library paging additional-free.
        """
        if space != "team":  # trash lives in the team share only
            return frozenset()
        cached = trash_cache_get()
        if cached and (_time.monotonic() - cached[0]) < _TRASH_TTL:
            return cached[1]
        async with _TRASH_LOCK:
            # 잠금 대기 중 다른 요청이 재구축을 끝냈으면 그 결과를 그대로 쓴다.
            cached = trash_cache_get()
            if cached and (_time.monotonic() - cached[0]) < _TRASH_TTL:
                return cached[1]
            return await self._rebuild_trash_ids()

    async def _rebuild_trash_ids(self) -> frozenset[str]:
        try:
            trash = next(
                (
                    f
                    for f in await self._list_children("team", 0)
                    if f.get("name") == f"/{self.TRASH_DIRNAME}"
                ),
                None,
            )
            ids: set[str] = set()
            if trash is not None:
                # 단순 삭제는 #trash/t<ns>/files(2단계)지만, 폴더 재귀 삭제는
                # #trash/t<ns>/<folder>/…로 서브트리를 통째로 옮겨 임의 깊이가
                # 된다. 대량 폴더 삭제 후 트래시가 150+ 폴더로 커질 수 있어
                # (2026-07-09 실측: 순차 수집이 분 단위 → 타임라인 5분+)
                # 폴더별 아이템 수집을 병렬로 돌린다(DSM 세마포어가 상한).
                folder_ids = await self._descendant_folder_ids(
                    "team", int(trash["id"])
                )

                async def collect(fid: int) -> set[str]:
                    got: set[str] = set()
                    offset = 0
                    while True:
                        data = await self._dsm.call(
                            _ns("team", "SYNO.Foto.Browse.Item"),
                            "list",
                            version=1,
                            sid=self._sid,
                            extra={"folder_id": fid, "offset": offset, "limit": 1000},
                        )
                        page = data.get("list", [])
                        got.update(str(it.get("id")) for it in page)
                        if len(page) < 1000:
                            return got
                        offset += 1000

                parts = await _bounded_gather(
                    [collect(f) for f in folder_ids], _TRASH_CONCURRENCY
                )
                for part in parts:
                    ids.update(part)
        except DsmError:
            # Filtering is best-effort — a probe failure must not break the
            # timeline. Uncached so the next call retries.
            return frozenset()
        result = frozenset(ids)
        trash_cache_set(result)
        return result

    @staticmethod
    def _to_item(it: dict) -> PhotoItem:
        additional = it.get("additional", {})
        resolution = additional.get("resolution", {})
        thumb = additional.get("thumbnail", {})
        video_meta = additional.get("video_meta") or {}
        gps = additional.get("gps") or {}
        lat = gps.get("latitude")
        lng = gps.get("longitude")
        return PhotoItem(
            id=str(it.get("id")),
            filename=it.get("filename", ""),
            taken_at=decode_wall_clock(it.get("time", 0)).isoformat(),
            width=int(resolution.get("width", 4)) or 4,
            height=int(resolution.get("height", 3)) or 3,
            size=it.get("filesize"),
            cache_key=thumb.get("cache_key", ""),
            type="video" if it.get("type") == "video" else "photo",
            duration_ms=video_meta.get("duration"),
            placeholder_color=None,  # thumbhash lands with photo_cache (phase 2)
            folder=None,
            lat=float(lat) if lat not in (None, "") else None,
            lng=float(lng) if lng not in (None, "") else None,
        )

    async def folders(self, parent_id: str | None = None) -> list[PhotoFolder]:
        """One level of the folder tree (lazy).

        ``parent_id`` None → top-level folders of both spaces. Otherwise → the
        direct children of that folder (its space is recalled from the metadata
        cache, populated as levels are browsed). Depth is derived from the
        Photos folder name (full path). The full tree is 1500+ folders and each
        node is a round-trip, so loading everything up front is impractical —
        the UI expands nodes on demand.
        """
        metas = _FOLDER_META.setdefault(self._sid, {})
        tombstoned = _tombstoned_folders(self._sid)
        out: list[PhotoFolder] = []

        def _keep(f: dict) -> bool:
            # 시스템 폴더(#trash)와 방금 삭제됐지만 인덱스에 남은 폴더 제외.
            return not self._is_system_folder(f) and str(f.get("id")) not in tombstoned

        if parent_id is None:
            cached = _TOP_FOLDER_CACHE.get(self._sid)
            if cached and (_time.monotonic() - cached[0]) < _BUCKET_TTL:
                return cached[1]
            # Both spaces' top level in parallel — team's scan is the slow part.
            team, personal = await asyncio.gather(
                self._list_children("team", 0), self._list_children("personal", 0)
            )
            for space, children in (("team", team), ("personal", personal)):
                for f in children:
                    if not _keep(f):
                        continue
                    pf = self._folder_from(f, space, parent_id=None)
                    metas[pf.id] = (space, pf.name)
                    out.append(pf)
            _TOP_FOLDER_CACHE[self._sid] = (_time.monotonic(), out)
            return out

        meta = metas.get(parent_id)
        if meta is None:
            raise DsmError(100, "폴더를 먼저 탐색해야 합니다 (경로 캐시 없음).")
        space = meta[0]
        for f in await self._list_children(space, int(parent_id)):
            if not _keep(f):
                continue
            pf = self._folder_from(f, space, parent_id=parent_id)
            metas[pf.id] = (space, pf.name)
            out.append(pf)
        return out

    @staticmethod
    def _is_system_folder(f: dict) -> bool:
        # '#'-prefixed basenames are app/system folders (#trash, DSM #recycle).
        return f.get("name", "").rstrip("/").rsplit("/", 1)[-1].startswith("#")

    @staticmethod
    def _folder_from(f: dict, space: str, parent_id: str | None) -> PhotoFolder:
        name = f.get("name", "")
        # Photos folder name is the full path (/a/b/c) → depth from slash count.
        depth = max(0, name.strip("/").count("/"))
        return PhotoFolder(
            id=str(f.get("id")), name=name, space=space,
            parent_id=parent_id, depth=depth,
        )

    async def _list_children(self, space: str, parent_id: int) -> list[dict]:
        out: list[dict] = []
        offset = 0
        while True:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Folder"),
                "list",
                version=1,
                sid=self._sid,
                extra={"id": parent_id, "offset": offset, "limit": 1000},
            )
            page = data.get("list", [])
            out.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
        return out

    async def _descendant_folder_ids(self, space: str, root_id: int) -> list[int]:
        """root_id + 그 아래 모든 하위 폴더 id (재귀). 폴더 통째 삭제로 앱
        휴지통이 여러 단계 깊어질 수 있어, 트래시 아이템 수집 전 서브트리
        전체를 훑는다. 트래시는 대기 삭제만 담겨 대개 작다."""
        out = [root_id]
        frontier = [root_id]
        # 레벨 단위 병렬 조회 — 트래시가 폴더 150+로 커지면 순차 왕복이 분 단위가
        # 된다(2026-07-09 실측). 상한을 두어 DSM 세마포어를 독점하지 않는다
        # (독점하면 로그인·폴더 목록까지 굶는다 — 같은 날 장애).
        while frontier:
            results = await _bounded_gather(
                [self._list_children(space, fid) for fid in frontier],
                _TRASH_CONCURRENCY,
            )
            frontier = []
            for children in results:
                for f in children:
                    cid = int(f["id"])
                    out.append(cid)
                    frontier.append(cid)
        return out

    async def _filtered_items(
        self, space: str, filters: dict, limit: int | None = None
    ) -> list[PhotoItem]:
        """Browse.Item results matching a filter (folder/person/place). limit이
        없으면 전량 페이징(limit-1000 truncation 방지), 있으면 한 페이지만
        (미리보기 카드용 — 수천 장 그룹을 통째로 받지 않도록). 휴지통·삭제/이동
        대기 아이템은 제외(Photos 인덱스는 재색인 전까지 계속 반환한다)."""
        trash_ids = await self._trash_item_ids(space)
        tomb = _tombstoned_items(self._sid)
        out: list[PhotoItem] = []
        offset = 0
        # 미리보기는 필터로 몇 장 빠질 수 있으니 여유 있게 한 페이지.
        page_size = min(limit + 8, 1000) if limit is not None else 1000
        while True:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Item"),
                "list",
                version=1,
                sid=self._sid,
                extra={
                    **filters,
                    "offset": offset,
                    "limit": page_size,
                    # gps: 장소 지도 뷰의 핀 좌표(폴더/인물/장소 아이템 공용).
                    "additional": json.dumps(
                        ["thumbnail", "resolution", "video_meta", "gps"]
                    ),
                },
            )
            page = data.get("list", [])
            out.extend(
                self._to_item(it)
                for it in page
                if str(it.get("id")) not in trash_ids
                and str(it.get("id")) not in tomb
            )
            if limit is not None or len(page) < page_size:
                break  # 미리보기는 한 페이지로 종료
            offset += page_size
        return out[:limit] if limit is not None else out

    async def folder_items(
        self, folder_id: str, limit: int | None = None
    ) -> list[PhotoItem]:
        # folder_id 필터는 실 NAS 동작 확인됨(2026-07): 해당 폴더의 "직속" 사진만
        # 반환(하위 폴더 사진 미포함). 폴더 space는 메타 캐시에서 판정(UI가 트리
        # 탐색 중 채움); 미스면 최상위를 한 번 로드해 시도.
        space = self._folder_space(folder_id)
        return await self._filtered_items(
            space, {"folder_id": int(folder_id)}, limit
        )

    async def capture_items(self, space: str, folder_id: str) -> list[PhotoItem]:
        """Direct items of a folder for 촬영일 교정, with space given explicitly
        (avoids the meta-cache dependency of folder_items — the capture dialog may
        run right after a restart before the tree was browsed)."""
        return await self._filtered_items(space, {"folder_id": int(folder_id)}, None)

    async def capture_subtree(
        self, space: str, root_id: str
    ) -> list[tuple[str, str]]:
        """(folder_id, full_name) for the folder + ALL descendants (촬영일 교정
        재귀). Foto folder name is the full path within the space, so the caller
        derives each folder's disk path as base + name."""
        ns = _ns(space, "SYNO.Foto.Browse.Folder")
        out: list[tuple[str, str]] = []
        root = await self._dsm.call(
            ns, "get", version=1, sid=self._sid, extra={"id": int(root_id)}
        )
        rf = (root or {}).get("folder")
        if rf:
            out.append((str(rf["id"]), rf.get("name", "")))
        # 레벨 병렬(BFS) — 깊은 트리에서 폴더당 1왕복 순차(N+1)로 수 초씩 걸리던
        # 것을 트래시 워크와 같은 상한(_TRASH_CONCURRENCY)으로 병렬화.
        frontier = [int(root_id)]
        while frontier:
            results = await _bounded_gather(
                [self._list_children(space, pid) for pid in frontier],
                _TRASH_CONCURRENCY,
            )
            frontier = []
            for children in results:
                for f in children:
                    out.append((str(f["id"]), f.get("name", "")))
                    frontier.append(int(f["id"]))
        return out

    async def set_item_time(self, space: str, item_id: str, epoch: int) -> None:
        """Set a Synology Photos item's taken time (촬영일 교정, 내 사진/공용).

        SYNO.Foto(Team).Browse.Item `set` with id=[..] + time=<epoch초> updates
        Synology's own index directly (실 NAS 확인 2026-07-09) — no file edit and
        no reindex needed, so it's the reliable fix for photos already in Photos.
        """
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Item"),
            "set",
            version=1,
            sid=self._sid,
            extra={"id": json.dumps([int(item_id)]), "time": int(epoch)},
        )
        # 응답 top-level은 success여도, 개별 항목 실패는 data.error_list에 담긴다
        # (실 NAS 확인: 일부 항목은 Synology가 시간 변경을 거부). 실패로 처리.
        if (data or {}).get("error_list"):
            raise DsmError(
                100, f"Synology가 이 사진의 촬영시간을 변경하지 못했습니다 (id {item_id})."
            )

    # EXIF keys worth showing, normalized to fixed names the frontend labels.
    _EXIF_KEYS = (
        "camera",
        "lens",
        "aperture",
        "exposure_time",
        "iso",
        "focal_length",
    )

    async def item_detail(self, space: str, item_id: str) -> ItemDetail:
        # Browse.Item "get" with the heavy additionals — panel-open only, so
        # list responses stay light. 실 NAS raw 확인(2026-07-02, DSM 세션):
        # additional.folder는 dict가 아니라 "경로 문자열"로 온다(조합 요청
        # 포함) — _item_meta의 문자열 fallback과 동일하게 처리해야 한다.
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Item"),
            "get",
            version=1,
            sid=self._sid,
            extra={
                "id": json.dumps([int(item_id)]),
                "additional": json.dumps(["exif", "folder", "address", "gps"]),
            },
        )
        items = data.get("list", [])
        if not items:
            raise DsmError(100, "사진을 찾을 수 없습니다.")
        additional = items[0].get("additional") or {}

        folder = additional.get("folder")
        folder_name = (
            folder.get("name") if isinstance(folder, dict) else (folder or None)
        )

        raw_exif = additional.get("exif") or {}
        exif = {
            k: str(raw_exif[k])
            for k in self._EXIF_KEYS
            if raw_exif.get(k) not in (None, "", 0)
        }

        # Address arrives as granular fields (country/city/…): join what's
        # there, most-significant first, skipping duplicates.
        raw_addr = additional.get("address") or {}
        parts: list[str] = []
        for key in ("country", "state", "county", "city", "town", "district",
                    "village", "route", "landmark"):
            v = raw_addr.get(key)
            if v and v not in parts:
                parts.append(str(v))
        address = " ".join(parts) or None
        # 이벤트 이름에 붙일 도시급 라벨: 세밀한 단위 우선(town→city→…).
        place_label = next(
            (
                str(raw_addr[k])
                for k in ("town", "city", "county", "state", "country")
                if raw_addr.get(k)
            ),
            None,
        )

        return ItemDetail(
            id=item_id, folder=folder_name, exif=exif, address=address,
            place_label=place_label
        )

    async def item_folders(
        self, space: str, item_ids: list[str]
    ) -> dict[str, str | None]:
        # Batched Browse.Item get — additional.folder is a path STRING on the
        # real NAS (2026-07-02 raw 확인). Used by dedup group cards, so one
        # call per ~100 items instead of one per item.
        out: dict[str, str | None] = {}
        for start in range(0, len(item_ids), 100):
            chunk = item_ids[start : start + 100]
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Item"),
                "get",
                version=1,
                sid=self._sid,
                extra={
                    "id": json.dumps([int(i) for i in chunk]),
                    "additional": json.dumps(["folder"]),
                },
            )
            for it in data.get("list", []):
                folder = (it.get("additional") or {}).get("folder")
                out[str(it.get("id"))] = (
                    folder.get("name") if isinstance(folder, dict) else (folder or None)
                )
        return out

    # Search results are capped: a broad keyword on a 90k-photo archive could
    # otherwise pull tens of thousands of items into one response.
    SEARCH_CAP = 2000

    async def search_items(self, space: str, keyword: str) -> list[PhotoItem]:
        # SYNO.Foto(Team).Search.Search "list_item" — 실 NAS raw 검증
        # (2026-07-03): 한국어 키워드·폴더명 매칭 동작 확인.
        trash_ids = await self._trash_item_ids(space)
        tomb = _tombstoned_items(self._sid)
        out: list[PhotoItem] = []
        offset = 0
        page_size = 500
        while offset < self.SEARCH_CAP:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Search.Search"),
                "list_item",
                version=1,
                sid=self._sid,
                extra={
                    # JSON 인코딩 필수: 평문이면 "2016"·"2016-08" 같은 숫자/날짜꼴
                    # 키워드를 DSM이 수식으로 파싱해 code 120 (rename과 동일 함정,
                    # 2026-07-10 실 NAS 확인).
                    "keyword": json.dumps(keyword),
                    "offset": offset,
                    "limit": page_size,
                    "additional": json.dumps(["thumbnail", "resolution", "video_meta"]),
                },
            )
            page = data.get("list", [])
            out.extend(
                self._to_item(it)
                for it in page
                if str(it.get("id")) not in trash_ids
                and str(it.get("id")) not in tomb
            )
            if len(page) < page_size:
                break
            offset += page_size
        return out

    # ------------------------------------------- AI classification (3단계)
    # Synology Photos 내장 AI 결과 재활용 — SYNO.API.Info 프로브로 실 NAS 확인
    # (2026-07-02): (Foto|FotoTeam).Browse.Person v1~3, Browse.Geocoding v1.

    async def persons(self, space: str) -> list[PersonInfo]:
        # 전량 페이징(100/왕복)이라 캐시 — 이름 지정/병합마다 name_person이
        # persons()를 재호출해 매번 풀스캔하던 것도 이 캐시로 흡수.
        cached = _PERSON_CACHE.get((self._sid, space))
        if cached and (_time.monotonic() - cached[0]) < _BUCKET_TTL:
            return cached[1]
        out = await self._persons_scan(space)
        _PERSON_CACHE[(self._sid, space)] = (_time.monotonic(), out)
        return out

    async def _persons_scan(self, space: str) -> list[PersonInfo]:
        out: list[PersonInfo] = []
        offset = 0
        while True:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Person"),
                "list",
                version=1,
                sid=self._sid,
                extra={
                    "offset": offset,
                    "limit": 100,
                    "additional": json.dumps(["thumbnail"]),
                },
            )
            page = data.get("list", [])
            for p in page:
                if p.get("show") is False:
                    continue  # user hid this face group in Synology Photos
                thumb = (p.get("additional") or {}).get("thumbnail") or {}
                # 실 NAS(DSM 7.2, 2026-07 raw 확인): 썸네일 프록시는 type=unit
                # + id=<unit id>로 동작하는데, 사람 커버의 unit id는 cache_key
                # 접두어("<unit_id>_<mtime>", 예 "78112_1762208160" → 78112)에
                # 들어 있다. top-level `cover`(=item id, 예 10860)는 이 unit과
                # 달라 그대로 넘기면 썸네일이 404가 난다. cache_key 접두어를
                # 우선 쓰고 unit_id/cover는 fallback.
                cache_key = thumb.get("cache_key") or ""
                unit = cache_key.split("_", 1)[0] if "_" in cache_key else None
                cover = unit or thumb.get("unit_id") or p.get("cover")
                out.append(
                    PersonInfo(
                        id=str(p.get("id")),
                        space=space,
                        name=p.get("name") or "",
                        item_count=p.get("item_count"),
                        cover_item_id=str(cover) if cover else None,
                        cover_cache_key=cache_key or None,
                    )
                )
            if len(page) < 100:
                break
            offset += 100
        out.sort(key=lambda p: -(p.item_count or 0))
        return out

    async def person_items(self, space: str, person_id: str) -> list[PhotoItem]:
        return await self._filtered_items(space, {"person_id": int(person_id)})

    async def name_person(self, space: str, person_id: str, name: str) -> dict:
        """인물 이름 지정 + 같은 이름 자동 병합.

        set_name(이름 지정)은 실 NAS에서 확실하나, 병합 API 메서드/파라미터는
        **미검증**이라 best-effort로 처리한다: 이름을 먼저 지정하고, 같은 이름의
        기존 인물이 있으면 병합을 시도하되 실패해도(메서드 상이/자동병합 등)
        이름은 이미 적용됐으므로 계속 진행한다. 관련: name_person(mock)."""
        _PERSON_CACHE.pop((self._sid, space), None)  # 이름/병합은 목록을 바꾼다
        name = name.strip()
        if not name:
            raise DsmError(100, "이름이 비어 있습니다.")

        persons = await self.persons(space)
        target = next(
            (
                p
                for p in persons
                if p.name.strip() == name and str(p.id) != str(person_id)
            ),
            None,
        )

        # 1) 이름 지정 — 실 NAS 확인(2026-07): 메서드는 `set`(set_name 아님).
        await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Person"),
            "set",
            version=1,
            sid=self._sid,
            extra={"id": int(person_id), "name": name},
        )

        merged_into: str | None = None
        if target is not None:
            # 2) 같은 이름 인물로 병합 — 실 NAS raw 오류로 확정(2026-07):
            # merge(target_id=유지할 인물, merged_id=병합해 넣을 인물[]).
            merged_into = str(target.id)
            try:
                await self._dsm.call(
                    _ns(space, "SYNO.Foto.Browse.Person"),
                    "merge",
                    version=1,
                    sid=self._sid,
                    extra={
                        "target_id": int(target.id),
                        "merged_id": json.dumps([int(person_id)]),
                    },
                )
            except DsmError as exc:
                logger.warning(
                    "person merge 실패(이름은 지정됨): %s", exc
                )
        return {"name": name, "merged_into": merged_into}


    async def merge_duplicate_persons(self, space: str) -> dict:
        _PERSON_CACHE.pop((self._sid, space), None)
        # 같은 이름 인물들을 가장 큰 그룹(persons가 개수 내림차순)으로 병합.
        # merge(target_id=유지, merged_id=[나머지들]) — 실 NAS 확정 파라미터.
        persons = await self.persons(space)
        by_name: dict[str, list] = {}
        for p in persons:
            if p.name:
                by_name.setdefault(p.name, []).append(p)
        merged = 0
        for group in by_name.values():
            if len(group) < 2:
                continue
            keeper = group[0]
            sources = [int(p.id) for p in group[1:]]
            await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Person"),
                "merge",
                version=1,
                sid=self._sid,
                extra={
                    "target_id": int(keeper.id),
                    "merged_id": json.dumps(sources),
                },
            )
            merged += len(sources)
        return {"merged": merged}

    async def places(self, space: str) -> list[PlaceInfo]:
        cached = _PLACE_CACHE.get((self._sid, space))
        if cached and (_time.monotonic() - cached[0]) < _BUCKET_TTL:
            return cached[1]
        out = await self._places_scan(space)
        _PLACE_CACHE[(self._sid, space)] = (_time.monotonic(), out)
        return out

    async def _places_scan(self, space: str) -> list[PlaceInfo]:
        out: list[PlaceInfo] = []
        offset = 0
        while True:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Geocoding"),
                "list",
                version=1,
                sid=self._sid,
                extra={"offset": offset, "limit": 200},
            )
            page = data.get("list", [])
            out.extend(
                PlaceInfo(
                    id=str(g.get("id")),
                    space=space,
                    name=g.get("name") or "",
                    item_count=g.get("item_count"),
                    country=g.get("country") or None,
                    country_id=g.get("country_id"),
                    first_level=g.get("first_level") or None,
                    second_level=g.get("second_level") or None,
                )
                for g in page
            )
            if len(page) < 200:
                break
            offset += 200
        out.sort(key=lambda g: -(g.item_count or 0))
        return out

    async def place_items(
        self, space: str, place_id: str, limit: int | None = None
    ) -> list[PhotoItem]:
        return await self._filtered_items(
            space, {"geocoding_id": int(place_id)}, limit
        )

    async def videos(self, space: str) -> list[PhotoItem]:
        # 라이브러리 전체를 스캔해 type=="video"만 (DSM에 파일유형 필터
        # 파라미터가 있는지 실 NAS 프로브 미검증 → 앱단 필터). 무거운 작업이라
        # ① 결과를 buckets와 같은 창으로 캐시하고 ② 페이지를 동시에 조회해
        # 첫 조회 지연을 순차 페이징 대비 크게 줄인다. 휴지통/tombstone 제외.
        cache_key = (self._sid, space)
        cached = _VIDEO_CACHE.get(cache_key)
        if cached and (_time.monotonic() - cached[0]) < _BUCKET_TTL:
            return cached[1]

        trash_ids = await self._trash_item_ids(space)
        tomb = _tombstoned_items(self._sid)

        out: list[PhotoItem] = []
        for page in await self._scan_item_pages(
            space, ["thumbnail", "resolution", "video_meta"]
        ):
            for it in page:
                iid = str(it.get("id"))
                if (
                    it.get("type") == "video"
                    and iid not in trash_ids
                    and iid not in tomb
                ):
                    out.append(self._to_item(it))

        out.sort(key=lambda i: i.taken_at, reverse=True)
        _VIDEO_CACHE[cache_key] = (_time.monotonic(), out)
        return out

    # -------------------------------------------- User albums (개인 공간 전용)
    # 실 NAS 프로브(2026-07-07): SYNO.Foto.Browse.Album v1-5(목록),
    # SYNO.Foto.Browse.NormalAlbum v1-4(생성/추가/삭제). FotoTeam엔 앨범 API가
    # 없어 개인 공간만. 목록/아이템(read)은 Person/Geocoding와 동형이라 신뢰도가
    # 높고, create/add_item/delete(write)는 커뮤니티 문서 기반 메서드·파라미터라
    # **실 NAS 검증 대기**(name_person 병합과 동일한 best-effort 취급).

    def _album_from(self, a: dict) -> AlbumInfo:
        thumb = (a.get("additional") or {}).get("thumbnail") or {}
        cache_key = thumb.get("cache_key") or ""
        # 인물 커버와 동일: cache_key 접두어(unit id) 우선, unit_id/cover fallback.
        unit = cache_key.split("_", 1)[0] if "_" in cache_key else None
        cover = unit or thumb.get("unit_id") or a.get("cover")
        return AlbumInfo(
            id=str(a.get("id")),
            name=a.get("name") or "",
            item_count=a.get("item_count"),
            cover_item_id=str(cover) if cover else None,
            cover_cache_key=cache_key or None,
            shared=bool(a.get("shared", False)),
        )

    async def albums(self, space: str) -> list[AlbumInfo]:
        if space == "team":
            return []  # 공유 공간엔 앨범 API가 없음
        out: list[AlbumInfo] = []
        offset = 0
        while True:
            data = await self._dsm.call(
                "SYNO.Foto.Browse.Album",
                "list",
                version=1,
                sid=self._sid,
                extra={
                    "offset": offset,
                    "limit": 100,
                    "sort_by": "create_time",
                    "sort_direction": "desc",
                    "additional": json.dumps(["thumbnail"]),
                },
            )
            page = data.get("list", [])
            out.extend(self._album_from(a) for a in page)
            if len(page) < 100:
                break
            offset += 100
        return out

    async def album_items(self, space: str, album_id: str) -> list[PhotoItem]:
        if space == "team":
            return []
        return await self._filtered_items("personal", {"album_id": int(album_id)})

    async def create_album(
        self, space: str, name: str, item_ids: list[str]
    ) -> AlbumInfo:
        # write — 실 NAS 검증 대기. item을 주면 만들면서 담는다(빈 앨범도 허용).
        extra: dict = {"name": name}
        if item_ids:
            extra["item"] = json.dumps([int(i) for i in item_ids])
        data = await self._dsm.call(
            "SYNO.Foto.Browse.NormalAlbum",
            "create",
            version=1,
            sid=self._sid,
            extra=extra,
            http_method="POST",
        )
        # 응답 형태 미검증: {album:{...}} / {...} / {id:..} 모두 방어적으로 수용.
        album = data.get("album") if isinstance(data, dict) else None
        if not isinstance(album, dict):
            album = data if isinstance(data, dict) else {}
        if not album.get("name"):
            album = {**album, "name": name, "item_count": len(item_ids)}
        return self._album_from(album)

    async def add_to_album(
        self, space: str, album_id: str, item_ids: list[str]
    ) -> int:
        await self._dsm.call(
            "SYNO.Foto.Browse.NormalAlbum",
            "add_item",
            version=1,
            sid=self._sid,
            extra={
                "id": int(album_id),
                "item": json.dumps([int(i) for i in item_ids]),
            },
            http_method="POST",
        )
        return len(item_ids)

    async def rename_album(self, space: str, album_id: str, name: str) -> None:
        # 실 NAS 확정(2026-07-11): set_name은 Browse.Album에만 있다(NormalAlbum은
        # 103). name은 JSON 인코딩(날짜꼴 이름 code 120 함정 공통).
        await self._dsm.call(
            "SYNO.Foto.Browse.Album",
            "set_name",
            version=1,
            sid=self._sid,
            extra={"id": int(album_id), "name": json.dumps(name)},
            http_method="POST",
        )

    async def remove_from_album(
        self, space: str, album_id: str, item_ids: list[str]
    ) -> int:
        # 실 NAS 확정(2026-07-11): NormalAlbum delete_item v1.
        await self._dsm.call(
            "SYNO.Foto.Browse.NormalAlbum",
            "delete_item",
            version=1,
            sid=self._sid,
            extra={
                "id": int(album_id),
                "item": json.dumps([int(i) for i in item_ids]),
            },
            http_method="POST",
        )
        return len(item_ids)

    async def delete_album(self, space: str, album_id: str) -> None:
        # 실 NAS 확정(2026-07-11): delete는 Browse.Album에 있다(NormalAlbum
        # delete는 code 103 — 기존 구현이 실 NAS에서 실패하고 있었음).
        await self._dsm.call(
            "SYNO.Foto.Browse.Album",
            "delete",
            version=1,
            sid=self._sid,
            extra={"id": json.dumps([int(album_id)])},
            http_method="POST",
        )

    # 폴더 이름 정리는 마운트 스캔 기반이라 1차 구역/homes(FileStation) 전용.
    # 개인/공용 Foto 폴더는 지원 안 함(빈 목록 / 명확한 오류).
    async def audit_folder_names(self, root_id: str | None) -> list:
        return []

    async def rename_folder(
        self, space: str, folder_id: str, new_name: str
    ) -> tuple[str, str]:
        """Rename a Synology Photos folder (내 사진/공용). SYNO.Foto(Team).
        Browse.Folder `rename`(id + name) — 실 NAS 확인 2026-07-09. Foto folder
        id는 그대로, 이름만 바뀐다. 개인/공용 네임스페이스가 분리돼 있어, 넘어온
        space가 틀리면(옛 클라이언트가 space 미전송 등) 반대 공간으로도 시도한다."""
        spaces = [space, "team" if space == "personal" else "personal"]
        last: DsmError | None = None
        for sp in spaces:
            try:
                await self._dsm.call(
                    _ns(sp, "SYNO.Foto.Browse.Folder"),
                    "rename",
                    version=1,
                    sid=self._sid,
                    # name은 JSON 인코딩 필수: 평문이면 날짜꼴 이름("2012-01-29")을
                    # DSM이 숫자/수식으로 파싱해 code 120(type) — 실 NAS 확인.
                    extra={"id": int(folder_id), "name": json.dumps(new_name)},
                )
                invalidate_folder_cache(self._sid)
                # 경로 캐시 즉시 갱신 — 안 하면 rename 직후 이 폴더로의 이동이
                # 옛 경로로 CopyMove 되는 실버그(경로 해석이 meta에 의존).
                metas = _FOLDER_META.get(self._sid, {})
                old = metas.get(str(folder_id))
                if old:
                    parent = old[1].rsplit("/", 1)[0]
                    metas[str(folder_id)] = (old[0], f"{parent}/{new_name}")
                return str(folder_id), new_name
            except DsmError as exc:
                last = exc
        raise last if last else DsmError(100, "폴더 이름 변경 실패")

    async def folder_count(self, folder_id: str) -> int:
        """하위 전체(재귀) 아이템 수 — 폴더 배지.

        Browse.Item "count"의 folder_id 필터는 **직속만** 세서, 자식이 폴더뿐인
        중간 폴더(연도 폴더 등) 배지가 0장이 되던 문제(2026-08-13)를 서브트리
        합산으로 해결. ① 마운트가 설정돼 있으면 디스크에서 직접 재귀 카운트
        (DSM 왕복 0회) ② 없으면 서브트리 폴더를 훑어 폴더별 count를 상한 병렬로
        합산(레벨 병렬, _TRASH_CONCURRENCY 상한 — 세마포어 독점 방지)."""
        space = self._folder_space(folder_id)
        n = await self._folder_count_disk(space, folder_id)
        if n is not None:
            return n
        ids = await self._descendant_folder_ids(space, int(folder_id))

        async def one(fid: int) -> int:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Item"),
                "count",
                version=1,
                sid=self._sid,
                extra={"folder_id": fid},
            )
            return int(data.get("count", 0))

        counts = await _bounded_gather([one(fid) for fid in ids], _TRASH_CONCURRENCY)
        return sum(counts)

    async def _folder_count_disk(self, space: str, folder_id: str) -> int | None:
        """마운트(THUMB_MOUNT_TEAM/HOMES)에서 서브트리 사진·동영상 수를 직접
        센다. 폴더 메타의 Photos 경로(name)를 실제 공유 경로로 환산 — 공용은
        /photo+name, 개인은 /homes/<계정>/Photos+name. 마운트 미설정·경로 부재
        (인덱스 지연/rename 직후)면 None → API 폴백."""
        meta = _FOLDER_META.get(self._sid, {}).get(folder_id)
        if meta is None:
            return None
        name = meta[1]
        if space == "team":
            fs_id = f"/photo{name}"
        else:
            account = _SID_ACCOUNT.get(self._sid)
            if not account:
                return None
            fs_id = f"/homes/{account}/Photos{name}"
        from .capture_fix import disk_path  # 지연 임포트 (모듈 순환 방지)

        disk = disk_path(fs_id)
        if not disk:
            return None
        from .homes_source import _count_media_on_disk

        return await asyncio.to_thread(_count_media_on_disk, disk)

    async def members(self) -> list[MemberInfo]:
        # 관리자 전용: /homes 하위 폴더명 = 구성원 계정 (user home 서비스 전제).
        # 전부 노출하되 개인 사진 공간(/homes/<u>/Photos) 유무를 표기 —
        # Photos를 안 써본 가족도 선택은 가능해야 한다 (2026-07-03 컨셉 결정).
        data = await self._dsm.call(
            "SYNO.FileStation.List",
            "list",
            sid=self._sid,
            extra={"folder_path": "/homes", "limit": 200},
        )
        names = [
            f.get("name", "")
            for f in data.get("files", [])
            if f.get("isdir") and not f.get("name", "").startswith("@")
        ]

        async def probe(name: str) -> MemberInfo:
            try:
                await self._dsm.call(
                    "SYNO.FileStation.List",
                    "list",
                    sid=self._sid,
                    extra={"folder_path": f"/homes/{name}/Photos", "limit": 1},
                )
                return MemberInfo(name=name, has_photos=True)
            except Exception:  # no Photos dir yet (408)
                return MemberInfo(name=name, has_photos=False)

        results = await asyncio.gather(*(probe(n) for n in names))
        return sorted(results, key=lambda m: (not m.has_photos, m.name))

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        # 썸네일은 item id가 아니라 cache_key 접두의 unit_id로 요청해야 한다.
        # 복사/이동으로 생긴 항목은 원본의 썸네일 유닛을 공유해 두 id가 다르고,
        # item id로 부르면 DSM이 404를 준다(2026-07-10 실 NAS 확인: id=102703은
        # 404, unit 102622는 OK — Synology Photos 웹도 unit_id로 요청).
        unit = cache_key.split("_", 1)[0]
        return await self._dsm.fetch_binary(
            _ns(space, "SYNO.Foto.Thumbnail"),
            "get",
            sid=self._sid,
            extra={
                "id": unit if unit.isdigit() else item_id,
                "cache_key": cache_key,
                "type": "unit",
                "size": size,
            },
        )

    async def video_stream(
        self, space: str, item_id: str, range_header: str | None,
        cache_key: str = "",
    ):
        # SYNO.Foto(Team).Download 는 Range 요청에 206 + Content-Range 로
        # 응답한다 (실 NAS raw 확인 2026-07-03) — 시킹까지 그대로 프록시.
        # Download도 썸네일처럼 item id가 아니라 cache_key 접두의 unit_id를
        # 요구한다(복사본은 원본 유닛 공유 — 2026-07-12 실 NAS: item id=117,
        # unit id=정상). cache_key가 없으면 item id로 폴백(비복사본은 동일).
        unit = cache_key.split("_", 1)[0]
        uid = int(unit) if unit.isdigit() else int(item_id)
        return await self._dsm.stream_binary(
            _ns(space, "SYNO.Foto.Download"),
            "download",
            version=1,
            sid=self._sid,
            extra={"unit_id": f"[{uid}]"},
            range_header=range_header,
        )

    async def item_hashes(self, space: str, item: PhotoItem) -> tuple[str, str, str]:
        """Real hashes over the small thumbnail (D절: 원본 전송 회피).

        SHA-256 over thumbnail bytes(동일 원본 → 동일 Synology 썸네일 전제,
        실 NAS 검증 항목), pHash + ThumbHash over the decoded pixels.
        """
        data, _ = await self.thumbnail(space, item.id, item.cache_key, "sm")
        return compute_hashes(data)

    # ------------------------------------------------------------ write side
    #
    # 실 NAS 검증(DSM 7.2, 2026-07):
    # - item→경로: Browse.Item get + additional=["folder"] → prefix+folder+name
    # - 이동/복사: FileStation.CopyMove start→status 폴링(remove_src=이동/복사)
    # - 삭제: photo 공유폴더 휴지통 비활성이라 Delete는 영구삭제 → 앱 관리
    #   휴지통 폴더(/photo/#trash/<time_ns>/)로 CopyMove. 복원은 역이동.
    # - 복사 취소(undo)만 실제 Delete(영구) — 방금 만든 사본이므로 안전.
    # 재인덱싱 지연으로 buckets 캐시는 쓰기 후 무효화한다.
    TRASH_DIRNAME = "#trash"
    TRASH_ROOT = f"/photo/{TRASH_DIRNAME}"

    def _share_prefix(self, space: str) -> str:
        # 실 NAS 검증(2026-07): 공용 = /photo, 개인 = /home/Photos(로그인 사용자
        # 홈 alias, = /homes/<user>/Photos). 관리자가 타인 개인 공간을 조작하는
        # 경우의 /homes/<other>/Photos 프리픽스는 관리자 기능 단계에서 별도 처리.
        return "/photo" if space == "team" else "/home/Photos"
