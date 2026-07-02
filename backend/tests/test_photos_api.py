"""API tests for the photo routes, exercised end-to-end in mock mode."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "app.db"))
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture()
def logged_in(client):
    resp = client.post(
        "/api/auth/login", json={"account": "tester", "passwd": "any"}
    )
    assert resp.status_code == 200
    return client


def test_mock_login_accepts_any_credentials(client):
    resp = client.post("/api/auth/login", json={"account": "mom", "passwd": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["account"] == "mom"
    assert body["role"] == "member"
    assert body["mock_mode"] is True


def test_mock_admin_account_gets_admin_role(client):
    resp = client.post("/api/auth/login", json={"account": "admin", "passwd": "x"})
    body = resp.json()
    assert body["role"] == "admin"
    assert body["can_browse_homes"] is True


def test_photos_require_login(client):
    assert client.get("/api/photos/buckets").status_code == 401


def test_buckets_and_items_roundtrip(logged_in):
    resp = logged_in.get("/api/photos/buckets", params={"space": "team"})
    assert resp.status_code == 200
    buckets = resp.json()["buckets"]
    assert len(buckets) > 0

    first = buckets[0]
    resp = logged_in.get(
        "/api/photos/items", params={"space": "team", "day": first["day"]}
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == first["count"]


def test_items_rejects_bad_day_format(logged_in):
    resp = logged_in.get(
        "/api/photos/items", params={"space": "team", "day": "junk"}
    )
    assert resp.status_code == 422


def test_invalid_space_rejected(logged_in):
    resp = logged_in.get("/api/photos/buckets", params={"space": "everything"})
    assert resp.status_code == 422


def test_thumbnail_serves_svg(logged_in):
    buckets = logged_in.get(
        "/api/photos/buckets", params={"space": "personal"}
    ).json()["buckets"]
    items = logged_in.get(
        "/api/photos/items", params={"space": "personal", "day": buckets[0]["day"]}
    ).json()["items"]
    resp = logged_in.get(
        "/api/photos/thumbnail",
        params={"space": "personal", "id": items[0]["id"], "size": "sm"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "max-age" in resp.headers.get("cache-control", "")


def test_folders_listed(logged_in):
    resp = logged_in.get("/api/photos/folders")
    assert resp.status_code == 200
    folders = resp.json()["folders"]
    assert any(f["space"] == "team" for f in folders)
    assert any(f["space"] == "personal" for f in folders)


def test_system_info_mocked(logged_in):
    resp = logged_in.get("/api/system/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dsm_webapi_base"] == "(mock)"
    assert all(e["available"] for e in body["endpoints"])


def test_logout_works_without_nas(logged_in):
    assert logged_in.post("/api/auth/logout").status_code == 204
