"""Week windows. A report week is the 7 days (00:00 local time) before the send day."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Week:
    start: date  # first day of the window
    tz: ZoneInfo

    @property
    def key(self) -> str:
        return self.start.isoformat()

    @property
    def end(self) -> date:
        """First day after the window (exclusive)."""
        return self.start + timedelta(days=7)

    @property
    def last_day(self) -> date:
        return self.end - timedelta(days=1)

    def start_dt(self) -> datetime:
        return datetime.combine(self.start, time(0), self.tz)

    def end_dt(self) -> datetime:
        return datetime.combine(self.end, time(0), self.tz)

    def search_range(self) -> str:
        """Inclusive GitHub search range with local UTC offsets (DST-safe)."""
        a = self.start_dt().isoformat(timespec="seconds")
        b = (self.end_dt() - timedelta(seconds=1)).isoformat(timespec="seconds")
        return f"{a}..{b}"

    def prev(self, n: int = 1) -> "Week":
        return Week(self.start - timedelta(days=7 * n), self.tz)

    def contains(self, moment: datetime) -> bool:
        return self.start_dt() <= moment < self.end_dt()

    def label(self) -> str:
        a, b = self.start, self.last_day
        if a.year != b.year:
            return f"{a:%b} {a.day}, {a.year} – {b:%b} {b.day}, {b.year}"
        if a.month != b.month:
            return f"{a:%b} {a.day} – {b:%b} {b.day}, {b.year}"
        return f"{a:%b} {a.day} – {b.day}, {b.year}"

    def short_label(self) -> str:
        a, b = self.start, self.last_day
        if a.month != b.month:
            return f"{a:%b} {a.day} – {b:%b} {b.day}"
        return f"{a:%b} {a.day} – {b.day}"


def due_week(now: datetime, tz: ZoneInfo, send_weekday: int = 0, send_hour: int = 7) -> Week:
    """The week whose report is due at `now`.

    The report for a week is due at `send_hour` on the send day right after it.
    The returned week always covers the 7 days before the latest send time that has passed.
    """
    local = now.astimezone(tz)
    days_back = (local.weekday() - send_weekday) % 7
    send_day = local.date() - timedelta(days=days_back)
    if days_back == 0 and local.time() < time(send_hour):
        send_day -= timedelta(days=7)
    return Week(send_day - timedelta(days=7), tz)


def week_from_key(key: str, tz: ZoneInfo) -> Week:
    return Week(date.fromisoformat(key), tz)


def local_date(iso_ts: str, tz: ZoneInfo) -> str:
    """ISO timestamp (any offset, or Z) -> local calendar date string."""
    ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return ts.astimezone(tz).date().isoformat()
