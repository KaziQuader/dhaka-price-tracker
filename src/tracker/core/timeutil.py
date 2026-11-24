"""Time helpers. Timestamps are stored in UTC and shown in Asia/Dhaka (spec §5)."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

DHAKA = ZoneInfo("Asia/Dhaka")


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_dhaka(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("naive datetime: store and pass timestamps with a timezone")
    return ts.astimezone(DHAKA)


def dhaka_date(ts: datetime) -> date:
    """The calendar day in Dhaka. A run at 01:00 Dhaka time is still 'yesterday' in UTC."""
    return to_dhaka(ts).date()
