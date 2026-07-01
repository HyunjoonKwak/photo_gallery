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


class EndpointInfo(BaseModel):
    api: str
    path: str
    min_version: int
    max_version: int
    available: bool


class ApiInfoResponse(BaseModel):
    dsm_webapi_base: str
    endpoints: list[EndpointInfo]
