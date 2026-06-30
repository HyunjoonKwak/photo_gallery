"""Synology DSM Web API client (async, httpx-based).

Design notes (per spec ch.7):
- We ALWAYS resolve real endpoint path + version via ``SYNO.API.Info`` first,
  then call each API at its advertised ``path``. We never hardcode cgi paths.
- The client itself is stateless w.r.t. user sessions: a DSM ``sid`` is passed
  in per call. The app maps its own HttpOnly cookie -> sid (see session_store).
- All failures raise ``DsmError`` with a friendly Korean message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .errors import DsmError, message_for


@dataclass(frozen=True)
class ApiEndpoint:
    """Resolved endpoint metadata from SYNO.API.Info."""

    path: str
    min_version: int
    max_version: int

    def pick_version(self, preferred: int | None = None) -> int:
        """Choose a usable version, optionally clamped toward ``preferred``."""
        if preferred is None:
            return self.max_version
        return max(self.min_version, min(self.max_version, preferred))


@dataclass(frozen=True)
class LoginResult:
    sid: str
    account: str
    # Raw extra fields DSM returned (did, is_portal_port, ...) for debugging.
    raw: dict[str, Any]


class DsmClient:
    """Thin async wrapper over the DSM Web API."""

    # APIs the MVP relies on; probed up-front so the UI can confirm availability.
    CORE_APIS: tuple[str, ...] = (
        "SYNO.API.Auth",
        "SYNO.API.Info",
        "SYNO.FileStation.Info",
        "SYNO.FileStation.List",
        "SYNO.FileStation.CreateFolder",
        "SYNO.FileStation.Rename",
        "SYNO.FileStation.CopyMove",
        "SYNO.FileStation.Delete",
        "SYNO.FileStation.Thumb",
        "SYNO.Foto.Browse.Folder",
        "SYNO.Foto.Browse.Item",
        "SYNO.Foto.Thumbnail",
        "SYNO.FotoTeam.Browse.Folder",
        "SYNO.FotoTeam.Browse.Item",
    )

    def __init__(self, webapi_base: str, http: httpx.AsyncClient):
        self._base = webapi_base.rstrip("/")
        self._http = http
        self._info_cache: dict[str, ApiEndpoint] = {}

    # ------------------------------------------------------------------ info
    async def query_api_info(
        self, apis: tuple[str, ...] | None = None, *, refresh: bool = False
    ) -> dict[str, ApiEndpoint]:
        """Resolve path/version for the given APIs via SYNO.API.Info.

        Results are cached on the client (DSM API map is server-global).
        """
        wanted = apis or self.CORE_APIS
        if not refresh:
            cached = {a: self._info_cache[a] for a in wanted if a in self._info_cache}
            if len(cached) == len(wanted):
                return cached

        # SYNO.API.Info itself always lives at query.cgi.
        url = f"{self._base}/query.cgi"
        params = {
            "api": "SYNO.API.Info",
            "version": "1",
            "method": "query",
            "query": ",".join(wanted),
        }
        data = await self._send(url, params, api="SYNO.API.Info")
        resolved: dict[str, ApiEndpoint] = {}
        for name, meta in data.items():
            if not isinstance(meta, dict) or "path" not in meta:
                continue
            endpoint = ApiEndpoint(
                path=str(meta["path"]),
                min_version=int(meta.get("minVersion", 1)),
                max_version=int(meta.get("maxVersion", 1)),
            )
            resolved[name] = endpoint
            self._info_cache[name] = endpoint
        return resolved

    async def _endpoint(self, api: str) -> ApiEndpoint:
        if api in self._info_cache:
            return self._info_cache[api]
        await self.query_api_info((api,))
        if api not in self._info_cache:
            raise DsmError(102, f"DSM에 '{api}' API가 없습니다.", api=api)
        return self._info_cache[api]

    # ------------------------------------------------------------------ call
    async def call(
        self,
        api: str,
        method: str,
        *,
        version: int | None = None,
        sid: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Any:
        """Generic authenticated DSM API call returning the ``data`` payload."""
        endpoint = await self._endpoint(api)
        params: dict[str, Any] = {
            "api": api,
            "version": str(endpoint.pick_version(version)),
            "method": method,
        }
        if extra:
            params.update({k: v for k, v in extra.items() if v is not None})
        if sid:
            params["_sid"] = sid
        url = f"{self._base}/{endpoint.path}"
        return await self._send(url, params, api=api)

    # ------------------------------------------------------------------ auth
    async def login(
        self, account: str, passwd: str, otp_code: str | None = None
    ) -> LoginResult:
        """Authenticate against SYNO.API.Auth and obtain a session id (sid)."""
        endpoint = await self._endpoint("SYNO.API.Auth")
        params: dict[str, Any] = {
            "api": "SYNO.API.Auth",
            # DSM 7 advertises up to v7; prefer it for the richer login flow.
            "version": str(endpoint.pick_version(7)),
            "method": "login",
            "account": account,
            "passwd": passwd,
            "session": "FileStation",
            "format": "sid",
        }
        if otp_code:
            params["otp_code"] = otp_code
        url = f"{self._base}/{endpoint.path}"
        data = await self._send(url, params, api="SYNO.API.Auth")
        sid = data.get("sid")
        if not sid:
            raise DsmError(100, "로그인 응답에 세션 정보가 없습니다.", api="SYNO.API.Auth")
        return LoginResult(sid=sid, account=account, raw=data)

    async def logout(self, sid: str) -> None:
        endpoint = await self._endpoint("SYNO.API.Auth")
        params = {
            "api": "SYNO.API.Auth",
            "version": str(endpoint.pick_version(7)),
            "method": "logout",
            "session": "FileStation",
            "_sid": sid,
        }
        url = f"{self._base}/{endpoint.path}"
        # Logout failures are non-fatal; swallow DSM errors but surface transport.
        try:
            await self._send(url, params, api="SYNO.API.Auth")
        except DsmError:
            pass

    # --------------------------------------------------------------- transport
    async def _send(self, url: str, params: dict[str, Any], *, api: str) -> Any:
        """Perform the HTTP GET and unwrap DSM's success/error envelope."""
        try:
            resp = await self._http.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise DsmError(
                100, f"NAS에 연결할 수 없습니다: {type(exc).__name__}", api=api
            ) from exc

        try:
            body = resp.json()
        except ValueError as exc:
            raise DsmError(100, "NAS 응답을 해석할 수 없습니다.", api=api) from exc

        if not isinstance(body, dict) or not body.get("success", False):
            code = 100
            if isinstance(body, dict):
                err = body.get("error")
                if isinstance(err, dict) and "code" in err:
                    code = int(err["code"])
            raise DsmError(code, message_for(api, code), api=api)

        return body.get("data", {})
