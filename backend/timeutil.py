
from datetime import datetime, timezone


UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now() -> str:
    """Return the current UTC timestamp in canonical whole-second format."""
    return datetime.now(timezone.utc).strftime(UTC_FORMAT)


def parse_utc(value: str) -> datetime:
    """
    Parse a canonical UTC timestamp.

    Rejects malformed timestamps and impossible calendar dates.
    """
    if not isinstance(value, str):
        raise TypeError("Timestamp must be a string.")

    try:
        parsed = datetime.strptime(value, UTC_FORMAT)
    except ValueError as exc:
        raise ValueError(
            "Timestamp must use YYYY-MM-DDTHH:MM:SSZ "
            "and contain a valid calendar date."
        ) from exc

    # Enforce exact canonical formatting.
    if parsed.strftime(UTC_FORMAT) != value:
        raise ValueError("Timestamp is not in canonical UTC format.")

    return parsed.replace(tzinfo=timezone.utc)


def is_valid_utc(value: str) -> bool:
    """Return whether a value is a valid canonical UTC timestamp."""
    try:
        parse_utc(value)
        return True
    except (TypeError, ValueError):
        return False


def utc_to_datetime(value: str) -> datetime:
    """Convert a canonical UTC timestamp to an aware datetime."""
    return parse_utc(value)


def datetime_to_utc(value: datetime) -> str:
    """Convert an aware datetime to canonical UTC format."""
    if not isinstance(value, datetime):
        raise TypeError("Value must be a datetime object.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must be timezone-aware.")

    return value.astimezone(timezone.utc).strftime(UTC_FORMAT)
