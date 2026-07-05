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


def _folder_filenames(client, folder_id):
    items = client.get(
        "/api/photos/folder-items", params={"folder_id": folder_id}
    ).json()["items"]
    return [i["filename"] for i in items]


def _seed_conflict(client):
    """가족앨범(f-team-1)에 사진 1장을 넣고, 같은 파일명이 다시 들어오도록
    그 사진의 복사본을 대상으로 준비한다. (원본, 대상폴더에_이미있는_파일명)"""
    _, items = _first_day_items(client)
    original = items[0]["id"]
    client.post(
        "/api/photos/ops/move",
        json={"item_ids": [original], "dest_folder_id": "f-team-1", "copy_mode": False},
    )
    fname = _folder_filenames(client, "f-team-1")[0]
    # 복사본은 원본과 같은 파일명 → f-team-1에 다시 넣으면 충돌.
    op = client.post(
        "/api/photos/ops/move",
        json={"item_ids": [original], "dest_folder_id": "f-team-2", "copy_mode": True},
    ).json()
    # op 응답엔 새 id가 없으니 f-team-2에서 복사본 id를 찾는다.
    copy_id = client.get(
        "/api/photos/folder-items", params={"folder_id": "f-team-2"}
    ).json()["items"][0]["id"]
    return copy_id, fname


def test_move_check_reports_filename_conflicts(client):
    copy_id, fname = _seed_conflict(client)
    resp = client.post(
        "/api/photos/ops/move-check",
        json={"item_ids": [copy_id], "dest_folder_id": "f-team-1"},
    )
    assert resp.status_code == 200
    conflicts = resp.json()["conflicts"]
    assert conflicts == [{"item_id": copy_id, "filename": fname}]


def test_move_default_asks_on_conflict_with_409(client):
    """전략 미지정(ask) + 충돌 → 409 + 충돌 목록. 어느 이동 경로든 조용히
    건너뛰지 않고 클라이언트가 다이얼로그를 띄우게 한다 (2026-07-05 보고)."""
    copy_id, fname = _seed_conflict(client)
    resp = client.post(
        "/api/photos/ops/move",
        json={"item_ids": [copy_id], "dest_folder_id": "f-team-1", "copy_mode": True},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "filename_conflict"
    assert detail["conflicts"] == [{"item_id": copy_id, "filename": fname}]


def test_move_default_no_conflict_proceeds(client):
    _, items = _first_day_items(client)
    resp = client.post(
        "/api/photos/ops/move",
        json={"item_ids": [items[0]["id"]], "dest_folder_id": "f-team-3"},
    )
    assert resp.status_code == 200  # 충돌 없으면 ask라도 그대로 진행


def test_move_skip_leaves_conflicting_item(client):
    copy_id, _ = _seed_conflict(client)
    before = len(_folder_filenames(client, "f-team-1"))
    client.post(
        "/api/photos/ops/move",
        json={
            "item_ids": [copy_id],
            "dest_folder_id": "f-team-1",
            "copy_mode": True,
            "conflict_strategy": "skip",
        },
    )
    # skip: 대상 폴더 파일 수 그대로.
    assert len(_folder_filenames(client, "f-team-1")) == before


def test_move_rename_keeps_both_with_suffix(client):
    copy_id, fname = _seed_conflict(client)
    base, ext = fname.rsplit(".", 1)
    client.post(
        "/api/photos/ops/move",
        json={
            "item_ids": [copy_id],
            "dest_folder_id": "f-team-1",
            "copy_mode": True,
            "conflict_strategy": "rename",
        },
    )
    names = _folder_filenames(client, "f-team-1")
    assert fname in names and f"{base}_1.{ext}" in names


def test_move_overwrite_replaces_and_keeps_one(client):
    copy_id, fname = _seed_conflict(client)
    before = len(_folder_filenames(client, "f-team-1"))
    client.post(
        "/api/photos/ops/move",
        json={
            "item_ids": [copy_id],
            "dest_folder_id": "f-team-1",
            "copy_mode": True,
            "conflict_strategy": "overwrite",
        },
    )
    names = _folder_filenames(client, "f-team-1")
    # overwrite: 기존 동명 파일이 교체돼 파일 수는 그대로, 이름은 1개만.
    assert len(names) == before
    assert names.count(fname) == 1


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
        async def folder_conflicts(self, *args, **kwargs):
            return []  # no name clashes → proceed to move (which no-ops)

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


def test_move_folders_default_asks_on_name_conflict(client):
    """대상에 같은 이름 폴더가 있으면 ask(기본)는 409+목록 → 조용히 건너뛰지
    않는다 (2026-07-05 보고: 폴더 이동이 아무 변화 없이 성공 보고)."""
    # 가족앨범 아래 "행사" 폴더 생성 → 최상위 "행사"를 가족앨범으로 옮기면 충돌.
    client.post(
        "/api/photos/folders",
        json={"space": "team", "name": "행사", "parent_id": "f-team-1"},
    )
    resp = client.post(
        "/api/photos/ops/move-folders",
        json={
            "space": "team",
            "folder_ids": ["f-team-2"],
            "dest_folder_id": "f-team-1",
            "copy_mode": False,
        },
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "folder_conflict"
    assert detail["conflicts"] == [{"folder_id": "f-team-2", "name": "행사"}]


def test_move_folders_rename_keeps_both(client):
    client.post(
        "/api/photos/folders",
        json={"space": "team", "name": "행사", "parent_id": "f-team-1"},
    )
    op = client.post(
        "/api/photos/ops/move-folders",
        json={
            "space": "team",
            "folder_ids": ["f-team-2"],
            "dest_folder_id": "f-team-1",
            "copy_mode": False,
            "conflict_strategy": "rename",
        },
    )
    assert op.status_code == 200
    names = {f["name"] for f in client.get("/api/photos/folders").json()["folders"]}
    assert "가족앨범/행사" in names and "가족앨범/행사_1" in names


def _folder_item_count(client, folder_id):
    return len(
        client.get(
            "/api/photos/folder-items", params={"folder_id": folder_id}
        ).json()["items"]
    )


def test_move_folders_merge_combines_photos(client):
    """merge: 소스 폴더의 사진이 대상의 동명 폴더로 합쳐지고 소스는 비워진다."""
    _, items = _first_day_items(client)
    assert len(items) >= 3
    # 행사(f-team-2)에 사진 2장.
    client.post(
        "/api/photos/ops/move",
        json={
            "item_ids": [items[0]["id"], items[1]["id"]],
            "dest_folder_id": "f-team-2",
        },
    )
    # 가족앨범 아래 "행사" 폴더(충돌 대상) 생성 + 다른 사진 1장.
    child = client.post(
        "/api/photos/folders",
        json={"space": "team", "name": "행사", "parent_id": "f-team-1"},
    ).json()["folder"]
    client.post(
        "/api/photos/ops/move",
        json={"item_ids": [items[2]["id"]], "dest_folder_id": child["id"]},
    )

    op = client.post(
        "/api/photos/ops/move-folders",
        json={
            "space": "team",
            "folder_ids": ["f-team-2"],
            "dest_folder_id": "f-team-1",
            "copy_mode": False,
            "conflict_strategy": "merge",
        },
    )
    assert op.status_code == 200
    # 병합 폴더에 기존 1장 + 옮겨온 2장, 소스는 비었다.
    assert _folder_item_count(client, child["id"]) == 3
    assert _folder_item_count(client, "f-team-2") == 0


def test_move_folders_merge_undo_restores(client):
    _, items = _first_day_items(client)
    assert len(items) >= 3
    client.post(
        "/api/photos/ops/move",
        json={
            "item_ids": [items[0]["id"], items[1]["id"]],
            "dest_folder_id": "f-team-2",
        },
    )
    child = client.post(
        "/api/photos/folders",
        json={"space": "team", "name": "행사", "parent_id": "f-team-1"},
    ).json()["folder"]
    client.post(
        "/api/photos/ops/move",
        json={"item_ids": [items[2]["id"]], "dest_folder_id": child["id"]},
    )
    op = client.post(
        "/api/photos/ops/move-folders",
        json={
            "space": "team",
            "folder_ids": ["f-team-2"],
            "dest_folder_id": "f-team-1",
            "copy_mode": False,
            "conflict_strategy": "merge",
        },
    ).json()

    assert client.post(f"/api/ops/{op['operation_id']}/undo").status_code == 200
    # 병합 되돌리기: 대상 폴더는 원래 1장, 소스는 다시 2장.
    assert _folder_item_count(client, child["id"]) == 1
    assert _folder_item_count(client, "f-team-2") == 2


def test_move_reports_emptied_source_folder(client):
    """사진을 다른 폴더로 옮겨 원본 폴더가 비면 emptied_folders로 정리 제안."""
    _, items = _first_day_items(client)
    # 폴더 밖 → f-team-1 (원본이 폴더가 아니라 정리 제안 없음).
    first = client.post(
        "/api/photos/ops/move",
        json={"item_ids": [items[0]["id"]], "dest_folder_id": "f-team-1"},
    ).json()
    assert first["emptied_folders"] == []
    # f-team-1 → f-team-2: 이제 f-team-1이 비워져 정리 제안 대상.
    second = client.post(
        "/api/photos/ops/move",
        json={"item_ids": [items[0]["id"]], "dest_folder_id": "f-team-2"},
    ).json()
    emptied = second["emptied_folders"]
    assert [e["folder_id"] for e in emptied] == ["f-team-1"]
    assert emptied[0]["name"] == "가족앨범"


def test_copy_never_reports_emptied(client):
    _, items = _first_day_items(client)
    client.post(
        "/api/photos/ops/move",
        json={"item_ids": [items[0]["id"]], "dest_folder_id": "f-team-1"},
    )
    op = client.post(
        "/api/photos/ops/move",
        json={
            "item_ids": [items[0]["id"]],
            "dest_folder_id": "f-team-2",
            "copy_mode": True,
        },
    ).json()
    assert op["emptied_folders"] == []  # 복사는 원본이 남으므로 비지 않는다


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


def test_remove_folder_empty_only_by_default(client):
    """recursive 미지정: 사진이 있으면 409(빈 폴더만)."""
    _, items = _first_day_items(client)
    folder = client.post(
        "/api/photos/folders", json={"space": "team", "name": "지울폴더"}
    ).json()["folder"]
    client.post(
        "/api/photos/ops/move",
        json={"item_ids": [items[0]["id"]], "dest_folder_id": folder["id"]},
    )
    resp = client.post(
        "/api/photos/folders/delete",
        json={"space": "team", "folder_id": folder["id"]},
    )
    assert resp.status_code == 409


def test_recursive_folder_delete_and_undo(client):
    """recursive: 사진이 있어도 통째로 휴지통 이동 + undo로 원상복구."""
    _, items = _first_day_items(client)
    folder = client.post(
        "/api/photos/folders", json={"space": "team", "name": "통째삭제"}
    ).json()["folder"]
    client.post(
        "/api/photos/ops/move",
        json={
            "item_ids": [items[0]["id"], items[1]["id"]],
            "dest_folder_id": folder["id"],
        },
    )
    assert _folder_item_count(client, folder["id"]) == 2

    op = client.post(
        "/api/photos/folders/delete",
        json={"space": "team", "folder_id": folder["id"], "recursive": True},
    )
    assert op.status_code == 200
    body = op.json()
    assert body["undoable"] is True and "휴지통" in body["summary"]
    # 폴더가 목록에서 사라지고 사진도 빠졌다.
    assert not any(
        f["id"] == folder["id"]
        for f in client.get("/api/photos/folders").json()["folders"]
    )

    # undo: 폴더와 사진이 되돌아온다.
    assert client.post(f"/api/ops/{body['operation_id']}/undo").status_code == 200
    assert any(
        f["id"] == folder["id"]
        for f in client.get("/api/photos/folders").json()["folders"]
    )
    assert _folder_item_count(client, folder["id"]) == 2


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
