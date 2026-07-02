"""Pydantic request/response models (input validation per coding rules)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=128)
    passwd: str = Field(min_length=1, max_length=256)
    otp_code: str | None = Field(default=None, max_length=16)


class UserInfo(BaseModel):
    account: str
    role: str  # admin | member
    can_browse_homes: bool  # may list /homes → gates the admin cross-user UI
    mock_mode: bool = False  # True when the backend serves fake data (dev only)


class EndpointInfo(BaseModel):
    api: str
    path: str
    min_version: int
    max_version: int
    available: bool


class ApiInfoResponse(BaseModel):
    dsm_webapi_base: str
    endpoints: list[EndpointInfo]


# --- Photos (timeline) ---


class PhotoBucket(BaseModel):
    """Count-first timeline unit: one day and how many photos it holds.

    The frontend pre-allocates section heights from counts alone, so the
    scrollbar represents the whole archive before any item detail loads.
    """

    day: str  # YYYY-MM-DD
    count: int


class PhotoItem(BaseModel):
    id: str
    filename: str
    taken_at: str  # ISO datetime
    width: int
    height: int
    size: int | None = None  # bytes
    cache_key: str
    # Solid placeholder color shown before the thumbnail loads. Replaced by a
    # thumbhash once the photo_cache pipeline lands (phase 2).
    placeholder_color: str | None = None
    folder: str | None = None


class BucketsResponse(BaseModel):
    space: str  # personal | team
    buckets: list[PhotoBucket]  # sorted newest-day first


class BucketItemsResponse(BaseModel):
    space: str
    day: str
    items: list[PhotoItem]


class PhotoFolder(BaseModel):
    id: str
    name: str
    space: str  # personal | team


class FoldersResponse(BaseModel):
    folders: list[PhotoFolder]
