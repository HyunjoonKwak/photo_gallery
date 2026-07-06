"""1차 구역(zone) API + zone 소스 흐름 테스트 (mock 모드)."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.photos.mock import mock_source, reset_mock_zones


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "app.db"))
    get_settings.cache_clear()
    mock_source.reset()
    reset_mock_zones()
    from app.main import create_app

    with TestClient(create_app()) as c:
        c.post("/api/auth/login", json={"account": "tester", "passwd": "x"})
        yield c
    mock_source.reset()
    reset_mock_zones()
    get_settings.cache_clear()


def _register_backup(client, label="기기 백업"):
    return client.post(
        "/api/zones",
        json={"root_path": "/homes/tester/MobileBackup", "label": label},
    )


def test_zone_crud(client):
    assert client.get("/api/zones").json()["zones"] == []
    resp = _register_backup(client)
    assert resp.status_code == 200
    zone = resp.json()
    assert zone["root_path"] == "/homes/tester/MobileBackup"
    assert zone["label"] == "기기 백업"

    zones = client.get("/api/zones").json()["zones"]
    assert [z["id"] for z in zones] == [zone["id"]]

    assert client.delete(f"/api/zones/{zone['id']}").status_code == 200
    assert client.get("/api/zones").json()["zones"] == []
    # 이미 없는 zone 삭제 → 404
    assert client.delete(f"/api/zones/{zone['id']}").status_code == 404


def test_zone_path_validation(client):
    # 남의 홈 → 거부
    r = client.post("/api/zones", json={"root_path": "/homes/otheruser/x", "label": "x"})
    assert r.status_code == 422
    # 시스템 경로 → 거부
    r = client.post("/api/zones", json={"root_path": "/etc", "label": "x"})
    assert r.status_code == 422
    # 트래버설 → 거부
    r = client.post(
        "/api/zones", json={"root_path": "/homes/tester/../otheruser", "label": "x"}
    )
    assert r.status_code == 422
    # 공용(/photo) 하위는 허용
    r = client.post("/api/zones", json={"root_path": "/photo/백업", "label": "공용백업"})
    assert r.status_code == 200


def test_zone_browse(client):
    # 기본(내 홈) → mock 트리의 MobileBackup/Drive
    root = client.get("/api/zones/browse").json()
    assert root["parent"] is None
    names = {d["name"] for d in root["dirs"]}
    assert {"MobileBackup", "Drive"} <= names
    # 파고들기
    sub = client.get(
        "/api/zones/browse", params={"path": "/homes/tester/MobileBackup"}
    ).json()
    assert sub["parent"] == "/homes/tester"
    assert {d["name"] for d in sub["dirs"]} == {"2024-01", "2024-02", "2024-03"}
    # 남의 홈 탐색 거부
    assert (
        client.get("/api/zones/browse", params={"path": "/homes/other"}).status_code
        == 422
    )


def test_zone_folders_and_items(client):
    zone_id = _register_backup(client).json()["id"]
    # zone 루트 하위 = 월 폴더들 (개인/공용 Foto 폴더 안 섞임)
    folders = client.get(f"/api/photos/folders?zone={zone_id}").json()["folders"]
    # zone 루트(=/homes/tester/MobileBackup) 기준 상대경로 이름.
    assert {f["name"].strip("/") for f in folders} == {"2024-01", "2024-02", "2024-03"}
    # 리프 폴더의 사진(경로형 id)
    leaf = "/homes/tester/MobileBackup/2024-01"
    items = client.get(
        f"/api/photos/folder-items?zone={zone_id}&folder_id={leaf}"
    ).json()["items"]
    assert len(items) >= 1
    assert all(i["id"].startswith(leaf) for i in items)


def test_zone_and_target_user_conflict(client):
    zone_id = _register_backup(client).json()["id"]
    resp = client.get(
        f"/api/photos/folders?zone={zone_id}&target_user=someone"
    )
    assert resp.status_code == 422


def test_unknown_zone_404(client):
    assert client.get("/api/photos/folders?zone=deadbeef").status_code == 404


def test_zone_move_to_personal_and_undo(client):
    """zone 사진을 2차로 이동 → zone 목록에서 사라짐 + undo로 복원."""
    zone_id = _register_backup(client).json()["id"]
    leaf = "/homes/tester/MobileBackup/2024-01"
    items = client.get(
        f"/api/photos/folder-items?zone={zone_id}&folder_id={leaf}"
    ).json()["items"]
    before = len(items)
    move_id = items[0]["id"]

    # 개인 폴더(mock f-personal-1)로 이동 — execute_move 경유.
    op = client.post(
        f"/api/photos/ops/move?zone={zone_id}",
        json={
            "space": "personal",
            "item_ids": [move_id],
            "dest_folder_id": "f-personal-1",
            "copy_mode": False,
        },
    )
    assert op.status_code == 200
    body = op.json()
    assert body["undoable"] is True

    after = client.get(
        f"/api/photos/folder-items?zone={zone_id}&folder_id={leaf}"
    ).json()["items"]
    assert len(after) == before - 1
    assert move_id not in {i["id"] for i in after}

    # undo → zone에 복원 (undo도 zone 컨텍스트에서 — 프론트는 scopeQS로 부착)
    assert (
        client.post(
            f"/api/ops/{body['operation_id']}/undo?zone={zone_id}"
        ).status_code
        == 200
    )
    restored = client.get(
        f"/api/photos/folder-items?zone={zone_id}&folder_id={leaf}"
    ).json()["items"]
    assert len(restored) == before
    assert move_id in {i["id"] for i in restored}
