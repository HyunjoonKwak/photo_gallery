"""API tests for the photo routes, exercised end-to-end in mock mode."""

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


def test_fill_thumbhashes_runs_off_event_loop(monkeypatch):
    from app.api import photos as photos_api

    caller_thread = threading.get_ident()
    worker_threads: list[int] = []
    items = []

    def fake_fill(_sqlite_path, source_items):
        worker_threads.append(threading.get_ident())
        return source_items

    monkeypatch.setattr(photos_api, "fill_thumbhashes", fake_fill)

    result = asyncio.run(photos_api._fill_thumbhashes_off_loop("unused.db", items))

    assert result is items
    assert worker_threads
    assert worker_threads[0] != caller_thread


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


def test_thumbnail_cache_scope_is_bound_to_session(client):
    login = client.post(
        "/api/auth/login", json={"account": "mom", "passwd": "x"}
    ).json()
    valid = login["thumbnail_cache_scope"]
    assert len(valid) >= 16 and "mom" not in valid
    day = client.get("/api/photos/buckets?space=personal").json()["buckets"][0]["day"]
    item = client.get(
        "/api/photos/items", params={"space": "personal", "day": day}
    ).json()["items"][0]

    ok = client.get(
        "/api/photos/thumbnail",
        params={"space": "personal", "id": item["id"], "size": "sm", "u": valid},
    )
    assert ok.status_code == 200
    denied = client.get(
        "/api/photos/thumbnail",
        params={"space": "personal", "id": item["id"], "size": "sm", "u": "other"},
    )
    assert denied.status_code == 403


def test_missing_thumbnail_returns_404_not_502(logged_in, monkeypatch):
    """Synology가 생성하지 않은 썸네일(DSM 404)은 502가 아니라 깔끔한 404여야
    프론트 <img> onError가 조용히 폴백한다 (2026-07-04 실 NAS: 개인 동영상 38%)."""
    from app.dsm.errors import DsmError
    from app.photos.mock import mock_source

    async def boom(space, item_id, cache_key, size):
        raise DsmError(100, "NAS 응답 오류 (HTTP 404)", http_status=404)

    monkeypatch.setattr(mock_source, "thumbnail", boom)
    resp = logged_in.get(
        "/api/photos/thumbnail",
        params={"space": "personal", "id": "x", "size": "sm"},
    )
    assert resp.status_code == 404


def test_thumbnail_transport_error_still_502(logged_in, monkeypatch):
    """404가 아닌 실제 연결 실패는 계속 502 (폴백으로 감추면 안 되는 오류)."""
    from app.dsm.errors import DsmError
    from app.photos.mock import mock_source

    async def boom(space, item_id, cache_key, size):
        raise DsmError(100, "NAS에 연결할 수 없습니다: ConnectError")

    monkeypatch.setattr(mock_source, "thumbnail", boom)
    resp = logged_in.get(
        "/api/photos/thumbnail",
        params={"space": "personal", "id": "x", "size": "sm"},
    )
    assert resp.status_code == 502


def test_folders_listed(logged_in):
    resp = logged_in.get("/api/photos/folders")
    assert resp.status_code == 200
    folders = resp.json()["folders"]
    assert any(f["space"] == "team" for f in folders)
    assert any(f["space"] == "personal" for f in folders)


def test_folder_counts_include_subfolder_photos(logged_in):
    # f-demo-1은 직계 자식이 폴더(f-demo-1-a/b)뿐 — 배지가 0장으로 나오던
    # 회귀(2026-08-13) 방지: 하위 폴더 사진까지 합산돼야 한다.
    resp = logged_in.get(
        "/api/photos/folder-counts?ids=f-demo-1,f-demo-1-a,f-demo-1-b"
    )
    assert resp.status_code == 200
    counts = resp.json()["counts"]
    assert counts["f-demo-1-a"] > 0 and counts["f-demo-1-b"] > 0
    assert counts["f-demo-1"] == counts["f-demo-1-a"] + counts["f-demo-1-b"]


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


def test_videos_returns_only_videos_newest_first(logged_in):
    items = logged_in.get("/api/photos/videos?space=team").json()["items"]
    assert items, "mock에는 비디오가 있어야 한다"
    assert all(i["type"] == "video" for i in items)
    # 최신순 정렬.
    taken = [i["taken_at"] for i in items]
    assert taken == sorted(taken, reverse=True)


def test_albums_crud_lifecycle(logged_in):
    # 목록: mock은 데모 앨범 1개를 시드한다.
    albums = logged_in.get("/api/photos/albums").json()["albums"]
    assert albums, "mock에는 데모 앨범이 있어야 한다"
    demo = albums[0]
    assert demo["cover_item_id"] and demo["item_count"] > 0

    # 열람: 앨범 아이템 수가 item_count와 일치.
    items = logged_in.get(f"/api/photos/album-items?id={demo['id']}").json()["items"]
    assert len(items) == demo["item_count"]
    some_ids = [i["id"] for i in items[:3]]

    # 생성(사진과 함께).
    created = logged_in.post(
        "/api/photos/albums", json={"name": "새 앨범", "item_ids": some_ids}
    ).json()["album"]
    assert created["name"] == "새 앨범" and created["item_count"] == len(some_ids)
    new_id = created["id"]

    # 목록 맨 위에 새 앨범(최근 생성순).
    assert logged_in.get("/api/photos/albums").json()["albums"][0]["id"] == new_id

    # 추가(중복 무시): 이미 담긴 3장 + 새 2장 → 2장만 추가.
    more = [i["id"] for i in items[2:5]]  # 1장 겹침
    added = logged_in.post(
        "/api/photos/albums/add", json={"album_id": new_id, "item_ids": more}
    ).json()["added"]
    assert added == len(set(more) - set(some_ids))

    # 삭제 → 목록에서 사라짐.
    assert logged_in.delete(f"/api/photos/albums/{new_id}").status_code == 200
    ids = [a["id"] for a in logged_in.get("/api/photos/albums").json()["albums"]]
    assert new_id not in ids

    # 없는 앨범 열람 → 404.
    assert logged_in.get("/api/photos/album-items?id=nope").status_code == 404


def test_albums_require_login(client):
    assert client.get("/api/photos/albums").status_code == 401
    assert client.post("/api/photos/albums", json={"name": "x"}).status_code == 401


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
