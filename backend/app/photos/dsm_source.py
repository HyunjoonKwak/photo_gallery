"""DSM-backed photo source (SYNO.Foto.* / SYNO.FotoTeam.*).

⚠️ 실 NAS 미검증 (spec ch.7: Photos API는 비공식 문서만 존재).
아래 엔드포인트/파라미터/응답 필드는 커뮤니티 문서(zeichensatz/SynologyPhotosAPI,
N4S4/synology-api) 기준의 최선 추정이며, 실제 NAS 검증 단계(명세 13장)에서
반드시 확인·수정해야 한다. 검증 전까지 개발은 MOCK_MODE=true 로 진행한다.

검증 필요 항목:
- SYNO.Foto.Browse.Timeline `get` 의 존재 여부와 timeline_group_unit 파라미터,
  응답의 section/list 구조 (day별 item_count)
- SYNO.Foto.Browse.Item `list` 의 start_time/end_time epoch 필터 지원 여부
- additional 파라미터의 JSON 인코딩 방식 (["thumbnail","resolution"])
- 썸네일 바이너리 응답 (SYNO.Foto.Thumbnail `get` + type/size 파라미터)
- 파일 작업(이동/복사/삭제): Foto item id → 실제 파일 경로 매핑
  (Browse.Item `get` + additional=["folder"]) 후 FileStation CopyMove/Delete.
  FileStation 쪽은 공식 문서화된 API지만, 경로 매핑과 Photos 재인덱싱 지연은
  실 NAS에서 확인 필요 (spec ch.4 '두 경로 모두 검증').
- 휴지통 복원(undo delete): #recycle 경로 규칙 확인 필요.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time
from collections import Counter
from datetime import date, datetime, timedelta

from ..dsm.client import DsmClient
from ..dsm.errors import DsmError
from ..progress import ProgressFn
from ..schemas import (
    ItemDetail,
    MemberInfo,
    PersonInfo,
    PhotoBucket,
    PhotoFolder,
    PhotoItem,
    PlaceInfo,
    PlacedItem,
)
from .hashing import compute_hashes
from .source import Affected, DeleteOutcome, MoveOutcome

logger = logging.getLogger(__name__)

# Bucket cache: (sid, space) -> (monotonic_ts, buckets). Building buckets pages
# the entire library (~2s per 5000 items), so we cache the result briefly and
# invalidate on writes. Process-local; lost on restart (rebuilds on demand).
_BUCKET_CACHE: dict[tuple[str, str], tuple[float, list[PhotoBucket]]] = {}
# Folder metadata cache: sid -> {folder_id: (space, name)}. The folder tree is
# huge (1500+) and hierarchical, so we load it lazily (one level per request)
# and remember id→(space,path) as levels are browsed. File-op helpers resolve a
# folder's space/path from here; cleared on folder create/remove.
_FOLDER_META: dict[str, dict[str, tuple[str, str]]] = {}
# Top-level folders are the one slow level (DSM scans all top folders); cache
# them per sid. Deeper levels are fast and fetched live.
_TOP_FOLDER_CACHE: dict[str, tuple[float, list[PhotoFolder]]] = {}
# App-trash item ids: sid -> (monotonic_ts, ids). Photos indexes /photo/#trash
# like any folder, so listings must subtract these (see _trash_item_ids).
_TRASH_ID_CACHE: dict[str, tuple[float, frozenset[str]]] = {}
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
    # Trash contents change on the same writes that stale the buckets
    # (delete/restore/purge) — one invalidation hook covers both.
    _TRASH_ID_CACHE.pop(sid, None)
    if space is None:
        for key in [k for k in _BUCKET_CACHE if k[0] == sid]:
            _BUCKET_CACHE.pop(key, None)
    else:
        _BUCKET_CACHE.pop((sid, space), None)


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


class DsmPhotoSource:
    """PhotoSource implementation talking to Synology Photos via the Web API."""

    def __init__(self, dsm: DsmClient, sid: str):
        self._dsm = dsm
        self._sid = sid

    async def buckets(self, space: str) -> list[PhotoBucket]:
        """Day buckets grouped in local (KST) time by paging the whole library.

        실 NAS 검증(DSM 7.2, 2026-07): SYNO.Foto.Browse.Timeline 의 일별 count 는
        UTC 계열로 그룹핑되어 우리가 쓰는 로컬(KST) 자정 경계 items() 와 날짜별
        개수가 어긋난다(사진 표시는 정확하나 헤더 count 불일치). 정확도를 위해
        Timeline 을 쓰지 않고 Browse.Item 을 전량 페이징하며 taken time 을 서버
        로컬 타임존으로 그룹핑한다 — buckets 와 items 가 동일 소스·동일 TZ 라
        개수가 정확히 일치한다. (배포 컨테이너 TZ=Asia/Seoul 전제 — docker 설정)

        비용: 라이브러리당 ~2s/5000장. 결과는 (sid,space)로 짧게 캐시하고
        쓰기 작업 시 무효화한다.
        """
        cache_key = (self._sid, space)
        cached = _BUCKET_CACHE.get(cache_key)
        if cached and (_time.monotonic() - cached[0]) < _BUCKET_TTL:
            return cached[1]

        trash_ids = await self._trash_item_ids(space)
        tomb = _tombstoned_items(self._sid)
        counter: Counter[str] = Counter()
        offset = 0
        while True:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Item"),
                "list",
                version=1,
                sid=self._sid,
                # additional 생략 → time 만 받아 페이로드 최소화.
                extra={"offset": offset, "limit": _PAGE},
            )
            items = data.get("list", [])
            for it in items:
                ts = it.get("time")
                iid = str(it.get("id"))
                if ts and iid not in trash_ids and iid not in tomb:
                    counter[date.fromtimestamp(ts).isoformat()] += 1
            if len(items) < _PAGE:
                break
            offset += _PAGE

        out = [
            PhotoBucket(day=day, count=count)
            for day, count in sorted(counter.items(), reverse=True)
        ]
        _BUCKET_CACHE[cache_key] = (_time.monotonic(), out)
        return out

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        d = date.fromisoformat(day)
        start = int(datetime(d.year, d.month, d.day).timestamp())
        end = int((datetime(d.year, d.month, d.day) + timedelta(days=1)).timestamp())
        trash_ids = await self._trash_item_ids(space)
        tomb = _tombstoned_items(self._sid)
        # Page through the whole day — a single mobile-backup day can hold
        # thousands of photos, so a fixed limit would silently truncate it.
        out: list[PhotoItem] = []
        offset = 0
        while True:
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
                    "sort_direction": "asc",
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
            if len(page) < _PAGE:
                break
            offset += _PAGE
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
        cached = _TRASH_ID_CACHE.get(self._sid)
        if cached and (_time.monotonic() - cached[0]) < _BUCKET_TTL:
            return cached[1]
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
                # 된다. 따라서 #trash 아래 모든 하위 폴더를 재귀 수집해야
                # 중첩된 사진까지 타임라인에서 빠진다(2026-07-06 사용자 보고).
                folder_ids = await self._descendant_folder_ids(
                    "team", int(trash["id"])
                )
                for fid in folder_ids:
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
                        ids.update(str(it.get("id")) for it in page)
                        if len(page) < 1000:
                            break
                        offset += 1000
        except DsmError:
            # Filtering is best-effort — a probe failure must not break the
            # timeline. Uncached so the next call retries.
            return frozenset()
        result = frozenset(ids)
        _TRASH_ID_CACHE[self._sid] = (_time.monotonic(), result)
        return result

    @staticmethod
    def _to_item(it: dict) -> PhotoItem:
        additional = it.get("additional", {})
        resolution = additional.get("resolution", {})
        thumb = additional.get("thumbnail", {})
        video_meta = additional.get("video_meta") or {}
        return PhotoItem(
            id=str(it.get("id")),
            filename=it.get("filename", ""),
            taken_at=datetime.fromtimestamp(it.get("time", 0)).isoformat(),
            width=int(resolution.get("width", 4)) or 4,
            height=int(resolution.get("height", 3)) or 3,
            size=it.get("filesize"),
            cache_key=thumb.get("cache_key", ""),
            type="video" if it.get("type") == "video" else "photo",
            duration_ms=video_meta.get("duration"),
            placeholder_color=None,  # thumbhash lands with photo_cache (phase 2)
            folder=None,
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
        stack = [root_id]
        while stack:
            fid = stack.pop()
            for f in await self._list_children(space, fid):
                cid = int(f["id"])
                out.append(cid)
                stack.append(cid)
        return out

    async def _filtered_items(self, space: str, filters: dict) -> list[PhotoItem]:
        """All Browse.Item results matching a filter (folder/person/place),
        fully paginated (limit-1000 truncation 방지). 휴지통·삭제/이동 대기 아이템은
        제외 (Photos 인덱스는 삭제·이동을 재색인 전까지 계속 반환한다)."""
        trash_ids = await self._trash_item_ids(space)
        tomb = _tombstoned_items(self._sid)
        out: list[PhotoItem] = []
        offset = 0
        page_size = 1000
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

    async def folder_items(self, folder_id: str) -> list[PhotoItem]:
        # folder_id 필터는 실 NAS 동작 확인됨(2026-07): 해당 폴더의 "직속" 사진만
        # 반환(하위 폴더 사진 미포함). 폴더 space는 메타 캐시에서 판정(UI가 트리
        # 탐색 중 채움); 미스면 최상위를 한 번 로드해 시도.
        space = self._folder_space(folder_id)
        return await self._filtered_items(space, {"folder_id": int(folder_id)})

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

        return ItemDetail(
            id=item_id, folder=folder_name, exif=exif, address=address
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
                    "keyword": keyword,
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
                # 실 NAS(DSM 7.2, 2026-07 raw 확인): 사람 커버 사진 id는
                # top-level `cover`에 오고, 썸네일 cache_key는
                # additional.thumbnail.cache_key. (구버전 호환으로 unit_id도
                # fallback.) 사진 썸네일과 동일하게 id=item id + type=unit로 프록시.
                cover = p.get("cover") or thumb.get("unit_id")
                out.append(
                    PersonInfo(
                        id=str(p.get("id")),
                        space=space,
                        name=p.get("name") or "",
                        item_count=p.get("item_count"),
                        cover_item_id=str(cover) if cover else None,
                        cover_cache_key=thumb.get("cache_key"),
                    )
                )
            if len(page) < 100:
                break
            offset += 100
        out.sort(key=lambda p: -(p.item_count or 0))
        return out

    async def person_items(self, space: str, person_id: str) -> list[PhotoItem]:
        return await self._filtered_items(space, {"person_id": int(person_id)})

    async def debug_persons_raw(self, space: str) -> dict:
        """진단용: Person list 원본 응답(첫 3명)을 가공 없이 반환. 사람 탭에
        👤 placeholder만 뜨는 경우(=cover_item_id 미확보) 실 NAS의 썸네일
        정보가 실제로 어느 필드에 오는지 확인하려는 용도."""
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Person"),
            "list",
            version=1,
            sid=self._sid,
            extra={
                "offset": 0,
                "limit": 3,
                "additional": json.dumps(["thumbnail"]),
            },
        )
        return {"space": space, "persons": data.get("list", [])[:3]}

    async def places(self, space: str) -> list[PlaceInfo]:
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
                )
                for g in page
            )
            if len(page) < 200:
                break
            offset += 200
        out.sort(key=lambda g: -(g.item_count or 0))
        return out

    async def place_items(self, space: str, place_id: str) -> list[PhotoItem]:
        return await self._filtered_items(space, {"geocoding_id": int(place_id)})

    async def videos(self, space: str) -> list[PhotoItem]:
        # 라이브러리 전체를 페이징하며 type=="video"만 (buckets 패턴 복제).
        # DSM에 파일유형 필터 파라미터가 있는지는 실 NAS 프로브 미검증이라,
        # 앱단 필터로 동작(있으면 추후 최적화). 휴지통/tombstone 제외.
        trash_ids = await self._trash_item_ids(space)
        tomb = _tombstoned_items(self._sid)
        out: list[PhotoItem] = []
        offset = 0
        while True:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Item"),
                "list",
                version=1,
                sid=self._sid,
                extra={
                    "offset": offset,
                    "limit": _PAGE,
                    "additional": json.dumps(
                        ["thumbnail", "resolution", "video_meta"]
                    ),
                },
            )
            page = data.get("list", [])
            for it in page:
                iid = str(it.get("id"))
                if (
                    it.get("type") == "video"
                    and iid not in trash_ids
                    and iid not in tomb
                ):
                    out.append(self._to_item(it))
            if len(page) < _PAGE:
                break
            offset += _PAGE
        out.sort(key=lambda i: i.taken_at, reverse=True)
        return out

    async def folder_count(self, folder_id: str) -> int:
        # Browse.Item "count" takes the same filters as "list" — one cheap call
        # instead of paging every item just to count it.
        space = self._folder_space(folder_id)
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Item"),
            "count",
            version=1,
            sid=self._sid,
            extra={"folder_id": int(folder_id)},
        )
        return int(data.get("count", 0))

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
        return await self._dsm.fetch_binary(
            _ns(space, "SYNO.Foto.Thumbnail"),
            "get",
            sid=self._sid,
            extra={
                "id": item_id,
                "cache_key": cache_key,
                "type": "unit",
                "size": size,
            },
        )

    async def video_stream(
        self, space: str, item_id: str, range_header: str | None
    ):
        # SYNO.Foto(Team).Download 는 Range 요청에 206 + Content-Range 로
        # 응답한다 (실 NAS raw 확인 2026-07-03) — 시킹까지 그대로 프록시.
        return await self._dsm.stream_binary(
            _ns(space, "SYNO.Foto.Download"),
            "download",
            version=1,
            sid=self._sid,
            extra={"unit_id": f"[{int(item_id)}]"},
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

    async def _copymove(
        self,
        src_paths: list[str],
        dest_dir: str,
        *,
        remove_src: bool,
        overwrite: bool = False,
    ) -> None:
        data = await self._dsm.call(
            "SYNO.FileStation.CopyMove",
            "start",
            version=3,
            sid=self._sid,
            extra={
                "path": json.dumps(src_paths),
                "dest_folder_path": dest_dir,
                "remove_src": "true" if remove_src else "false",
                "overwrite": "true" if overwrite else "false",
            },
        )
        await self._poll_task("SYNO.FileStation.CopyMove", 3, data.get("taskid"))

    async def _rename(self, path: str, new_name: str) -> None:
        data = await self._dsm.call(
            "SYNO.FileStation.Rename",
            "rename",
            version=2,
            sid=self._sid,
            extra={"path": path, "name": new_name},
        )
        # Rename may run as a task (taskid) or return synchronously — poll if async.
        if data.get("taskid"):
            await self._poll_task("SYNO.FileStation.Rename", 2, data.get("taskid"))

    async def _list_entries(self, dir_path: str) -> list[dict]:
        try:
            data = await self._dsm.call(
                "SYNO.FileStation.List",
                "list",
                sid=self._sid,
                extra={
                    "folder_path": dir_path,
                    "limit": 100000,
                    # size for folder-equality comparison (완전 일치 판정).
                    "additional": json.dumps(["size"]),
                },
            )
        except DsmError:
            return []
        return data.get("files", [])

    @staticmethod
    def _entry_size(entry: dict) -> int | None:
        # FileStation.List returns size under additional (or occasionally flat).
        add = entry.get("additional") or {}
        return add.get("size", entry.get("size"))

    async def _folder_extra_count(self, src_dir: str, dest_dir: str) -> int:
        """How many items ``src_dir`` holds that ``dest_dir`` does NOT, compared
        by name+size and recursing into same-named subfolders. 0 ⇒ the source is
        fully contained in the destination (완전 일치). Junk/sidecar entries are
        ignored. Best-effort: a listing error counts as "not contained" so we
        never claim a false full-match."""
        dest = {e.get("name", ""): e for e in await self._list_entries(dest_dir)}
        extra = 0
        for e in await self._list_entries(src_dir):
            name = e.get("name", "")
            if name.startswith("@") or name in self._JUNK_ENTRIES:
                continue
            d = dest.get(name)
            if e.get("isdir"):
                if d and d.get("isdir"):
                    extra += await self._folder_extra_count(
                        f"{src_dir}/{name}", f"{dest_dir}/{name}"
                    )
                else:
                    extra += 1  # 대상에 없는 하위 폴더 = 추가 항목
            elif not d or d.get("isdir") or self._entry_size(d) != self._entry_size(e):
                extra += 1  # 대상에 없거나 크기가 다른 파일 = 추가 항목
        return extra

    async def _list_filenames(self, dir_path: str) -> set[str]:
        """Filenames directly in a folder (filesystem truth), for conflict checks."""
        return {f.get("name", "") for f in await self._list_entries(dir_path)}

    async def _is_dir_empty(self, dir_path: str) -> bool:
        """True if a folder holds no real content — Synology sidecars(@eaDir)
        and desktop droppings don't count (DSM's own UI treats such folders as
        empty too). Filesystem truth (FileStation), not the lagging Photos
        index."""
        for entry in await self._list_entries(dir_path):
            name = entry.get("name", "")
            if name.startswith("@") or name in self._JUNK_ENTRIES:
                continue
            return False
        return True

    async def _list_subdir_names(self, dir_path: str) -> set[str]:
        """Sub-folder names directly in a folder, for folder-move conflict checks."""
        return {
            f.get("name", "") for f in await self._list_entries(dir_path) if f.get("isdir")
        }

    @staticmethod
    def _unique_dir_name(taken: set[str], name: str) -> str:
        """folder → folder_1 (or _2, …) not already present (no extension logic)."""
        n = 1
        while f"{name}_{n}" in taken:
            n += 1
        return f"{name}_{n}"

    @staticmethod
    def _unique_name(taken: set[str], filename: str) -> str:
        """photo.jpg → photo_1.jpg (or _2, … ) not present in ``taken``."""
        if "." in filename:
            base, ext = filename.rsplit(".", 1)
            ext = "." + ext
        else:
            base, ext = filename, ""
        n = 1
        while f"{base}_{n}{ext}" in taken:
            n += 1
        return f"{base}_{n}{ext}"

    async def _delete_paths(self, paths: list[str]) -> None:
        data = await self._dsm.call(
            "SYNO.FileStation.Delete",
            "start",
            version=2,
            sid=self._sid,
            extra={"path": json.dumps(paths)},
        )
        await self._poll_task("SYNO.FileStation.Delete", 2, data.get("taskid"))

    async def _poll_task(self, api: str, version: int, taskid: str | None) -> None:
        if not taskid:
            raise DsmError(100, "파일 작업 태스크를 시작하지 못했습니다.")
        for _ in range(120):  # ≤ 60s
            status = await self._dsm.call(
                api, "status", version=version, sid=self._sid,
                extra={"taskid": taskid},
            )
            if status.get("finished"):
                return
            await asyncio.sleep(0.5)
        raise DsmError(100, "파일 작업이 제한 시간 안에 끝나지 않았습니다.")

    async def _item_meta(
        self, space: str, item_ids: list[str]
    ) -> dict[str, dict]:
        """id → {path, folder_id, day} for the given items."""
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Item"),
            "get",
            version=1,
            sid=self._sid,
            extra={
                "id": json.dumps([int(i) for i in item_ids]),
                "additional": json.dumps(["folder"]),
            },
        )
        prefix = self._share_prefix(space)
        metas = _FOLDER_META.setdefault(self._sid, {})
        out: dict[str, dict] = {}
        for it in data.get("list", []):
            folder = it.get("additional", {}).get("folder") or {}
            folder_name = folder.get("name") if isinstance(folder, dict) else folder
            filename = it.get("filename", "")
            day = date.fromtimestamp(it.get("time", 0)).isoformat()
            fid = str(it.get("folder_id", ""))
            # Remember the source folder's (space, path) so a later 정리 제안 can
            # resolve it by id without the tree having been browsed first — the
            # move originates from the timeline as often as the folder view.
            if fid and folder_name:
                metas.setdefault(fid, (space, folder_name))
            out[str(it.get("id"))] = {
                "path": f"{prefix}{folder_name}/{filename}".replace("//", "/"),
                "filename": filename,
                "folder_id": fid,
                "day": day,
            }
        return out

    def _folder_space(self, folder_id: str) -> str:
        meta = _FOLDER_META.get(self._sid, {}).get(folder_id)
        if meta is None:
            raise DsmError(100, "폴더를 먼저 탐색해야 합니다 (경로 캐시 없음).")
        return meta[0]

    async def _dest_dir(self, dest_folder_id: str) -> tuple[str, str]:
        """dest folder id → (absolute dir path, space) via the metadata cache."""
        meta = _FOLDER_META.get(self._sid, {}).get(dest_folder_id)
        if meta is None:
            raise DsmError(100, "대상 폴더를 먼저 탐색해야 합니다 (경로 캐시 없음).")
        space, name = meta
        prefix = self._share_prefix(space)
        return f"{prefix}{name}".replace("//", "/").rstrip("/") or prefix, space

    # Bulk CopyMove is chunked so count-based progress can be reported between
    # chunks (B-6 진행 바). Partial-failure semantics are unchanged: DSM's own
    # task also processes files one by one server-side.
    COPYMOVE_CHUNK = 25

    async def _copymove_chunked(
        self,
        src_paths: list[str],
        dest_dir: str,
        *,
        remove_src: bool,
        on_progress: ProgressFn | None,
    ) -> None:
        total = len(src_paths)
        if on_progress:
            on_progress(0, total)
        for start in range(0, total, self.COPYMOVE_CHUNK):
            chunk = src_paths[start : start + self.COPYMOVE_CHUNK]
            await self._copymove(chunk, dest_dir, remove_src=remove_src)
            if on_progress:
                on_progress(min(start + len(chunk), total), total)

    async def conflicts(
        self, space: str, item_ids: list[str], dest_folder_id: str
    ) -> list[tuple[str, str]]:
        metas = await self._item_meta(space, item_ids)
        dest_dir, _ = await self._dest_dir(dest_folder_id)
        existing = await self._list_filenames(dest_dir)
        return [
            (i, metas[i]["filename"])
            for i in item_ids
            if i in metas and metas[i]["filename"] in existing
        ]

    async def move(
        self,
        space: str,
        item_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
        conflict_strategy: str = "skip",
    ) -> MoveOutcome:
        metas = await self._item_meta(space, item_ids)
        dest_dir, dest_space = await self._dest_dir(dest_folder_id)
        dest_name = _FOLDER_META.get(self._sid, {}).get(dest_folder_id, (dest_space, ""))[1]
        outcome = MoveOutcome(dest_space=dest_space, dest_name=dest_name)
        affected: set[tuple[str, str]] = set()

        existing = await self._list_filenames(dest_dir)
        present = [i for i in item_ids if i in metas]
        clashing = [i for i in present if metas[i]["filename"] in existing]
        clash_ids = set(clashing)

        # Items that move under their own name: non-clashing always, plus the
        # clashing ones when overwriting (they replace the existing file).
        if conflict_strategy == "overwrite":
            plain = present
        else:  # skip or rename → clashing items are handled separately/omitted
            plain = [i for i in present if i not in clash_ids]

        if plain:
            await self._copymove_chunked(
                [metas[i]["path"] for i in plain],
                dest_dir,
                remove_src=not copy,
                overwrite=(conflict_strategy == "overwrite"),
                on_progress=on_progress,
            )
        for item_id in plain:
            self._record_placed(outcome, affected, space, dest_space, dest_dir,
                                 metas[item_id], item_id, copy, metas[item_id]["filename"])

        # rename: give each clashing file a fresh "name_1.ext" and place it via a
        # temp folder (CopyMove can't rename its target, so copy→rename→move).
        if conflict_strategy == "rename" and clashing:
            taken = set(existing)
            for item_id in clashing:
                m = metas[item_id]
                new_name = self._unique_name(taken, m["filename"])
                taken.add(new_name)
                await self._place_renamed(m["path"], dest_dir, m["filename"],
                                          new_name, copy=copy)
                self._record_placed(outcome, affected, space, dest_space, dest_dir,
                                    m, item_id, copy, new_name)

        if not copy and outcome.moved:
            # Hide moved ids at their OLD location right away — Photos keeps them
            # under the old folder_id until it reindexes (실 NAS: "이동했는데
            # 원본 폴더에 그대로 보임"). The item reappears at the destination
            # with a new id once reindexed (프론트 resettle 재조회).
            _tombstone_items(self._sid, [p.id for p in outcome.moved])
            # A move can leave the source folder(s) empty — surface them so the
            # client can offer 정리(빈 폴더 삭제).
            outcome.emptied = await self._detect_emptied(space, metas, outcome.moved)

        outcome.affected = sorted(affected)
        self._invalidate(affected)
        return outcome

    async def _detect_emptied(
        self, space: str, metas: dict[str, dict], moved: list[PlacedItem]
    ) -> list[tuple[str, str, str]]:
        """Source folders left empty after moving ``moved`` out of them.

        Grouped by source folder id; each is re-listed once (post-move) against
        the filesystem. Returns (folder_id, basename, space) for the empty ones.
        """
        # folder_id → (dir_path, basename); dedup so each folder is listed once.
        by_folder: dict[str, tuple[str, str]] = {}
        for p in moved:
            m = metas.get(p.id)
            if not m or not p.folder_id:
                continue
            dir_path = m["path"].rsplit("/", 1)[0]
            by_folder[p.folder_id] = (dir_path, dir_path.rsplit("/", 1)[-1])
        out: list[tuple[str, str, str]] = []
        for fid, (dir_path, basename) in by_folder.items():
            try:
                if await self._is_dir_empty(dir_path):
                    out.append((fid, basename, space))
            except DsmError:
                continue  # best-effort — a probe failure just omits the offer
        return out

    @staticmethod
    def _record_placed(outcome, affected, space, dest_space, dest_dir, m, item_id,
                       copy, dest_filename) -> None:
        day = m["day"]
        dest_path = f"{dest_dir}/{dest_filename}"
        affected.add((space, day))
        affected.add((dest_space, day))
        if copy:
            outcome.created_ids.append(dest_path)  # DSM: path, not item id
        else:
            outcome.moved.append(
                PlacedItem(
                    id=item_id, space=space, folder_id=m["folder_id"], day=day,
                    src_path=m["path"], trash_path=dest_path,  # current location
                )
            )

    async def _place_renamed(
        self, src_path: str, dest_dir: str, filename: str, new_name: str, *, copy: bool
    ) -> None:
        # temp folder under dest so the copy/move never collides, then rename and
        # move into place. '#'-prefixed → hidden from the folder tree.
        tmp = f"{dest_dir}/#dup{_time.time_ns()}"
        await self._ensure_dir(tmp)
        try:
            await self._copymove([src_path], tmp, remove_src=not copy)
            await self._rename(f"{tmp}/{filename}", new_name)
            await self._copymove([f"{tmp}/{new_name}"], dest_dir, remove_src=True)
        finally:
            await self._delete_paths([tmp])

    async def delete(
        self,
        space: str,
        item_ids: list[str],
        on_progress: ProgressFn | None = None,
    ) -> DeleteOutcome:
        metas = await self._item_meta(space, item_ids)
        outcome = DeleteOutcome()
        affected: set[tuple[str, str]] = set()
        # One unique trash subfolder per delete op (avoids filename collisions).
        # 't' prefix: DSM rejects all-numeric folder names (code 400).
        trash_dir = f"{self.TRASH_ROOT}/t{_time.time_ns()}"
        await self._ensure_dir(trash_dir)
        src_paths = [metas[i]["path"] for i in item_ids if i in metas]
        await self._copymove_chunked(
            src_paths, trash_dir, remove_src=True, on_progress=on_progress
        )

        for item_id in item_ids:
            m = metas.get(item_id)
            if not m:
                continue
            affected.add((space, m["day"]))
            outcome.deleted.append(
                PlacedItem(
                    id=item_id, space=space, folder_id=m["folder_id"], day=m["day"],
                    src_path=m["path"], trash_path=f"{trash_dir}/{m['filename']}",
                )
            )
        # Hide the deleted ids immediately — Photos keeps returning them from the
        # folder/timeline filters until it reindexes the #trash move.
        _tombstone_items(self._sid, [p.id for p in outcome.deleted])
        outcome.affected = sorted(affected)
        self._invalidate(affected)
        return outcome

    async def _reverse(
        self, placements: list[PlacedItem], on_progress: ProgressFn | None = None
    ) -> Affected:
        """Move each item from its current (trash_path) location back to src.

        Per-item CopyMove (items return to different folders), so undoing a
        large operation is the slowest bulk path — progress is per item.
        """
        affected: set[tuple[str, str]] = set()
        total = len(placements)
        if on_progress:
            on_progress(0, total)
        for i, p in enumerate(placements):
            if not p.src_path or not p.trash_path:
                continue
            dest_dir = p.src_path.rsplit("/", 1)[0]
            await self._copymove([p.trash_path], dest_dir, remove_src=True)
            affected.add((p.space, p.day))
            if on_progress:
                on_progress(i + 1, total)
        self._invalidate(affected)
        return sorted(affected)

    async def place(
        self, placements: list[PlacedItem], on_progress: ProgressFn | None = None
    ) -> Affected:
        # Undo move: the item returns to its old path — drop its tombstone so
        # the restored location shows it again without waiting for reindex.
        _untombstone_items(self._sid, [p.id for p in placements])
        return await self._reverse(placements, on_progress)

    async def restore(
        self, placements: list[PlacedItem], on_progress: ProgressFn | None = None
    ) -> Affected:
        _untombstone_items(self._sid, [p.id for p in placements])  # undo delete
        return await self._reverse(placements, on_progress)

    async def remove_items(self, item_ids: list[str]) -> Affected:
        # undo copy: item_ids are actually the created copies' absolute paths.
        await self._delete_paths(item_ids)
        invalidate_bucket_cache(self._sid)  # day unknown per path — clear all
        return []

    async def purge_trash(self) -> None:
        # Recursively delete the whole app trash folder; it is recreated by
        # _ensure_dir on the next delete. A missing folder (never deleted
        # anything yet / already purged) is not an error.
        try:
            await self._delete_paths([self.TRASH_ROOT])
        except DsmError as exc:
            if exc.code not in (408, 900):  # no such file/dir
                raise

    async def _ensure_dir(self, path: str) -> None:
        # Create each level below the share root (/photo). Nested one-shot
        # creation with force_parent fails on '#'-prefixed segments (code 1002),
        # so build the path level by level; existing levels error out harmlessly.
        parts = path.split("/")  # ['', 'photo', '#trash', '<id>']
        for i in range(3, len(parts) + 1):
            parent = "/".join(parts[: i - 1])
            name = parts[i - 1]
            try:
                await self._dsm.call(
                    "SYNO.FileStation.CreateFolder", "create", version=2,
                    sid=self._sid, extra={"folder_path": parent, "name": name},
                )
            except DsmError:
                pass  # already exists → fine

    async def create_folder(
        self, space: str, name: str, parent_id: str | None = None
    ) -> PhotoFolder:
        if parent_id is not None:
            # 하위 폴더 생성: Browse.Folder create + target_id — 실 NAS raw
            # 검증(2026-07-03). Foto id를 즉시 돌려줘 재탐색이 필요 없다.
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Folder"),
                "create",
                version=1,
                sid=self._sid,
                extra={"target_id": int(parent_id), "name": json.dumps(name)},
            )
            folder = data.get("folder") or {}
            invalidate_folder_cache(self._sid)
            pf = PhotoFolder(
                id=str(folder.get("id")),
                name=folder.get("name", f"/{name}"),
                space=space,
                parent_id=parent_id,
                depth=max(0, str(folder.get("name", "")).strip("/").count("/")),
            )
            _FOLDER_META.setdefault(self._sid, {})[pf.id] = (space, pf.name)
            return pf
        prefix = self._share_prefix(space)
        await self._dsm.call(
            "SYNO.FileStation.CreateFolder", "create", version=2, sid=self._sid,
            extra={"folder_path": prefix, "name": name},
        )
        invalidate_folder_cache(self._sid)
        # Re-resolve via Photos so the new folder carries a Photos folder id
        # (FileStation create returns a filesystem path, not a Foto id).
        for f in await self.folders():
            if f.space == space and f.name.rstrip("/").endswith(name):
                return f
        return PhotoFolder(id=f"{prefix}/{name}", name=f"/{name}", space=space)

    # Synology sidecar dirs (@eaDir) and desktop droppings don't count as
    # folder contents — DSM's own UI treats such folders as empty too.
    _JUNK_ENTRIES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})

    async def remove_folder(self, folder_id: str) -> bool:
        # SAFETY: only EMPTY folders are removable — this also backs the
        # folder-view 삭제 버튼, so a photo-bearing folder must never vanish.
        # Emptiness is checked against the FILESYSTEM (FileStation.List), not
        # the Photos index: the index lags both ways — it kept counting
        # moved-out photos (blocking deletion of a truly empty folder,
        # 2026-07-04 실 NAS 사용자 보고) and it can miss just-added files
        # (which would delete them for good — photo share has no recycle bin).
        try:
            dest_dir, _ = await self._dest_dir(folder_id)
            if not await self._is_dir_empty(dest_dir):
                return False
        except DsmError:
            return False
        await self._delete_paths([dest_dir])
        invalidate_folder_cache(self._sid)
        # Photos keeps listing the folder until it reindexes → hide it now
        # (tombstone) so the tree drops it immediately after the toast.
        _REMOVED_FOLDERS.setdefault(self._sid, {})[str(folder_id)] = _time.monotonic()
        return True

    async def trash_folder(self, space: str, folder_id: str) -> dict:
        # 재귀 삭제 = 폴더를 통째로 앱 휴지통(/photo/#trash/t<ns>/)으로 이동.
        # 파일 단위로 풀지 않고 CopyMove 한 번으로 서브트리 전체를 옮겨(FileStation
        # 재귀), 하위 구조를 그대로 보존한다 → undo는 폴더를 원위치로 역이동.
        dest_dir, _ = await self._dest_dir(folder_id)
        basename = dest_dir.rsplit("/", 1)[-1]
        trash_dir = f"{self.TRASH_ROOT}/t{_time.time_ns()}"
        await self._ensure_dir(trash_dir)
        await self._copymove([dest_dir], trash_dir, remove_src=True)
        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)
        # 트리에서 즉시 감춤(폴더 인덱스 지연 대비, remove_folder와 동일 패턴).
        _REMOVED_FOLDERS.setdefault(self._sid, {})[str(folder_id)] = _time.monotonic()
        return {
            "name": basename,
            "undo": {"trash_path": f"{trash_dir}/{basename}", "src_dir": dest_dir},
        }

    async def restore_folder(self, undo_payload: dict) -> None:
        parent = undo_payload["src_dir"].rsplit("/", 1)[0]
        await self._ensure_dir(parent)
        await self._copymove(
            [undo_payload["trash_path"]], parent, remove_src=True
        )
        _REMOVED_FOLDERS.pop(self._sid, None)  # 복원된 폴더가 다시 보이게
        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)

    async def folder_conflicts(
        self, space: str, folder_ids: list[str], dest_folder_id: str
    ) -> list[tuple[str, str, int]]:
        dest_dir, _ = await self._dest_dir(dest_folder_id)
        existing = await self._list_subdir_names(dest_dir)
        out: list[tuple[str, str, int]] = []
        for fid in folder_ids:
            src, _ = await self._dest_dir(fid)
            if src.rsplit("/", 1)[0] == dest_dir:
                continue  # 이미 대상 안 — 충돌 아님(no-op)
            name = src.rsplit("/", 1)[-1]
            if name in existing:
                extra = await self._folder_extra_count(src, f"{dest_dir}/{name}")
                out.append((fid, name, extra))
        return out

    async def move_folders(
        self,
        space: str,
        folder_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
        conflict_strategy: str = "skip",
    ) -> dict:
        dest_dir, _ = await self._dest_dir(dest_folder_id)
        taken = await self._list_subdir_names(dest_dir)
        plain: list[str] = []  # src dirs moving under their own name
        plain_names: list[str] = []
        renamed: list[tuple[str, str]] = []  # (src, new_name)
        merges: list[tuple[str, str]] = []  # (src, basename) folded into a twin
        for fid in folder_ids:
            src, _ = await self._dest_dir(fid)
            # Guard: 자기 자신/자기 하위로의 이동은 무한 중첩 — 차단.
            if dest_dir == src or dest_dir.startswith(src + "/"):
                raise DsmError(
                    100, f"'{src.rsplit('/', 1)[-1]}' 폴더를 자기 자신(하위) 안으로 옮길 수 없습니다."
                )
            if src.rsplit("/", 1)[0] == dest_dir and not copy:
                continue  # 이미 대상 폴더 안 — no-op
            name = src.rsplit("/", 1)[-1]
            if name in taken:
                # 같은 이름 폴더가 대상에 있음: skip 건너뜀 / rename name_1 /
                # merge 내용 합치기(재귀).
                if conflict_strategy == "rename":
                    new_name = self._unique_dir_name(taken, name)
                    taken.add(new_name)
                    renamed.append((src, new_name))
                elif conflict_strategy == "merge":
                    merges.append((src, name))
                continue
            taken.add(name)
            plain.append(src)
            plain_names.append(name)

        if plain:
            # CopyMove는 디렉터리도 재귀 이동/복사한다 (실 NAS 검증 —
            # 2026-07-03 MobileBackup 평탄화 작업에서 대량 실사용).
            await self._copymove_chunked(
                plain, dest_dir, remove_src=not copy, on_progress=on_progress
            )
        for src, new_name in renamed:
            await self._place_renamed(
                src, dest_dir, src.rsplit("/", 1)[-1], new_name, copy=copy
            )
        merge_undo: list[dict] = []
        merge_names: list[str] = []
        for src, base in merges:
            undo_entry = await self._merge_dir(src, f"{dest_dir}/{base}", copy=copy)
            merge_undo.append(undo_entry)
            merge_names.append(base)

        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)
        # NOTE: 이동한 폴더는 tombstone하지 않는다 (2026-07-04 실 NAS 보고 — 재색인이
        # 폴더 id를 유지하면 대상 위치까지 숨는다). 원본 잔상은 프론트 resettle로 정리.
        names = plain_names + [nn for _, nn in renamed] + merge_names
        undo = (
            [{"src": s, "dest": f"{dest_dir}/{n}"} for s, n in zip(plain, plain_names)]
            + [{"src": s, "dest": f"{dest_dir}/{nn}"} for s, nn in renamed]
            + merge_undo
        )
        return {"names": names, "undo": undo}

    async def _merge_dir(self, src_dir: str, dest_dir: str, *, copy: bool) -> dict:
        """Fold ``src_dir``'s contents into the same-named ``dest_dir``.

        Files: non-clashing ones move/copy in; a name clash keeps the existing
        destination file and leaves the source one alone (사용자 결정). Sub-
        folders: a same-named twin recurses (merge), otherwise the whole subtree
        moves/copies in one shot. In move mode the source folder is deleted once
        fully emptied (병합 완료). Returns an undo entry for revert_move_folders.
        """
        await self._ensure_dir(dest_dir)
        dest_names = await self._list_filenames(dest_dir)
        moved: list[dict] = []  # move-undo: [{"from": dest, "to": src}]
        created: list[str] = []  # copy-undo: paths to delete
        children: list[dict] = []  # nested merge undo entries
        move_files: list[tuple[str, str]] = []
        for entry in await self._list_entries(src_dir):
            name = entry.get("name", "")
            if name.startswith("@") or name in self._JUNK_ENTRIES:
                continue
            src_path = f"{src_dir}/{name}"
            dest_path = f"{dest_dir}/{name}"
            if entry.get("isdir"):
                if name in dest_names:
                    children.append(
                        await self._merge_dir(src_path, dest_path, copy=copy)
                    )
                else:
                    await self._copymove([src_path], dest_dir, remove_src=not copy)
                    (created if copy else moved).append(
                        dest_path if copy else {"from": dest_path, "to": src_path}
                    )
            elif name in dest_names:
                continue  # 파일 충돌 → 기존 유지, 소스는 그대로 둠
            else:
                move_files.append((src_path, dest_path))
        if move_files:
            await self._copymove_chunked(
                [s for s, _ in move_files], dest_dir, remove_src=not copy,
                on_progress=None,
            )
            for s, d in move_files:
                (created if copy else moved).append(
                    d if copy else {"from": d, "to": s}
                )
        emptied = False
        if not copy and await self._is_dir_empty(src_dir):
            await self._delete_paths([src_dir])
            emptied = True
        return {
            "kind": "merge_copy" if copy else "merge",
            "moved": moved,
            "created": created,
            "children": children,
            "src_dir": src_dir,
            "emptied": emptied,
        }

    async def revert_move_folders(self, undo_payload: list, copy: bool) -> None:
        # Entries are heterogeneous: plain move/copy (whole subtree, no "kind")
        # and merge/merge_copy (per-file, recursive). Dispatch per entry so a
        # single op can mix them (merge strategy folds clashers, moves the rest).
        for e in undo_payload:
            await self._revert_folder_entry(e, copy)
        if not copy:
            # 되돌린 원본 폴더가 트리에 다시 보여야 한다 — 혹 Photos가 폴더 id를
            # 재사용하면 tombstone이 복원본을 가릴 수 있으므로 전부 해제.
            _REMOVED_FOLDERS.pop(self._sid, None)
        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)

    async def _revert_folder_entry(self, e: dict, copy: bool) -> None:
        kind = e.get("kind", "move")
        if kind == "merge_copy":
            if e.get("created"):
                await self._delete_paths(e["created"])
            for child in e.get("children", []):
                await self._revert_folder_entry(child, True)
        elif kind == "merge":
            # Move each merged file back to its source folder (recreating the
            # deleted source dir first), then recurse into nested merges.
            for mv in e.get("moved", []):
                parent = mv["to"].rsplit("/", 1)[0]
                await self._ensure_dir(parent)
                await self._copymove([mv["from"]], parent, remove_src=True)
            for child in e.get("children", []):
                await self._revert_folder_entry(child, False)
        elif copy:  # 통째 복사 취소: 사본 폴더 영구 삭제
            await self._delete_paths([e["dest"]])
        else:  # 통째 이동 취소: 원위치로 역이동
            parent = e["src"].rsplit("/", 1)[0]
            await self._copymove([e["dest"]], parent, remove_src=True)

    def _invalidate(self, affected: set[tuple[str, str]]) -> None:
        for space, _ in affected:
            invalidate_bucket_cache(self._sid, space)
