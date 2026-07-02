"""Deterministic mock photo source — lets the UI be built without a NAS.

Everything derives from seeded PRNGs keyed on (space, day), so the same call
always returns the same data: bucket counts, aspect ratios, colors, filenames.
Thumbnails are generated SVGs (gradient + size-dependent detail), which the
browser renders in <img> like any raster image.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from random import Random
from zlib import crc32

from fastapi import HTTPException, status

from ..schemas import PhotoBucket, PhotoFolder, PhotoItem

# (w, h) aspect seeds — mixed portrait/landscape so justified layout is exercised.
_ASPECTS = [(4, 3), (3, 4), (3, 2), (2, 3), (16, 9), (1, 1), (9, 16)]
_DAYS_BACK = 540  # ~18 months of history

_ID_RE = re.compile(r"^m-(personal|team)-(\d{4}-\d{2}-\d{2})-(\d+)$")

_FOLDERS = [
    PhotoFolder(id="f-team-1", name="가족앨범", space="team"),
    PhotoFolder(id="f-team-2", name="행사", space="team"),
    PhotoFolder(id="f-team-3", name="인화용", space="team"),
    PhotoFolder(id="f-personal-1", name="여행", space="personal"),
    PhotoFolder(id="f-personal-2", name="아이들", space="personal"),
    PhotoFolder(id="f-personal-3", name="스크린샷", space="personal"),
]


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


def _svg_thumbnail(item: PhotoItem, size: str) -> bytes:
    long_edge = 320 if size == "sm" else 1280
    if item.width >= item.height:
        w = long_edge
        h = max(1, round(long_edge * item.height / item.width))
    else:
        h = long_edge
        w = max(1, round(long_edge * item.width / item.height))

    # Recover the hue from the placeholder color for a matching gradient.
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
    """PhotoSource implementation backed by seeded fake data."""

    async def buckets(self, space: str) -> list[PhotoBucket]:
        today = date.today()
        out: list[PhotoBucket] = []
        for i in range(_DAYS_BACK):
            d = (today - timedelta(days=i)).isoformat()
            count = _day_count(space, d)
            if count:
                out.append(PhotoBucket(day=d, count=count))
        return out

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        count = _day_count(space, day)
        r = _rng(f"{space}:{day}:items")
        return [_build_item(space, day, idx, r) for idx in range(count)]

    async def folders(self) -> list[PhotoFolder]:
        return list(_FOLDERS)

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        m = _ID_RE.match(item_id)
        if not m:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="사진을 찾을 수 없습니다."
            )
        id_space, day, idx = m.group(1), m.group(2), int(m.group(3))
        items = await self.items(id_space, day)
        if idx >= len(items):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="사진을 찾을 수 없습니다."
            )
        return _svg_thumbnail(items[idx], size), "image/svg+xml"


mock_source = MockPhotoSource()
