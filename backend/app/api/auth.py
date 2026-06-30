"""Authentication endpoints: login / logout / me.

Login exchanges DSM credentials for a sid, wraps it in a server-side session,
and returns only an opaque HttpOnly cookie to the browser.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..config import Settings, get_settings
from ..dsm.client import DsmClient
from ..dsm.errors import DsmError
from ..schemas import LoginRequest, UserInfo
from ..session_store import Session, create_session, delete_session
from .deps import get_current_session, get_dsm_client

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def detect_role(dsm: DsmClient, sid: str) -> str:
    """Best-effort role detection (refined in the admin-features step).

    Admins with the user-home service enabled can list ``/homes``; regular
    members get a permission error. We use that capability as the signal,
    since it is exactly the privilege the admin features depend on.
    """
    try:
        await dsm.call(
            "SYNO.FileStation.List",
            "list",
            sid=sid,
            extra={"folder_path": "/homes", "limit": 1},
        )
        return "admin"
    except DsmError:
        return "member"


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
    try:
        result = await dsm.login(body.account, body.passwd, body.otp_code)
    except DsmError as exc:
        # 400/401/402 -> bad credentials/disabled; 403/404 -> OTP needed/wrong.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    role = await detect_role(dsm, result.sid)
    session = create_session(
        settings.sqlite_path,
        sid=result.sid,
        account=result.account,
        role=role,
        ttl_seconds=settings.session_ttl_seconds,
    )
    _set_session_cookie(response, settings, session.token)
    return UserInfo(account=session.account, role=session.role)


@router.get("/me", response_model=UserInfo)
async def me(session: Session = Depends(get_current_session)) -> UserInfo:
    return UserInfo(account=session.account, role=session.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
    dsm: DsmClient = Depends(get_dsm_client),
    session: Session = Depends(get_current_session),
) -> Response:
    sid = delete_session(settings.sqlite_path, session.token)
    if sid:
        await dsm.logout(sid)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
