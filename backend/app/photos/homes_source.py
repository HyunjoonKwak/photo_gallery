"""Admin impersonation source: another member's personal space (spec 4.5).

Synology Photos' API only exposes the *logged-in* user's personal space, so an
admin organizing someone else's photos goes through FileStation instead —
``/homes/<user>/Photos`` browsing (List), thumbnails (Thumb), and the existing
CopyMove/trash pipeline (admin permissions enforce access; 실 NAS 프로브
2026-07-03: List·Thumb 동작 확인).

Design: impersonation ONLY changes what "personal space" means. This class
subclasses ``DsmPhotoSource`` so the team space and the whole move/delete/undo
machinery are inherited; items/folders of the target's personal space use
**absolute paths as ids** (Foto ids are numeric — ``/``-prefixed ids mark the
FileStation world). ``_item_meta``/``_dest_dir`` translate those paths, which
is all move/delete need.

Not supported for another user's space (Photos' index is per-session):
timeline buckets, persons/places, search, EXIF — those return empty and the
UI says folder view is the way to browse someone else's photos.
"""

from __future__ import annotations

import json
import posixpath
from datetime import datetime

from ..dsm.client import DsmClient
from ..schemas import (
    ItemDetail,
    PersonInfo,
    PhotoBucket,
    PhotoFolder,
    PhotoItem,
    PlaceInfo,
)
from .dsm_source import DsmPhotoSource

_PHOTO_EXT = (
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic", ".heif", ".webp",
    ".tif", ".tiff", ".mp4", ".mov", ".m4v", ".avi", ".mkv",
)


def _is_path_id(some_id: str) -> bool:
    return some_id.startswith("/")


class HomesPhotoSource(DsmPhotoSource):
    """DsmPhotoSource with the personal space remapped to a member's home."""

    def __init__(self, dsm: DsmClient, sid: str, target_user: str) -> None:
        super().__init__(dsm, sid)
        self._target = target_user

    @property
    def _home_root(self) -> str:
        return f"/homes/{self._target}/Photos"

    def _share_prefix(self, space: str) -> str:
        if space == "personal":
            return self._home_root
        return super()._share_prefix(space)

    # ------------------------------------------------------------ browsing
    async def _fs_list(self, path: str, *, files: bool) -> list[dict]:
        data = await self._dsm.call(
            "SYNO.FileStation.List",
            "list",
            version=2,
            sid=self._sid,
            extra={
                "folder_path": path,
                "limit": 2000,
                "filetype": "file" if files else "dir",
                "additional": json.dumps(["size", "time"]),
                "sort_by": "mtime",
                "sort_direction": "desc",
            },
        )
        return data.get("files", [])

    def _rel(self, path: str) -> str:
        """Display name: path relative to the target's Photos root."""
        return path.removeprefix(self._home_root) or "/"

    def _fs_folder(self, f: dict, parent_id: str | None) -> PhotoFolder:
        rel = self._rel(f["path"])
        return PhotoFolder(
            id=f["path"],  # path-style id — marks the FileStation world
            name=rel,
            space="personal",
            parent_id=parent_id,
            depth=max(0, rel.strip("/").count("/")),
        )

    def _fs_item(self, f: dict) -> PhotoItem:
        t = (f.get("additional") or {}).get("time") or {}
        mtime = int(t.get("mtime", 0))
        size = (f.get("additional") or {}).get("size")
        return PhotoItem(
            id=f["path"],
            filename=f.get("name", ""),
            taken_at=datetime.fromtimestamp(mtime or 0).isoformat(),
            # FileStation has no image dimensions — a neutral 4:3 keeps the
            # justified layout stable until the thumbnail loads.
            width=400,
            height=300,
            size=int(size) if size is not None else None,
            cache_key=str(mtime),
            placeholder_color=None,
            folder=self._rel(posixpath.dirname(f["path"])),
        )

    async def folders(self, parent_id: str | None = None) -> list[PhotoFolder]:
        if parent_id is None:
            team = await super().folders(None)
            team_only = [f for f in team if f.space == "team"]
            try:
                dirs = await self._fs_list(self._home_root, files=False)
            except Exception:  # 대상 홈에 Photos가 없으면(408) 빈 개인 트리
                dirs = []
            personal = [
                self._fs_folder(f, None) for f in dirs if f.get("name") != "@eaDir"
            ]
            return team_only + personal
        if _is_path_id(parent_id):
            dirs = await self._fs_list(parent_id, files=False)
            return [
                self._fs_folder(f, parent_id)
                for f in dirs
                if f.get("name") != "@eaDir"
            ]
        return await super().folders(parent_id)

    async def folder_items(self, folder_id: str) -> list[PhotoItem]:
        if not _is_path_id(folder_id):
            return await super().folder_items(folder_id)
        files = await self._fs_list(folder_id, files=True)
        return [
            self._fs_item(f)
            for f in files
            if f.get("name", "").lower().endswith(_PHOTO_EXT)
        ]

    async def folder_count(self, folder_id: str) -> int:
        if not _is_path_id(folder_id):
            return await super().folder_count(folder_id)
        return len(await self.folder_items(folder_id))

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        if not _is_path_id(item_id):
            return await super().thumbnail(space, item_id, cache_key, size)
        return await self._dsm.fetch_binary(
            "SYNO.FileStation.Thumb",
            "get",
            sid=self._sid,
            extra={
                "path": item_id,
                "size": "small" if size == "sm" else "large",
            },
        )

    async def item_detail(self, space: str, item_id: str) -> ItemDetail:
        if not _is_path_id(item_id):
            return await super().item_detail(space, item_id)
        # FileStation has no EXIF/geo — folder path is still useful.
        return ItemDetail(
            id=item_id,
            folder=self._rel(posixpath.dirname(item_id)),
            exif={},
            address=None,
        )

    async def item_folders(
        self, space: str, item_ids: list[str]
    ) -> dict[str, str | None]:
        if item_ids and _is_path_id(item_ids[0]):
            return {i: self._rel(posixpath.dirname(i)) for i in item_ids}
        return await super().item_folders(space, item_ids)

    # ------------------------------------- unsupported for another user
    # Photos' timeline/AI/search indexes are per-session — empty, not wrong.
    async def buckets(self, space: str) -> list[PhotoBucket]:
        return [] if space == "personal" else await super().buckets(space)

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        return [] if space == "personal" else await super().items(space, day)

    async def persons(self, space: str) -> list[PersonInfo]:
        return [] if space == "personal" else await super().persons(space)

    async def places(self, space: str) -> list[PlaceInfo]:
        return [] if space == "personal" else await super().places(space)

    async def search_items(self, space: str, keyword: str) -> list[PhotoItem]:
        if space == "personal":
            return []
        return await super().search_items(space, keyword)

    # ---------------------------------------------------------- file ops
    # move/delete/undo are INHERITED — only the id→path translation differs.
    async def _item_meta(self, space: str, item_ids: list[str]) -> dict[str, dict]:
        if item_ids and _is_path_id(item_ids[0]):
            return {
                item_id: {
                    "path": item_id,
                    "filename": posixpath.basename(item_id),
                    "folder_id": posixpath.dirname(item_id),
                    # day is only used for cache invalidation hints; unknown
                    # here (no EXIF) — the frontend does a broad invalidate.
                    "day": "",
                }
                for item_id in item_ids
            }
        return await super()._item_meta(space, item_ids)

    async def _dest_dir(self, dest_folder_id: str) -> tuple[str, str]:
        if _is_path_id(dest_folder_id):
            return dest_folder_id, "personal"
        return await super()._dest_dir(dest_folder_id)
