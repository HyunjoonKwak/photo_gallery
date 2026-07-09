"""Filename → capture-date parser (촬영일 교정의 자동 감지 핵심)."""

from datetime import datetime

import pytest

from app.photos.capture_date import parse_from_filename


@pytest.mark.parametrize(
    "name,expected",
    [
        # Screenshot with dashed date+time
        ("Screenshot_2016-05-10-19-41-17.jpg", datetime(2016, 5, 10, 19, 41, 17)),
        # IMG_YYYYMMDD_HHMMSS
        ("IMG_20170221_143022.jpg", datetime(2017, 2, 21, 14, 30, 22)),
        # 8-digit date only
        ("20240105_family.jpg", datetime(2024, 1, 5)),
        # dashed date only
        ("2019-08-15 여행.jpg", datetime(2019, 8, 15)),
        # underscore date
        ("2016_06_06_행사.png", datetime(2016, 6, 6)),
    ],
)
def test_parses_known_patterns(name, expected):
    assert parse_from_filename(name) == expected


@pytest.mark.parametrize(
    "name,epoch_s",
    [
        # 13-digit millisecond epoch (KakaoTalk/앱). Compare via fromtimestamp so
        # the assertion is timezone-independent (parser floors ms → seconds).
        ("1487654687945.jpg", 1487654687),
        ("1469950414226.jpg", 1469950414),
    ],
)
def test_parses_millisecond_epoch(name, epoch_s):
    assert parse_from_filename(name) == datetime.fromtimestamp(epoch_s)


@pytest.mark.parametrize(
    "name",
    [
        "IMG_5726.jpg",       # 짧은 카운터 — 날짜 아님
        "새_그림_(7).png",     # 날짜 없음
        "vacation.jpg",       # 날짜 없음
        "12345.jpg",          # 5자리 — 어떤 패턴도 아님
        "99999999.jpg",       # 8자리지만 유효 날짜 아님(연도 9999)
    ],
)
def test_rejects_without_confident_date(name):
    assert parse_from_filename(name) is None


def test_rejects_out_of_range_year():
    # 18000101 → year 1800 < 1990 하한
    assert parse_from_filename("18000101.jpg") is None


def test_does_not_match_inside_longer_digit_run():
    # 17-digit run should not be read as a 13-digit epoch fragment
    assert parse_from_filename("12345678901234567.jpg") is None
