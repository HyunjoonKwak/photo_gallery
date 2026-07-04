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
import re
from datetime import date, timedelta
from random import Random
from zlib import crc32

from fastapi import HTTPException, status

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
from .source import Affected, DeleteOutcome, MoveOutcome

# (w, h) aspect seeds — mixed portrait/landscape so justified layout is exercised.
_ASPECTS = [(4, 3), (3, 4), (3, 2), (2, 3), (16, 9), (1, 1), (9, 16)]
_DAYS_BACK = 540  # ~18 months of history

# Copies get a "-cN" suffix; parsing falls back to the base item for rendering.
_ID_RE = re.compile(r"^m-(personal|team)-(\d{4}-\d{2}-\d{2})-(\d+)(?:-c\d+)?$")

_DEFAULT_FOLDERS = [
    PhotoFolder(id="f-team-1", name="가족앨범", space="team"),
    PhotoFolder(id="f-team-2", name="행사", space="team"),
    PhotoFolder(id="f-team-3", name="인화용", space="team"),
    PhotoFolder(id="f-personal-1", name="여행", space="personal"),
    PhotoFolder(id="f-personal-2", name="아이들", space="personal"),
    PhotoFolder(id="f-personal-3", name="스크린샷", space="personal"),
]

_MEMBERS = ["admin", "dad", "mom", "jimin"]

# AI classification fakes (3단계): items are assigned deterministically by
# index modulo, so groups stay stable across restarts. (name, modulo, remainder)
_PERSONS = [
    ("p-1", "지민", 3, 0),
    ("p-2", "엄마", 4, 1),
    ("p-3", "", 5, 2),  # unnamed face group — UI placeholder case
]
_PLACES = [
    ("g-1", "대한민국 서울", 4, 0),
    ("g-2", "대한민국 제주", 6, 1),
]
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
        if item_id in self._extras:
            return self._extras[item_id]
        if item_id in self._deleted:
            return self._deleted[item_id][0]
        space, day, idx = _parse_id(item_id)
        generated = _generate_day(space, day)
        if idx >= len(generated):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="사진을 찾을 수 없습니다."
            )
        base = generated[idx]
        if base.id != item_id:
            # A copy id ("-cN") resolves to its base pixels but keeps its own id.
            base = base.model_copy(update={"id": item_id})
        return base

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
        # Mock folders are a flat top-level set; children requests return empty.
        return [] if parent_id else self._all_folders()

    async def folder_items(self, folder_id: str) -> list[PhotoItem]:
        self._folder_by_id(folder_id)  # 404 for unknown folders
        out: list[PhotoItem] = []
        for item_id, (_, fid) in self._loc.items():
            if fid != folder_id or item_id in self._deleted:
                continue
            item = self._resolve_item(item_id)
            out.append(item.model_copy(update={"folder": self._folder_name(fid)}))
        out.sort(key=lambda i: (i.taken_at, i.id))
        return out

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

    async def persons(self, space: str) -> list[PersonInfo]:
        pool = self._classify_pool(space)
        out: list[PersonInfo] = []
        for pid, name, mod, rem in _PERSONS:
            members = [it for it in pool if self._in_group(it.id, mod, rem)]
            if not members:
                continue
            out.append(
                PersonInfo(
                    id=pid,
                    space=space,
                    name=name,
                    item_count=len(members),
                    cover_item_id=members[0].id,
                    cover_cache_key="mock",
                )
            )
        out.sort(key=lambda p: -(p.item_count or 0))
        return out

    async def person_items(self, space: str, person_id: str) -> list[PhotoItem]:
        spec = next((p for p in _PERSONS if p[0] == person_id), None)
        if spec is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="인물을 찾을 수 없습니다."
            )
        _, _, mod, rem = spec
        return [
            it for it in self._classify_pool(space) if self._in_group(it.id, mod, rem)
        ]

    async def places(self, space: str) -> list[PlaceInfo]:
        pool = self._classify_pool(space)
        out = [
            PlaceInfo(
                id=gid,
                space=space,
                name=name,
                item_count=sum(1 for it in pool if self._in_group(it.id, mod, rem)),
            )
            for gid, name, mod, rem in _PLACES
        ]
        out.sort(key=lambda g: -(g.item_count or 0))
        return [g for g in out if g.item_count]

    async def place_items(self, space: str, place_id: str) -> list[PhotoItem]:
        spec = next((g for g in _PLACES if g[0] == place_id), None)
        if spec is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="장소를 찾을 수 없습니다."
            )
        _, _, mod, rem = spec
        return [
            it for it in self._classify_pool(space) if self._in_group(it.id, mod, rem)
        ]

    async def move_folders(
        self,
        space: str,
        folder_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress=None,
    ) -> dict:
        dest = self._folder_by_id(dest_folder_id)
        names: list[str] = []
        undo: list[dict] = []
        for fid in folder_ids:
            if fid == dest_folder_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="폴더를 자기 자신 안으로 옮길 수 없습니다.",
                )
            f = self._folder_by_id(fid)
            base = f.name.split("/")[-1]
            names.append(base)
            if copy:
                self._folder_seq += 1
                nf = PhotoFolder(
                    id=f"f-{dest.space}-c{self._folder_seq}",
                    name=f"{dest.name}/{base}",
                    space=dest.space,
                )
                self._custom_folders.append(nf)
                undo.append({"kind": "copy", "id": nf.id})
            else:
                undo.append({"kind": "move", "id": fid, "prev": f.name})
                self._folder_renames[fid] = f"{dest.name}/{base}"
        return {"names": names, "undo": undo}

    async def revert_move_folders(self, undo_payload: list, copy: bool) -> None:
        for e in undo_payload:
            if e.get("kind") == "copy":
                self._custom_folders = [
                    f for f in self._custom_folders if f.id != e["id"]
                ]
            else:
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

    async def move(
        self,
        space: str,
        item_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress=None,
    ) -> MoveOutcome:
        # space is ignored: the mock encodes the space in each item id.
        dest = self._folder_by_id(dest_folder_id)
        outcome = MoveOutcome(dest_space=dest.space, dest_name=dest.name)
        affected: set[tuple[str, str]] = set()

        for done, item_id in enumerate(item_ids, start=1):
            await self._tick(on_progress, done, len(item_ids))
            if item_id in self._deleted:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="휴지통에 있는 사진은 이동/복사할 수 없습니다.",
                )
            item = self._resolve_item(item_id)
            day = self._day_of(item_id)
            if copy:
                self._copy_seq += 1
                copy_id = f"{item_id}-c{self._copy_seq}"
                self._extras[copy_id] = item.model_copy(update={"id": copy_id})
                self._loc[copy_id] = (dest.space, dest.id)
                outcome.created_ids.append(copy_id)
                affected.add((dest.space, day))
            else:
                prev_space, prev_folder = self._effective_loc(item_id)
                outcome.moved.append(
                    PlacedItem(id=item_id, space=prev_space, folder_id=prev_folder, day=day)
                )
                self._loc[item_id] = (dest.space, dest.id)
                affected.add((prev_space, day))
                affected.add((dest.space, day))

        outcome.affected = sorted(affected)
        self._touch(outcome.affected)
        return outcome

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


mock_source = MockPhotoSource()
