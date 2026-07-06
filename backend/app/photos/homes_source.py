"""FileStation-backed photo sources for folders outside the logged-in user's
Synology Photos index.

Two use cases share one mechanism (browsing a raw filesystem tree by absolute
path instead of the Photos index):

- ``HomesPhotoSource`` — admin impersonation (spec 4.5): another member's
  personal space ``/homes/<user>/Photos``. Photos' API only exposes the
  logged-in user's own space, so an admin organizing someone else's photos goes
  through FileStation.
- ``ZonePhotoSource`` (zone_source.py) — the user's own "1차 구역" (기기 백업)
  folder that sits OUTSIDE ``/homes/<me>/Photos`` so it stays off the timeline.

Both subclass ``DsmPhotoSource`` and reuse the whole move/delete/undo machinery;
the only difference is that items/folders of the FileStation root use **absolute
paths as ids** (Foto ids are numeric — a ``/``-prefixed id marks the FileStation
world). The path handling lives in ``_FsRootMixin`` (keyed only on the abstract
``_root_path``); each subclass supplies that root and any space-specific
overrides. ``_item_meta``/``_dest_dir`` translate path ids for move/delete.
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
_VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv")


def _is_path_id(some_id: str) -> bool:
    return some_id.startswith("/")


class _FsRootMixin:
    """FileStation path-id handling rooted at an abstract ``_root_path``.

    Mixed in BEFORE ``DsmPhotoSource`` in the MRO so ``super()`` in each method
    falls through to the Foto implementation for non-path (numeric) ids. Every
    method here only acts when the id is a ``/``-prefixed absolute path.
    """

    # Subclasses must expose the absolute FileStation root (e.g. a home's Photos
    # dir, or a 기기 백업 zone folder).
    @property
    def _root_path(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

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
        """Display name: path relative to the FileStation root."""
        return path.removeprefix(self._root_path) or "/"

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
        is_video = f.get("name", "").lower().endswith(_VIDEO_EXT)
        return PhotoItem(
            type="video" if is_video else "photo",
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

    async def _fs_children_folders(self, path: str) -> list[PhotoFolder]:
        """Sub-folders directly under an absolute path, as path-id folders.
        The parent id is None only at the root (drives breadcrumb reset)."""
        parent = None if path == self._root_path else path
        dirs = await self._fs_list(path, files=False)
        return [self._fs_folder(f, parent) for f in dirs if f.get("name") != "@eaDir"]

    async def folders(self, parent_id: str | None = None) -> list[PhotoFolder]:
        if parent_id is None:
            return await self._fs_children_folders(self._root_path)
        if _is_path_id(parent_id):
            return await self._fs_children_folders(parent_id)
        return await super().folders(parent_id)

    async def folder_items(
        self, folder_id: str, limit: int | None = None
    ) -> list[PhotoItem]:
        if not _is_path_id(folder_id):
            return await super().folder_items(folder_id, limit)
        files = await self._fs_list(folder_id, files=True)
        items = [
            self._fs_item(f)
            for f in files
            if f.get("name", "").lower().endswith(_PHOTO_EXT)
        ]
        return items[:limit] if limit is not None else items

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

    async def video_stream(
        self, space: str, item_id: str, range_header: str | None
    ):
        if not _is_path_id(item_id):
            return await super().video_stream(space, item_id, range_header)
        return await self._dsm.stream_binary(
            "SYNO.FileStation.Download",
            "download",
            version=2,
            sid=self._sid,
            extra={"path": item_id, "mode": "download"},
            range_header=range_header,
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

    async def create_folder(
        self, space: str, name: str, parent_id: str | None = None
    ):
        if parent_id is None or not _is_path_id(parent_id):
            return await super().create_folder(space, name, parent_id)
        await self._dsm.call(
            "SYNO.FileStation.CreateFolder",
            "create",
            version=2,
            sid=self._sid,
            extra={"folder_path": parent_id, "name": name},
        )
        path = f"{parent_id}/{name}"
        return self._fs_folder({"path": path}, parent_id)

    async def remove_folder(self, folder_id: str) -> bool:
        if not _is_path_id(folder_id):
            return await super().remove_folder(folder_id)
        entries = await self._fs_list(folder_id, files=False) + await self._fs_list(
            folder_id, files=True
        )
        if any(e.get("name") != "@eaDir" for e in entries):
            return False  # not empty
        await self._delete_paths([folder_id])
        return True

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


class HomesPhotoSource(_FsRootMixin, DsmPhotoSource):
    """Admin impersonation: the PERSONAL space is remapped to a member's home.

    Not supported for another user's space (Photos' index is per-session):
    timeline buckets, persons/places, search, EXIF — those return empty and the
    UI says folder view is the way to browse someone else's photos.
    """

    def __init__(self, dsm: DsmClient, sid: str, target_user: str) -> None:
        super().__init__(dsm, sid)
        self._target = target_user

    @property
    def _root_path(self) -> str:
        return f"/homes/{self._target}/Photos"

    # Impersonation hijacks the personal share so inherited Foto path building
    # (rarely reached here) points at the target's home rather than /home/Photos.
    def _share_prefix(self, space: str) -> str:
        if space == "personal":
            return self._root_path
        return super()._share_prefix(space)

    async def folders(self, parent_id: str | None = None) -> list[PhotoFolder]:
        if parent_id is None:
            team = await DsmPhotoSource.folders(self, None)
            team_only = [f for f in team if f.space == "team"]
            try:
                personal = await self._fs_children_folders(self._root_path)
            except Exception:  # 대상 홈에 Photos가 없으면(408) 빈 개인 트리
                personal = []
            return team_only + personal
        return await super().folders(parent_id)

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

    async def videos(self, space: str) -> list[PhotoItem]:
        return [] if space == "personal" else await super().videos(space)
