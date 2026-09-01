"""Lossy re-encode of DSM thumbnails to WebP (실전송 바이트 절감).

Synology's grid and viewer thumbnails are relatively large JPEGs. Re-encoding
them to WebP q80 cuts the wire size without touching the original downloaded by
the "저장" button. Grid thumbnails use a faster method because many are encoded
at once; viewer thumbnails favour a little more compression.

CPU cost is one encode per (account, item) — the result is stored in the
on-disk ThumbCache, so repeats are free. Callers run this in a thread
(``asyncio.to_thread``) to keep the event loop responsive.
"""

from __future__ import annotations

import io
import logging

from PIL import Image

log = logging.getLogger(__name__)

WEBP_MEDIA_TYPE = "image/webp"

_QUALITY = 80
# 운영 캐시 실측: sm method2는 method4와 용량 차이가 작고 인코딩은 약 2배 빠름.
WEBP_GRID_METHOD = 2
# xl은 화면당 한 장만 인코딩하며 더 큰 파일이므로 기존 압축률 우선 설정 유지.
WEBP_VIEWER_METHOD = 4


def encode_webp(
    data: bytes, *, method: int = WEBP_VIEWER_METHOD
) -> bytes | None:
    """Re-encode image bytes as WebP; None on any failure (serve original)."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=_QUALITY, method=method)
        out = buf.getvalue()
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 원본 폴백
        log.warning("WebP 인코딩 실패(원본 JPEG로 폴백): %s", exc)
        return None
    # 재인코딩이 오히려 커지는 예외적 이미지는 원본이 이득.
    if len(out) >= len(data):
        return None
    return out


def media_type_of(data: bytes) -> str:
    """Sniff WebP vs JPEG. 변형 캐시에는 '협상 결과'가 들어가므로(이득 없던
    이미지는 원본 JPEG 그대로 저장 — 재시도 CPU 방지) 시그니처로 판별한다."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP_MEDIA_TYPE
    return "image/jpeg"
