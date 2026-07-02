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

from ..photos.source import PhotoSource
from ..schemas import BucketItemsResponse, BucketsResponse, FoldersResponse
from .deps import get_photo_source

router = APIRouter(prefix="/api/photos", tags=["photos"])

Space = Literal["personal", "team"]
ThumbSize = Literal["sm", "xl"]


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
    source: PhotoSource = Depends(get_photo_source),
) -> FoldersResponse:
    return FoldersResponse(folders=await source.folders())


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
