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
    _FOLDER_META.pop(sid, None)
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
                if ts and str(it.get("id")) not in trash_ids:
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
                # Trash layout is one level deep (#trash/t<ns>/files); include
                # the root itself in case files ever land there directly.
                folder_ids = [int(trash["id"])] + [
                    int(f["id"])
                    for f in await self._list_children("team", int(trash["id"]))
                ]
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

    async def _filtered_items(self, space: str, filters: dict) -> list[PhotoItem]:
        """All Browse.Item results matching a filter (folder/person/place),
        fully paginated (limit-1000 truncation 방지). 휴지통 아이템은 제외
        (인물/장소 태그는 삭제 후에도 인덱스에 남는다)."""
        trash_ids = await self._trash_item_ids(space)
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
                unit = thumb.get("unit_id")
                out.append(
                    PersonInfo(
                        id=str(p.get("id")),
                        space=space,
                        name=p.get("name") or "",
                        item_count=p.get("item_count"),
                        cover_item_id=str(unit) if unit else None,
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
        self, src_paths: list[str], dest_dir: str, *, remove_src: bool
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
                "overwrite": "false",
            },
        )
        await self._poll_task("SYNO.FileStation.CopyMove", 3, data.get("taskid"))

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
        out: dict[str, dict] = {}
        for it in data.get("list", []):
            folder = it.get("additional", {}).get("folder") or {}
            folder_name = folder.get("name") if isinstance(folder, dict) else folder
            filename = it.get("filename", "")
            day = date.fromtimestamp(it.get("time", 0)).isoformat()
            out[str(it.get("id"))] = {
                "path": f"{prefix}{folder_name}/{filename}".replace("//", "/"),
                "filename": filename,
                "folder_id": str(it.get("folder_id", "")),
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

    async def move(
        self,
        space: str,
        item_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
    ) -> MoveOutcome:
        metas = await self._item_meta(space, item_ids)
        dest_dir, dest_space = await self._dest_dir(dest_folder_id)
        dest_name = _FOLDER_META.get(self._sid, {}).get(dest_folder_id, (dest_space, ""))[1]
        outcome = MoveOutcome(dest_space=dest_space, dest_name=dest_name)
        affected: set[tuple[str, str]] = set()
        src_paths = [metas[i]["path"] for i in item_ids if i in metas]

        await self._copymove_chunked(
            src_paths, dest_dir, remove_src=not copy, on_progress=on_progress
        )

        for item_id in item_ids:
            m = metas.get(item_id)
            if not m:
                continue
            day = m["day"]
            dest_path = f"{dest_dir}/{m['filename']}"
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
        outcome.affected = sorted(affected)
        self._invalidate(affected)
        return outcome

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
        return await self._reverse(placements, on_progress)  # undo move

    async def restore(
        self, placements: list[PlacedItem], on_progress: ProgressFn | None = None
    ) -> Affected:
        return await self._reverse(placements, on_progress)  # undo delete

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
            data = await self._dsm.call(
                "SYNO.FileStation.List",
                "list",
                sid=self._sid,
                extra={"folder_path": dest_dir, "limit": 1000},
            )
        except DsmError:
            return False
        for entry in data.get("files", []):
            name = entry.get("name", "")
            if name.startswith("@") or name in self._JUNK_ENTRIES:
                continue
            return False
        await self._delete_paths([dest_dir])
        invalidate_folder_cache(self._sid)
        # Photos keeps listing the folder until it reindexes → hide it now
        # (tombstone) so the tree drops it immediately after the toast.
        _REMOVED_FOLDERS.setdefault(self._sid, {})[str(folder_id)] = _time.monotonic()
        return True

    async def move_folders(
        self,
        space: str,
        folder_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
    ) -> dict:
        dest_dir, _ = await self._dest_dir(dest_folder_id)
        src_dirs: list[str] = []
        names: list[str] = []
        moved_ids: list[str] = []
        for fid in folder_ids:
            src, _ = await self._dest_dir(fid)
            # Guard: 자기 자신/자기 하위로의 이동은 무한 중첩 — 차단.
            if dest_dir == src or dest_dir.startswith(src + "/"):
                raise DsmError(
                    100, f"'{src.rsplit('/', 1)[-1]}' 폴더를 자기 자신(하위) 안으로 옮길 수 없습니다."
                )
            if src.rsplit("/", 1)[0] == dest_dir and not copy:
                continue  # 이미 대상 폴더 안 — no-op
            src_dirs.append(src)
            names.append(src.rsplit("/", 1)[-1])
            moved_ids.append(str(fid))
        if src_dirs:
            # CopyMove는 디렉터리도 재귀 이동/복사한다 (실 NAS 검증 —
            # 2026-07-03 MobileBackup 평탄화 작업에서 대량 실사용).
            await self._copymove_chunked(
                src_dirs, dest_dir, remove_src=not copy, on_progress=on_progress
            )
        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)
        if not copy:
            # 이동된 원본 폴더도 인덱스 재색인 전까지 트리에 남으므로 tombstone.
            tomb = _REMOVED_FOLDERS.setdefault(self._sid, {})
            now = _time.monotonic()
            for fid in moved_ids:
                tomb[fid] = now
        undo = [
            {"src": src, "dest": f"{dest_dir}/{src.rsplit('/', 1)[-1]}"}
            for src in src_dirs
        ]
        return {"names": names, "undo": undo}

    async def revert_move_folders(self, undo_payload: list, copy: bool) -> None:
        if copy:
            # 복사 취소: 만들어진 사본 폴더를 영구 삭제 (방금 만든 사본).
            await self._delete_paths([e["dest"] for e in undo_payload])
        else:
            for e in undo_payload:
                parent = e["src"].rsplit("/", 1)[0]
                await self._copymove([e["dest"]], parent, remove_src=True)
            # 되돌린 원본 폴더가 트리에 다시 보여야 한다 — 혹 Photos가 폴더 id를
            # 재사용하면 tombstone이 복원본을 가릴 수 있으므로 전부 해제.
            _REMOVED_FOLDERS.pop(self._sid, None)
        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)

    def _invalidate(self, affected: set[tuple[str, str]]) -> None:
        for space, _ in affected:
            invalidate_bucket_cache(self._sid, space)
