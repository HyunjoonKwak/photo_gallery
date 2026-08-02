"""Lossy re-encode of DSM thumbnails to WebP (실전송 바이트 절감).

Synology's XL thumbnail is a moderately-compressed JPEG (~150-500KB at
1280px). Re-encoding to WebP q80 cuts the wire size by roughly 30-45% with
no visible quality loss at viewer sizes — the "저장" button still downloads
the untouched original, so this only affects the in-app viewing copy.

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

# q80/method4: 1280px 기준 인코딩 ~100ms(NAS x86)에 30-45% 절감 균형점.
_QUALITY = 80
_METHOD = 4


def encode_webp(data: bytes) -> bytes | None:
    """Re-encode image bytes as WebP; None on any failure (serve original)."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=_QUALITY, method=_METHOD)
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
