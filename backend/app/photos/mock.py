"""Deterministic + stateful mock photo source — full app flows without a NAS.

Read side stays deterministic (seeded PRNGs per (space, day)), while an
in-memory overlay tracks mutations so move/copy/delete/undo behave visibly:

- ``_loc``      id → (space, folder_id): effective location overrides
- ``_deleted``  id → (item, space, folder_id): the trash, with snapshots
- ``_extras``   id → PhotoItem: copies created by copy-mode moves
- ``_touched``  (space, day) pairs whose counts can no longer use the seed

The overlay is process-local: restarting the dev server resets all mutations
(the generated photo data itself is stable). Personal-space data is shared
across accounts — a mock artifact; real per-user data arrives with DSM.
"""

from __future__ import annotations

import asyncio
import posixpath
import re
from datetime import date, timedelta
from random import Random
from zlib import crc32

from fastapi import HTTPException, status

from ..schemas import (
    AlbumInfo,
    FolderRename,
    ItemDetail,
    MemberInfo,
    PersonInfo,
    PhotoBucket,
    PhotoFolder,
    PhotoItem,
    PlaceInfo,
    PlacedItem,
)
from .folder_naming import fix_date_prefix
from .source import Affected, DeleteOutcome, MoveOutcome

def _unique_name(taken: set[str], filename: str) -> str:
    """photo.jpg → photo_1.jpg (or _2, …) not already in ``taken``."""
    if "." in filename:
        base, ext = filename.rsplit(".", 1)
        ext = "." + ext
    else:
        base, ext = filename, ""
    n = 1
    while f"{base}_{n}{ext}" in taken:
        n += 1
    return f"{base}_{n}{ext}"


# (w, h) aspect seeds — mixed portrait/landscape so justified layout is exercised.
_ASPECTS = [(4, 3), (3, 4), (3, 2), (2, 3), (16, 9), (1, 1), (9, 16)]
_DAYS_BACK = 540  # ~18 months of history

# Copies get a "-cN" suffix; parsing falls back to the base item for rendering.
_ID_RE = re.compile(r"^m-(personal|team)-(\d{4}-\d{2}-\d{2})-(\d+)(?:-c\d+)?$")

# 기본 폴더(f-team-1..3 / f-personal-1..3)는 operations 테스트가 "빈 폴더"
# fixture로 강하게 의존하므로 그대로 flat·empty로 둔다. 폴더 뷰어(drill-in +
# leaf thumbnails) 데모/검증용 콘텐츠는 테스트가 참조하지 않는 전용 데모
# 폴더(f-demo-*)로 격리하고, 리프에는 reset()에서 생성 아이템을 배정한다.
_DEFAULT_FOLDERS = [
    PhotoFolder(id="f-team-1", name="가족앨범", space="team"),
    PhotoFolder(id="f-team-2", name="행사", space="team"),
    PhotoFolder(id="f-team-3", name="인화용", space="team"),
    PhotoFolder(id="f-personal-1", name="여행", space="personal"),
    PhotoFolder(id="f-personal-2", name="아이들", space="personal"),
    PhotoFolder(id="f-personal-3", name="스크린샷", space="personal"),
    # 데모 전용(테스트 미참조): 중첩 + 리프 사진.
    PhotoFolder(id="f-demo-1", name="정리 앨범", space="team"),
    PhotoFolder(id="f-demo-1-a", name="2024_설날", space="team",
                parent_id="f-demo-1", depth=1),
    PhotoFolder(id="f-demo-1-b", name="2024_여름휴가", space="team",
                parent_id="f-demo-1", depth=1),
    PhotoFolder(id="f-demo-2", name="행사 모음", space="team"),
    PhotoFolder(id="f-demo-p1", name="제주도 여행", space="personal"),
]

# reset() 시 리프 폴더에 배정할 (folder_id, space) — 각기 다른 최근 날짜의
# 생성 아이템을 담아 폴더 뷰어에 미리보기/썸네일이 보이도록 한다.
_SEED_FOLDERS = [
    ("f-demo-1-a", "team"),
    ("f-demo-1-b", "team"),
    ("f-demo-2", "team"),
    ("f-demo-p1", "personal"),
]

_MEMBERS = ["admin", "dad", "mom", "jimin"]

# AI classification fakes (3단계): items are assigned deterministically by
# index modulo, so groups stay stable across restarts. (name, modulo, remainder)
_PERSONS = [
    ("p-1", "지민", 3, 0),
    ("p-2", "엄마", 4, 1),
    ("p-3", "", 5, 2),  # unnamed face group — UI placeholder case
]
# (id, country, country_id, first_level, second_level, mod, rem) — 실 NAS
# 지오코딩 계층(country→first_level)을 흉내. 같은 first_level(Seoul)에 그룹이
# 여럿인 케이스도 포함(지역 클릭 시 합쳐 보이는 동작 데모).
_PLACES = [
    ("g-1", "South Korea", 1, "Seoul", "", 3, 0),
    ("g-2", "South Korea", 1, "Seoul", "Gangnam-gu", 5, 1),
    ("g-3", "South Korea", 1, "Suwon-si", "", 6, 2),
    ("g-4", "Japan", 2, "Tokyo", "", 7, 3),
    ("g-5", "Australia", 1087, "Sydney", "", 4, 4),
]
# 지도 뷰 데모용 first_level 대표 좌표(lat, lng).
_PLACE_COORDS = {
    "Seoul": (37.5665, 126.9780),
    "Suwon-si": (37.2636, 127.0286),
    "Tokyo": (35.6762, 139.6503),
    "Sydney": (-33.8688, 151.2093),
}
# Scanning every generated day is wasteful for a mock — cap the lookback.
_CLASSIFY_DAYS_BACK = 60


def _rng(seed: str) -> Random:
    return Random(crc32(seed.encode()))


def _day_count(space: str, day: str) -> int:
    """Photos taken on a given day (0 = no bucket). Deterministic per (space, day)."""
    r = _rng(f"{space}:{day}:count")
    x = r.random()
    if x < 0.35:
        return 0
    if x < 0.40:
        # Occasional "event day" — stresses per-bucket layout and virtualization.
        return r.randint(90, 220)
    return r.randint(1, 42)


def _build_item(space: str, day: str, idx: int, r: Random) -> PhotoItem:
    aw, ah = r.choice(_ASPECTS)
    base = r.choice([300, 400, 500])
    hue = r.randint(0, 359)
    hour = 8 + (idx * 7) % 12
    minute = r.randint(0, 59)
    # Sprinkle videos in (~1 in 19) so the ▶ badge/duration UI is exercisable.
    is_video = idx % 19 == 4
    ext = "mp4" if is_video else "jpg"
    return PhotoItem(
        id=f"m-{space}-{day}-{idx}",
        filename=f"IMG_{day.replace('-', '')}_{idx:04d}.{ext}",
        taken_at=f"{day}T{hour:02d}:{minute:02d}:00",
        width=aw * base,
        height=ah * base,
        size=r.randint(800_000, 8_000_000),
        cache_key="mock",
        type="video" if is_video else "photo",
        duration_ms=r.randint(4_000, 185_000) if is_video else None,
        placeholder_color=f"hsl({hue} 45% 78%)",
        folder=None,
    )


def _generate_day(space: str, day: str) -> list[PhotoItem]:
    count = _day_count(space, day)
    r = _rng(f"{space}:{day}:items")
    return [_build_item(space, day, idx, r) for idx in range(count)]


def _parse_id(item_id: str) -> tuple[str, str, int]:
    """(base_space, day, idx) from an id — 404 for anything unparseable."""
    m = _ID_RE.match(item_id)
    if not m:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="사진을 찾을 수 없습니다."
        )
    return m.group(1), m.group(2), int(m.group(3))


def _sim_hashes(space: str, day: str, idx: int) -> tuple[str, int]:
    """Deterministic simulated (sha256, phash) with planted duplicates.

    Resolved recursively so chains stay consistent: an item whose anchor is
    itself a duplicate lands on the same final hash pair.
    """
    if idx > 0 and idx % 23 == 1:
        # Exact duplicate of the previous item (~1 per average day).
        return _sim_hashes(space, day, idx - 1)
    if idx > 0 and idx % 13 == 1:
        # Near duplicate: same photo with 1–4 perceptual bits flipped.
        _, anchor_ph = _sim_hashes(space, day, idx - 1)
        r = _rng(f"{space}:{day}:{idx}:flip")
        ph = anchor_ph
        for _ in range(r.randint(1, 4)):
            ph ^= 1 << r.randrange(64)
        return f"{r.getrandbits(256):064x}", ph
    r = _rng(f"{space}:{day}:{idx}:hash")
    return f"{r.getrandbits(256):064x}", r.getrandbits(64)


_THUMBHASH_CACHE: dict[tuple[int, int, int], str] = {}


def _sim_thumbhash(item: PhotoItem) -> str:
    """Real thumbhash encoded from a small gradient matching the item's
    placeholder hue — validates the encode/decode pipeline without a NAS.
    Cached by (hue, w, h): mock items share a small hue/aspect space, so scans
    stay fast."""
    import base64
    from colorsys import hls_to_rgb

    from PIL import Image

    from .hashing import thumbhash_bytes

    m = re.match(r"hsl\((\d+)", item.placeholder_color or "hsl(200")
    hue = int(m.group(1)) if m else 200
    hue2 = (hue + 40) % 360
    # tiny gradient canvas in the item's aspect ratio
    w = 24 if item.width >= item.height else max(8, round(24 * item.width / item.height))
    h = 24 if item.height > item.width else max(8, round(24 * item.height / item.width))
    cached = _THUMBHASH_CACHE.get((hue, w, h))
    if cached:
        return cached
    img = Image.new("RGB", (w, h))
    c1 = hls_to_rgb(hue / 360, 0.78, 0.45)
    c2 = hls_to_rgb(hue2 / 360, 0.6, 0.55)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / max(1, w - 1) + y / max(1, h - 1)) / 2
            px[x, y] = tuple(round(255 * (a * (1 - t) + b * t)) for a, b in zip(c1, c2))
    result = base64.b64encode(thumbhash_bytes(img)).decode()
    _THUMBHASH_CACHE[(hue, w, h)] = result
    return result


def _svg_thumbnail(item: PhotoItem, size: str) -> bytes:
    long_edge = 320 if size == "sm" else 1280
    if item.width >= item.height:
        w = long_edge
        h = max(1, round(long_edge * item.height / item.width))
    else:
        h = long_edge
        w = max(1, round(long_edge * item.width / item.height))

    m = re.match(r"hsl\((\d+)", item.placeholder_color or "hsl(200")
    hue = int(m.group(1)) if m else 200
    hue2 = (hue + 40) % 360
    label = (
        f'<text x="12" y="{h - 14}" font-family="monospace" font-size="16" '
        f'fill="rgba(255,255,255,0.85)">{item.filename}</text>'
        if size == "xl"
        else ""
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="hsl({hue} 50% 82%)"/>'
        f'<stop offset="1" stop-color="hsl({hue2} 55% 60%)"/>'
        f"</linearGradient></defs>"
        f'<rect width="100%" height="100%" fill="url(#g)"/>'
        f'<circle cx="{w * 0.78:.0f}" cy="{h * 0.24:.0f}" r="{min(w, h) * 0.08:.0f}" '
        f'fill="hsl({hue} 60% 92%)"/>'
        f"{label}</svg>"
    )
    return svg.encode()


class MockPhotoSource:
    """PhotoSource implementation: deterministic reads + in-memory mutations."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Clear all mutation state (used between tests / dev restarts)."""
        self._loc: dict[str, tuple[str, str | None]] = {}
        self._deleted: dict[str, tuple[PhotoItem, str, str | None]] = {}
        self._extras: dict[str, PhotoItem] = {}
        self._custom_folders: list[PhotoFolder] = []
        self._touched: set[tuple[str, str]] = set()
        self._copy_seq = 0
        self._folder_seq = 0
        # 폴더 이동 시뮬레이션: id → 바뀐 이름 (mock 폴더는 flat이라 이름만)
        self._folder_renames: dict[str, str] = {}
        # 충돌 rename 시뮬레이션: 이동된 아이템 id → 바뀐 파일명 (name_1.ext)
        self._filename_override: dict[str, str] = {}
        # 인물 이름 지정/병합 시뮬레이션.
        self._person_names: dict[str, str] = {}  # pid → 지정한 이름
        self._person_merged: dict[str, str] = {}  # source pid → target pid
        # 사용자 앨범 시뮬레이션(개인 공간 전용): aid → {name, item_ids}
        self._albums: dict[str, dict] = {}
        self._album_seq = 0
        self._albums_seeded = False
        self._seed_folder_contents()

    def _person_specs_for(self, pid: str) -> list[tuple[int, int]]:
        """pid 본인 + 이 pid로 병합된 소스들의 (mod, rem) 파티션."""
        specs: list[tuple[int, int]] = []
        own = next((p for p in _PERSONS if p[0] == pid), None)
        if own:
            specs.append((own[2], own[3]))
        for src, tgt in self._person_merged.items():
            if tgt == pid:
                s = next((p for p in _PERSONS if p[0] == src), None)
                if s:
                    specs.append((s[2], s[3]))
        return specs

    def _seed_folder_contents(self) -> None:
        """리프 폴더에 생성 아이템 몇 장씩 배정 — 폴더 뷰어를 MOCK_MODE에서
        검증/데모하기 위함(실 DSM은 실제 파일이 들어 있음). 같은 space에
        머무르므로 타임라인에서 사라지지 않고 폴더 라벨만 얻는다."""
        today = date.today()
        used_days: set[str] = set()
        # 최근 날짜(테스트의 _first_day_items = buckets[0])를 오염시키지 않도록
        # 충분히 과거 날짜부터 스캔해 배정한다.
        for order, (folder_id, space) in enumerate(_SEED_FOLDERS):
            for back in range(300 + order * 7, _DAYS_BACK):
                day = (today - timedelta(days=back)).isoformat()
                if day in used_days:
                    continue
                n = _day_count(space, day)
                if n >= 5:
                    for idx in range(min(n, 8)):
                        self._loc[f"m-{space}-{day}-{idx}"] = (space, folder_id)
                    used_days.add(day)
                    break

    # ------------------------------------------------------------ internals
    def _all_folders(self) -> list[PhotoFolder]:
        out = [*_DEFAULT_FOLDERS, *self._custom_folders]
        if self._folder_renames:
            out = [
                f.model_copy(update={"name": self._folder_renames[f.id]})
                if f.id in self._folder_renames
                else f
                for f in out
            ]
        return out

    def _folder_by_id(self, folder_id: str) -> PhotoFolder:
        # "root:<space>" = 그 공간의 최상위(분할 뷰 루트 대상). 합성 폴더로 취급.
        if folder_id.startswith("root:"):
            space = folder_id.split(":", 1)[1]
            return PhotoFolder(id=folder_id, name="", space=space, parent_id=None)
        for f in self._all_folders():
            if f.id == folder_id:
                return f
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="폴더를 찾을 수 없습니다."
        )

    def _folder_name(self, folder_id: str | None) -> str | None:
        if folder_id is None:
            return None
        try:
            return self._folder_by_id(folder_id).name
        except HTTPException:
            return None

    def _resolve_item(self, item_id: str) -> PhotoItem:
        """The PhotoItem object for an id (copy, trash snapshot, or generated)."""
        if item_id in self._deleted:
            return self._deleted[item_id][0]  # trash snapshot — fixed at delete
        if item_id in self._extras:
            item = self._extras[item_id]
        else:
            space, day, idx = _parse_id(item_id)
            generated = _generate_day(space, day)
            if idx >= len(generated):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="사진을 찾을 수 없습니다.",
                )
            item = generated[idx]
            if item.id != item_id:
                # A copy id ("-cN") resolves to its base pixels but keeps its id.
                item = item.model_copy(update={"id": item_id})
        override = self._filename_override.get(item_id)
        if override:  # 충돌 rename으로 파일명이 바뀐 이동 아이템 (extras 포함)
            item = item.model_copy(update={"filename": override})
        return item

    def _effective_loc(self, item_id: str) -> tuple[str, str | None]:
        loc = self._loc.get(item_id)
        if loc:
            return loc
        space, _, _ = _parse_id(item_id)
        return (space, None)

    def _day_of(self, item_id: str) -> str:
        _, day, _ = _parse_id(item_id)
        return day

    def _touch(self, pairs: Affected) -> None:
        for space, day in pairs:
            self._touched.add((space, day))

    # ------------------------------------------------------------- read side
    async def buckets(self, space: str) -> list[PhotoBucket]:
        today = date.today()
        out: list[PhotoBucket] = []
        for i in range(_DAYS_BACK):
            d = (today - timedelta(days=i)).isoformat()
            if (space, d) in self._touched:
                count = len(await self.items(space, d))
            else:
                count = _day_count(space, d)
            if count:
                out.append(PhotoBucket(day=d, count=count))
        return out

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        result: list[PhotoItem] = []

        # Base items generated for this (space, day), unless deleted/moved away.
        for item in _generate_day(space, day):
            if item.id in self._deleted:
                continue
            loc = self._loc.get(item.id)
            if loc and loc[0] != space:
                continue  # moved to the other space
            folder = self._folder_name(loc[1]) if loc else None
            result.append(item.model_copy(update={"folder": folder}))

        # Items relocated *into* this (space, day): cross-space moves + copies.
        base_ids = {i.id for i in result}
        for item_id, (loc_space, folder_id) in self._loc.items():
            if loc_space != space or item_id in base_ids or item_id in self._deleted:
                continue
            if self._day_of(item_id) != day:
                continue
            item = self._resolve_item(item_id)
            result.append(
                item.model_copy(update={"folder": self._folder_name(folder_id)})
            )

        result.sort(key=lambda i: (i.taken_at, i.id))
        return result

    async def folders(self, parent_id: str | None = None) -> list[PhotoFolder]:
        # parent_id=None → 전체 flat(기존 계약 — manage 폴더 트리/테스트가 이
        # 목록에서 중첩 폴더까지 본다). parent 지정 시 그 폴더의 직속 하위만
        # (폴더 뷰어 drill-in). 최상위만 필요한 뷰어는 parent_id로 자체 필터.
        folders = self._all_folders()
        if parent_id is None:
            return folders
        return [f for f in folders if f.parent_id == parent_id]

    async def folder_items(
        self, folder_id: str, limit: int | None = None
    ) -> list[PhotoItem]:
        self._folder_by_id(folder_id)  # 404 for unknown folders
        out: list[PhotoItem] = []
        for item_id, (_, fid) in self._loc.items():
            if fid != folder_id or item_id in self._deleted:
                continue
            item = self._resolve_item(item_id)
            out.append(item.model_copy(update={"folder": self._folder_name(fid)}))
        out.sort(key=lambda i: (i.taken_at, i.id))
        return out[:limit] if limit is not None else out

    async def item_detail(self, space: str, item_id: str) -> ItemDetail:
        base_space, day, idx = _parse_id(item_id)
        self._resolve_item(item_id)  # 404 for unknown items
        r = _rng(f"{base_space}:{day}:{idx}:exif")
        cameras = [
            ("Samsung Galaxy S23 Ultra", "f/1.7", "1/120", "50", "6.3mm"),
            ("Apple iPhone 15 Pro", "f/1.8", "1/250", "80", "6.9mm"),
            ("SONY ILCE-7M4", "f/2.8", "1/500", "200", "35mm"),
        ]
        cam, ap, exp, iso, focal = r.choice(cameras)
        _, folder_id = self._effective_loc(item_id)
        return ItemDetail(
            id=item_id,
            folder=self._folder_name(folder_id),
            exif={
                "camera": cam,
                "aperture": ap,
                "exposure_time": exp,
                "iso": iso,
                "focal_length": focal,
            },
            address=r.choice(["대한민국 서울 강남구", "대한민국 제주 서귀포시", ""]) or None,
        )

    async def item_folders(
        self, space: str, item_ids: list[str]
    ) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for item_id in item_ids:
            try:
                _, folder_id = self._effective_loc(item_id)
                out[item_id] = self._folder_name(folder_id)
            except HTTPException:
                out[item_id] = None
        return out

    async def search_items(self, space: str, keyword: str) -> list[PhotoItem]:
        # Filename/folder-name substring match over the recent pool — enough
        # to exercise the search UI without a NAS.
        kw = keyword.strip().lower()
        if not kw:
            return []
        out: list[PhotoItem] = []
        for it in self._classify_pool(space):
            _, folder_id = self._effective_loc(it.id)
            folder = self._folder_name(folder_id) or ""
            if kw in it.filename.lower() or kw in folder.lower():
                out.append(it.model_copy(update={"folder": folder or None}))
        return out

    # ------------------------------------------- AI classification (3단계)
    def _classify_pool(self, space: str) -> list[PhotoItem]:
        """Recent items of a space (base ids, trash excluded) to group over."""
        out: list[PhotoItem] = []
        today = date.today()
        for back in range(_CLASSIFY_DAYS_BACK):
            day = (today - timedelta(days=back)).isoformat()
            out.extend(
                it
                for it in _generate_day(space, day)
                if it.id not in self._deleted
            )
        return out

    @staticmethod
    def _in_group(item_id: str, mod: int, rem: int) -> bool:
        _, _, idx = _parse_id(item_id)
        return idx % mod == rem

    def _person_members(self, space: str, pid: str) -> list[PhotoItem]:
        """pid(본인 + 병합된 소스)의 멤버 사진 (id 중복 제거)."""
        pool = self._classify_pool(space)
        byid: dict[str, PhotoItem] = {}
        for mod, rem in self._person_specs_for(pid):
            for it in pool:
                if self._in_group(it.id, mod, rem):
                    byid[it.id] = it
        return list(byid.values())

    async def persons(self, space: str) -> list[PersonInfo]:
        out: list[PersonInfo] = []
        for pid, name, _mod, _rem in _PERSONS:
            if pid in self._person_merged:  # 다른 인물로 병합돼 사라짐
                continue
            members = self._person_members(space, pid)
            if not members:
                continue
            out.append(
                PersonInfo(
                    id=pid,
                    space=space,
                    name=self._person_names.get(pid, name),
                    item_count=len(members),
                    cover_item_id=members[0].id,
                    cover_cache_key="mock",
                )
            )
        out.sort(key=lambda p: -(p.item_count or 0))
        return out

    async def person_items(self, space: str, person_id: str) -> list[PhotoItem]:
        if next((p for p in _PERSONS if p[0] == person_id), None) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="인물을 찾을 수 없습니다."
            )
        return self._person_members(space, person_id)

    async def name_person(self, space: str, person_id: str, name: str) -> dict:
        if next((p for p in _PERSONS if p[0] == person_id), None) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="인물을 찾을 수 없습니다."
            )
        name = name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="이름이 비어 있습니다."
            )
        # 같은 이름의 기존(병합 안 된) 인물이 있으면 그리로 병합.
        target = next(
            (
                p
                for p in await self.persons(space)
                if p.name.strip() == name and p.id != person_id
            ),
            None,
        )
        if target is not None:
            self._person_merged[person_id] = target.id
            self._person_names.pop(person_id, None)
            return {"name": name, "merged_into": target.id}
        self._person_names[person_id] = name
        return {"name": name, "merged_into": None}

    async def merge_duplicate_persons(self, space: str) -> dict:
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
            for src in group[1:]:
                self._person_merged[src.id] = keeper.id
                merged += 1
        return {"merged": merged}

    async def places(self, space: str) -> list[PlaceInfo]:
        pool = self._classify_pool(space)
        out = [
            PlaceInfo(
                id=gid,
                space=space,
                name=second or first,
                item_count=sum(1 for it in pool if self._in_group(it.id, mod, rem)),
                country=country,
                country_id=country_id,
                first_level=first,
                second_level=second or None,
            )
            for gid, country, country_id, first, second, mod, rem in _PLACES
        ]
        out.sort(key=lambda g: -(g.item_count or 0))
        return [g for g in out if g.item_count]

    async def place_items(
        self, space: str, place_id: str, limit: int | None = None
    ) -> list[PhotoItem]:
        spec = next((g for g in _PLACES if g[0] == place_id), None)
        if spec is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="장소를 찾을 수 없습니다."
            )
        mod, rem = spec[5], spec[6]
        first_level = spec[3]
        base = _PLACE_COORDS.get(first_level)
        out: list[PhotoItem] = []
        for it in self._classify_pool(space):
            if not self._in_group(it.id, mod, rem):
                continue
            if base is not None:  # 대표 좌표 + 사진별 소폭 지터
                r = _rng(f"{it.id}:gps")
                it = it.model_copy(
                    update={
                        "lat": base[0] + (r.random() - 0.5) * 0.05,
                        "lng": base[1] + (r.random() - 0.5) * 0.05,
                    }
                )
            out.append(it)
        return out[:limit] if limit is not None else out

    async def videos(self, space: str) -> list[PhotoItem]:
        out = [
            it
            for it in self._classify_pool(space)
            if it.type == "video" and it.id not in self._deleted
        ]
        out.sort(key=lambda i: i.taken_at, reverse=True)
        return out

    # ---- User albums (개인 공간 전용) ----

    def _album_info(self, aid: str) -> AlbumInfo:
        rec = self._albums[aid]
        items = self._album_resolved(rec["item_ids"])
        return AlbumInfo(
            id=aid,
            name=rec["name"],
            item_count=len(items),
            cover_item_id=items[0].id if items else None,
            cover_cache_key="mock" if items else None,
        )

    def _album_resolved(self, item_ids: list[str]) -> list[PhotoItem]:
        out: list[PhotoItem] = []
        for iid in item_ids:
            if iid in self._deleted:
                continue
            try:
                out.append(self._resolve_item(iid))
            except Exception:
                continue  # id가 더는 유효하지 않으면 건너뜀
        return out

    def _seed_albums(self) -> None:
        # 데모용 앨범 하나 — 목록·열람 뷰를 MOCK에서 확인하기 위함.
        if self._albums_seeded:
            return
        self._albums_seeded = True
        pool = [it.id for it in self._classify_pool("personal")[:8]]
        if pool:
            self._album_seq += 1
            aid = f"al-{self._album_seq}"
            self._albums[aid] = {"name": "가족 여행", "item_ids": pool}

    async def albums(self, space: str) -> list[AlbumInfo]:
        if space == "team":
            return []
        self._seed_albums()
        out = [self._album_info(aid) for aid in self._albums]
        # 최근 생성순(뒤에 만든 것이 위로).
        out.reverse()
        return out

    async def album_items(self, space: str, album_id: str) -> list[PhotoItem]:
        if album_id not in self._albums:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="앨범을 찾을 수 없습니다.",
            )
        return self._album_resolved(self._albums[album_id]["item_ids"])

    async def create_album(
        self, space: str, name: str, item_ids: list[str]
    ) -> AlbumInfo:
        self._seed_albums()
        self._album_seq += 1
        aid = f"al-{self._album_seq}"
        self._albums[aid] = {"name": name.strip(), "item_ids": list(item_ids)}
        return self._album_info(aid)

    async def add_to_album(
        self, space: str, album_id: str, item_ids: list[str]
    ) -> int:
        if album_id not in self._albums:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="앨범을 찾을 수 없습니다.",
            )
        existing = self._albums[album_id]["item_ids"]
        seen = set(existing)
        added = [i for i in item_ids if i not in seen]
        existing.extend(added)
        return len(added)

    async def delete_album(self, space: str, album_id: str) -> None:
        self._albums.pop(album_id, None)

    # ---- 폴더 이름 정리 ----

    async def audit_folder_names(self, root_id: str | None) -> list[FolderRename]:
        out: list[FolderRename] = []
        for f in self._all_folders():
            base = f.name.split("/")[-1]
            fixed = fix_date_prefix(base)
            if fixed:
                out.append(
                    FolderRename(id=f.id, current_name=base, proposed_name=fixed)
                )
        return out

    async def rename_folder(
        self, space: str, folder_id: str, new_name: str
    ) -> tuple[str, str]:
        f = self._folder_by_id(folder_id)
        parent = f.name.rsplit("/", 1)[0] if "/" in f.name else ""
        self._folder_renames[folder_id] = (
            f"{parent}/{new_name}" if parent else new_name
        )
        return folder_id, new_name

    def _folder_extra_count(self, src_folder_id: str, dest_folder_name: str) -> int:
        """소스 폴더가 대상 동명 폴더에 없는(파일명 기준) 사진 수. mock은 flat
        구조라 직속 사진만 비교한다. 0이면 완전 포함(완전 일치)."""
        dest_f = next(
            (f for f in self._all_folders() if f.name == dest_folder_name), None
        )
        dest_files = self._folder_filenames(dest_f.id) if dest_f else set()
        extra = 0
        for item_id, (_, fid) in self._loc.items():
            if fid != src_folder_id or item_id in self._deleted:
                continue
            if self._resolve_item(item_id).filename not in dest_files:
                extra += 1
        return extra

    async def folder_conflicts(
        self, space: str, folder_ids: list[str], dest_folder_id: str
    ) -> list[tuple[str, str, int]]:
        dest = self._folder_by_id(dest_folder_id)
        existing = {f.name for f in self._all_folders()}
        out: list[tuple[str, str, int]] = []
        for fid in folder_ids:
            if fid == dest_folder_id:
                continue
            base = self._folder_by_id(fid).name.split("/")[-1]
            target = f"{dest.name}/{base}"
            if target in existing:
                out.append((fid, base, self._folder_extra_count(fid, target)))
        return out

    async def move_folders(
        self,
        space: str,
        folder_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress=None,
        conflict_strategy: str = "skip",
    ) -> dict:
        dest = self._folder_by_id(dest_folder_id)
        taken = {f.name for f in self._all_folders()}
        names: list[str] = []
        undo: list[dict] = []
        # 루트 대상은 접두어 없이 최상위 이름. (dest.name == "" → "base")
        join = lambda base: base if not dest.name else f"{dest.name}/{base}"
        for fid in folder_ids:
            if fid == dest_folder_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="폴더를 자기 자신 안으로 옮길 수 없습니다.",
                )
            f = self._folder_by_id(fid)
            base = f.name.split("/")[-1]
            # 이미 대상 바로 아래(루트면 최상위)면 이동은 no-op — 자기 자신과의
            # 이름 충돌을 피한다(DSM move_folders의 동일 가드와 대응).
            parent = f.name.rsplit("/", 1)[0] if "/" in f.name else ""
            if parent == dest.name and not copy:
                names.append(base)
                continue
            target = join(base)
            if target in taken:
                if conflict_strategy == "merge":
                    self._merge_mock(f, target, copy, undo)
                    names.append(base)
                    continue
                if conflict_strategy != "rename":
                    continue  # skip
                n = 1
                while join(f"{base}_{n}") in taken:
                    n += 1
                base = f"{base}_{n}"
                target = join(base)
            taken.add(target)
            names.append(base)
            if copy:
                self._folder_seq += 1
                nf = PhotoFolder(
                    id=f"f-{dest.space}-c{self._folder_seq}",
                    name=target,
                    space=dest.space,
                )
                self._custom_folders.append(nf)
                undo.append({"kind": "copy", "id": nf.id})
            else:
                undo.append({"kind": "move", "id": fid, "prev": f.name})
                self._folder_renames[fid] = target
        return {"names": names, "undo": undo}

    def _merge_mock(
        self, src_folder: PhotoFolder, target_name: str, copy: bool, undo: list[dict]
    ) -> None:
        """Fold src_folder's photos into the same-named destination folder;
        clashing filenames are skipped (기존 유지). Mock folders are flat so only
        the folder's direct photos merge (subtree recursion is a DSM concern)."""
        dest_f = next(f for f in self._all_folders() if f.name == target_name)
        dest_files = self._folder_filenames(dest_f.id)
        moved: list[dict] = []
        for item_id, (_, fid) in list(self._loc.items()):
            if fid != src_folder.id or item_id in self._deleted:
                continue
            if self._resolve_item(item_id).filename in dest_files:
                continue  # 파일 충돌 → 기존 유지
            if copy:
                self._copy_seq += 1
                cid = f"{item_id}-c{self._copy_seq}"
                self._extras[cid] = self._resolve_item(item_id).model_copy(
                    update={"id": cid}
                )
                self._loc[cid] = (dest_f.space, dest_f.id)
                moved.append({"kind": "copy", "id": cid})
            else:
                prev = self._loc[item_id]
                self._loc[item_id] = (dest_f.space, dest_f.id)
                moved.append({"kind": "move", "id": item_id, "prev": list(prev)})
        # 이동 모드에서 소스가 custom 폴더이고 완전히 비면 제거 (DSM 병합 완료 대응).
        if not copy and not any(
            f == src_folder.id and iid not in self._deleted
            for iid, (_, f) in self._loc.items()
        ):
            self._custom_folders = [
                f for f in self._custom_folders if f.id != src_folder.id
            ]
        undo.append({"kind": "merge", "moved": moved})

    async def revert_move_folders(self, undo_payload: list, copy: bool) -> None:
        for e in undo_payload:
            kind = e.get("kind")
            if kind == "copy":
                self._custom_folders = [
                    f for f in self._custom_folders if f.id != e["id"]
                ]
            elif kind == "merge":
                for mv in e["moved"]:
                    if mv["kind"] == "copy":
                        self._extras.pop(mv["id"], None)
                        self._loc.pop(mv["id"], None)
                    else:
                        self._loc[mv["id"]] = tuple(mv["prev"])
            else:  # 폴더 통째 이동 rename 복원
                self._folder_renames[e["id"]] = e["prev"]

    async def purge_trash(self) -> None:
        # Trashed snapshots are gone for good; the op-log status flip (purged)
        # blocks undo before it would ever reach restore().
        self._deleted.clear()

    async def folder_count(self, folder_id: str) -> int:
        self._folder_by_id(folder_id)  # 404 for unknown folders
        return sum(
            1
            for item_id, (_, fid) in self._loc.items()
            if fid == folder_id and item_id not in self._deleted
        )

    async def capture_items(self, space: str, folder_id: str) -> list[PhotoItem]:
        return await self.folder_items(folder_id)

    async def capture_subtree(
        self, space: str, root_id: str
    ) -> list[tuple[str, str]]:
        f = self._folder_by_id(root_id)
        return [(root_id, f.name)]

    async def set_item_time(self, space: str, item_id: str, epoch: int) -> None:
        # Dev mock: no persistent taken-time store — accept and no-op.
        return None

    async def members(self) -> list[MemberInfo]:
        # 마지막 한 명은 "사진 없음" 케이스 데모용.
        return [
            MemberInfo(name=m, has_photos=(m != "jimin")) for m in _MEMBERS
        ]

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        return _svg_thumbnail(self._resolve_item(item_id), size), "image/svg+xml"

    async def video_stream(self, space: str, item_id: str, range_header):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MOCK 모드에서는 동영상 재생을 지원하지 않습니다.",
        )

    async def item_hashes(self, space: str, item: PhotoItem) -> tuple[str, str, str]:
        """Simulated hashes with planted duplicate clusters (deterministic).

        Roles by base index within a day: idx%23==1 → exact duplicate of the
        previous item (same sha+phash); idx%13==1 → near duplicate (1–4 phash
        bits flipped). Copies ("-cN" ids) inherit the base item's hashes —
        copying a photo then scanning finds it as an exact duplicate, which is
        exactly the workflow the dedup UI demonstrates.

        The thumbhash is REAL (encoded from a gradient matching the item's
        placeholder hue) so the blur pipeline is exercisable end-to-end
        without a NAS.
        """
        base_space, day, idx = _parse_id(item.id)
        sha, ph = _sim_hashes(base_space, day, idx)
        return sha, f"{ph:016x}", _sim_thumbhash(item)

    # ------------------------------------------------------------ write side
    @staticmethod
    async def _tick(on_progress, done: int, total: int) -> None:
        """Simulate bulk latency for the progress bar (every 10th item) — real
        NAS bulk ops take seconds (CopyMove task per chunk), mock mimics that
        so the B-6 progress bar is exercisable without a NAS."""
        if on_progress and (done % 10 == 0 or done == total):
            on_progress(done, total)
            await asyncio.sleep(0.1)

    def _folder_filenames(self, folder_id: str | None) -> set[str]:
        return {
            self._resolve_item(iid).filename
            for iid, (_, fid) in self._loc.items()
            if fid == folder_id and iid not in self._deleted
        }

    async def conflicts(
        self, space: str, item_ids: list[str], dest_folder_id: str
    ) -> list[tuple[str, str]]:
        dest = self._folder_by_id(dest_folder_id)
        existing = self._folder_filenames(dest.id)
        out: list[tuple[str, str]] = []
        for iid in item_ids:
            if iid in self._deleted:
                continue
            fn = self._resolve_item(iid).filename
            if fn in existing:
                out.append((iid, fn))
        return out

    async def move(
        self,
        space: str,
        item_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress=None,
        conflict_strategy: str = "skip",
    ) -> MoveOutcome:
        # space is ignored: the mock encodes the space in each item id.
        dest = self._folder_by_id(dest_folder_id)
        dest_name = "최상위" if dest_folder_id.startswith("root:") else dest.name
        outcome = MoveOutcome(dest_space=dest.space, dest_name=dest_name)
        affected: set[tuple[str, str]] = set()
        existing = self._folder_filenames(dest.id)
        taken = set(existing)

        for done, item_id in enumerate(item_ids, start=1):
            await self._tick(on_progress, done, len(item_ids))
            if item_id in self._deleted:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="휴지통에 있는 사진은 이동/복사할 수 없습니다.",
                )
            item = self._resolve_item(item_id)
            day = self._day_of(item_id)
            filename = item.filename
            clash = filename in existing
            dest_fn = filename

            if clash and conflict_strategy == "skip":
                continue
            if clash and conflict_strategy == "overwrite":
                # 기존 동명 파일 제거 (덮어쓰기 — 원본 소실, 비가역).
                for other, (_, fid) in list(self._loc.items()):
                    if (
                        fid == dest.id
                        and other not in self._deleted
                        and self._resolve_item(other).filename == filename
                    ):
                        self._loc.pop(other, None)
                        self._filename_override.pop(other, None)
                        affected.add((dest.space, self._day_of(other)))
            elif clash and conflict_strategy == "rename":
                dest_fn = _unique_name(taken, filename)
                taken.add(dest_fn)

            if copy:
                self._copy_seq += 1
                copy_id = f"{item_id}-c{self._copy_seq}"
                self._extras[copy_id] = item.model_copy(
                    update={"id": copy_id, "filename": dest_fn}
                )
                self._loc[copy_id] = (dest.space, dest.id)
                outcome.created_ids.append(copy_id)
                affected.add((dest.space, day))
            else:
                prev_space, prev_folder = self._effective_loc(item_id)
                outcome.moved.append(
                    PlacedItem(id=item_id, space=prev_space, folder_id=prev_folder, day=day)
                )
                self._loc[item_id] = (dest.space, dest.id)
                if dest_fn != filename:
                    self._filename_override[item_id] = dest_fn
                affected.add((prev_space, day))
                affected.add((dest.space, day))

        if not copy and outcome.moved:
            outcome.emptied = self._detect_emptied(outcome.moved)
        outcome.affected = sorted(affected)
        self._touch(outcome.affected)
        return outcome

    def _detect_emptied(
        self, moved: list[PlacedItem]
    ) -> list[tuple[str, str, str]]:
        """Source folders (folder_id set) left with no live photos after a move."""
        out: list[tuple[str, str, str]] = []
        for fid in {p.folder_id for p in moved if p.folder_id}:
            remaining = any(
                f == fid and iid not in self._deleted
                for iid, (_, f) in self._loc.items()
            )
            if remaining:
                continue
            try:
                folder = self._folder_by_id(fid)
            except HTTPException:
                continue
            out.append((fid, folder.name.split("/")[-1], folder.space))
        return out

    async def delete(
        self, space: str, item_ids: list[str], on_progress=None
    ) -> DeleteOutcome:
        outcome = DeleteOutcome()
        affected: set[tuple[str, str]] = set()
        for done, item_id in enumerate(item_ids, start=1):
            await self._tick(on_progress, done, len(item_ids))
            if item_id in self._deleted:
                continue  # already trashed — idempotent
            item = self._resolve_item(item_id)
            space, folder_id = self._effective_loc(item_id)
            day = self._day_of(item_id)
            self._deleted[item_id] = (item, space, folder_id)
            self._loc.pop(item_id, None)
            outcome.deleted.append(
                PlacedItem(id=item_id, space=space, folder_id=folder_id, day=day)
            )
            affected.add((space, day))
        outcome.affected = sorted(affected)
        self._touch(outcome.affected)
        return outcome

    # ------------------------------------------------------ undo primitives
    async def place(
        self, placements: list[PlacedItem], on_progress=None
    ) -> Affected:
        affected: set[tuple[str, str]] = set()
        for done, p in enumerate(placements, start=1):
            await self._tick(on_progress, done, len(placements))
            current_space, _ = self._effective_loc(p.id)
            base_space, _, _ = _parse_id(p.id)
            if p.space == base_space and p.folder_id is None and p.id not in self._extras:
                self._loc.pop(p.id, None)  # back to pristine base location
            else:
                self._loc[p.id] = (p.space, p.folder_id)
            affected.add((current_space, p.day))
            affected.add((p.space, p.day))
        result = sorted(affected)
        self._touch(result)
        return result

    async def restore(
        self, placements: list[PlacedItem], on_progress=None
    ) -> Affected:
        affected: set[tuple[str, str]] = set()
        for done, p in enumerate(placements, start=1):
            await self._tick(on_progress, done, len(placements))
            snapshot = self._deleted.pop(p.id, None)
            if snapshot is None:
                # Server restarted since the delete — mock trash is in-memory.
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="휴지통 데이터가 없어 복원할 수 없습니다 (mock은 서버 재시작 시 초기화).",
                )
            item, _, _ = snapshot
            if p.id.count("-c") or p.id in self._extras:
                self._extras[p.id] = item
            base_space, _, _ = _parse_id(p.id)
            if p.space == base_space and p.folder_id is None and p.id not in self._extras:
                self._loc.pop(p.id, None)
            else:
                self._loc[p.id] = (p.space, p.folder_id)
            affected.add((p.space, p.day))
        result = sorted(affected)
        self._touch(result)
        return result

    async def remove_items(self, item_ids: list[str]) -> Affected:
        affected: set[tuple[str, str]] = set()
        for item_id in item_ids:
            space, _ = self._effective_loc(item_id)
            affected.add((space, self._day_of(item_id)))
            self._extras.pop(item_id, None)
            self._loc.pop(item_id, None)
            self._deleted.pop(item_id, None)
        result = sorted(affected)
        self._touch(result)
        return result

    async def create_folder(
        self, space: str, name: str, parent_id: str | None = None
    ) -> PhotoFolder:
        # Mock folders are flat — a sub-folder shows the parent in its name.
        if parent_id is not None:
            parent = self._folder_by_id(parent_id)
            name = f"{parent.name}/{name}"
        if any(f.space == space and f.name == name for f in self._all_folders()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="같은 이름의 폴더가 이미 있습니다.",
            )
        self._folder_seq += 1
        folder = PhotoFolder(
            id=f"f-{space}-c{self._folder_seq}",
            name=name,
            space=space,
            parent_id=parent_id,
        )
        self._custom_folders.append(folder)
        return folder

    async def remove_folder(self, folder_id: str) -> bool:
        if any(fid == folder_id for _, fid in self._loc.values()):
            return False  # not empty
        for i, f in enumerate(self._custom_folders):
            if f.id == folder_id:
                del self._custom_folders[i]
                return True
        return False  # default folders are not removable

    async def trash_folder(self, space: str, folder_id: str) -> dict:
        # 재귀 삭제: 폴더 직속 사진을 휴지통으로 + 폴더 제거(custom). mock은 flat
        # 구조라 하위 폴더 재귀는 없다(DSM 관심사). undo는 사진 복원 + 폴더 재생성.
        folder = self._folder_by_id(folder_id)
        trashed: list[dict] = []
        for item_id, (_, fid) in list(self._loc.items()):
            if fid != folder_id or item_id in self._deleted:
                continue
            item = self._resolve_item(item_id)
            sp, f = self._effective_loc(item_id)
            self._deleted[item_id] = (item, sp, f)
            self._loc.pop(item_id, None)
            self._touch([(sp, self._day_of(item_id))])
            trashed.append({"id": item_id})
        removed = None
        for i, f in enumerate(self._custom_folders):
            if f.id == folder_id:
                removed = f
                del self._custom_folders[i]
                break
        return {
            "name": folder.name.split("/")[-1],
            "undo": {
                "items": trashed,
                "folder": removed.model_dump() if removed else None,
            },
        }

    async def restore_folder(self, undo_payload: dict) -> None:
        folder = undo_payload.get("folder")
        if folder and not any(f.id == folder["id"] for f in self._custom_folders):
            self._custom_folders.append(PhotoFolder(**folder))
        for entry in undo_payload.get("items", []):
            item_id = entry["id"]
            snapshot = self._deleted.pop(item_id, None)
            if snapshot is None:
                continue
            _, sp, fid = snapshot
            self._loc[item_id] = (sp, fid)
            self._touch([(sp, self._day_of(item_id))])


mock_source = MockPhotoSource()


# --------------------------------------------------- 1차 구역(zone) mock
# 홈(base=/homes/<account>) 기준 상대경로 트리 — browse(등록 UI)와 zone 소스가
# 공유하는 결정적 가짜 구조. leaf 폴더에만 사진이 있다(1차 = 기기 백업 더미).
_ZONE_DIRS: dict[str, list[str]] = {
    "": ["MobileBackup", "Drive"],
    "MobileBackup": ["2024-01", "2024-02", "2024-03"],
    "Drive": ["스캔"],
}
_ZONE_LEAVES = frozenset(
    {"MobileBackup/2024-01", "MobileBackup/2024-02", "MobileBackup/2024-03", "Drive/스캔"}
)


def _zone_rel(path: str) -> str:
    """/homes/<account>/A/B -> 'A/B' (홈 base 아래 상대경로)."""
    parts = path.strip("/").split("/")  # [homes, account, A, B]
    return "/".join(parts[2:]) if len(parts) > 2 else ""


def mock_zone_subdirs(path: str) -> list[tuple[str, str]]:
    """(이름, 절대경로) 하위 폴더 — browse + zone folders 공용."""
    rel = _zone_rel(path)
    base = path.rstrip("/")
    return [(name, f"{base}/{name}") for name in _ZONE_DIRS.get(rel, [])]


def _zone_leaf_files(path: str) -> list[str]:
    """leaf 폴더의 가짜 사진 절대경로 목록(결정적)."""
    rel = _zone_rel(path)
    if rel not in _ZONE_LEAVES:
        return []
    base = path.rstrip("/")
    n = 3 + (crc32(rel.encode()) % 4)
    tag = rel.replace("/", "_")
    return [f"{base}/IMG_{tag}_{i:03d}.jpg" for i in range(n)]


def _zone_item(path: str) -> PhotoItem:
    r = Random(crc32(path.encode()))
    return PhotoItem(
        id=path,
        filename=posixpath.basename(path),
        taken_at="2024-01-01T00:00:00",
        width=400,
        height=300,
        size=r.randint(800_000, 6_000_000),
        cache_key="zone",
        type="photo",
        placeholder_color=f"hsl({r.randint(0, 359)} 45% 78%)",
        folder=posixpath.dirname(path),
    )


class MockZonePhotoSource(MockPhotoSource):
    """1차 구역 mock: 등록된 root 아래 결정적 폴더 트리를 FileStation처럼 노출하고,
    2차(개인)로의 이동을 시뮬레이션한다. 완전 왕복(개인 폴더 재등장)까진 안 하고
    'zone에서 사라짐 + 되돌리기 복원'까지 재현(UI 계약 검증에 충분)."""

    def __init__(self, root_path: str) -> None:
        super().__init__()
        self._root = root_path
        self._zone_moved: set[str] = set()

    async def folders(self, parent_id: str | None = None) -> list[PhotoFolder]:
        base = parent_id or self._root
        out: list[PhotoFolder] = []
        for _name, abs_path in mock_zone_subdirs(base):
            rel = abs_path.removeprefix(self._root) or "/"
            out.append(
                PhotoFolder(
                    id=abs_path,
                    name=rel,
                    space="personal",
                    parent_id=None if base == self._root else base,
                    depth=max(0, rel.strip("/").count("/")),
                )
            )
        return out

    async def folder_items(
        self, folder_id: str, limit: int | None = None
    ) -> list[PhotoItem]:
        out = [
            _zone_item(p)
            for p in _zone_leaf_files(folder_id)
            if p not in self._zone_moved
        ]
        return out[:limit] if limit is not None else out

    async def folder_count(self, folder_id: str) -> int:
        return len(await self.folder_items(folder_id))

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        item = _zone_item(item_id) if item_id.startswith("/") else self._resolve_item(item_id)
        return _svg_thumbnail(item, size), "image/svg+xml"

    async def item_detail(self, space: str, item_id: str) -> ItemDetail:
        return ItemDetail(id=item_id, folder=posixpath.dirname(item_id), exif={}, address=None)

    async def move(
        self,
        space: str,
        item_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress=None,
        conflict_strategy: str = "skip",
    ) -> MoveOutcome:
        # zone→2차: 대상(개인 Photos 폴더)에 실제로 심지 않고, 이동한 zone 사진을
        # 숨겨(사라짐) undo로 되돌린다. moved에 원본 경로를 기록해 undo가 복원.
        outcome = MoveOutcome(dest_space="personal", dest_name="내 사진(2차)")
        for iid in item_ids:
            outcome.moved.append(
                PlacedItem(
                    id=iid, space="personal",
                    folder_id=posixpath.dirname(iid), day="",
                )
            )
            if not copy:
                self._zone_moved.add(iid)
        return outcome

    async def place(self, placements, on_progress=None) -> Affected:
        for p in placements:
            self._zone_moved.discard(p.id)
        return []

    async def conflicts(self, space, item_ids, dest_folder_id):
        return []  # zone→2차는 새 이벤트 폴더라 파일명 충돌을 가정하지 않음


_mock_zones: dict[str, MockZonePhotoSource] = {}


def get_mock_zone(root_path: str) -> MockZonePhotoSource:
    """Process-local zone source per root (이동 상태 유지)."""
    if root_path not in _mock_zones:
        _mock_zones[root_path] = MockZonePhotoSource(root_path)
    return _mock_zones[root_path]


def reset_mock_zones() -> None:
    _mock_zones.clear()
