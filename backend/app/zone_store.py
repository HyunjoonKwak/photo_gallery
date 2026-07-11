"""Per-user "1차 구역"(기기 백업 zone) registry — folders outside the user's
Synology Photos index that the app browses via FileStation.

Rows are scoped by ``account`` (the logged-in DSM account): a zone belongs to
whoever registered it, and ``get_photo_source`` only resolves zones for the
requesting account, so ownership itself is the access rule.
"""

from __future__ import annotations

import posixpath
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from .db import connect


@dataclass(frozen=True)
class Zone:
    id: str
    root_path: str
    label: str
    last_seen_at: str | None = None


class ZonePathError(ValueError):
    """A zone root that fails validation (traversal / outside the allowed area)."""


def validate_zone_root(account: str, root_path: str) -> str:
    """Normalize and whitelist a zone root path, or raise ZonePathError.

    Allowed: the user's own home subtree (``/homes/<account>/…``) or the shared
    photo share (``/photo``/``/photo/…``). Everything else — traversal, other
    users' homes, system folders — is rejected. Returns the normalized path.
    """
    if not root_path or not root_path.startswith("/"):
        raise ZonePathError("절대경로(/로 시작)만 등록할 수 있습니다.")
    norm = posixpath.normpath(root_path)
    if norm != root_path.rstrip("/") and norm != root_path:
        # normpath collapsed something (e.g. .. or //) — reject to be safe.
        if ".." in root_path.split("/"):
            raise ZonePathError("경로에 '..'를 쓸 수 없습니다.")
    home = f"/homes/{account}"
    if norm == home or norm.startswith(home + "/"):
        return norm
    if norm == "/photo" or norm.startswith("/photo/"):
        return norm
    raise ZonePathError(
        "내 홈 폴더(/homes/…) 또는 공용(/photo) 아래 경로만 1차 구역으로 등록할 수 있습니다."
    )


def list_zones(sqlite_path: str, account: str) -> list[Zone]:
    with connect(sqlite_path) as conn:
        rows = conn.execute(
            "SELECT id, root_path, label, last_seen_at FROM zone_config "
            "WHERE account = ? ORDER BY created_at",
            (account,),
        ).fetchall()
    return [
        Zone(
            id=r["id"],
            root_path=r["root_path"],
            label=r["label"],
            last_seen_at=r["last_seen_at"],
        )
        for r in rows
    ]


def get_zone(sqlite_path: str, account: str, zone_id: str) -> Zone | None:
    with connect(sqlite_path) as conn:
        row = conn.execute(
            "SELECT id, root_path, label, last_seen_at FROM zone_config "
            "WHERE account = ? AND id = ?",
            (account, zone_id),
        ).fetchone()
    if row is None:
        return None
    return Zone(
        id=row["id"],
        root_path=row["root_path"],
        label=row["label"],
        last_seen_at=row["last_seen_at"],
    )


def create_zone(sqlite_path: str, account: str, root_path: str, label: str) -> Zone:
    zone_id = secrets.token_hex(8)
    now = datetime.now(timezone.utc).isoformat()
    with connect(sqlite_path) as conn:
        conn.execute(
            "INSERT INTO zone_config (account, id, root_path, label, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (account, zone_id, root_path, label, now),
        )
        conn.commit()
    return Zone(id=zone_id, root_path=root_path, label=label)


def delete_zone(sqlite_path: str, account: str, zone_id: str) -> bool:
    with connect(sqlite_path) as conn:
        cur = conn.execute(
            "DELETE FROM zone_config WHERE account = ? AND id = ?",
            (account, zone_id),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_zone_seen(sqlite_path: str, account: str, zone_id: str) -> None:
    """신규 유입 뱃지 기준 시각 갱신 — 사용자가 해당 구역을 열었을 때 호출."""
    with connect(sqlite_path) as conn:
        conn.execute(
            "UPDATE zone_config SET last_seen_at = datetime('now') "
            "WHERE account = ? AND id = ?",
            (account, zone_id),
        )
        conn.commit()
