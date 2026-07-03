"""Shared FastAPI dependencies: settings, DSM client, session, photo source."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Query, Request, status

from ..config import Settings, get_settings
from ..dsm.client import DsmClient
from ..photos.dsm_source import DsmPhotoSource
from ..photos.homes_source import HomesPhotoSource
from ..photos.mock import mock_source
from ..photos.source import PhotoSource
from ..session_store import Session, get_session


def get_dsm_client(request: Request) -> DsmClient:
    """The shared DSM client created during app lifespan."""
    client = getattr(request.app.state, "dsm_client", None)
    if client is None:  # pragma: no cover - misconfiguration guard
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DSM 클라이언트가 초기화되지 않았습니다.",
        )
    return client


def get_current_session(
    request: Request, settings: Settings = Depends(get_settings)
) -> Session:
    """Resolve the logged-in session from the HttpOnly cookie, or 401."""
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다."
        )
    session = get_session(settings.sqlite_path, token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션이 만료되었습니다. 다시 로그인하세요.",
        )
    return session


def get_photo_source(
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_current_session),
    dsm: DsmClient = Depends(get_dsm_client),
    # Admin impersonation (spec 4.5): ?target_user= reroutes the PERSONAL
    # space to /homes/<user>/Photos via FileStation. Rides on the dependency
    # so every photo endpoint accepts it without per-route plumbing.
    target_user: str | None = Query(default=None, max_length=128),
) -> PhotoSource:
    """The photo data source for this request: mock (dev) or real DSM."""
    impersonating = bool(target_user) and target_user != session.account
    # Permission first — the rule must not depend on mock vs real mode.
    if impersonating and session.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자만 다른 구성원의 사진을 볼 수 있습니다.",
        )
    if settings.mock_mode:
        return mock_source
    if impersonating:
        assert target_user is not None
        return HomesPhotoSource(dsm, session.sid, target_user)
    return DsmPhotoSource(dsm, session.sid)
