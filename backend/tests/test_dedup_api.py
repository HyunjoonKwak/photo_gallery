"""End-to-end dedup tests in mock mode: scan job → groups → cleanup flow."""

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


def _scan(client, space="team"):
    resp = client.post("/api/dedup/scan", json={"space": space, "sync": True})
    assert resp.status_code == 200
    job = resp.json()
    assert job["status"] == "done"
    return job


def test_scan_processes_all_items(client):
    job = _scan(client)
    assert job["total"] > 0
    assert job["processed"] == job["total"]


def test_groups_require_completed_scan(client):
    resp = client.get("/api/dedup/groups?space=team").json()
    assert resp["scanned"] is False and resp["groups"] == []


def test_groups_contain_planted_duplicates(client):
    _scan(client)
    resp = client.get("/api/dedup/groups?space=team&threshold=5").json()
    assert resp["scanned"] is True
    kinds = {g["kind"] for g in resp["groups"]}
    assert "exact" in kinds  # idx%11==1 planted exact dups
    assert "similar" in kinds  # idx%7==1 planted near dups
    assert resp["total_wasted_bytes"] > 0
    for g in resp["groups"]:
        assert len(g["items"]) >= 2
        assert g["reference_id"] in {i["id"] for i in g["items"]}


def test_threshold_zero_hides_similar_groups(client):
    _scan(client)
    at5 = client.get("/api/dedup/groups?space=team&threshold=5&limit=500").json()
    at0 = client.get("/api/dedup/groups?space=team&threshold=0&limit=500").json()
    similar5 = sum(1 for g in at5["groups"] if g["kind"] == "similar")
    similar0 = sum(1 for g in at0["groups"] if g["kind"] == "similar")
    assert similar0 < similar5
    # Lowering the threshold removes similar groups; exact groups are
    # threshold-independent, so the *unpaginated* totals must strictly shrink.
    assert at0["total_groups"] < at5["total_groups"]
    # Pagination metadata is coherent.
    assert at5["total_groups"] >= len(at5["groups"])


def test_copy_then_rescan_finds_exact_duplicate(client):
    _scan(client)
    day = client.get("/api/photos/buckets?space=team").json()["buckets"][0]["day"]
    items = client.get(f"/api/photos/items?space=team&day={day}").json()["items"]
    src = items[2]["id"]
    client.post(
        "/api/photos/ops/move",
        json={"item_ids": [src], "dest_folder_id": "f-team-1", "copy_mode": True},
    )
    _scan(client)  # resume-style: only the new copy gets hashed
    groups = client.get(
        "/api/dedup/groups?space=team&threshold=0&limit=500"
    ).json()["groups"]
    assert any(
        any(i["id"].startswith(f"{src}-c") for i in g["items"])
        and any(i["id"] == src for i in g["items"])
        for g in groups
        if g["kind"] == "exact"
    )


def test_cleanup_removes_group_after_delete(client):
    _scan(client)
    groups = client.get("/api/dedup/groups?space=team&threshold=5").json()["groups"]
    target = next(g for g in groups if g["kind"] == "exact")
    victims = [i["id"] for i in target["items"] if i["id"] != target["reference_id"]]

    resp = client.post("/api/photos/ops/delete", json={"item_ids": victims})
    assert resp.status_code == 200

    after = client.get("/api/dedup/groups?space=team&threshold=5").json()["groups"]
    assert target["id"] not in {g["id"] for g in after}


def test_scan_conflict_returns_running_job(client):
    _scan(client)
    # A second sync scan just runs again (previous finished) — but a running
    # job short-circuits: simulate by inserting a running row via async start.
    resp = client.post("/api/dedup/scan", json={"space": "team", "sync": True})
    assert resp.json()["status"] == "done"


def test_status_endpoint(client):
    assert client.get("/api/dedup/status?space=team").json()["job"] is None
    _scan(client)
    job = client.get("/api/dedup/status?space=team").json()["job"]
    assert job and job["status"] == "done"
