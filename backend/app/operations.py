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
from .dedup import remove_cached_items
from .photos.source import PhotoSource
from .progress import ProgressFn
from .schemas import (
    AffectedDay,
    CreateFolderRequest,
    DeleteRequest,
    MoveFoldersRequest,
    MoveRequest,
    OperationEntry,
    OperationResponse,
    PlacedItem,
    RemoveFolderRequest,
)

UNDOABLE_TYPES = frozenset(
    {"move", "copy", "delete", "mkdir", "move_folder", "copy_folder"}
)
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
    source: PhotoSource,
    sqlite_path: str,
    *,
    user: str,
    req: MoveRequest,
    on_progress: ProgressFn | None = None,
) -> OperationResponse:
    # "ask" (default): surface filename collisions to the client as a 409 so it
    # can raise the 처리 방법 dialog — this covers EVERY move path (drag-drop,
    # 액션바, 라이트박스), not just the dual-pane buttons. The client then retries
    # with an explicit skip/overwrite/rename.
    strategy = req.conflict_strategy
    if strategy == "ask":
        clashes = await source.conflicts(
            req.space, req.item_ids, req.dest_folder_id
        )
        if clashes:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "filename_conflict",
                    "message": f"같은 이름의 사진 {len(clashes)}장이 대상 폴더에 있습니다.",
                    "conflicts": [
                        {"item_id": i, "filename": f} for i, f in clashes
                    ],
                },
            )
        strategy = "skip"  # no clashes → strategy is moot

    outcome = await source.move(
        req.space,
        req.item_ids,
        req.dest_folder_id,
        req.copy_mode,
        on_progress,
        conflict_strategy=strategy,
    )
    verb = "복사" if req.copy_mode else "이동"
    # 실제로 처리된 장수(skip으로 빠진 건 제외) — moved/created 기준.
    handled = len(outcome.moved) + len(outcome.created_ids)
    n = handled if req.copy_mode or outcome.moved else len(req.item_ids)
    summary = f"{n}장을 '{outcome.dest_name or '대상'}' 폴더로 {verb}"

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
    source: PhotoSource,
    sqlite_path: str,
    *,
    user: str,
    req: DeleteRequest,
    on_progress: ProgressFn | None = None,
) -> OperationResponse:
    outcome = await source.delete(req.space, req.item_ids, on_progress)
    # Trashed items must vanish from duplicate groups; a later restore simply
    # re-hashes them on the next scan (photo_cache is a rebuildable cache).
    remove_cached_items(sqlite_path, [p.id for p in outcome.deleted])
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
    folder = await source.create_folder(req.space, req.name, req.parent_id)
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


async def execute_move_folders(
    source: PhotoSource,
    sqlite_path: str,
    *,
    user: str,
    req: "MoveFoldersRequest",
    on_progress: ProgressFn | None = None,
) -> OperationResponse:
    """폴더째 이동/복사 (하위 전체 포함) — 여러 폴더 한 번에, undo 지원."""
    strategy = req.conflict_strategy
    if strategy == "ask":
        clashes = await source.folder_conflicts(
            req.space, req.folder_ids, req.dest_folder_id
        )
        if clashes:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "folder_conflict",
                    "message": f"같은 이름의 폴더 {len(clashes)}개가 대상 위치에 있습니다.",
                    "conflicts": [
                        {"folder_id": i, "name": n} for i, n in clashes
                    ],
                },
            )
        strategy = "skip"  # no clashes → moot

    outcome = await source.move_folders(
        req.space,
        req.folder_ids,
        req.dest_folder_id,
        req.copy_mode,
        on_progress,
        conflict_strategy=strategy,
    )
    verb = "복사" if req.copy_mode else "이동"
    names = outcome.get("names", [])
    if not names:
        # Every folder was already inside the destination (no-op skips).
        raise HTTPException(
            status.HTTP_409_CONFLICT, "선택한 폴더가 이미 대상 폴더 안에 있습니다."
        )
    label = (
        f"'{names[0]}'"
        if len(names) == 1
        else f"'{names[0]}' 외 {len(names) - 1}개"
    )
    # 토스트가 "…했습니다"를 덧붙이므로 동사로 끝나는 형태 유지.
    summary = f"{label} 폴더를 {verb}"
    op_id = _record(
        sqlite_path,
        user=user,
        target_user=req.target_user,
        type_="copy_folder" if req.copy_mode else "move_folder",
        space_from=req.space,
        space_to=None,
        payload={
            "summary": summary,
            "undo": outcome.get("undo", []),
            "copy": req.copy_mode,
        },
    )
    return OperationResponse(
        operation_id=op_id, summary=summary, affected=[], undoable=True
    )


async def execute_remove_folder(
    source: PhotoSource,
    sqlite_path: str,
    *,
    user: str,
    req: "RemoveFolderRequest",
) -> OperationResponse:
    """Delete an EMPTY folder (분할 뷰 폴더 정리). Non-empty → 409.

    Not undoable: nothing is lost (the folder had no photos), and recreating
    a Foto folder id on undo is not meaningful.
    """
    removed = await source.remove_folder(req.folder_id)
    if not removed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "비어 있는 폴더만 삭제할 수 있습니다 (사진/하위 폴더 확인).",
        )
    summary = "빈 폴더 삭제"
    op_id = _record(
        sqlite_path,
        user=user,
        target_user=req.target_user,
        type_="rmdir",
        space_from=req.space,
        space_to=None,
        payload={"summary": summary, "folder_id": req.folder_id},
    )
    return OperationResponse(
        operation_id=op_id, summary=summary, affected=[], undoable=False
    )


def trash_stats(sqlite_path: str) -> tuple[int, int]:
    """(delete-op count, item count) currently sitting in the app trash."""
    with connect(sqlite_path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM operation "
            "WHERE type = 'delete' AND status = 'done'"
        ).fetchall()
    items = sum(len(json.loads(r["payload_json"]).get("deleted", [])) for r in rows)
    return len(rows), items


async def execute_empty_trash(
    source: PhotoSource, sqlite_path: str, *, user: str
) -> OperationResponse:
    """Permanently delete all app-trash contents (the only irreversible op).

    Every pending delete op flips to 'purged' so its undo is refused — the
    files are gone. The purge itself is logged for the audit trail.
    """
    _, item_count = trash_stats(sqlite_path)
    await source.purge_trash()
    with connect(sqlite_path) as conn:
        conn.execute(
            "UPDATE operation SET status = 'purged' "
            "WHERE type = 'delete' AND status = 'done'"
        )
        conn.commit()
    summary = f"휴지통 비우기 ({item_count}장 영구 삭제)"
    op_id = _record(
        sqlite_path,
        user=user,
        target_user=None,
        type_="empty_trash",
        space_from=None,
        space_to=None,
        payload={"summary": summary, "purged_items": item_count},
    )
    return OperationResponse(
        operation_id=op_id, summary=summary, affected=[], undoable=False
    )


async def undo_operation(
    source: PhotoSource,
    sqlite_path: str,
    op_id: int,
    on_progress: ProgressFn | None = None,
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
        affected = await source.place(
            [PlacedItem(**p) for p in payload["moved"]], on_progress
        )
    elif op_type == "copy":
        affected = await source.remove_items(payload["created_ids"])
        remove_cached_items(sqlite_path, payload["created_ids"])
    elif op_type == "delete":
        affected = await source.restore(
            [PlacedItem(**p) for p in payload["deleted"]], on_progress
        )
    elif op_type == "mkdir":
        if not await source.remove_folder(payload["folder_id"]):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "폴더가 비어 있지 않아 되돌릴 수 없습니다."
            )
        affected = []
    elif op_type in ("move_folder", "copy_folder"):
        await source.revert_move_folders(
            payload.get("undo", []), payload.get("copy", False)
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
