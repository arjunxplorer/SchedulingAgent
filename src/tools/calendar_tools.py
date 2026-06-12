from datetime import datetime, timedelta
from typing import List, Dict, Any
import json
import threading
import pytz
import os
from dateutil.parser import isoparse

# Models
from src.models import CalendarModel, CalendarEvent, TaskListModel, TaskModel

# Agents and tools
from langchain.tools import tool

# Google API client libraries
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

timezone = pytz.timezone("America/Chicago")
# Scopes for API access
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]

# The port that matches your Google Cloud Console configuration
OAUTH_PORT = 8080

# Lazy-initialized service singletons (thread-safe)
_calendar_service = None
_tasks_service = None
_service_lock = threading.Lock()

# Per-thread web context flag — safe under concurrent requests
_thread_context = threading.local()


def _get_web_context() -> bool:
    return getattr(_thread_context, "web_context", False)


def _set_web_context(value: bool):
    _thread_context.web_context = value


def get_calendar_service():
    """Get or create the Google Calendar API service (thread-safe lazy singleton)."""
    global _calendar_service
    if _calendar_service is not None:
        return _calendar_service
    with _service_lock:
        if _calendar_service is not None:
            return _calendar_service
        creds = _authenticate()
        _calendar_service = build("calendar", "v3", credentials=creds)
        return _calendar_service


def get_tasks_service():
    """Get or create the Google Tasks API service (thread-safe lazy singleton)."""
    global _tasks_service
    if _tasks_service is not None:
        return _tasks_service
    with _service_lock:
        if _tasks_service is not None:
            return _tasks_service
        creds = _authenticate()
        _tasks_service = build("tasks", "v1", credentials=creds)
        return _tasks_service


def _authenticate():
    """Run OAuth flow and return valid credentials.

    Supports two modes:
    1. Saved token: token.json exists from a previous login
    2. Client secrets in env: GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in .env

    When called from the web API layer (_get_web_context()), does NOT fall through to
    run_local_server() — instead raises FileNotFoundError so the API can return
    a proper 401. For the web UI, use /auth/login instead (browser-based OAuth).
    """
    creds = None

    # Check for existing token
    if os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_info(
                json.loads(open("token.json").read()), SCOPES
            )
        except Exception as e:
            print(f"Error loading existing token: {e}")
            if os.path.exists("token.json"):
                os.remove("token.json")

    # Try to refresh expired token
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
        except Exception as e:
            print(f"Error refreshing token: {e}")
            creds = None

    # If still no valid creds, try env-based client secrets
    if not creds or not creds.valid:
        if _get_web_context():
            raise FileNotFoundError(
                "No valid Google credentials. Please authenticate via the web UI (/auth/login)."
            )

        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

        if client_id and client_secret:
            creds = _oauth_from_env(client_id, client_secret)
        elif os.path.exists("credentials.json"):
            # Fallback: legacy credentials.json file
            creds = _oauth_from_file("credentials.json")
        else:
            raise FileNotFoundError(
                "No Google credentials found. Either:\n"
                "  1. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env, or\n"
                "  2. Place credentials.json in the project root, or\n"
                "  3. Use the web UI to authenticate via /auth/login"
            )

    print("Authentication successful!")
    return creds


def _save_token(creds):
    """Save credentials to token.json."""
    with open("token.json", "w") as f:
        f.write(creds.to_json())


def _oauth_from_env(client_id: str, client_secret: str):
    """Run OAuth flow using client ID/secret from environment variables."""
    redirect_uri = f"http://localhost:{OAUTH_PORT}/"
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }

    print(f"Starting OAuth flow on port {OAUTH_PORT}...")
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES, redirect_uri=redirect_uri)
    creds = flow.run_local_server(
        port=OAUTH_PORT,
        success_message="Authentication successful! You can close this window.",
        open_browser=True,
    )
    _save_token(creds)
    return creds


def _oauth_from_file(path: str):
    """Run OAuth flow using a credentials.json file."""
    redirect_uri = f"http://localhost:{OAUTH_PORT}/"
    print(f"Starting OAuth flow on port {OAUTH_PORT}...")
    flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES, redirect_uri=redirect_uri)
    creds = flow.run_local_server(
        port=OAUTH_PORT,
        success_message="Authentication successful! You can close this window.",
        open_browser=True,
    )
    _save_token(creds)
    return creds


@tool
def create_calendar_events(calendar_events:list[dict[str, str]]):
    """Creates all new calendar events at once given in a list with the summary, start_time and end_time

    Args:
        calendar_events (list): List of calendar events.
            Each calendar event is a dictionary with the following attributes:
                summary (str): Summary of the event.
                start_time (str): Start time in ISO format.
                end_time (str): End time in ISO format.
    """
    print("Creating events...")
    created_events = []
    for event in calendar_events:
        created_event = create_calendar_event.invoke(event)
        created_events.append(created_event)

    return created_events

def check_time_conflict(
    calendar_id: str,
    start_time: str,
    end_time: str,
    date: datetime
) -> tuple[bool, list[dict]]:
    """Check if there are any time conflicts with existing events.

    Args:
        calendar_id (str): Calendar ID to check
        start_time (str): Start time in ISO format
        end_time (str): End time in ISO format
        date (datetime): Date to check conflicts for

    Returns:
        tuple[bool, list[dict]]: (has_conflict, conflicting_events)
    """
    calendar_service = get_calendar_service()

    # Ensure date is timezone-aware for Google Calendar API
    if date.tzinfo is None:
        date = timezone.localize(date)

    # Convert times to timezone-aware datetime objects
    new_start = isoparse(start_time)
    new_end = isoparse(end_time)
    if new_start.tzinfo is None:
        new_start = timezone.localize(new_start)
    if new_end.tzinfo is None:
        new_end = timezone.localize(new_end)

    # Get all events for the day
    day_events = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=date.replace(hour=0, minute=0, second=0).isoformat(),
        timeMax=date.replace(hour=23, minute=59, second=59).isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute().get("items", [])

    # Check for conflicts
    conflicting_events = []
    for ev in day_events:
        if "dateTime" in ev["start"]:  # Skip all-day events
            ev_start = isoparse(ev["start"]["dateTime"])
            ev_end = isoparse(ev["end"]["dateTime"])

            # Check if there's any overlap
            if (new_start < ev_end and new_end > ev_start):
                conflicting_events.append({
                    "summary": ev.get("summary", "(no title)"),
                    "start": ev_start.strftime("%I:%M %p").lstrip("0"),
                    "end": ev_end.strftime("%I:%M %p").lstrip("0")
                })

    return len(conflicting_events) > 0, conflicting_events

def format_day_events(day_events: list[dict], date: datetime) -> str:
    """Format a list of events for display.

    Args:
        day_events (list[dict]): List of events
        date (datetime): Date of the events

    Returns:
        str: Formatted string of events
    """
    resp_lines = [f"📅 Here's your schedule for {date.strftime('%Y-%m-%d')}:"]
    for ev in day_events:
        # start might be all-day (date) or dateTime
        raw_start = ev["start"].get("dateTime", ev["start"].get("date"))
        raw_end = ev["end"].get("dateTime", ev["end"].get("date"))
        dt_start = isoparse(raw_start)
        dt_end = isoparse(raw_end)
        if "dateTime" in ev["start"]:
            time_str = f"{dt_start.strftime('%I:%M %p').lstrip('0')} - {dt_end.strftime('%I:%M %p').lstrip('0')}"
        else:
            time_str = "All day"
        summary = ev.get("summary", "(no title)")
        resp_lines.append(f" • {time_str} — {summary}")

    return "\n".join(resp_lines)

def find_and_delete_event(
    calendar_id: str,
    summary: str,
    date: datetime
) -> tuple[bool, str, list[dict]]:
    """Find and delete an event based on summary and date.

    Args:
        calendar_id (str): Calendar ID to check
        summary (str): Event summary to match
        date (datetime): Date to search in

    Returns:
        tuple[bool, str, list[dict]]: (success, message, remaining_events)
    """
    try:
        calendar_service = get_calendar_service()

        # Ensure date is timezone-aware for Google Calendar API
        if date.tzinfo is None:
            date = timezone.localize(date)

        # Get all events for the day
        day_events = calendar_service.events().list(
            calendarId=calendar_id,
            timeMin=date.replace(hour=0, minute=0, second=0).isoformat(),
            timeMax=date.replace(hour=23, minute=59, second=59).isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])

        # Find matching events
        matching_events = []
        remaining_events = []

        for ev in day_events:
            if summary.lower() in ev.get("summary", "").lower():
                matching_events.append(ev)
            else:
                remaining_events.append(ev)

        if not matching_events:
            return False, f"No events found matching '{summary}' on {date.strftime('%Y-%m-%d')}", []

        # Delete matching events
        for ev in matching_events:
            calendar_service.events().delete(
                calendarId=calendar_id,
                eventId=ev["id"]
            ).execute()

        # Format response
        if len(matching_events) == 1:
            message = f"✅ Removed event: {matching_events[0].get('summary')}"
        else:
            message = f"✅ Removed {len(matching_events)} events matching '{summary}'"

        return True, message, remaining_events

    except Exception as e:
        return False, f"Error deleting event: {str(e)}", []

@tool
def create_calendar_event(
    summary: str, start_time: str, end_time: str
) -> Dict[str, Any]:
    """Create a new calendar event.

    Args:
        summary (str): Summary of the event.
        start_time (str): Start time in ISO format.
        end_time (str): End time in ISO format.
    """
    calendar_service = get_calendar_service()

    # Check if this is a removal request
    if summary.lower().startswith(("remove", "delete", "cancel")):
        # Extract the event name from the summary
        event_name = " ".join(summary.split()[1:])  # Remove the first word (remove/delete/cancel)

        # Extract date from start_time and convert to timezone-aware datetime
        event_date = datetime.fromisoformat(start_time.split('T')[0])
        event_date = timezone.localize(event_date)

        # Get the primary calendar ID
        calendar_id = "primary"  # Use primary calendar by default
        if os.getenv("CALENDAR_ID"):
            calendar_id = os.getenv("CALENDAR_ID")
            if "calendar.google.com" in calendar_id:
                calendar_id = calendar_id.split("src=")[1].split("&")[0]
                calendar_id = calendar_id.replace("%40", "@")

        # Try to find and delete the event
        success, message, remaining_events = find_and_delete_event(calendar_id, event_name, event_date)

        if success:
            # Format the remaining events
            resp_lines = [message]
            if remaining_events:
                resp_lines.append(format_day_events(remaining_events, event_date))
            return {
                "success": True,
                "message": "\n".join(resp_lines)
            }
        else:
            return {
                "error": True,
                "message": message
            }

    print(f"Creating new event '{summary}'...")

    # Create event body
    event_body = {
        "summary": summary,
        "start": {"dateTime": start_time, "timeZone": str(timezone)},
        "end": {"dateTime": end_time, "timeZone": str(timezone)},
    }

    # Get the primary calendar ID
    calendar_id = "primary"  # Use primary calendar by default
    if os.getenv("CALENDAR_ID"):
        calendar_id = os.getenv("CALENDAR_ID")
        # If it's a full URL, extract just the email part
        if "calendar.google.com" in calendar_id:
            calendar_id = calendar_id.split("src=")[1].split("&")[0]
            calendar_id = calendar_id.replace("%40", "@")

        # Verify the calendar exists
        try:
            calendar_service.calendars().get(calendarId=calendar_id).execute()
        except Exception as e:
            print(f"Warning: Could not access calendar {calendar_id}. Falling back to primary calendar.")
            calendar_id = "primary"

    try:
        # Extract date from start_time and convert to timezone-aware datetime
        event_date = datetime.fromisoformat(start_time.split('T')[0])
        event_date = timezone.localize(event_date)

        # Check for time conflicts
        has_conflict, conflicting_events = check_time_conflict(
            calendar_id, start_time, end_time, event_date
        )

        if has_conflict:
            # Format the conflicting events message
            conflict_msg = ["⚠️ Time conflict detected! The following events overlap with your requested time:"]
            for ev in conflicting_events:
                conflict_msg.append(f" • {ev['start']} - {ev['end']} — {ev['summary']}")

            # Suggest alternative times
            suggestions = suggest_alternative_times.invoke({
                "date": event_date.strftime("%Y-%m-%d"),
                "start_time": start_time.split("T")[1][:5] if "T" in start_time else start_time,
                "end_time": end_time.split("T")[1][:5] if "T" in end_time else end_time,
            })

            if suggestions:
                conflict_msg.append("\nSuggested alternatives:")
                for s in suggestions:
                    conflict_msg.append(f"  • {s['display']}")
            else:
                conflict_msg.append("\nNo free slots found for this duration today.")

            return {
                "error": True,
                "message": "\n".join(conflict_msg),
                "conflicting_events": conflicting_events,
                "suggestions": suggestions,
            }

        # Get current day's events for display
        day_events = calendar_service.events().list(
            calendarId=calendar_id,
            timeMin=event_date.replace(hour=0, minute=0, second=0).isoformat(),
            timeMax=event_date.replace(hour=23, minute=59, second=59).isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])

        # Insert new event (retry on SSL errors with fresh connection)
        for attempt in range(3):
            try:
                created_event = (
                    calendar_service.events()
                    .insert(calendarId=calendar_id, body=event_body)
                    .execute()
                )
                break
            except Exception as e:
                if "SSL" in str(e) or "WRONG_VERSION_NUMBER" in str(e):
                    print(f"SSL error on attempt {attempt+1}, retrying with fresh connection...")
                    # Force a fresh HTTP connection
                    import httplib2
                    calendar_service._http = httplib2.Http()
                    if attempt == 2:
                        raise
                else:
                    raise

        print(f"Event created: {created_event['htmlLink']}")

        # Add the new event to the list for display
        day_events.append(created_event)
        # Sort events by start time (skip events without valid start)
        def _sort_key(x):
            raw = x.get("start", {}).get("dateTime") or x.get("start", {}).get("date")
            if not raw:
                return datetime.min.replace(tzinfo=timezone)
            dt = isoparse(raw)
            if dt.tzinfo is None:
                dt = timezone.localize(dt)
            return dt
        day_events.sort(key=_sort_key)

        # Build response string
        resp_lines = [f"✅ Added {created_event.get('summary','(no title)')}."]
        resp_lines.append(format_day_events(day_events, event_date))

        # Add the formatted response to the return value
        created_event['formatted_response'] = "\n".join(resp_lines)
        return created_event

    except Exception as e:
        print(f"Error creating event: {str(e)}")
        raise


def list_calendars() -> List[Dict[str, Any]]:
    """List all calendars."""
    calendar_service = get_calendar_service()
    calendars_result = calendar_service.calendarList().list().execute()
    calendars = [
        CalendarModel(id=calendar["id"], summary=calendar["summary"])
        for calendar in calendars_result.get("items", [])
    ]
    return calendars


def get_calendar_events(id=None, date=None) -> List[CalendarEvent]:
    """Fetch calendar events for the specified date (today by default).

    Args:
        id (str): Calendar ID. Defaults to 'CALENDAR_ID' env var or 'primary'.
        date (datetime): Date for which to fetch events. Defaults to today.
    """
    if id is None:
        id = os.getenv("CALENDAR_ID", "primary")
    calendar_service = get_calendar_service()

    if not date:
        date = datetime.now(timezone)

    # Set time boundaries for the day
    start_time = date.replace(hour=0, minute=0, second=0).isoformat()
    end_time = date.replace(hour=23, minute=59, second=59).isoformat()

    events_result = (
        calendar_service.events()
        .list(
            calendarId=id,
            timeMin=start_time,
            timeMax=end_time,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = [
        CalendarEvent(
            id=event["id"],
            summary=event.get("summary", "No summary"),
            start=event["start"].get("dateTime", event["start"].get("date")),
            end=event["end"].get("dateTime", event["end"].get("date")),
        )
        for event in events_result.get("items", [])
    ]

    return events


def list_tasks() -> List[Dict[str, Any]]:
    """List all task lists."""
    tasks_service = get_tasks_service()
    tasklists_result = tasks_service.tasklists().list().execute()
    tasklists = [
        TaskListModel(title=task_list["title"], id=task_list["id"])
        for task_list in tasklists_result.get("items", [])
    ]
    return tasklists


def get_tasks(task_list_id:str="@default") -> List[Dict[str, Any]]:
    """Fetch tasks from a specific task list.

    Args:
        task_list_id (str): The id of the task list to get the tasks from.
    """
    tasks_service = get_tasks_service()

    # Get incomplete tasks
    tasks_result = (
        tasks_service.tasks()
        .list(
            tasklist=task_list_id,
            showCompleted=False,
            showHidden=False,
            showDeleted=False,
        )
        .execute()
    )

    tasks = tasks_result.get("items", [])

    tasks = [
        TaskModel(
            id=task["id"],
            title=task["title"],
            notes=task.get("notes", ""),
            due_date=task.get("due", "No due date"),
        )
        for task in tasks
    ]

    return tasks

def test_calendar_access():
    """Test function to verify calendar access and list available calendars."""
    try:
        calendar_service = get_calendar_service()

        # List all calendars
        calendar_list = calendar_service.calendarList().list().execute()
        print("\nAvailable calendars:")
        for calendar in calendar_list.get('items', []):
            print(f"- {calendar['summary']} (ID: {calendar['id']})")

        # Try to access primary calendar
        primary_calendar = calendar_service.calendars().get(calendarId='primary').execute()
        print(f"\nPrimary calendar access successful: {primary_calendar['summary']}")

        return True
    except Exception as e:
        print(f"\nError testing calendar access: {str(e)}")
        return False

@tool
def clear_calendar_events(calendar_id: str = "primary") -> bool:
    """Clear all events from the specified calendar.

    Args:
        calendar_id (str): The calendar ID to clear. Defaults to primary calendar.
    """
    try:
        calendar_service = get_calendar_service()

        # Get all events
        events_result = calendar_service.events().list(calendarId=calendar_id).execute()
        events = events_result.get('items', [])

        # Delete each event
        for event in events:
            calendar_service.events().delete(
                calendarId=calendar_id,
                eventId=event['id']
            ).execute()

        print(f"Successfully cleared {len(events)} events from calendar")
        return True
    except Exception as e:
        print(f"Error clearing calendar: {str(e)}")
        return False

@tool
def create_daily_schedule(events: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Create multiple calendar events for a daily schedule.

    Args:
        events (List[Dict[str, str]]): List of events with summary, start_time, and end_time
    """
    try:
        created_events = []
        for event in events:
            created_event = create_calendar_event(
                summary=event['summary'],
                start_time=event['start_time'],
                end_time=event['end_time']
            )
            created_events.append(created_event)
        return created_events
    except Exception as e:
        print(f"Error creating schedule: {str(e)}")
        return []

def format_schedule_for_calendar(schedule_text: str) -> List[Dict[str, str]]:
    """Convert schedule text into calendar event format.

    Args:
        schedule_text (str): Schedule text in the format:
            **YYYY-MM-DD HH:MM - YYYY-MM-DD HH:MM**: Event name
    """
    events = []
    for line in schedule_text.split('\n'):
        if '**' in line and '**:' in line:
            # Extract time and event name
            time_part = line.split('**:')[0].strip('*')
            event_name = line.split('**:')[1].strip()

            # Parse times
            start_time, end_time = time_part.split(' - ')

            # Convert to ISO format
            start_dt = datetime.strptime(start_time.strip(), '%Y-%m-%d %H:%M')
            end_dt = datetime.strptime(end_time.strip(), '%Y-%m-%d %H:%M')

            # Add timezone
            start_dt = timezone.localize(start_dt)
            end_dt = timezone.localize(end_dt)

            events.append({
                'summary': event_name,
                'start_time': start_dt.isoformat(),
                'end_time': end_dt.isoformat()
            })

    return events

@tool
def find_free_slots(date: str, duration_minutes: int = 60) -> list[dict]:
    """Find available time slots on a given date that fit a requested duration.

    Args:
        date (str): Date in YYYY-MM-DD format
        duration_minutes (int): Required slot duration in minutes (default 60)
    """
    calendar_service = get_calendar_service()
    calendar_id = os.getenv("CALENDAR_ID", "primary")

    day = datetime.fromisoformat(date)
    day = timezone.localize(day)

    # Get all events for the day
    day_events = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=day.replace(hour=0, minute=0, second=0).isoformat(),
        timeMax=day.replace(hour=23, minute=59, second=59).isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute().get("items", [])

    # Build list of busy intervals (skip all-day events, strip tzinfo for naive comparison)
    busy = []
    for ev in day_events:
        if "dateTime" in ev["start"]:
            ev_start = isoparse(ev["start"]["dateTime"])
            ev_end = isoparse(ev["end"]["dateTime"])
            # Strip timezone for consistent naive comparison
            if ev_start.tzinfo is not None:
                ev_start = ev_start.replace(tzinfo=None)
            if ev_end.tzinfo is not None:
                ev_end = ev_end.replace(tzinfo=None)
            busy.append({"start": ev_start, "end": ev_end})

    # Sort by start time
    busy.sort(key=lambda x: x["start"])

    # Find gaps between events (8am - 10pm window)
    # Use naive datetimes to match isoparse() output (naive from ISO strings)
    day_naive = day.replace(tzinfo=None)
    day_start = day_naive.replace(hour=8, minute=0, second=0)
    day_end = day_naive.replace(hour=22, minute=0, second=0)
    required = timedelta(minutes=duration_minutes)

    free_slots = []
    cursor = day_start

    for b in busy:
        if b["start"] - cursor >= required:
            free_slots.append({
                "start": cursor.strftime("%H:%M"),
                "end": b["start"].strftime("%H:%M"),
                "duration_minutes": int((b["start"] - cursor).total_seconds() / 60),
            })
        cursor = max(cursor, b["end"])

    # Check gap after last event
    if day_end - cursor >= required:
        free_slots.append({
            "start": cursor.strftime("%H:%M"),
            "end": day_end.strftime("%H:%M"),
            "duration_minutes": int((day_end - cursor).total_seconds() / 60),
        })

    return free_slots


@tool
def create_task(title: str, notes: str = "", due: str = "") -> dict:
    """Create a new task in Google Tasks.

    Args:
        title (str): Task title
        notes (str): Optional task notes
        due (str): Optional due date in ISO format (YYYY-MM-DD or full ISO datetime)
    """
    tasks_service = get_tasks_service()

    task_body = {"title": title}
    if notes:
        task_body["notes"] = notes
    if due:
        # Google Tasks expects RFC 3339 format for due date
        if "T" not in due:
            due_dt = datetime.fromisoformat(due)
            due_dt = timezone.localize(due_dt)
            task_body["due"] = due_dt.isoformat()
        else:
            task_body["due"] = due

    result = tasks_service.tasks().insert(
        tasklist="@default",
        body=task_body
    ).execute()

    return {
        "success": True,
        "message": f"✅ Task created: {result.get('title')}",
        "task_id": result.get("id"),
    }


@tool
def delete_task(title: str) -> dict:
    """Delete a task from Google Tasks by title.

    Args:
        title (str): Title (or partial title) of the task to delete
    """
    tasks_service = get_tasks_service()

    # List all tasks
    result = tasks_service.tasks().list(
        tasklist="@default",
        showCompleted=True,
        maxResults=100,
    ).execute()

    tasks = result.get("items", [])
    title_lower = title.lower().strip()

    # Find matching tasks
    deleted = []
    for task in tasks:
        task_title = task.get("title", "").lower()
        if title_lower in task_title or task_title in title_lower:
            tasks_service.tasks().delete(
                tasklist="@default",
                task=task["id"],
            ).execute()
            deleted.append(task.get("title", "Unknown"))

    if deleted:
        return {
            "success": True,
            "message": f"✅ Deleted task: {', '.join(deleted)}",
        }
    else:
        return {
            "success": False,
            "message": f"❌ No task found matching '{title}'",
        }


@tool
def suggest_alternative_times(date: str, start_time: str, end_time: str, num_suggestions: int = 3) -> list[dict]:
    """Suggest alternative time slots when a conflict is detected.

    Args:
        date (str): Date in YYYY-MM-DD format
        start_time (str): Original requested start time in HH:MM format
        end_time (str): Original requested end time in HH:MM format
        num_suggestions (int): Number of alternatives to suggest (default 3)
    """
    # Calculate duration from the requested times
    start_dt = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(f"{date} {end_time}", "%Y-%m-%d %H:%M")
    duration = int((end_dt - start_dt).total_seconds() / 60)

    # Find all free slots that fit the duration
    free_slots = find_free_slots.invoke({
        "date": date,
        "duration_minutes": duration,
    })

    if not free_slots:
        return []

    # Sort by proximity to the originally requested time
    requested_minutes = start_dt.hour * 60 + start_dt.minute

    def distance(slot):
        slot_minutes = int(slot["start"].split(":")[0]) * 60 + int(slot["start"].split(":")[1])
        return abs(slot_minutes - requested_minutes)

    free_slots.sort(key=distance)

    # Return the closest N suggestions with formatted times
    suggestions = []
    for slot in free_slots[:num_suggestions]:
        s_hour, s_min = slot["start"].split(":")
        e_hour, e_min = slot["end"].split(":")
        s_dt = datetime.strptime(f"{date} {slot['start']}", "%Y-%m-%d %H:%M")
        e_dt = datetime.strptime(f"{date} {slot['end']}", "%Y-%m-%d %H:%M")
        # Cap the end time to the original duration
        capped_end = s_dt + timedelta(minutes=duration)
        if capped_end > e_dt:
            continue
        suggestions.append({
            "start_time": slot["start"],
            "end_time": capped_end.strftime("%H:%M"),
            "display": f"{s_dt.strftime('%I:%M %p').lstrip('0')} - {capped_end.strftime('%I:%M %p').lstrip('0')}",
        })

    return suggestions


@tool
def update_calendar_event(event_id: str, summary: str = "", start_time: str = "", end_time: str = "") -> dict:
    """Update an existing calendar event. Only provided fields are changed.

    Args:
        event_id (str): The Google Calendar event ID
        summary (str): New summary (empty = don't change)
        start_time (str): New start time in ISO format (empty = don't change)
        end_time (str): New end time in ISO format (empty = don't change)
    """
    calendar_service = get_calendar_service()
    calendar_id = os.getenv("CALENDAR_ID", "primary")

    # Fetch existing event
    event = calendar_service.events().get(
        calendarId=calendar_id, eventId=event_id
    ).execute()

    if summary:
        event["summary"] = summary
    if start_time:
        event["start"] = {"dateTime": start_time, "timeZone": str(timezone)}
    if end_time:
        event["end"] = {"dateTime": end_time, "timeZone": str(timezone)}

    updated = calendar_service.events().update(
        calendarId=calendar_id,
        eventId=event_id,
        body=event,
    ).execute()

    return {
        "success": True,
        "message": f"✅ Updated event: {updated.get('summary')}",
        "htmlLink": updated.get("htmlLink"),
    }


@tool
def search_events(query: str, date_range: str = "today") -> list[dict]:
    """Search for events matching a query within a date range.

    Args:
        query (str): Text to search for in event summaries
        date_range (str): 'today', 'tomorrow', 'this_week', 'next_week', or a specific YYYY-MM-DD date
    """
    calendar_service = get_calendar_service()
    calendar_id = os.getenv("CALENDAR_ID", "primary")

    now = datetime.now(timezone)

    # Parse date range
    if date_range == "today":
        range_start = now.replace(hour=0, minute=0, second=0)
        range_end = now.replace(hour=23, minute=59, second=59)
    elif date_range == "tomorrow":
        tomorrow = now + timedelta(days=1)
        range_start = tomorrow.replace(hour=0, minute=0, second=0)
        range_end = tomorrow.replace(hour=23, minute=59, second=59)
    elif date_range == "this_week":
        # Start of current week (Monday)
        days_since_monday = now.weekday()
        range_start = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0)
        range_end = (range_start + timedelta(days=6)).replace(hour=23, minute=59, second=59)
    elif date_range == "next_week":
        days_since_monday = now.weekday()
        next_monday = now + timedelta(days=7 - days_since_monday)
        range_start = next_monday.replace(hour=0, minute=0, second=0)
        range_end = (range_start + timedelta(days=6)).replace(hour=23, minute=59, second=59)
    else:
        # Specific date
        target = datetime.fromisoformat(date_range)
        target = timezone.localize(target)
        range_start = target.replace(hour=0, minute=0, second=0)
        range_end = target.replace(hour=23, minute=59, second=59)

    events_result = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=range_start.isoformat(),
        timeMax=range_end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        q=query,
    ).execute()

    events = []
    for ev in events_result.get("items", []):
        events.append({
            "id": ev["id"],
            "summary": ev.get("summary", "(no title)"),
            "start": ev["start"].get("dateTime", ev["start"].get("date")),
            "end": ev["end"].get("dateTime", ev["end"].get("date")),
        })

    return events


# Add test call after authentication
if __name__ == "__main__":
    # Test calendar access
    if test_calendar_access():
        # Clear existing events
        if clear_calendar_events():
            # Example schedule text
            schedule_text = """
**2025-05-20 01:00 - 2025-05-20 02:00**: Mental model reading
**2025-05-20 02:00 - 2025-05-20 02:30**: Task - (No task assigned, free time)
**2025-05-20 02:30 - 2025-05-20 03:30**: Workout
**2025-05-20 03:30 - 2025-05-20 04:00**: Task - (No task assigned, free time)
**2025-05-20 04:30 - 2025-05-20 05:30**: Computing services
**2025-05-20 05:30 - 2025-05-20 08:00**: Task - (No task assigned, free time)
**2025-05-20 08:00 - 2025-05-20 09:00**: Mental model reading
**2025-05-20 09:00 - 2025-05-20 09:30**: Task - (No task assigned, free time)
**2025-05-20 09:30 - 2025-05-20 10:30**: Workout
**2025-05-20 10:30 - 2025-05-20 11:30**: Task - (No task assigned, free time)
**2025-05-20 11:30 - 2025-05-20 12:30**: Computing services
**2025-05-20 12:30 - 2025-05-20 15:00**: Task - (No task assigned, free time)
**2025-05-20 15:00 - 2025-05-20 16:00**: Mental model reading
**2025-05-20 16:00 - 2025-05-20 16:30**: Task - (No task assigned, free time)
**2025-05-20 16:30 - 2025-05-20 17:30**: Workout
**2025-05-20 17:30 - 2025-05-20 23:59**: Task - (No task assigned, free time)
            """

            # Format and create events
            events = format_schedule_for_calendar(schedule_text)
            created_events = create_daily_schedule(events)
            print(f"Created {len(created_events)} events in calendar")
