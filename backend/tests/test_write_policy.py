"""Gallery → Desk transition policy and route-boundary tests."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.photos.mock import mock_source
from app.write_policy import capabilities_for


@contextmanager
def _logged_in_client(
    monkeypatch,
    tmp_path,
    mode: str,
    *,
    account: str = "admin",
    legacy_date_repair: bool = False,
):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / f"{mode}-{account}.db"))
    monkeypatch.setenv("GALLERY_WRITE_MODE", mode)
    monkeypatch.setenv(
        "GALLERY_LEGACY_DATE_REPAIR", "true" if legacy_date_repair else "false"
    )
    get_settings.cache_clear()
    mock_source.reset()
    from app.main import create_app

    try:
        with TestClient(create_app()) as client:
            login = client.post(
                "/api/auth/login", json={"account": account, "passwd": "x"}
            )
            assert login.status_code == 200
            yield client
    finally:
        mock_source.reset()
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("mode", "physical", "recovery"),
    [
        ("legacy", True, True),
        ("drain", False, True),
        ("curation", False, False),
    ],
)
def test_capabilities_by_mode(mode, physical, recovery):
    settings = Settings(gallery_write_mode=mode)
    caps = capabilities_for(settings, "member")
    assert caps.physical_mutations is physical
    assert caps.undo_drain is recovery
    assert caps.synology_curation is True
    assert caps.legacy_date_repair is False


@pytest.mark.parametrize("mode", ["legacy", "drain"])
def test_legacy_date_repair_requires_admin_and_switch(mode):
    enabled = Settings(
        gallery_write_mode=mode, gallery_legacy_date_repair=True
    )
    assert capabilities_for(enabled, "admin").legacy_date_repair is True
    assert capabilities_for(enabled, "member").legacy_date_repair is False
    disabled = Settings(
        gallery_write_mode=mode, gallery_legacy_date_repair=False
    )
    assert capabilities_for(disabled, "admin").legacy_date_repair is False
    curation = Settings(
        gallery_write_mode="curation", gallery_legacy_date_repair=True
    )
    assert capabilities_for(curation, "admin").legacy_date_repair is False


@pytest.mark.parametrize(
    ("mode", "physical", "recovery"),
    [
        ("legacy", True, True),
        ("drain", False, True),
        ("curation", False, False),
    ],
)
def test_system_info_exposes_effective_capabilities(
    tmp_path, monkeypatch, mode, physical, recovery
):
    with _logged_in_client(monkeypatch, tmp_path, mode) as client:
        response = client.get("/api/system/info")
        assert response.status_code == 200
        body = response.json()
        assert body["gallery_write_mode"] == mode
        assert body["capabilities"] == {
            "physical_mutations": physical,
            "undo_drain": recovery,
            "synology_curation": True,
            "legacy_date_repair": False,
        }


PHYSICAL_ROUTES = [
    ("GET", "/api/photos/junk-candidates", None),
    ("GET", "/api/photos/event-suggestions", None),
    (
        "POST",
        "/api/photos/ops/move-check",
        {"space": "team", "item_ids": ["x"], "dest_folder_id": "dest"},
    ),
    (
        "POST",
        "/api/photos/ops/move",
        {"space": "team", "item_ids": ["x"], "dest_folder_id": "dest"},
    ),
    ("POST", "/api/photos/ops/delete", {"space": "team", "item_ids": ["x"]}),
    ("POST", "/api/photos/folders", {"space": "team", "name": "new"}),
    (
        "POST",
        "/api/photos/ops/move-folders",
        {"space": "team", "folder_ids": ["x"], "dest_folder_id": "dest"},
    ),
    (
        "POST",
        "/api/photos/folders/rename",
        {"space": "team", "folder_id": "x", "new_name": "renamed"},
    ),
    ("POST", "/api/photos/capture-fix", {"paths": []}),
    ("POST", "/api/photos/capture-fix-manual", {"items": []}),
    (
        "POST",
        "/api/photos/folders/delete",
        {"space": "team", "folder_id": "x", "recursive": False},
    ),
    ("POST", "/api/dedup/scan", {"space": "team"}),
    ("POST", "/api/dedup/cancel?space=team", None),
    ("PUT", "/api/organize/session", {"step": 1, "stats": {}}),
    ("POST", "/api/organize/copied", {"item_ids": ["x"]}),
    ("DELETE", "/api/organize/session", None),
    (
        "POST",
        "/api/zones",
        {"root_path": "/homes/admin/MobileBackup", "label": "phone"},
    ),
    ("DELETE", "/api/zones/not-found", None),
    ("POST", "/api/ops/trash/empty", None),
]


@pytest.mark.parametrize("mode", ["drain", "curation"])
def test_nonlegacy_modes_block_every_new_mutation(tmp_path, monkeypatch, mode):
    with _logged_in_client(monkeypatch, tmp_path, mode) as client:
        for method, path, body in PHYSICAL_ROUTES:
            response = client.request(method, path, json=body)
            assert response.status_code == 403, (
                method,
                path,
                response.status_code,
                response.text,
            )


def _first_ids(client: TestClient, count: int = 2) -> list[str]:
    day = client.get("/api/photos/buckets?space=team").json()["buckets"][0]["day"]
    items = client.get(
        "/api/photos/items", params={"space": "team", "day": day}
    ).json()["items"]
    return [item["id"] for item in items[:count]]


def test_drain_allows_existing_undo_and_item_restore(tmp_path, monkeypatch):
    # Seed two reversible operations in legacy, then switch the same process to
    # drain to exercise the recovery boundary without creating new work there.
    with _logged_in_client(monkeypatch, tmp_path, "legacy") as client:
        first, second = _first_ids(client, 2)
        delete_one = client.post(
            "/api/photos/ops/delete", json={"space": "team", "item_ids": [first]}
        )
        delete_two = client.post(
            "/api/photos/ops/delete", json={"space": "team", "item_ids": [second]}
        )
        assert delete_one.status_code == delete_two.status_code == 200

        settings = get_settings()
        settings.gallery_write_mode = "drain"

        trash_items = client.get("/api/ops/trash-items").json()["items"]
        entry = next(item for item in trash_items if item["item_id"] == first)
        restored = client.post(
            "/api/ops/trash-restore",
            json={"entries": [{"op_id": entry["op_id"], "item_id": first}]},
        )
        assert restored.status_code == 200

        undone = client.post(f"/api/ops/{delete_two.json()['operation_id']}/undo")
        assert undone.status_code == 200
        assert client.post("/api/ops/trash/empty").status_code == 403

        settings.gallery_write_mode = "curation"
        history = client.get("/api/ops")
        assert history.status_code == 200
        # Two deletes plus the explicit partial-restore audit entry.
        assert history.json()["total"] == 3
        assert history.json()["undoable"] == 0
        assert history.json()["needs_review"] == 0
        assert client.post(f"/api/ops/{delete_one.json()['operation_id']}/undo").status_code == 403
        assert (
            client.post(
                "/api/ops/trash-restore",
                json={"entries": [{"op_id": entry["op_id"], "item_id": first}]},
            ).status_code
            == 403
        )


@pytest.mark.parametrize("mode", ["drain", "curation"])
def test_synology_logical_curation_remains_available(tmp_path, monkeypatch, mode):
    with _logged_in_client(monkeypatch, tmp_path, mode) as client:
        album = client.post("/api/photos/albums", json={"name": "읽기 전용 앨범"})
        assert album.status_code == 200

        people = client.get("/api/photos/persons?space=personal").json()["persons"]
        renamed = client.post(
            "/api/photos/persons/name",
            json={
                "space": "personal",
                "person_id": people[0]["id"],
                "name": "가족",
            },
        )
        assert renamed.status_code == 200


@pytest.mark.parametrize(
    ("mode", "account", "enabled", "expected"),
    [
        ("legacy", "admin", False, 403),
        ("legacy", "tester", True, 403),
        ("drain", "admin", True, 200),
        ("curation", "admin", True, 403),
    ],
)
def test_legacy_foto_date_repair_route_gate(
    tmp_path, monkeypatch, mode, account, enabled, expected
):
    with _logged_in_client(
        monkeypatch,
        tmp_path,
        mode,
        account=account,
        legacy_date_repair=enabled,
    ) as client:
        response = client.post(
            "/api/photos/capture-fix-foto",
            json={"space": "personal", "items": []},
        )
        assert response.status_code == expected
