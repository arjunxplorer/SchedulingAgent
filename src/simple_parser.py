"""Simple intent parser using regex — no AI needed for common tasks."""

import re
from datetime import datetime, timedelta
import pytz

timezone = pytz.timezone("America/Chicago")

# ── Date Parsing ──────────────────────────────────────────────────────────────

def _parse_date(text: str) -> str:
    """Parse natural language date into YYYY-MM-DD."""
    today = datetime.now(timezone)
    text = text.lower().strip()

    if "today" in text:
        return today.strftime("%Y-%m-%d")
    if "tomorrow" in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if "next week" in text:
        return "next_week"
    if "this week" in text:
        return "this_week"
    if re.search(r"\b(my|the)?\s*week\b", text):
        return "this_week"

    # Day names
    days = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    }
    for day_name, day_num in days.items():
        if day_name in text:
            current_day = today.weekday()
            days_ahead = (day_num - current_day) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next occurrence, not today
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # "in X days"
    m = re.search(r"in (\d+) days?", text)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")

    # Default: today
    return today.strftime("%Y-%m-%d")


def _parse_time(text: str) -> str | None:
    """Parse natural language time into HH:MM (24h). Returns None if not found."""
    text = text.lower().strip()

    # "at 2pm", "at 2:30pm", "at 14:00"
    m = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    # "2pm", "2:30pm"
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    # "14:00", "9:30"
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"

    return None


def _parse_duration(text: str) -> int:
    """Parse duration from text, default 60 minutes."""
    text = text.lower()

    # "for 30 minutes", "for 1 hour", "for 1.5 hours"
    m = re.search(r"for (\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)", text)
    if m:
        value = float(m.group(1))
        unit = m.group(2)
        if "hour" in unit or "hr" in unit:
            return int(value * 60)
        return int(value)

    # "30 min", "1 hour"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)", text)
    if m:
        value = float(m.group(1))
        unit = m.group(2)
        if "hour" in unit or "hr" in unit:
            return int(value * 60)
        return int(value)

    return 60  # Default 1 hour


def _extract_title(text: str) -> str:
    """Extract event title from text, removing time/date/action words."""
    # Remove common prefixes
    text = re.sub(r"^(schedule|add|create|set up|block|plan|book)\s+(a\s+)?", "", text, flags=re.IGNORECASE)
    # Remove time references
    text = re.sub(r"\s*(at|from|tomorrow|today|this\s+\w+|next\s+\w+|in\s+\d+\s+days?).*", "", text, flags=re.IGNORECASE)
    # Remove duration
    text = re.sub(r"\s*for\s+\d+.*", "", text, flags=re.IGNORECASE)
    # Clean up
    text = text.strip().strip(".,!?")
    return text.title() if text else "Event"


# ── Intent Classification ─────────────────────────────────────────────────────

class SimpleIntent:
    """Parsed intent from regex — no AI needed."""
    def __init__(self, action: str, **kwargs):
        self.action = action
        for k, v in kwargs.items():
            setattr(self, k, v)


def parse_simple_intent(text: str) -> SimpleIntent | None:
    """Try to parse a simple intent from text using regex.

    Returns SimpleIntent if it's a common task, None if complex (needs AI).
    """
    lower = text.lower().strip()

    # ── DELETE ────────────────────────────────────────────────────────────
    if re.match(r"^(delete|remove|cancel|clear)\b", lower):
        # "delete all events", "clear my calendar"
        if "all" in lower or "clear" in lower:
            return SimpleIntent(
                action="delete",
                target_event="all",
                date=_parse_date(lower),
            )
        # Extract target: "delete the 2pm meeting" → "2pm meeting"
        # "remove task finish homework" → "finish homework"
        target = re.sub(r"^(delete|remove|cancel)\s+(the\s+|my\s+|a\s+)?(task\s+|event\s+)?", "", lower)
        target = re.sub(r"\s*(for|on|at|tomorrow|today|this\s+\w+|next\s+\w+).*", "", target)
        return SimpleIntent(
            action="delete",
            target_event=target.strip().title(),
            date=_parse_date(lower),
        )

    # ── PLAN SCHEDULE ─────────────────────────────────────────────────────
    if re.match(r"^(help me (schedule|plan)|plan my|schedule my)\b", lower):
        return SimpleIntent(
            action="plan_schedule",
            query_date=_parse_date(lower),
        )

    # ── QUERY ─────────────────────────────────────────────────────────────
    if re.match(r"^(what('?s| is| are)|show|list|check|do i have|am i free)\b", lower):
        return SimpleIntent(
            action="query",
            query_date=_parse_date(lower),
        )

    # ── MODIFY ────────────────────────────────────────────────────────────
    if re.match(r"^(move|change|rename|update|shift|make it)\b", lower):
        # "move my meeting to 3pm" → modify, field=time
        if "move" in lower or "shift" in lower or "to " in lower:
            new_time = _parse_time(lower)
            target = re.sub(r"^(move|shift|change)\s+(the\s+)?", "", lower)
            target = re.sub(r"\s*(to|at|on|for|tomorrow|today).*", "", target)
            return SimpleIntent(
                action="modify",
                target_event=target.strip().title(),
                modify_field="time",
                modify_value=new_time or "",
                date=_parse_date(lower),
            )
        if "rename" in lower:
            new_name = re.sub(r"^(rename|change)\s+(the\s+)?\w+\s+(to|as)\s+", "", lower)
            return SimpleIntent(
                action="modify",
                target_event="",
                modify_field="title",
                modify_value=new_name.strip().title(),
                date=_parse_date(lower),
            )
        if "make it" in lower and ("longer" in lower or "shorter" in lower):
            return SimpleIntent(
                action="modify",
                target_event="",
                modify_field="duration",
                modify_value=lower,
                date=_parse_date(lower),
            )

    # ── CREATE TASK ───────────────────────────────────────────────────────
    if re.match(r"^(add|create|new)\b.*(to|my)\s*(list|tasks?|todo)", lower):
        task_title = re.sub(r"^(add|create|new)\s+", "", lower)
        task_title = re.sub(r"\s*(to|on|my)\s*(list|tasks?|todo).*", "", task_title)
        return SimpleIntent(
            action="create_task",
            task_title=task_title.strip().title(),
        )

    # ── CREATE EVENT (simple, with time) ──────────────────────────────────
    time = _parse_time(lower)
    if time and re.match(r"^(schedule|add|create|set up|block|book)\b", lower):
        title = _extract_title(lower)
        date = _parse_date(lower)
        duration = _parse_duration(lower)

        # Calculate end time
        h, m = map(int, time.split(":"))
        end_minutes = h * 60 + m + duration
        end_h, end_m = divmod(end_minutes, 60)
        end_time = f"{end_h:02d}:{end_m:02d}"

        return SimpleIntent(
            action="create_event",
            title=title,
            date=date,
            start_time=time,
            end_time=end_time,
        )

    # ── COMPLEX (needs AI) ────────────────────────────────────────────────
    return None
