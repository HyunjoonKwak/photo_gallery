"""Image hashes computed over Synology thumbnails (원본 전송 회피).

- SHA-256 (exact duplicate) + 64-bit pHash (near duplicate) — D절.
- ThumbHash (B-2): ~25-byte blurred placeholder, decoded client-side by the
  official ``thumbhash`` npm package. Encoder is a faithful port of the
  reference implementation (github.com/evanw/thumbhash, MIT) — like pHash it
  is implemented directly to keep the container numpy-free.

pHash: grayscale 32×32 → DCT-II → 8×8 low-frequency block → median-threshold
bits; only the 8 needed DCT coefficients per axis are computed, so pure
Python stays fast enough (~a few ms per image).

Hamming-distance guidance (docs/IMPROVEMENTS.md D절): 0–2 ≈ same photo,
≤5 similar (default threshold), 10+ different.
"""

from __future__ import annotations

import base64
import hashlib
import math
from io import BytesIO
from statistics import median

from PIL import Image

_N = 32  # DCT input size
_LOW = 8  # low-frequency block size (8×8 → 64-bit hash)

# cos[u][x] = cos(pi * (2x+1) * u / (2N)) — only the _LOW coefficients we use.
_COS = [
    [math.cos(math.pi * (2 * x + 1) * u / (2 * _N)) for x in range(_N)]
    for u in range(_LOW)
]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def phash_int(image: Image.Image) -> int:
    """64-bit perceptual hash of an image."""
    gray = image.convert("L").resize((_N, _N), Image.LANCZOS)
    px = list(gray.getdata())  # row-major, len N*N

    # Separable DCT-II, computing only the _LOW×_LOW low-frequency block.
    # Rows: for each y, coefficients u=0.._LOW-1.
    rows = [
        [sum(px[y * _N + x] * _COS[u][x] for x in range(_N)) for u in range(_LOW)]
        for y in range(_N)
    ]
    # Columns: for each (v, u) in the low block.
    dct = [
        [sum(rows[y][u] * _COS[v][y] for y in range(_N)) for u in range(_LOW)]
        for v in range(_LOW)
    ]

    values = [dct[v][u] for v in range(_LOW) for u in range(_LOW)]
    mid = median(values)
    bits = 0
    for value in values:
        bits = (bits << 1) | (1 if value > mid else 0)
    return bits


def phash_hex(image: Image.Image) -> str:
    return f"{phash_int(image):016x}"


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


# --------------------------------------------------------------- ThumbHash


def _jround(v: float) -> int:
    """JS Math.round (half-up) — Python's round() is banker's rounding."""
    return math.floor(v + 0.5)


def thumbhash_bytes(image: Image.Image) -> bytes:
    """ThumbHash of an image (reference algorithm, encoder side only).

    Input is downscaled to ≤32px: the hash keeps at most a 7×7 DCT block, so
    a 32px source loses nothing visible while keeping the pure-Python encode
    fast enough for NAS-scale scans (~10ms vs ~0.5s at the reference's 100px).
    """
    w0, h0 = image.size
    scale = 32 / max(w0, h0)
    if scale < 1:
        image = image.resize(
            (max(1, round(w0 * scale)), max(1, round(h0 * scale))), Image.LANCZOS
        )
    rgba_img = image.convert("RGBA")
    w, h = rgba_img.size
    rgba = list(rgba_img.getdata())

    # Average color (alpha-weighted).
    avg_r = avg_g = avg_b = avg_a = 0.0
    for r, g, b, a in rgba:
        alpha = a / 255
        avg_r += alpha / 255 * r
        avg_g += alpha / 255 * g
        avg_b += alpha / 255 * b
        avg_a += alpha
    if avg_a:
        avg_r /= avg_a
        avg_g /= avg_a
        avg_b /= avg_a

    has_alpha = avg_a < w * h
    l_limit = 5 if has_alpha else 7  # use fewer luminance bits with alpha
    lx = max(1, _jround(l_limit * w / max(w, h)))
    ly = max(1, _jround(l_limit * h / max(w, h)))
    l_ch: list[float] = []  # luminance
    p_ch: list[float] = []  # yellow - blue
    q_ch: list[float] = []  # red - green
    a_ch: list[float] = []  # alpha
    for r, g, b, a in rgba:
        alpha = a / 255
        rr = avg_r * (1 - alpha) + alpha / 255 * r
        gg = avg_g * (1 - alpha) + alpha / 255 * g
        bb = avg_b * (1 - alpha) + alpha / 255 * b
        l_ch.append((rr + gg + bb) / 3)
        p_ch.append((rr + gg) / 2 - bb)
        q_ch.append(rr - gg)
        a_ch.append(alpha)

    def encode_channel(
        channel: list[float], nx: int, ny: int
    ) -> tuple[float, list[float], float]:
        dc, ac, sc = 0.0, [], 0.0
        for cy in range(ny):
            cx = 0
            while cx * ny < nx * (ny - cy):
                fx = [math.cos(math.pi / w * cx * (x + 0.5)) for x in range(w)]
                f = 0.0
                for y in range(h):
                    fy = math.cos(math.pi / h * cy * (y + 0.5))
                    row = y * w
                    f += fy * sum(channel[row + x] * fx[x] for x in range(w))
                f /= w * h
                if cx or cy:
                    ac.append(f)
                    sc = max(sc, abs(f))
                else:
                    dc = f
                cx += 1
        if sc:
            ac = [0.5 + 0.5 / sc * v for v in ac]
        return dc, ac, sc

    l_dc, l_ac, l_scale = encode_channel(l_ch, max(3, lx), max(3, ly))
    p_dc, p_ac, p_scale = encode_channel(p_ch, 3, 3)
    q_dc, q_ac, q_scale = encode_channel(q_ch, 3, 3)
    if has_alpha:
        a_dc, a_ac, a_scale = encode_channel(a_ch, 5, 5)

    is_landscape = w > h
    header24 = (
        _jround(63 * l_dc)
        | (_jround(31.5 + 31.5 * p_dc) << 6)
        | (_jround(31.5 + 31.5 * q_dc) << 12)
        | (_jround(31 * l_scale) << 18)
        | ((1 << 23) if has_alpha else 0)
    )
    header16 = (
        (ly if is_landscape else lx)
        | (_jround(63 * p_scale) << 3)
        | (_jround(63 * q_scale) << 9)
        | ((1 << 15) if is_landscape else 0)
    )
    out = [
        header24 & 255,
        (header24 >> 8) & 255,
        header24 >> 16,
        header16 & 255,
        header16 >> 8,
    ]
    if has_alpha:
        out.append(_jround(15 * a_dc) | (_jround(15 * a_scale) << 4))

    ac_lists = [l_ac, p_ac, q_ac, a_ac] if has_alpha else [l_ac, p_ac, q_ac]
    ac_index = 0
    for ac in ac_lists:
        for f in ac:
            u = _jround(15 * f)
            if ac_index & 1:
                out[-1] |= u << 4
            else:
                out.append(u)
            ac_index += 1
    return bytes(out)


def compute_hashes(image_bytes: bytes) -> tuple[str, str, str]:
    """(sha256, phash, thumbhash-base64) for one thumbnail's bytes.

    SHA-256 runs over the thumbnail bytes (D절: 원본 전송 회피 — identical
    originals produce identical Synology thumbnails), pHash and ThumbHash
    over the decoded pixels.
    """
    sha = sha256_hex(image_bytes)
    with Image.open(BytesIO(image_bytes)) as img:
        ph = phash_hex(img)
        th = base64.b64encode(thumbhash_bytes(img)).decode()
    return sha, ph, th
