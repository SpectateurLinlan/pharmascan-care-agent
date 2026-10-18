"""Pure calendar interpretation; unsupported dates never silently mean today."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DATE_PATTERN = r"\b\d{4}-\d{1,2}-\d{1,2}\b|\d{4}年\d{1,2}月\d{1,2}日"
RELATIVE_PATTERN = r"\byesterday\b|\btoday\b|昨天|昨日|今天|今日|前天"


@dataclass(frozen=True)
class CalendarSelection:
    day: date
    explicit: bool = False
    supported: bool = True


def calendar_selection(text: str, now: datetime, timezone: str) -> CalendarSelection:
    today = now.astimezone(ZoneInfo(timezone)).date()
    days: set[date] = set()
    for value in re.findall(DATE_PATTERN, text):
        try:
            days.add(date(*map(int, re.findall(r"\d+", value))))
        except ValueError:
            return CalendarSelection(today, explicit=True, supported=False)
    for value in re.findall(RELATIVE_PATTERN, text.lower()):
        offset = -2 if value == "前天" else -1 if value in {"yesterday", "昨天", "昨日"} else 0
        days.add(today + timedelta(days=offset))
    remainder = re.sub(DATE_PATTERN, " ", text.lower())
    unsupported = bool(
        re.search(
            r"明天|后天|上周|上个月|昨晚|去年|last night|tomorrow|last month|last week|last year|"
            r"\d+\s+days?\s+ago|\d+天前|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
            r"上星期|上个月|前几天|\d{1,2}月\d{1,2}[日号]|\d{1,2}号|"
            r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
            r"sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
            remainder,
        )
    )
    day = next(iter(days)) if len(days) == 1 else today
    return CalendarSelection(day, bool(days) or unsupported, not unsupported and len(days) <= 1 and day <= today)


def local_day_window(day: date, timezone: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    return (
        datetime.combine(day, time.min, zone).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC),
    )


def without_calendar_words(text: str) -> str:
    return re.sub(RELATIVE_PATTERN, " ", re.sub(DATE_PATTERN, " ", text), flags=re.IGNORECASE)
