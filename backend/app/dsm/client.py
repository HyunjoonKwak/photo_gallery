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
        "SYNO.Foto.Browse.Timeline",
        "SYNO.Foto.Thumbnail",
        "SYNO.FotoTeam.Browse.Folder",
        "SYNO.FotoTeam.Browse.Item",
        "SYNO.FotoTeam.Browse.Timeline",
        "SYNO.FotoTeam.Thumbnail",
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
        http_method: str = "GET",
    ) -> Any:
        """Generic authenticated DSM API call returning the ``data`` payload.
        ``http_method`` = "POST" sends params as a form body (일부 쓰기 API용)."""
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
        return await self._send(url, params, api=api, method=http_method)

    async def call_raw(
        self,
        api: str,
        method: str,
        *,
        version: int | None = None,
        sid: str | None = None,
        extra: dict[str, Any] | None = None,
        http_method: str = "GET",
    ) -> Any:
        """진단용: success/error 언래핑 없이 DSM 원본 JSON을 그대로 반환한다
        (오류의 error.errors 상세로 필요 파라미터를 파악하기 위함)."""
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
        if http_method == "POST":
            resp = await self._http.post(url, data=params)
        else:
            resp = await self._http.get(url, params=params)
        try:
            return resp.json()
        except ValueError:
            return {"_status": resp.status_code, "_text": resp.text[:300]}

    async def fetch_binary(
        self,
        api: str,
        method: str,
        *,
        version: int | None = None,
        sid: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        """Call an API that answers with raw bytes (e.g. SYNO.Foto.Thumbnail).

        Success responses are image bytes; failures still come back as the JSON
        error envelope, which we detect by content type and convert to DsmError.
        """
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

        try:
            resp = await self._http.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # DSM answered with an HTTP error status (commonly 404 for a
            # thumbnail Synology never generated). Preserve the status so the
            # caller can return a clean 404 instead of a scary 502.
            raise DsmError(
                100,
                f"NAS 응답 오류 (HTTP {exc.response.status_code})",
                api=api,
                http_status=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise DsmError(
                100, f"NAS에 연결할 수 없습니다: {type(exc).__name__}", api=api
            ) from exc

        content_type = resp.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            try:
                body = resp.json()
            except ValueError as exc:
                raise DsmError(100, "NAS 응답을 해석할 수 없습니다.", api=api) from exc
            code = 100
            if isinstance(body, dict):
                err = body.get("error")
                if isinstance(err, dict) and "code" in err:
                    code = int(err["code"])
            raise DsmError(code, message_for(api, code), api=api)

        return resp.content, content_type or "image/jpeg"

    async def stream_binary(
        self,
        api: str,
        method: str,
        *,
        version: int | None = None,
        sid: str | None = None,
        extra: dict[str, Any] | None = None,
        range_header: str | None = None,
    ) -> httpx.Response:
        """Open a STREAMING GET for large binary payloads (video playback).

        The Range header passes through so browser ``<video>`` seeking works
        (DSM answers 206 + Content-Range — 실 NAS 확인 2026-07-03). The caller
        must ``aclose()`` the returned response after consuming the stream.
        """
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
        headers = {"Range": range_header} if range_header else {}
        try:
            req = self._http.build_request("GET", url, params=params, headers=headers)
            resp = await self._http.send(req, stream=True)
        except httpx.HTTPError as exc:
            raise DsmError(
                100, f"NAS에 연결할 수 없습니다: {type(exc).__name__}", api=api
            ) from exc
        # DSM signals errors as a JSON envelope even here.
        if resp.headers.get("content-type", "").startswith("application/json"):
            await resp.aread()
            await resp.aclose()
            raise DsmError(100, message_for(api, 100), api=api)
        return resp

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
        # POST so credentials travel in the form body, never in the URL/query
        # string (which DSM and any reverse proxy in front of it would log).
        data = await self._send(url, params, api="SYNO.API.Auth", method="POST")
        sid = data.get("sid")
        if not sid:
            raise DsmError(100, "로그인 응답에 세션 정보가 없습니다.", api="SYNO.API.Auth")
        return LoginResult(sid=sid, account=account, raw=data)

    async def logout(self, sid: str) -> None:
        # Logout is best-effort: an unreachable NAS or already-dead sid must not
        # block the app-side logout, so every DsmError (including the endpoint
        # probe) is swallowed here.
        try:
            endpoint = await self._endpoint("SYNO.API.Auth")
            params = {
                "api": "SYNO.API.Auth",
                "version": str(endpoint.pick_version(7)),
                "method": "logout",
                "session": "FileStation",
                "_sid": sid,
            }
            url = f"{self._base}/{endpoint.path}"
            await self._send(url, params, api="SYNO.API.Auth")
        except DsmError:
            pass

    # --------------------------------------------------------------- transport
    async def _send(
        self, url: str, params: dict[str, Any], *, api: str, method: str = "GET"
    ) -> Any:
        """Perform the HTTP request and unwrap DSM's success/error envelope.

        ``GET`` puts parameters in the query string (fine for reads); ``POST``
        sends them as a form body so sensitive values (e.g. login credentials)
        never appear in URLs, access logs, or proxy logs.
        """
        try:
            if method == "POST":
                resp = await self._http.post(url, data=params)
            else:
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
