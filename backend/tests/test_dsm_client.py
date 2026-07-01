"""Unit tests for the DSM Web API client transport, using httpx MockTransport."""

import httpx
import pytest

from app.dsm.client import DsmClient
from app.dsm.errors import DsmError

BASE = "http://nas.test:5000/webapi"


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": data})


def _err(code: int) -> httpx.Response:
    return httpx.Response(200, json={"success": False, "error": {"code": code}})


def make_client(handler) -> tuple[DsmClient, httpx.AsyncClient]:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return DsmClient(BASE, http), http


def _info_payload(**apis) -> dict:
    return {name: {"path": path, "minVersion": 1, "maxVersion": mv} for name, (path, mv) in apis.items()}


async def test_query_api_info_parses_and_caches():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _ok(_info_payload(**{"SYNO.API.Auth": ("auth.cgi", 7)}))

    client, http = make_client(handler)
    try:
        resolved = await client.query_api_info(("SYNO.API.Auth",))
        assert resolved["SYNO.API.Auth"].path == "auth.cgi"
        assert resolved["SYNO.API.Auth"].max_version == 7
        # Second call is served from cache — no new HTTP request.
        await client.query_api_info(("SYNO.API.Auth",))
        assert calls["n"] == 1
    finally:
        await http.aclose()


async def test_login_uses_post_and_keeps_password_out_of_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("query.cgi"):
            return _ok(_info_payload(**{"SYNO.API.Auth": ("auth.cgi", 7)}))
        # The login call itself.
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return _ok({"sid": "SID-XYZ", "account": "alice"})

    client, http = make_client(handler)
    try:
        result = await client.login("alice", "s3cret")
        assert result.sid == "SID-XYZ"
        assert seen["method"] == "POST"
        # Password must never appear in the URL/query string.
        assert "s3cret" not in seen["url"]
        assert "s3cret" in seen["body"]
    finally:
        await http.aclose()


async def test_error_envelope_raises_dsm_error_with_code():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("query.cgi"):
            return _ok(_info_payload(**{"SYNO.API.Auth": ("auth.cgi", 7)}))
        return _err(400)

    client, http = make_client(handler)
    try:
        with pytest.raises(DsmError) as excinfo:
            await client.login("alice", "wrong")
        assert excinfo.value.code == 400
    finally:
        await http.aclose()


async def test_transport_failure_becomes_dsm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client, http = make_client(handler)
    try:
        with pytest.raises(DsmError):
            await client.query_api_info(("SYNO.API.Auth",))
    finally:
        await http.aclose()


async def test_non_json_response_raises_dsm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    client, http = make_client(handler)
    try:
        with pytest.raises(DsmError):
            await client.query_api_info(("SYNO.API.Auth",))
    finally:
        await http.aclose()


async def test_call_get_puts_params_in_query():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("query.cgi"):
            return _ok(_info_payload(**{"SYNO.FileStation.Info": ("entry.cgi", 2)}))
        seen["method"] = request.method
        seen["query"] = str(request.url.query)
        return _ok({"is_manager": True})

    client, http = make_client(handler)
    try:
        data = await client.call("SYNO.FileStation.Info", "get", sid="SID1")
        assert data["is_manager"] is True
        assert seen["method"] == "GET"
        assert "_sid=SID1" in seen["query"]
    finally:
        await http.aclose()
