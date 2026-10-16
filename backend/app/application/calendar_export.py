"""Bounded RFC5545 export; UTC instants preserve the schedule's DST conversion."""

import hashlib
from datetime import UTC, datetime, timedelta

from ..domain.errors import ValidationError
from .reminder_plan import PlannedReminder


def _escape_text(value: str) -> str:
    """Escape patient-provided text for an RFC5545 TEXT property."""
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold_line(line: str, *, max_octets: int = 75) -> list[str]:
    """Fold UTF-8 lines without splitting a code point or exceeding 75 octets."""
    parts: list[str] = []
    current = ""
    current_octets = 0
    for character in line:
        size = len(character.encode("utf-8"))
        if current and current_octets + size > max_octets:
            parts.append(current)
            current = " "
            current_octets = 1
        current += character
        current_octets += size
    parts.append(current)
    return parts


def calendar_export(rows: list[PlannedReminder], *, now: datetime, lead_minutes: int) -> str:
    if len(rows) > 500:
        raise ValidationError("Choose a smaller calendar window")
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MediThread//Reminder Export//EN", "CALSCALE:GREGORIAN"]
    for row in rows:
        uid = hashlib.sha256(str(row.occurrence_id).encode()).hexdigest()
        due = (row.due_at if row.slot == "scheduled" else row.remind_at).astimezone(UTC)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}@pharmascan-care",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{due.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTEND:{(due + timedelta(minutes=5)).strftime('%Y%m%dT%H%M%SZ')}",
                f"SUMMARY:Medication reminder: {_escape_text(row.medication_name.strip() or 'Medication plan')}",
                "CLASS:PRIVATE",
                "DESCRIPTION:One-time import. Update or remove old events after plan changes.",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                "DESCRIPTION:Review medication plan",
                f"TRIGGER:-PT{lead_minutes if row.slot == 'scheduled' else 0}M",
                "END:VALARM",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    # RFC5545 requires physical lines to be folded at 75 octets, including
    # multi-byte patient medication names and the continuation whitespace.
    folded = []
    for line in lines:
        folded.extend(_fold_line(line))
    return "\r\n".join(folded) + "\r\n"
