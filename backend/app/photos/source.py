"""PhotoSource protocol — the single interface the photo routes talk to.

Two implementations exist:
- ``MockPhotoSource`` (mock.py): deterministic fake data, no NAS needed.
- ``DsmPhotoSource`` (dsm_source.py): real SYNO.Foto / SYNO.FotoTeam calls.

Keeping the routes source-agnostic means the frontend can be built and
exercised fully in mock mode, then flipped to DSM without UI changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..schemas import PhotoBucket, PhotoFolder, PhotoItem, PlacedItem

SPACES = ("personal", "team")
THUMB_SIZES = ("sm", "xl")

# (space, day) pairs whose cached timeline data must be refreshed client-side.
Affected = list[tuple[str, str]]


@dataclass
class MoveOutcome:
    dest_space: str
    # Prior locations of moved items (empty in copy mode) — the undo payload.
    moved: list[PlacedItem] = field(default_factory=list)
    # Ids of copies made in copy mode — undo deletes these permanently.
    created_ids: list[str] = field(default_factory=list)
    affected: Affected = field(default_factory=list)


@dataclass
class DeleteOutcome:
    # Locations at deletion time — the undo (restore) payload.
    deleted: list[PlacedItem] = field(default_factory=list)
    affected: Affected = field(default_factory=list)


class PhotoSource(Protocol):
    # ------------------------------------------------------------- read side
    async def buckets(self, space: str) -> list[PhotoBucket]:
        """Day buckets (newest first) with item counts only — count-first API."""
        ...

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        """All items of one day bucket, in display (taken_at) order."""
        ...

    async def folders(self) -> list[PhotoFolder]:
        """Drop-target folders across both spaces (team always included)."""
        ...

    async def folder_items(self, folder_id: str) -> list[PhotoItem]:
        """Items currently assigned to a folder (folder view)."""
        ...

    async def members(self) -> list[str]:
        """Family member accounts (admin: cross-user organizing)."""
        ...

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        """Thumbnail bytes + content type. ``size`` is ``sm`` (grid) or ``xl``."""
        ...

    # ----------------------------------------------------------- write side
    async def move(
        self, item_ids: list[str], dest_folder_id: str, copy: bool
    ) -> MoveOutcome:
        """Move (or copy) items into a folder — cross-space allowed."""
        ...

    async def delete(self, item_ids: list[str]) -> DeleteOutcome:
        """Send items to trash (never permanent — spec: 휴지통 + Undo)."""
        ...

    # ------------------------------------------------------ undo primitives
    async def place(self, placements: list[PlacedItem]) -> Affected:
        """Put items back at recorded locations (undo of a move)."""
        ...

    async def restore(self, placements: list[PlacedItem]) -> Affected:
        """Bring items back from trash (undo of a delete)."""
        ...

    async def remove_items(self, item_ids: list[str]) -> Affected:
        """Remove copies made by a copy operation (undo of a copy)."""
        ...

    async def create_folder(self, space: str, name: str) -> PhotoFolder:
        ...

    async def remove_folder(self, folder_id: str) -> bool:
        """Remove an empty folder (undo of mkdir). False if not empty/removable."""
        ...
