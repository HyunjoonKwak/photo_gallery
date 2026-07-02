"""Authentication endpoints: login / logout / me.

Login exchanges DSM credentials for a sid, wraps it in a server-side session,
and returns only an opaque HttpOnly cookie to the browser.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..config import Settings, get_settings
from ..dsm.client import DsmClient
from ..dsm.errors import DsmError
from ..rate_limit import clear_failures, record_failure, seconds_until_unblocked
from ..schemas import LoginRequest, UserInfo
from ..session_store import (
    Session,
    create_session,
    delete_session,
    purge_expired,
)
from .deps import get_current_session, get_dsm_client

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def detect_role(dsm: DsmClient, sid: str) -> str:
    """Determine role from DSM's own admin flag.

    ``SYNO.FileStation.Info`` reports ``is_manager`` — true for accounts in the
    administrators group. This is the authoritative signal and, unlike probing
    ``/homes``, does not misfire when the user-home service happens to be off.
    """
    try:
        info = await dsm.call("SYNO.FileStation.Info", "get", sid=sid)
    except DsmError:
        return "member"
    return "admin" if bool(info.get("is_manager")) else "member"


async def detect_can_browse_homes(dsm: DsmClient, sid: str) -> bool:
    """Whether this session can list ``/homes`` (the admin cross-user feature).

    Separate from role: it needs both administrator rights *and* the user-home
    service enabled. Gating the admin UI on this capability (rather than on
    ``role``) lets us show an accurate "why unavailable" reason later.
    """
    try:
        await dsm.call(
            "SYNO.FileStation.List",
            "list",
            sid=sid,
            extra={"folder_path": "/homes", "limit": 1},
        )
        return True
    except DsmError:
        return False


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=UserInfo)
async def login(
    body: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    dsm: DsmClient = Depends(get_dsm_client),
) -> UserInfo:
    # Throttle before touching DSM so repeated bad passwords can't trip DSM's
    # Auto Block and lock out the whole container IP for every family member.
    retry_after = seconds_until_unblocked(
        settings.sqlite_path,
        body.account,
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_window_seconds,
    )
    if retry_after > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"로그인 시도가 너무 많습니다. {retry_after}초 후 다시 시도하세요.",
            headers={"Retry-After": str(retry_after)},
        )

    if settings.mock_mode:
        # Dev-only path (no NAS): accept any credentials. "admin" account gets
        # the admin role so both role variants of the UI can be exercised.
        role = "admin" if body.account == "admin" else "member"
        session = create_session(
            settings.sqlite_path,
            sid="mock-sid",
            account=body.account,
            role=role,
            can_browse_homes=role == "admin",
            ttl_seconds=settings.session_ttl_seconds,
        )
        _set_session_cookie(response, settings, session.token)
        return UserInfo(
            account=session.account,
            role=session.role,
            can_browse_homes=session.can_browse_homes,
            mock_mode=True,
        )

    try:
        result = await dsm.login(body.account, body.passwd, body.otp_code)
    except DsmError as exc:
        # 400/401/402 -> bad credentials/disabled; 403/404 -> OTP needed/wrong.
        record_failure(settings.sqlite_path, body.account)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    clear_failures(settings.sqlite_path, body.account)
    # Opportunistically prune expired sessions on each login so stale rows don't
    # accumulate between server restarts (no separate background sweeper needed).
    purge_expired(settings.sqlite_path)
    role = await detect_role(dsm, result.sid)
    can_browse_homes = await detect_can_browse_homes(dsm, result.sid)
    session = create_session(
        settings.sqlite_path,
        sid=result.sid,
        account=result.account,
        role=role,
        can_browse_homes=can_browse_homes,
        ttl_seconds=settings.session_ttl_seconds,
    )
    _set_session_cookie(response, settings, session.token)
    return UserInfo(
        account=session.account,
        role=session.role,
        can_browse_homes=session.can_browse_homes,
        mock_mode=False,
    )


@router.get("/me", response_model=UserInfo)
async def me(
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_current_session),
) -> UserInfo:
    return UserInfo(
        account=session.account,
        role=session.role,
        can_browse_homes=session.can_browse_homes,
        mock_mode=settings.mock_mode,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
    dsm: DsmClient = Depends(get_dsm_client),
    session: Session = Depends(get_current_session),
) -> Response:
    sid = delete_session(settings.sqlite_path, session.token)
    if sid and not settings.mock_mode:
        await dsm.logout(sid)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
