"""Photo timeline endpoints (count-first buckets → per-day items → thumbnails).

The shape follows the Google Photos / Immich timeline pattern documented in
docs/IMPROVEMENTS.md B-1: the client first fetches day buckets with counts
only (cheap, whole archive), pre-allocates section heights, then lazily loads
each day's items as the viewport approaches them. Day-level buckets keep any
single geometry computation small (the Immich #28861 freeze mitigation).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..config import Settings, get_settings
from ..operations import execute_create_folder, execute_delete, execute_move
from ..photos.source import PhotoSource
from ..schemas import (
    BucketItemsResponse,
    BucketsResponse,
    CreateFolderRequest,
    DeleteRequest,
    FoldersResponse,
    MembersResponse,
    MoveRequest,
    OperationResponse,
)
from ..session_store import Session
from .deps import get_current_session, get_photo_source

router = APIRouter(prefix="/api/photos", tags=["photos"])

Space = Literal["personal", "team"]
ThumbSize = Literal["sm", "xl"]


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
) -> BucketItemsResponse:
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="day 형식은 YYYY-MM-DD 입니다.",
        ) from exc
    items = await source.items(space, day)
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
    source: PhotoSource = Depends(get_photo_source),
) -> BucketItemsResponse:
    """Items assigned to one folder (folder view). Space rides on the folder."""
    items = await source.folder_items(folder_id)
    folders = {f.id: f for f in await source.folders()}
    space = folders[folder_id].space if folder_id in folders else "team"
    return BucketItemsResponse(space=space, day="", items=items)


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


# ------------------------------------------------------------ file operations


@router.post("/ops/move", response_model=OperationResponse)
async def op_move(
    req: MoveRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    _check_target_user(session, req.target_user)
    return await execute_move(
        source, settings.sqlite_path, user=session.account, req=req
    )


@router.post("/ops/delete", response_model=OperationResponse)
async def op_delete(
    req: DeleteRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    _check_target_user(session, req.target_user)
    return await execute_delete(
        source, settings.sqlite_path, user=session.account, req=req
    )


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


@router.get("/thumbnail")
async def get_thumbnail(
    id: str,
    cache_key: str = "",
    space: Space = Query("team"),
    size: ThumbSize = Query("sm"),
    source: PhotoSource = Depends(get_photo_source),
) -> Response:
    content, media_type = await source.thumbnail(space, id, cache_key, size)
    return Response(
        content=content,
        media_type=media_type,
        # Session-scoped images; safe to let the browser cache aggressively.
        headers={"Cache-Control": "private, max-age=86400"},
    )
