"""Unit tests for the deterministic mock photo source."""

import pytest
from fastapi import HTTPException

from app.photos.mock import MockPhotoSource

source = MockPhotoSource()


async def test_buckets_are_deterministic_and_sorted_desc():
    a = await source.buckets("personal")
    b = await source.buckets("personal")
    assert [(x.day, x.count) for x in a] == [(x.day, x.count) for x in b]
    days = [x.day for x in a]
    assert days == sorted(days, reverse=True)
    assert all(x.count > 0 for x in a)
    assert len(a) > 100  # ~18 months with ~65% non-empty days


async def test_spaces_have_different_data():
    p = await source.buckets("personal")
    t = await source.buckets("team")
    assert [(x.day, x.count) for x in p] != [(x.day, x.count) for x in t]


async def test_items_count_matches_bucket_count():
    buckets = await source.buckets("team")
    for bucket in buckets[:5]:
        items = await source.items("team", bucket.day)
        assert len(items) == bucket.count
        order = [(item.taken_at, item.id) for item in items]
        assert order == sorted(order, reverse=True)


async def test_item_fields_are_plausible():
    buckets = await source.buckets("personal")
    items = await source.items("personal", buckets[0].day)
    it = items[0]
    assert it.id.startswith("m-personal-")
    assert it.width > 0 and it.height > 0
    assert it.taken_at.startswith(buckets[0].day)
    assert it.placeholder_color and it.placeholder_color.startswith("hsl(")


async def test_thumbnail_returns_svg_for_valid_id():
    buckets = await source.buckets("team")
    items = await source.items("team", buckets[0].day)
    content, media_type = await source.thumbnail("team", items[0].id, "mock", "sm")
    assert media_type == "image/svg+xml"
    assert content.startswith(b"<svg")


async def test_thumbnail_xl_includes_filename_label():
    buckets = await source.buckets("team")
    items = await source.items("team", buckets[0].day)
    content, _ = await source.thumbnail("team", items[0].id, "mock", "xl")
    assert items[0].filename.encode() in content


async def test_thumbnail_invalid_id_raises_404():
    with pytest.raises(HTTPException) as excinfo:
        await source.thumbnail("team", "not-a-valid-id", "mock", "sm")
    assert excinfo.value.status_code == 404


async def test_folders_cover_both_spaces():
    folders = await source.folders()
    spaces = {f.space for f in folders}
    assert spaces == {"personal", "team"}
