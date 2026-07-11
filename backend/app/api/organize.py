"""정리 마법사 세션(이어하기) API — ORGANIZE_WIZARD.md Phase 3.

단계 이동/처리 통계를 사용자당 1행으로 저장해, 다음 진입 때 "이어하기"를
지원한다. 실행 액션은 전부 기존 이동/복사/삭제 API를 재사용하므로 여기는
상태 저장만 담당한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..db import connect
from ..session_store import Session
from .deps import get_current_session

router = APIRouter(prefix="/api/organize", tags=["organize"])


class WizardSession(BaseModel):
    step: int = Field(1, ge=1, le=4)
    stats: dict = Field(default_factory=dict)
    updated_at: str | None = None


@router.get("/session", response_model=WizardSession)
async def get_wizard_session(
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> WizardSession:
    with connect(settings.sqlite_path) as conn:
        row = conn.execute(
            "SELECT step, stats_json, updated_at FROM workflow_session WHERE user = ?",
            (session.account,),
        ).fetchone()
    if row is None:
        return WizardSession()
    return WizardSession(
        step=row["step"],
        stats=json.loads(row["stats_json"] or "{}"),
        updated_at=row["updated_at"],
    )


@router.put("/session", response_model=WizardSession)
async def put_wizard_session(
    body: WizardSession,
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> WizardSession:
    now = datetime.now(timezone.utc).isoformat()
    with connect(settings.sqlite_path) as conn:
        conn.execute(
            "INSERT INTO workflow_session (user, step, stats_json, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user) DO UPDATE SET step=excluded.step, "
            "stats_json=excluded.stats_json, updated_at=excluded.updated_at",
            (session.account, body.step, json.dumps(body.stats, ensure_ascii=False), now),
        )
        conn.commit()
    return WizardSession(step=body.step, stats=body.stats, updated_at=now)


@router.delete("/session")
async def reset_wizard_session(
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """새로 시작 — 세션 삭제."""
    with connect(settings.sqlite_path) as conn:
        conn.execute(
            "DELETE FROM workflow_session WHERE user = ?", (session.account,)
        )
        conn.commit()
    return {"ok": True}
