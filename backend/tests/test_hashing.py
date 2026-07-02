"""Unit tests for the SHA-256 + pHash implementation (real pixels, no NAS)."""

from io import BytesIO

from PIL import Image, ImageDraw

from app.photos.hashing import compute_hashes, hamming, phash_int


def _photo_like(seed: int, tweak: bool = False) -> Image.Image:
    """A gradient + shapes image — structured enough for a meaningful pHash.

    Shape *positions* derive from the seed: pHash is structural (grayscale
    low-frequency), so "different photos" must differ in layout, not just hue.
    """
    img = Image.new("RGB", (320, 240))
    px = img.load()
    for y in range(240):
        for x in range(320):
            px[x, y] = ((x + seed * 37) % 256, (y * 2 + seed * 71) % 256, (x + y) % 256)
    d = ImageDraw.Draw(img)
    ex = (seed * 61) % 180
    ey = (seed * 43) % 120
    d.ellipse((ex, ey, ex + 110, ey + 110), fill=(seed * 53 % 256, 200, 100))
    rx = (seed * 97) % 200
    ry = (seed * 29) % 140
    d.rectangle((rx, ry, rx + 90, ry + 90), fill=(30, seed * 91 % 256, 220))
    if tweak:
        # Small local edit — a near-duplicate, not a different photo.
        d.rectangle((10, 10, 28, 28), fill=(255, 255, 255))
    return img


def _jpeg_bytes(img: Image.Image, quality: int = 90) -> bytes:
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def test_phash_is_deterministic():
    img = _photo_like(1)
    assert phash_int(img) == phash_int(img)


def test_identical_bytes_share_sha_and_phash():
    data = _jpeg_bytes(_photo_like(2))
    assert compute_hashes(data) == compute_hashes(data)


def test_small_edit_is_near_duplicate():
    a = phash_int(_photo_like(3))
    b = phash_int(_photo_like(3, tweak=True))
    assert 0 < hamming(a, b) <= 10


def test_recompression_is_perceptually_identical():
    img = _photo_like(4)
    a, _, _ = compute_hashes(_jpeg_bytes(img, quality=95))
    b, _, _ = compute_hashes(_jpeg_bytes(img, quality=70))
    ph_a = phash_int(Image.open(BytesIO(_jpeg_bytes(img, quality=95))))
    ph_b = phash_int(Image.open(BytesIO(_jpeg_bytes(img, quality=70))))
    assert a != b  # different bytes → different sha
    assert hamming(ph_a, ph_b) <= 4  # ...but the same photo perceptually


def test_different_photos_are_far_apart():
    a = phash_int(_photo_like(5))
    b = phash_int(_photo_like(11))
    assert hamming(a, b) > 10


def test_thumbhash_structure_and_determinism():
    from app.photos.hashing import thumbhash_bytes

    img = _photo_like(7)  # 320×240 landscape, no alpha
    th = thumbhash_bytes(img)
    # 5-byte header + AC coefficients; well under the ~32-byte typical size.
    assert isinstance(th, bytes) and 5 < len(th) <= 40
    header16 = th[3] | (th[4] << 8)
    assert header16 >> 15 == 1  # landscape flag
    assert (th[2] >> 7) == 0  # hasAlpha bit off for RGB input
    assert thumbhash_bytes(img) == th  # deterministic

    portrait = img.transpose(Image.Transpose.ROTATE_90)
    th_p = thumbhash_bytes(portrait)
    assert (th_p[3] | (th_p[4] << 8)) >> 15 == 0  # portrait → flag off
