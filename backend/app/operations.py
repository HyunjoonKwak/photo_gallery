"""Operation log + undo service (spec ch.8).

Every destructive action records its reverse in ``operation.payload_json``:
- move   → prior locations of each item → undo re-places them
- copy   → ids of created copies       → undo removes the copies
- delete → trash locations             → undo restores from trash
- mkdir  → folder id                   → undo removes the (empty) folder

The service is source-agnostic: it executes through the PhotoSource protocol,
so the same log/undo flow drives mock today and DSM after NAS verification.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from .db import connect
from .photos.source import PhotoSource
from .schemas import (
    AffectedDay,
    CreateFolderRequest,
    DeleteRequest,
    MoveRequest,
    OperationEntry,
    OperationResponse,
    PlacedItem,
)

UNDOABLE_TYPES = frozenset({"move", "copy", "delete", "mkdir"})
# Deleted items sit in the trash; keep undo open for 7 days (spec: 휴지통 보존).
DELETE_UNDO_WINDOW = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _affected(pairs: list[tuple[str, str]]) -> list[AffectedDay]:
    return [AffectedDay(space=s, day=d) for s, d in pairs]


def _record(
    sqlite_path: str,
    *,
    user: str,
    target_user: str | None,
    type_: str,
    space_from: str | None,
    space_to: str | None,
    payload: dict,
    undo_deadline: datetime | None = None,
) -> int:
    with connect(sqlite_path) as conn:
        cur = conn.execute(
            "INSERT INTO operation "
            "(user, target_user, type, space_from, space_to, payload_json, status, "
            " created_at, undo_deadline) "
            "VALUES (?, ?, ?, ?, ?, ?, 'done', ?, ?)",
            (
                user,
                target_user,
                type_,
                space_from,
                space_to,
                json.dumps(payload, ensure_ascii=False),
                _now().isoformat(),
                undo_deadline.isoformat() if undo_deadline else None,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


async def execute_move(
    source: PhotoSource, sqlite_path: str, *, user: str, req: MoveRequest
) -> OperationResponse:
    outcome = await source.move(req.item_ids, req.dest_folder_id, req.copy_mode)
    folders = {f.id: f for f in await source.folders()}
    dest_name = folders[req.dest_folder_id].name if req.dest_folder_id in folders else "?"
    verb = "복사" if req.copy_mode else "이동"
    summary = f"{len(req.item_ids)}장을 '{dest_name}' 폴더로 {verb}"

    payload = {
        "summary": summary,
        "moved": [p.model_dump() for p in outcome.moved],
        "created_ids": outcome.created_ids,
    }
    space_from = outcome.moved[0].space if outcome.moved else None
    op_id = _record(
        sqlite_path,
        user=user,
        target_user=req.target_user,
        type_="copy" if req.copy_mode else "move",
        space_from=space_from,
        space_to=outcome.dest_space,
        payload=payload,
    )
    return OperationResponse(
        operation_id=op_id,
        summary=summary,
        affected=_affected(outcome.affected),
        undoable=True,
    )


async def execute_delete(
    source: PhotoSource, sqlite_path: str, *, user: str, req: DeleteRequest
) -> OperationResponse:
    outcome = await source.delete(req.item_ids)
    summary = f"{len(outcome.deleted)}장을 휴지통으로 이동"
    payload = {
        "summary": summary,
        "deleted": [p.model_dump() for p in outcome.deleted],
    }
    op_id = _record(
        sqlite_path,
        user=user,
        target_user=req.target_user,
        type_="delete",
        space_from=outcome.deleted[0].space if outcome.deleted else None,
        space_to=None,
        payload=payload,
        undo_deadline=_now() + DELETE_UNDO_WINDOW,
    )
    return OperationResponse(
        operation_id=op_id,
        summary=summary,
        affected=_affected(outcome.affected),
        undoable=True,
    )


async def execute_create_folder(
    source: PhotoSource, sqlite_path: str, *, user: str, req: CreateFolderRequest
) -> OperationResponse:
    folder = await source.create_folder(req.space, req.name)
    summary = f"'{folder.name}' 폴더 생성"
    op_id = _record(
        sqlite_path,
        user=user,
        target_user=req.target_user,
        type_="mkdir",
        space_from=None,
        space_to=req.space,
        payload={"summary": summary, "folder_id": folder.id},
    )
    return OperationResponse(
        operation_id=op_id,
        summary=summary,
        affected=[],
        undoable=True,
        folder=folder,
    )


async def undo_operation(
    source: PhotoSource, sqlite_path: str, op_id: int
) -> OperationResponse:
    with connect(sqlite_path) as conn:
        row = conn.execute(
            "SELECT id, type, status, payload_json, undo_deadline "
            "FROM operation WHERE id = ?",
            (op_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "작업을 찾을 수 없습니다.")
    if row["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 되돌렸거나 되돌릴 수 없는 작업입니다.")
    if row["undo_deadline"] and datetime.fromisoformat(row["undo_deadline"]) <= _now():
        raise HTTPException(status.HTTP_409_CONFLICT, "되돌리기 가능 기한이 지났습니다.")

    payload = json.loads(row["payload_json"])
    op_type = row["type"]

    if op_type == "move":
        affected = await source.place([PlacedItem(**p) for p in payload["moved"]])
    elif op_type == "copy":
        affected = await source.remove_items(payload["created_ids"])
    elif op_type == "delete":
        affected = await source.restore([PlacedItem(**p) for p in payload["deleted"]])
    elif op_type == "mkdir":
        if not await source.remove_folder(payload["folder_id"]):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "폴더가 비어 있지 않아 되돌릴 수 없습니다."
            )
        affected = []
    else:  # pragma: no cover - guarded by UNDOABLE_TYPES on insert
        raise HTTPException(status.HTTP_409_CONFLICT, "되돌릴 수 없는 작업 유형입니다.")

    with connect(sqlite_path) as conn:
        conn.execute("UPDATE operation SET status = 'undone' WHERE id = ?", (op_id,))
        conn.commit()

    summary = f"되돌림: {payload.get('summary', op_type)}"
    return OperationResponse(
        operation_id=op_id,
        summary=summary,
        affected=_affected(affected),
        undoable=False,
    )


def list_operations(sqlite_path: str, limit: int = 30) -> list[OperationEntry]:
    with connect(sqlite_path) as conn:
        rows = conn.execute(
            "SELECT id, type, status, payload_json, created_at, undo_deadline, "
            "       target_user "
            "FROM operation ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    now = _now()
    out: list[OperationEntry] = []
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        deadline_ok = not row["undo_deadline"] or datetime.fromisoformat(
            row["undo_deadline"]
        ) > now
        out.append(
            OperationEntry(
                id=row["id"],
                type=row["type"],
                summary=payload.get("summary", row["type"]),
                status=row["status"],
                created_at=row["created_at"],
                can_undo=row["status"] == "done"
                and row["type"] in UNDOABLE_TYPES
                and deadline_ok,
                target_user=row["target_user"],
            )
        )
    return out
