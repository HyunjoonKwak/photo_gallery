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

import asyncio
import json
import os
import posixpath
from datetime import datetime

from ..dsm.client import DsmClient
from .folder_naming import fix_date_prefix
from ..schemas import (
    FolderRename,
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

# 읽기전용으로 마운트된 /volume1/homes 의 컨테이너 경로(설정 시). 설정돼 있으면
# 1차 구역/homes 썸네일을 파일 옆 @eaDir/<name>/SYNOPHOTO_THUMB_* 에서 **디스크
# 직접 읽기**로 서빙한다 — DSM FileStation API가 @eaDir을 막아(동영상 포스터
# 미표시·사진 저화질) 못 주던 것을 우회. 미설정/파일부재면 API로 폴백한다.
_THUMB_MOUNT_HOMES = os.environ.get("THUMB_MOUNT_HOMES", "").rstrip("/")


def _is_path_id(some_id: str) -> bool:
    return some_id.startswith("/")


def _read_file_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _mount_path(item_id: str) -> str | None:
    """/homes/<user>/... 경로형 id를 마운트된 실제 디스크 경로로 매핑."""
    if not (_THUMB_MOUNT_HOMES and item_id.startswith("/homes/")):
        return None
    return os.path.join(_THUMB_MOUNT_HOMES, item_id[len("/homes/") :])


async def _eadir_thumb(item_id: str, size: str) -> bytes | None:
    """마운트된 볼륨에서 @eaDir 미디어 썸네일(SYNOPHOTO_THUMB)을 직접 읽는다.
    사진·동영상 공통으로 존재. 큰 것(그리드 M / 라이트박스 XL) 우선, 없으면 SM."""
    if not (_THUMB_MOUNT_HOMES and item_id.startswith("/homes/")):
        return None
    rel = item_id[len("/homes/") :]
    parent, name = posixpath.split(rel)
    variants = ("XL", "M", "SM") if size == "xl" else ("M", "SM")
    for v in variants:
        disk = os.path.join(
            _THUMB_MOUNT_HOMES, parent, "@eaDir", name, f"SYNOPHOTO_THUMB_{v}.jpg"
        )
        data = await asyncio.to_thread(_read_file_bytes, disk)
        if data:
            return data
    return None


def _resize_original_sync(path: str, target: int) -> bytes | None:
    """원본 이미지를 마운트에서 읽어 target(긴 변) 이하로 리사이즈한 JPEG 반환.
    Synology가 @eaDir 썸네일을 안 만든(또는 초소형만 있는) 폴더용. draft로 JPEG
    부분 디코딩해 비용을 낮춘다. 디코드 불가(HEIC 등 미지원) 시 None → API 폴백."""
    from io import BytesIO

    from PIL import Image, ImageOps

    try:
        with Image.open(path) as im:
            im.draft("RGB", (target, target))  # JPEG는 축소 스케일로 빠르게 디코딩
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((target, target), Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, "JPEG", quality=82)
            return buf.getvalue()
    except Exception:
        return None


async def _resized_original(item_id: str, size: str) -> bytes | None:
    if item_id.lower().endswith(_VIDEO_EXT):
        return None  # 동영상은 프레임 추출 필요 → 여기서 처리 안 함
    disk = _mount_path(item_id)
    if not disk:
        return None
    target = 1280 if size == "xl" else 320
    return await asyncio.to_thread(_resize_original_sync, disk, target)


def _count_media_on_disk(disk_dir: str) -> int | None:
    """디렉터리의 사진·동영상 파일 수(마운트 직접 나열). 폴더 배지 카운트용 —
    수백 폴더를 DSM FileStation.List로 동시에 세면 지연·실패하지만, 소유자 uid로
    도는 컨테이너는 마운트에서 즉시 셀 수 있다. 접근 불가면 None → API 폴백."""
    try:
        return sum(
            1
            for f in os.listdir(disk_dir)
            if f.lower().endswith(_PHOTO_EXT)
        )
    except OSError:
        return None


def _scan_name_violations(disk_root: str) -> list[tuple[str, str, str]]:
    """마운트 경로 하위를 재귀로 훑어 이름 규칙 위반 폴더를 찾는다.
    반환: (fs_id=/homes/… 경로형 id, 현재이름, 교정안) 목록. @/#로 시작하는
    시스템 폴더(@eaDir 등)는 제외."""
    out: list[tuple[str, str, str]] = []
    prefix = _THUMB_MOUNT_HOMES
    try:
        for dirpath, dirnames, _files in os.walk(disk_root):
            dirnames[:] = [
                d for d in dirnames if not (d.startswith("@") or d.startswith("#"))
            ]
            for d in dirnames:
                fixed = fix_date_prefix(d)
                if fixed:
                    fs_id = "/homes" + os.path.join(dirpath, d)[len(prefix) :]
                    out.append((fs_id, d, fixed))
    except OSError:
        pass
    return out


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
        t = (f.get("additional") or {}).get("time") or {}
        # 생성일 우선(crtime, btrfs 지원), 없으면 수정일(mtime)로 대체.
        stamp = t.get("crtime") or t.get("mtime")
        return PhotoFolder(
            id=f["path"],  # path-style id — marks the FileStation world
            name=rel,
            space="personal",
            parent_id=parent_id,
            depth=max(0, rel.strip("/").count("/")),
            mtime=int(stamp) if stamp else None,
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
        # 마운트에서 직접 카운트(빠르고 안정적) — 하위폴더가 수백 개인 폴더에서
        # DSM FileStation.List를 폴더마다 동시 호출하면 지연·실패해 배지가 빈칸이
        # 되던 문제 해결. 마운트 없으면 API(folder_items)로 폴백.
        disk = _mount_path(folder_id)
        if disk:
            n = await asyncio.to_thread(_count_media_on_disk, disk)
            if n is not None:
                return n
        return len(await self.folder_items(folder_id))

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        if not _is_path_id(item_id):
            return await super().thumbnail(space, item_id, cache_key, size)
        # 마운트가 설정돼 있으면 @eaDir의 SYNOPHOTO_THUMB을 디스크에서 직접 읽어
        # 서빙한다(사진 고화질 + 동영상 포스터까지 해결, DSM 왕복도 없음). DSM API는
        # @eaDir을 막지만 파일시스템 직접 읽기엔 그 제약이 없다(실 NAS 검증 2026-07-07).
        disk = await _eadir_thumb(item_id, size)
        if disk is not None:
            return disk, "image/jpeg"
        # @eaDir SYNOPHOTO가 없는 폴더(Synology 미인덱싱 → 썸네일 없음, 또는 초소형
        # SYNOFILE만) — 원본을 마운트에서 읽어 백엔드가 직접 리사이즈해 서빙한다.
        # 사진 전용(동영상은 프레임 추출 필요). 결과는 디스크 캐시에 저장돼 반복 즉시.
        resized = await _resized_original(item_id, size)
        if resized is not None:
            return resized, "image/jpeg"
        # 폴백: File Station 썸네일 API. (마운트 미설정 또는 원본 디코드 불가한 경우)
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
        # zone/homes(FileStation 세계)에서는 **최상위(부모 없음)든 하위(경로형
        # 부모)든** FileStation.CreateFolder로 만든다. 예전엔 parent_id=None을
        # super()(Foto)로 넘겨 개인 Photos 루트(/home/Photos)에 만들어, 1차 구역
        # 최상위에 새 폴더가 "내 사진"에 생기는 버그가 있었다(2026-07-07).
        # 부모가 비경로 Foto id인 예외 경우만 super()로.
        if parent_id is not None and not _is_path_id(parent_id):
            return await super().create_folder(space, name, parent_id)
        folder_path = parent_id if parent_id else self._root_path
        await self._dsm.call(
            "SYNO.FileStation.CreateFolder",
            "create",
            version=2,
            sid=self._sid,
            extra={"folder_path": folder_path, "name": name},
        )
        path = f"{folder_path.rstrip('/')}/{name}"
        return self._fs_folder({"path": path}, parent_id)

    async def audit_folder_names(self, root_id: str | None) -> list[FolderRename]:
        # 마운트에서 재귀 스캔(소유자 uid로 os.walk). 마운트 없으면 빈 목록.
        root_fs = root_id if (root_id and _is_path_id(root_id)) else self._root_path
        disk = _mount_path(root_fs)
        if not disk:
            return []
        rows = await asyncio.to_thread(_scan_name_violations, disk)
        return [
            FolderRename(id=i, current_name=c, proposed_name=p) for i, c, p in rows
        ]

    async def rename_folder(
        self, space: str, folder_id: str, new_name: str
    ) -> tuple[str, str]:
        if not _is_path_id(folder_id):
            return await super().rename_folder(space, folder_id, new_name)
        await self._dsm.call(
            "SYNO.FileStation.Rename",
            "rename",
            version=2,
            sid=self._sid,
            extra={"path": folder_id, "name": new_name},
        )
        parent = posixpath.dirname(folder_id)
        return f"{parent}/{new_name}", new_name

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
