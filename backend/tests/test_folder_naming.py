"""폴더 이름 정리 — 규칙 유틸 단위 + audit/rename e2e(mock)."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.photos.folder_naming import fix_date_prefix
from app.photos.mock import mock_source


def test_fix_date_prefix_rule():
    assert fix_date_prefix("2016_06_06 상윤 첫 자전거") == "2016-06-06 상윤 첫 자전거"
    # 날짜부 밑줄만 — 이벤트명 밑줄은 유지
    assert fix_date_prefix("2016_06_06 상윤_자전거") == "2016-06-06 상윤_자전거"
    # 이미 하이픈이면 교정 없음
    assert fix_date_prefix("2016-06-06 여행") is None
    # 날짜 형태 아님
    assert fix_date_prefix("가족앨범") is None
    assert fix_date_prefix("2016_6_6 여행") is None  # 자리수 안 맞음


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "app.db"))
    get_settings.cache_clear()
    mock_source.reset()
    from app.main import create_app

    with TestClient(create_app()) as c:
        c.post("/api/auth/login", json={"account": "tester", "passwd": "x"})
        yield c
    mock_source.reset()
    get_settings.cache_clear()


def test_audit_and_rename_lifecycle(client):
    # 밑줄 날짜 폴더 생성 → audit가 잡아냄 → rename으로 교정 → 다시 audit 없음.
    client.post("/api/photos/folders", json={"space": "team", "name": "2019_08_15 여행"})

    audit = client.get("/api/photos/folder-name-audit").json()["items"]
    hit = next((i for i in audit if i["current_name"] == "2019_08_15 여행"), None)
    assert hit is not None
    assert hit["proposed_name"] == "2019-08-15 여행"

    r = client.post(
        "/api/photos/folders/rename",
        json={"folder_id": hit["id"], "new_name": hit["proposed_name"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "2019-08-15 여행"

    audit2 = client.get("/api/photos/folder-name-audit").json()["items"]
    assert all(i["current_name"] != "2019_08_15 여행" for i in audit2)


def test_audit_requires_login(client):
    client.post("/api/auth/logout")
    assert client.get("/api/photos/folder-name-audit").status_code == 401
