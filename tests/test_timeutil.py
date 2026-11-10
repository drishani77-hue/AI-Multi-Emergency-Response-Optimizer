
from datetime import datetime, timezone, timedelta

import pytest

from backend.timeutil import (
    utc_now,
    parse_utc,
    is_valid_utc,
    datetime_to_utc,
)


def test_utc_now_returns_canonical_timestamp():
    value = utc_now()
    parsed = parse_utc(value)

    assert parsed.tzinfo == timezone.utc
    assert is_valid_utc(value)


@pytest.mark.parametrize(
    "value",
    [
        "2024-02-29T12:30:45Z",
        "2026-11-11T00:00:00Z",
        "2000-01-01T00:00:00Z",
    ],
)
def test_valid_timestamps(value):
    assert is_valid_utc(value)


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-29T12:30:45Z",
        "2100-02-29T12:30:45Z",
        "2026-04-31T12:30:45Z",
        "2026-06-15",
        "2026-11-11T12:30:45+00:00",
        "",
    ],
)
def test_invalid_timestamps(value):
    assert not is_valid_utc(value)


def test_parse_utc_rejects_non_string():
    with pytest.raises(TypeError):
        parse_utc(None)


def test_datetime_to_utc_converts_timezone():
    value = datetime(
        2026, 11, 11, 10, 0, 0,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert datetime_to_utc(value) == "2026-11-11T04:30:00Z"


def test_datetime_to_utc_rejects_naive_datetime():
    with pytest.raises(ValueError):
        datetime_to_utc(datetime(2026, 11, 11, 10, 0, 0))
