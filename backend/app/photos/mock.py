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

import re
from datetime import date, timedelta
from random import Random
from zlib import crc32

from fastapi import HTTPException, status

from ..schemas import PhotoBucket, PhotoFolder, PhotoItem, PlacedItem
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
    return PhotoItem(
        id=f"m-{space}-{day}-{idx}",
        filename=f"IMG_{day.replace('-', '')}_{idx:04d}.jpg",
        taken_at=f"{day}T{hour:02d}:{minute:02d}:00",
        width=aw * base,
        height=ah * base,
        size=r.randint(800_000, 8_000_000),
        cache_key="mock",
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

    # ------------------------------------------------------------ internals
    def _all_folders(self) -> list[PhotoFolder]:
        return [*_DEFAULT_FOLDERS, *self._custom_folders]

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

    async def folders(self) -> list[PhotoFolder]:
        return self._all_folders()

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

    async def members(self) -> list[str]:
        return list(_MEMBERS)

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        return _svg_thumbnail(self._resolve_item(item_id), size), "image/svg+xml"

    # ------------------------------------------------------------ write side
    async def move(
        self, item_ids: list[str], dest_folder_id: str, copy: bool
    ) -> MoveOutcome:
        dest = self._folder_by_id(dest_folder_id)
        outcome = MoveOutcome(dest_space=dest.space)
        affected: set[tuple[str, str]] = set()

        for item_id in item_ids:
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

    async def delete(self, item_ids: list[str]) -> DeleteOutcome:
        outcome = DeleteOutcome()
        affected: set[tuple[str, str]] = set()
        for item_id in item_ids:
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
    async def place(self, placements: list[PlacedItem]) -> Affected:
        affected: set[tuple[str, str]] = set()
        for p in placements:
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

    async def restore(self, placements: list[PlacedItem]) -> Affected:
        affected: set[tuple[str, str]] = set()
        for p in placements:
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

    async def create_folder(self, space: str, name: str) -> PhotoFolder:
        if any(f.space == space and f.name == name for f in self._all_folders()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="같은 이름의 폴더가 이미 있습니다.",
            )
        self._folder_seq += 1
        folder = PhotoFolder(id=f"f-{space}-c{self._folder_seq}", name=name, space=space)
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
