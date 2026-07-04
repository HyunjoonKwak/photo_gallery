"""End-to-end tests for file operations + undo, in mock mode."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.photos.mock import mock_source


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


def _first_day_items(client, space="team"):
    buckets = client.get(f"/api/photos/buckets?space={space}").json()["buckets"]
    day = buckets[0]["day"]
    items = client.get(f"/api/photos/items?space={space}&day={day}").json()["items"]
    return day, items


def test_move_assigns_folder_and_logs_operation(client):
    day, items = _first_day_items(client)
    ids = [items[0]["id"], items[1]["id"]] if len(items) > 1 else [items[0]["id"]]

    resp = client.post(
        "/api/photos/ops/move",
        json={"item_ids": ids, "dest_folder_id": "f-team-1", "copy_mode": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "가족앨범" in body["summary"]
    assert body["undoable"] is True
    assert {"space": "team", "day": day} in body["affected"]

    # Item now carries the folder name in the timeline...
    after = client.get(f"/api/photos/items?space=team&day={day}").json()["items"]
    moved = [i for i in after if i["id"] in ids]
    assert all(i["folder"] == "가족앨범" for i in moved)
    # ...and shows up in the folder view.
    folder_items = client.get(
        "/api/photos/folder-items", params={"folder_id": "f-team-1"}
    ).json()["items"]
    assert {i["id"] for i in folder_items} >= set(ids)


def test_undo_move_restores_prior_location(client):
    day, items = _first_day_items(client)
    item_id = items[0]["id"]
    op = client.post(
        "/api/photos/ops/move",
        json={"item_ids": [item_id], "dest_folder_id": "f-team-2", "copy_mode": False},
    ).json()

    undo = client.post(f"/api/ops/{op['operation_id']}/undo")
    assert undo.status_code == 200
    after = client.get(f"/api/photos/items?space=team&day={day}").json()["items"]
    restored = next(i for i in after if i["id"] == item_id)
    assert restored["folder"] is None
    # Second undo is rejected.
    assert client.post(f"/api/ops/{op['operation_id']}/undo").status_code == 409


def test_cross_space_move_switches_timelines(client):
    day, items = _first_day_items(client, space="personal")
    item_id = items[0]["id"]
    client.post(
        "/api/photos/ops/move",
        json={"item_ids": [item_id], "dest_folder_id": "f-team-1", "copy_mode": False},
    )
    personal_after = client.get(
        f"/api/photos/items?space=personal&day={day}"
    ).json()["items"]
    team_after = client.get(f"/api/photos/items?space=team&day={day}").json()["items"]
    assert item_id not in {i["id"] for i in personal_after}
    assert item_id in {i["id"] for i in team_after}
    # Bucket counts reflect the overlay on both sides.
    p_bucket = [
        b
        for b in client.get("/api/photos/buckets?space=personal").json()["buckets"]
        if b["day"] == day
    ]
    assert not p_bucket or p_bucket[0]["count"] == len(personal_after)


def test_copy_creates_new_item_and_undo_removes_it(client):
    day, items = _first_day_items(client)
    item_id = items[0]["id"]
    before_count = len(items)

    op = client.post(
        "/api/photos/ops/move",
        json={"item_ids": [item_id], "dest_folder_id": "f-team-1", "copy_mode": True},
    ).json()
    after = client.get(f"/api/photos/items?space=team&day={day}").json()["items"]
    assert len(after) == before_count + 1
    copy_ids = {i["id"] for i in after} - {i["id"] for i in items}
    assert all(cid.startswith(item_id) for cid in copy_ids)

    client.post(f"/api/ops/{op['operation_id']}/undo")
    restored = client.get(f"/api/photos/items?space=team&day={day}").json()["items"]
    assert len(restored) == before_count


def test_delete_and_restore(client):
    day, items = _first_day_items(client)
    ids = [items[0]["id"]]
    op = client.post("/api/photos/ops/delete", json={"item_ids": ids}).json()
    assert "휴지통" in op["summary"]

    after = client.get(f"/api/photos/items?space=team&day={day}").json()["items"]
    assert ids[0] not in {i["id"] for i in after}

    client.post(f"/api/ops/{op['operation_id']}/undo")
    restored = client.get(f"/api/photos/items?space=team&day={day}").json()["items"]
    assert ids[0] in {i["id"] for i in restored}


def test_deleted_item_cannot_be_moved(client):
    _, items = _first_day_items(client)
    item_id = items[0]["id"]
    client.post("/api/photos/ops/delete", json={"item_ids": [item_id]})
    resp = client.post(
        "/api/photos/ops/move",
        json={"item_ids": [item_id], "dest_folder_id": "f-team-1", "copy_mode": False},
    )
    assert resp.status_code == 409


def test_create_folder_and_undo(client):
    op = client.post(
        "/api/photos/folders", json={"space": "team", "name": "테스트폴더"}
    ).json()
    assert op["folder"]["name"] == "테스트폴더"
    folders = client.get("/api/photos/folders").json()["folders"]
    assert any(f["name"] == "테스트폴더" for f in folders)

    client.post(f"/api/ops/{op['operation_id']}/undo")
    folders = client.get("/api/photos/folders").json()["folders"]
    assert not any(f["name"] == "테스트폴더" for f in folders)


def _folder_names(client):
    return {f["name"] for f in client.get("/api/photos/folders").json()["folders"]}


def test_move_folders_and_undo(client):
    op = client.post(
        "/api/photos/ops/move-folders",
        json={
            "space": "team",
            "folder_ids": ["f-team-2"],
            "dest_folder_id": "f-team-1",
            "copy_mode": False,
        },
    ).json()
    assert op["summary"] == "'행사' 폴더를 이동"
    assert op["undoable"] is True
    assert "가족앨범/행사" in _folder_names(client)
    assert "행사" not in _folder_names(client)

    assert client.post(f"/api/ops/{op['operation_id']}/undo").status_code == 200
    assert "행사" in _folder_names(client)
    assert "가족앨범/행사" not in _folder_names(client)


def test_copy_folders_and_undo(client):
    op = client.post(
        "/api/photos/ops/move-folders",
        json={
            "space": "team",
            "folder_ids": ["f-team-2", "f-team-3"],
            "dest_folder_id": "f-team-1",
            "copy_mode": True,
        },
    ).json()
    assert op["summary"] == "'행사' 외 1개 폴더를 복사"
    names = _folder_names(client)
    # Originals stay, copies appear under the destination.
    assert {"행사", "인화용", "가족앨범/행사", "가족앨범/인화용"} <= names

    assert client.post(f"/api/ops/{op['operation_id']}/undo").status_code == 200
    names = _folder_names(client)
    assert "행사" in names and "가족앨범/행사" not in names


def test_move_folders_all_noop_returns_conflict(tmp_path):
    """DSM source skips folders already inside the destination — if ALL were
    skipped there is nothing to record; the API must 409, not crash."""
    import asyncio

    from fastapi import HTTPException

    from app.operations import execute_move_folders
    from app.schemas import MoveFoldersRequest

    class _NoopSource:
        async def move_folders(self, *args, **kwargs):
            return {"names": [], "undo": []}

    req = MoveFoldersRequest(
        space="team", folder_ids=["f-1"], dest_folder_id="f-2", copy_mode=False
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            execute_move_folders(
                _NoopSource(), str(tmp_path / "op.db"), user="tester", req=req
            )
        )
    assert exc.value.status_code == 409


def test_move_folder_into_itself_is_rejected(client):
    resp = client.post(
        "/api/photos/ops/move-folders",
        json={
            "space": "team",
            "folder_ids": ["f-team-1"],
            "dest_folder_id": "f-team-1",
            "copy_mode": False,
        },
    )
    assert resp.status_code == 409


def test_mkdir_undo_fails_when_folder_not_empty(client):
    _, items = _first_day_items(client)
    op = client.post(
        "/api/photos/folders", json={"space": "team", "name": "채워질폴더"}
    ).json()
    client.post(
        "/api/photos/ops/move",
        json={
            "item_ids": [items[0]["id"]],
            "dest_folder_id": op["folder"]["id"],
            "copy_mode": False,
        },
    )
    assert client.post(f"/api/ops/{op['operation_id']}/undo").status_code == 409


def test_operations_list_reflects_status(client):
    _, items = _first_day_items(client)
    op = client.post(
        "/api/photos/ops/delete", json={"item_ids": [items[0]["id"]]}
    ).json()
    ops = client.get("/api/ops").json()["operations"]
    entry = next(o for o in ops if o["id"] == op["operation_id"])
    assert entry["can_undo"] is True and entry["status"] == "done"

    client.post(f"/api/ops/{op['operation_id']}/undo")
    ops = client.get("/api/ops").json()["operations"]
    entry = next(o for o in ops if o["id"] == op["operation_id"])
    assert entry["can_undo"] is False and entry["status"] == "undone"


def test_member_cannot_target_other_user(client):
    _, items = _first_day_items(client)
    resp = client.post(
        "/api/photos/ops/delete",
        json={"item_ids": [items[0]["id"]], "target_user": "mom"},
    )
    assert resp.status_code == 403  # "tester" is a member, not admin


def test_admin_can_target_other_user_and_it_is_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "admin.db"))
    get_settings.cache_clear()
    mock_source.reset()
    from app.main import create_app

    with TestClient(create_app()) as c:
        c.post("/api/auth/login", json={"account": "admin", "passwd": "x"})
        buckets = c.get("/api/photos/buckets?space=personal").json()["buckets"]
        items = c.get(
            f"/api/photos/items?space=personal&day={buckets[0]['day']}"
        ).json()["items"]
        resp = c.post(
            "/api/photos/ops/delete",
            json={"item_ids": [items[0]["id"]], "target_user": "mom"},
        )
        assert resp.status_code == 200
        ops = c.get("/api/ops").json()["operations"]
        assert ops[0]["target_user"] == "mom"

        # Members list is admin-only.
        assert c.get("/api/photos/members").status_code == 200
    mock_source.reset()
    get_settings.cache_clear()


def test_members_endpoint_forbidden_for_member(client):
    assert client.get("/api/photos/members").status_code == 403


# ------------------------------------------------------------ trash (B-6)


def test_trash_stats_and_member_cannot_empty(client):
    _, items = _first_day_items(client)
    ids = [items[0]["id"], items[1]["id"]]
    client.post("/api/photos/ops/delete", json={"item_ids": ids})

    stats = client.get("/api/ops/trash").json()
    assert stats == {"operations": 1, "items": 2}

    # Emptying the shared trash kills everyone's delete undos — admin only.
    assert client.post("/api/ops/trash/empty").status_code == 403


def test_empty_trash_purges_and_blocks_undo(client):
    client.post("/api/auth/login", json={"account": "admin", "passwd": "x"})
    _, items = _first_day_items(client)
    op = client.post(
        "/api/photos/ops/delete", json={"item_ids": [items[0]["id"]]}
    ).json()

    resp = client.post("/api/ops/trash/empty")
    assert resp.status_code == 200
    assert "영구 삭제" in resp.json()["summary"]
    assert resp.json()["undoable"] is False

    # Trash is empty and the purged delete can no longer be undone.
    assert client.get("/api/ops/trash").json() == {"operations": 0, "items": 0}
    assert client.post(f"/api/ops/{op['operation_id']}/undo").status_code == 409

    ops = client.get("/api/ops").json()["operations"]
    assert ops[0]["type"] == "empty_trash" and ops[0]["can_undo"] is False
    purged = next(o for o in ops if o["id"] == op["operation_id"])
    assert purged["status"] == "purged"


def test_progress_endpoint_reports_and_clears(client):
    _, items = _first_day_items(client)
    # Unknown key → inactive.
    assert client.get("/api/ops/progress?key=nope").json()["active"] is False
    # After an op with a progress_key completes, the key is cleared.
    client.post(
        "/api/photos/ops/delete",
        json={"item_ids": [items[0]["id"]], "progress_key": "k1"},
    )
    assert client.get("/api/ops/progress?key=k1").json()["active"] is False
