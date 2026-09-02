"""Synology Photos' epoch-shaped values are floating local wall-clocks."""

from datetime import date, datetime

import pytest

from app.photos.dsm_time import (
    date_from_epoch,
    day_range,
    decode_wall_clock,
    encode_wall_clock,
)


def test_decode_does_not_add_the_container_timezone_again():
    # DSM raw value observed for EXIF DateTimeOriginal 2020:02:25 12:20:49.
    raw = 1_582_633_249
    assert decode_wall_clock(raw) == datetime(2020, 2, 25, 12, 20, 49)
    assert date_from_epoch(raw) == date(2020, 2, 25)


def test_day_query_uses_floating_utc_boundaries():
    assert day_range(date(2020, 2, 25)) == (1_582_588_800, 1_582_675_200)


def test_user_wall_clock_round_trips_for_set_item_time():
    value = datetime(2020, 2, 25, 12, 20, 49)
    assert decode_wall_clock(encode_wall_clock(value)) == value


def test_aware_datetime_is_rejected_instead_of_silently_shifted():
    from datetime import timezone

    with pytest.raises(ValueError):
        encode_wall_clock(datetime(2020, 2, 25, tzinfo=timezone.utc))
