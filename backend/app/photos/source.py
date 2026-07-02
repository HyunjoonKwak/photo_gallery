"""PhotoSource protocol — the single interface the photo routes talk to.

Two implementations exist:
- ``MockPhotoSource`` (mock.py): deterministic fake data, no NAS needed.
- ``DsmPhotoSource`` (dsm_source.py): real SYNO.Foto / SYNO.FotoTeam calls.

Keeping the routes source-agnostic means the frontend can be built and
exercised fully in mock mode, then flipped to DSM without UI changes.
"""

from __future__ import annotations

from typing import Protocol

from ..schemas import PhotoBucket, PhotoFolder, PhotoItem

SPACES = ("personal", "team")
THUMB_SIZES = ("sm", "xl")


class PhotoSource(Protocol):
    async def buckets(self, space: str) -> list[PhotoBucket]:
        """Day buckets (newest first) with item counts only — count-first API."""
        ...

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        """All items of one day bucket, in display (taken_at) order."""
        ...

    async def folders(self) -> list[PhotoFolder]:
        """Drop-target folders across both spaces (team always included)."""
        ...

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        """Thumbnail bytes + content type. ``size`` is ``sm`` (grid) or ``xl``."""
        ...
