"""잡동사니(정리 후보) 판별 — 정리 마법사 Phase 1 (ORGANIZE_WIZARD.md).

photo_cache(dedup 스캔 산출)를 재사용해 개인 공간에서 스크린샷/메신저 저장본
후보를 사유 태그와 함께 추출한다. 순수 함수 + 얇은 SQL이라 단위테스트 대상.

v1 룰 조정(2026-07-12): 설계의 `no_exif`(camera IS NULL) 룰은 제외 — 실 NAS
photo_cache에 camera가 전 행 NULL로 수집돼(해시 스캔이 EXIF 카메라를 안 채움)
전량 오탐이 된다. 파일명 기반 룰만 v1로 시작.
"""

from __future__ import annotations

import re

from ..db import connect

# 사유 태그: 사용자 신뢰를 위해 후보마다 '왜 골랐는지'를 반드시 붙인다.
REASON_LABELS = {
    "screenshot": "스크린샷",
    "messenger": "메신저 저장본",
}

_SCREENSHOT = re.compile(r"^(screenshot|스크린샷|scr_)", re.IGNORECASE)
_MESSENGER = re.compile(
    r"^(kakaotalk_|img_kakao|fb_img|telegram|line_|received_)", re.IGNORECASE
)


def classify(filename: str) -> str | None:
    """파일명 → 사유 태그(없으면 None). 확장자 무관, 접두 패턴만 본다."""
    name = filename.rsplit("/", 1)[-1]
    if _SCREENSHOT.match(name):
        return "screenshot"
    if name.lower().endswith(".png") and not _MESSENGER.match(name):
        # 카메라 원본은 PNG가 아니다 — PNG는 사실상 캡처/저장 이미지.
        return "screenshot"
    if _MESSENGER.match(name):
        return "messenger"
    return None


def junk_candidates(sqlite_path: str, space: str = "personal") -> dict[str, list[dict]]:
    """사유 → photo_cache 행 목록. 행은 PhotoItem 구성에 필요한 필드만."""
    groups: dict[str, list[dict]] = {}
    with connect(sqlite_path) as conn:
        rows = conn.execute(
            "SELECT file_id, path, taken_at, thumb_key, width, height, size "
            "FROM photo_cache WHERE space = ?",
            (space,),
        ).fetchall()
    for r in rows:
        reason = classify(r["path"] or "")
        if reason is None:
            continue
        groups.setdefault(reason, []).append(
            {
                "id": r["file_id"],
                "filename": (r["path"] or "").rsplit("/", 1)[-1],
                "taken_at": r["taken_at"] or "",
                "cache_key": r["thumb_key"] or "",
                "width": r["width"] or 4,
                "height": r["height"] or 3,
                "size": r["size"],
            }
        )
    for items in groups.values():
        items.sort(key=lambda x: x["taken_at"], reverse=True)
    return groups
