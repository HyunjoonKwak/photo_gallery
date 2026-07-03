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


# --------------------------------------------- AI classification (3단계)


def test_persons_and_person_items(logged_in):
    persons = logged_in.get("/api/photos/persons?space=team").json()["persons"]
    assert persons, "mock에는 항상 인물 그룹이 있어야 한다"
    # Sorted biggest-first, cover thumbnail present, unnamed group included.
    counts = [p["item_count"] for p in persons]
    assert counts == sorted(counts, reverse=True)
    assert persons[0]["cover_item_id"]
    assert any(p["name"] == "" for p in persons)

    items = logged_in.get(
        f"/api/photos/person-items?space=team&id={persons[0]['id']}"
    ).json()["items"]
    assert len(items) == persons[0]["item_count"]

    # Unknown person → 404.
    assert logged_in.get("/api/photos/person-items?space=team&id=nope").status_code == 404


def test_places_and_place_items(logged_in):
    places = logged_in.get("/api/photos/places?space=team").json()["places"]
    assert places
    items = logged_in.get(
        f"/api/photos/place-items?space=team&id={places[0]['id']}"
    ).json()["items"]
    assert len(items) == places[0]["item_count"]


# ------------------------------------------- admin impersonation (spec 4.5)


def test_member_cannot_read_another_users_photos(logged_in):
    # target_user on a READ endpoint requires admin.
    resp = logged_in.get("/api/photos/folders?target_user=mom")
    assert resp.status_code == 403


def test_admin_can_read_with_target_user(client):
    client.post("/api/auth/login", json={"account": "admin", "passwd": "x"})
    resp = client.get("/api/photos/folders?target_user=mom")
    assert resp.status_code == 200


def test_target_user_self_is_allowed_for_member(logged_in):
    # Passing your own account is not impersonation.
    resp = logged_in.get("/api/photos/folders?target_user=tester")
    assert resp.status_code == 200
