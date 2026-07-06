"""Photo timeline endpoints (count-first buckets → per-day items → thumbnails).

The shape follows the Google Photos / Immich timeline pattern documented in
docs/IMPROVEMENTS.md B-1: the client first fetches day buckets with counts
only (cheap, whole archive), pre-allocates section heights, then lazily loads
each day's items as the viewport approaches them. Day-level buckets keep any
single geometry computation small (the Immich #28861 freeze mitigation).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from ..config import Settings, get_settings
from ..dedup import fill_thumbhashes
from ..dsm.errors import SESSION_INVALID_CODES, DsmError
from ..operations import (
    execute_create_folder,
    execute_delete,
    execute_move,
    execute_move_folders,
    execute_remove_folder,
)
from ..photos.source import PhotoSource
from .. import progress
from ..schemas import (
    BucketItemsResponse,
    BucketsResponse,
    CreateFolderRequest,
    DeleteRequest,
    FolderCountsResponse,
    FoldersResponse,
    ConflictItem,
    ItemDetail,
    MembersResponse,
    MoveCheckRequest,
    MoveCheckResponse,
    MoveFoldersRequest,
    MoveRequest,
    OperationResponse,
    PersonsResponse,
    PlacesResponse,
    RemoveFolderRequest,
)
from ..session_store import Session
from .deps import get_current_session, get_photo_source

router = APIRouter(prefix="/api/photos", tags=["photos"])

Space = Literal["personal", "team"]
# sm=grid, m=sm이 broken일 때 폴백(동영상 등), xl=라이트박스. 전부 DSM 실제
# 썸네일 사이즈명과 1:1 (SYNO.Foto.Thumbnail size 파라미터).
ThumbSize = Literal["sm", "m", "xl"]


def _check_target_user(session: Session, target_user: str | None) -> None:
    """Only admins may act on another member's behalf (audit-logged)."""
    if target_user and target_user != session.account and session.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자만 다른 구성원을 대상으로 작업할 수 있습니다.",
        )


@router.get("/buckets", response_model=BucketsResponse)
async def list_buckets(
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> BucketsResponse:
    buckets = await source.buckets(space)
    return BucketsResponse(space=space, buckets=buckets)


@router.get("/items", response_model=BucketItemsResponse)
async def list_bucket_items(
    day: str,
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="day 형식은 YYYY-MM-DD 입니다.",
        ) from exc
    items = fill_thumbhashes(settings.sqlite_path, await source.items(space, day))
    return BucketItemsResponse(space=space, day=day, items=items)


@router.get("/folders", response_model=FoldersResponse)
async def list_folders(
    parent_id: str | None = None,
    source: PhotoSource = Depends(get_photo_source),
) -> FoldersResponse:
    """One level of the folder tree. Omit parent_id for top-level folders."""
    return FoldersResponse(folders=await source.folders(parent_id))


@router.get("/folder-items", response_model=BucketItemsResponse)
async def list_folder_items(
    folder_id: str,
    limit: int | None = Query(None, ge=1, le=100),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    """Items assigned to one folder (folder view). Space rides on the folder.
    ``limit`` (미리보기 카드) caps to a cheap single page."""
    items = fill_thumbhashes(
        settings.sqlite_path, await source.folder_items(folder_id, limit)
    )
    folders = {f.id: f for f in await source.folders()}
    space = folders[folder_id].space if folder_id in folders else "team"
    return BucketItemsResponse(space=space, day="", items=items)


@router.get("/folder-counts", response_model=FolderCountsResponse)
async def get_folder_counts(
    ids: str,
    source: PhotoSource = Depends(get_photo_source),
) -> FolderCountsResponse:
    """Direct item counts for a set of folders (folder view badges).

    Comma-separated ids, counted in parallel; a folder whose count fails is
    omitted (the UI simply hides that badge) so one bad id can't 500 the batch.
    """
    id_list = [i.strip() for i in ids.split(",") if i.strip()][:200]

    async def one(fid: str) -> tuple[str, int | None]:
        try:
            return fid, await source.folder_count(fid)
        except Exception:
            return fid, None

    pairs = await asyncio.gather(*(one(fid) for fid in id_list))
    return FolderCountsResponse(
        counts={fid: n for fid, n in pairs if n is not None}
    )


@router.get("/members", response_model=MembersResponse)
async def list_members(
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> MembersResponse:
    if session.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자만 가족 구성원 목록을 볼 수 있습니다.",
        )
    return MembersResponse(members=await source.members())


@router.get("/search", response_model=BucketItemsResponse)
async def search_photos(
    q: str = Query(min_length=1, max_length=100),
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    """Keyword search over DSM's own index (filename/folder/tag)."""
    items = fill_thumbhashes(
        settings.sqlite_path, await source.search_items(space, q)
    )
    return BucketItemsResponse(space=space, day="", items=items)


@router.get("/item-detail", response_model=ItemDetail)
async def get_item_detail(
    id: str,
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> ItemDetail:
    """Lightbox info panel: folder path + EXIF + location, fetched on open."""
    return await source.item_detail(space, id)


# --------------------------------------------- AI classification (3단계)
# Synology Photos' built-in AI groups (faces, GPS places) — read-only here;
# acting on them reuses the regular move/delete + undo pipeline.


@router.get("/persons", response_model=PersonsResponse)
async def list_persons(
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> PersonsResponse:
    return PersonsResponse(space=space, persons=await source.persons(space))


@router.get("/person-items", response_model=BucketItemsResponse)
async def list_person_items(
    id: str,
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    items = fill_thumbhashes(
        settings.sqlite_path, await source.person_items(space, id)
    )
    return BucketItemsResponse(space=space, day="", items=items)


@router.get("/places", response_model=PlacesResponse)
async def list_places(
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> PlacesResponse:
    return PlacesResponse(space=space, places=await source.places(space))


@router.get("/place-items", response_model=BucketItemsResponse)
async def list_place_items(
    id: str,
    space: Space = Query("team"),
    limit: int | None = Query(None, ge=1, le=100),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    """``limit`` (미리보기 카드) caps to a cheap single page."""
    items = fill_thumbhashes(
        settings.sqlite_path, await source.place_items(space, id, limit)
    )
    return BucketItemsResponse(space=space, day="", items=items)


@router.get("/videos", response_model=BucketItemsResponse)
async def list_videos(
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    """앨범 · 비디오 — 라이브러리 전체의 영상만(최신순)."""
    items = fill_thumbhashes(settings.sqlite_path, await source.videos(space))
    return BucketItemsResponse(space=space, day="", items=items)


# ------------------------------------------------------------ file operations


@router.post("/ops/move-check", response_model=MoveCheckResponse)
async def op_move_check(
    req: MoveCheckRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> MoveCheckResponse:
    """Pre-flight: which selected items would collide by filename at the dest.
    The frontend calls this before a move/copy to raise the 충돌 처리 dialog."""
    _check_target_user(session, req.target_user)
    pairs = await source.conflicts(req.space, req.item_ids, req.dest_folder_id)
    return MoveCheckResponse(
        conflicts=[ConflictItem(item_id=i, filename=f) for i, f in pairs]
    )


@router.post("/ops/move", response_model=OperationResponse)
async def op_move(
    req: MoveRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    _check_target_user(session, req.target_user)
    verb = "복사" if req.copy_mode else "이동"
    try:
        return await execute_move(
            source,
            settings.sqlite_path,
            user=session.account,
            req=req,
            on_progress=progress.callback(req.progress_key, verb),
        )
    finally:
        progress.clear(req.progress_key)


@router.post("/ops/delete", response_model=OperationResponse)
async def op_delete(
    req: DeleteRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    _check_target_user(session, req.target_user)
    try:
        return await execute_delete(
            source,
            settings.sqlite_path,
            user=session.account,
            req=req,
            on_progress=progress.callback(req.progress_key, "삭제"),
        )
    finally:
        progress.clear(req.progress_key)


@router.post("/folders", response_model=OperationResponse)
async def op_create_folder(
    req: CreateFolderRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    _check_target_user(session, req.target_user)
    if req.space not in ("personal", "team"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="space는 personal 또는 team 이어야 합니다.",
        )
    return await execute_create_folder(
        source, settings.sqlite_path, user=session.account, req=req
    )


@router.get("/video")
async def stream_video(
    id: str,
    request: Request,
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> StreamingResponse:
    """Video playback proxy — Range passthrough so <video> seeking works."""
    upstream = await source.video_stream(space, id, request.headers.get("range"))
    passthrough = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() in ("content-type", "content-length", "content-range")
    }
    passthrough.setdefault("Accept-Ranges", "bytes")

    async def body():
        try:
            async for chunk in upstream.aiter_bytes(64 * 1024):
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        body(), status_code=upstream.status_code, headers=passthrough
    )


@router.post("/ops/move-folders", response_model=OperationResponse)
async def op_move_folders(
    req: MoveFoldersRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    """폴더째(하위 포함) 이동/복사 — 여러 폴더 한 번에."""
    _check_target_user(session, req.target_user)
    verb = "복사" if req.copy_mode else "이동"
    try:
        return await execute_move_folders(
            source,
            settings.sqlite_path,
            user=session.account,
            req=req,
            on_progress=progress.callback(req.progress_key, f"폴더 {verb}"),
        )
    finally:
        progress.clear(req.progress_key)


@router.post("/folders/delete", response_model=OperationResponse)
async def op_remove_folder(
    req: RemoveFolderRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    """빈 폴더 삭제 (분할 뷰 정리) — 비어 있지 않으면 409."""
    _check_target_user(session, req.target_user)
    return await execute_remove_folder(
        source, settings.sqlite_path, user=session.account, req=req
    )


@router.get("/thumbnail")
async def get_thumbnail(
    id: str,
    cache_key: str = "",
    space: Space = Query("team"),
    size: ThumbSize = Query("sm"),
    source: PhotoSource = Depends(get_photo_source),
) -> Response:
    try:
        content, media_type = await source.thumbnail(space, id, cache_key, size)
    except DsmError as exc:
        # Session problems still need a 401 so the client re-auths; a genuinely
        # missing thumbnail (DSM 404 — Synology never generated a poster for
        # this item, common for videos) is a clean 404, not a 502. The frontend
        # <img> onError then shows its fallback tile without noisy errors.
        if exc.code in SESSION_INVALID_CODES:
            raise
        if exc.http_status == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "썸네일이 없습니다.") from exc
        raise
    return Response(
        content=content,
        media_type=media_type,
        # Session-scoped images; safe to let the browser cache aggressively.
        headers={"Cache-Control": "private, max-age=86400"},
    )
