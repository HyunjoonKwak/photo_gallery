"""Duplicate-detection hashes: SHA-256 (exact) + 64-bit pHash (near-duplicate).

pHash is implemented directly (grayscale 32×32 → DCT-II → 8×8 low-frequency
block → median-threshold bits) instead of pulling in the ``imagehash`` package:
imagehash drags numpy+scipy into the NAS container for the one function we
need. The algorithm is identical in spirit; only the 8 needed DCT coefficients
per axis are computed, so pure Python stays fast enough (~a few ms per image).
Swap to a numpy implementation later if DSM-scale scanning demands it.

Hamming-distance guidance (docs/IMPROVEMENTS.md D절): 0–2 ≈ same photo,
≤5 similar (default threshold), 10+ different.
"""

from __future__ import annotations

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


def compute_hashes(image_bytes: bytes) -> tuple[str, str]:
    """(sha256, phash) for one thumbnail's bytes.

    SHA-256 runs over the thumbnail bytes (D절: 원본 전송 회피 — identical
    originals produce identical Synology thumbnails), pHash over the pixels.
    """
    sha = sha256_hex(image_bytes)
    with Image.open(BytesIO(image_bytes)) as img:
        ph = phash_hex(img)
    return sha, ph
