"""WebP negotiation for xl thumbnails (실전송 절감) — unit + endpoint tests."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.photos.transcode import encode_webp, media_type_of


def _jpeg() -> bytes:
    # Smooth two-channel gradient: compresses differently per format, so the
    # "webp is smaller" assertion is meaningful (uniform color would not be).
    g = Image.linear_gradient("L")
    r = Image.radial_gradient("L")
    img = Image.merge("RGB", (r, g, g))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


# ------------------------------------------------------------ transcode unit


def test_encode_webp_smaller_and_valid():
    src = _jpeg()
    out = encode_webp(src)
    assert out is not None
    assert out[:4] == b"RIFF" and out[8:12] == b"WEBP"
    assert len(out) < len(src)
    assert media_type_of(out) == "image/webp"


def test_encode_webp_garbage_returns_none():
    assert encode_webp(b"definitely not an image") is None


def test_media_type_of_jpeg():
    assert media_type_of(_jpeg()) == "image/jpeg"


# ------------------------------------------------------------ endpoint


class StubSource:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls = 0

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        self.calls += 1
        return self.data, "image/jpeg"


@pytest.fixture()
def webp_client(tmp_path, monkeypatch):
    # Non-mock app (webp 협상은 mock에서 꺼진다); DSM은 스텁 소스로 대체.
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "app.db"))
    get_settings.cache_clear()
    from app.api.deps import get_current_session, get_photo_source
    from app.main import create_app
    from app.session_store import Session

    app = create_app()
    stub = StubSource(_jpeg())
    app.dependency_overrides[get_current_session] = lambda: Session(
        token="t", sid="s", account="alice", role="member", can_browse_homes=False
    )
    app.dependency_overrides[get_photo_source] = lambda: stub
    with TestClient(app) as c:
        yield c, stub
    get_settings.cache_clear()


def _get(client, size, accept):
    return client.get(
        "/api/photos/thumbnail",
        params={"space": "team", "id": "1", "cache_key": "ck", "size": size},
        headers={"Accept": accept},
    )


def test_xl_negotiates_webp_and_caches_variant(webp_client):
    client, stub = webp_client
    resp = _get(client, "xl", "image/webp,image/jpeg,*/*")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert resp.headers["vary"] == "Accept"
    assert resp.content[:4] == b"RIFF"
    assert stub.calls == 1

    # Repeat: served from the on-disk variant cache — no DSM call, no re-encode.
    resp2 = _get(client, "xl", "image/webp,image/jpeg,*/*")
    assert resp2.headers["content-type"] == "image/webp"
    assert stub.calls == 1


def test_xl_without_webp_accept_stays_jpeg(webp_client):
    client, stub = webp_client
    resp = _get(client, "xl", "image/webp,*/*")
    assert stub.calls == 1
    # 같은 아이템을 webp 미지원 Accept로: 원본 캐시에서 JPEG 서빙(재페치 없음).
    resp2 = _get(client, "xl", "image/jpeg")
    assert resp2.status_code == 200
    assert resp2.headers["content-type"] == "image/jpeg"
    assert stub.calls == 1
    # 포맷이 다르면 ETag도 달라야 한다(Vary: Accept와 짝).
    assert resp.headers["etag"] != resp2.headers["etag"]


def test_sm_is_never_transcoded(webp_client):
    client, _ = webp_client
    resp = _get(client, "sm", "image/webp,*/*")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert "vary" not in resp.headers


def test_etag_304_roundtrip(webp_client):
    client, _ = webp_client
    resp = _get(client, "xl", "image/webp,*/*")
    etag = resp.headers["etag"]
    resp2 = client.get(
        "/api/photos/thumbnail",
        params={"space": "team", "id": "1", "cache_key": "ck", "size": "xl"},
        headers={"Accept": "image/webp,*/*", "If-None-Match": etag},
    )
    assert resp2.status_code == 304
