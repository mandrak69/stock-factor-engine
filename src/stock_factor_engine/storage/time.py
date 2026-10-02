from datetime import UTC, datetime


def timestamp(value: datetime) -> str:
    """Fixed-width UTC representation for SQLite timestamp ordering."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timestamp must be timezone-aware')
    return value.astimezone(UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')
