from datetime import datetime
from typing import List, Dict, Any
import json
import pytz
import os
from dateutil.parser import isoparse

# Models
from src.models import CalendarModel, CalendarEvent, TaskListModel, TaskModel

# Agents and tools
from langchain.tools import tool
# from smolagents import tool

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

# If there are no valid credentials, authenticate
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"Error refreshing token: {e}")
            creds = None

    if not creds:
        try:
            print(f"Starting OAuth flow on port {OAUTH_PORT}...")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(
                port=OAUTH_PORT,
                success_message="Authentication successful! You can close this window.",
                open_browser=True
            )

            # Save credentials for next run
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        except Exception as e:
            print(f"Error during OAuth flow: {e}")
            print("Please make sure you have added http://localhost:8080/ to your authorized redirect URIs in the Google Cloud Console")
            raise

print("Authentication successful!")

# Build service clients
calendar_service = build("calendar", "v3", credentials=creds)
tasks_service = build("tasks", "v1", credentials=creds)

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
    # Convert times to datetime objects
    new_start = isoparse(start_time)
    new_end = isoparse(end_time)

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
            conflict_msg.append("\nPlease choose a different time.")
            return {
                "error": True,
                "message": "\n".join(conflict_msg),
                "conflicting_events": conflicting_events
            }

        # Get current day's events for display
        day_events = calendar_service.events().list(
            calendarId=calendar_id,
            timeMin=event_date.replace(hour=0, minute=0, second=0).isoformat(),
            timeMax=event_date.replace(hour=23, minute=59, second=59).isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])

        # Insert new event
        created_event = (
            calendar_service.events()
            .insert(calendarId=calendar_id, body=event_body)
            .execute()
        )

        print(f"Event created: {created_event['htmlLink']}")

        # Add the new event to the list for display
        day_events.append(created_event)
        # Sort events by start time
        day_events.sort(key=lambda x: isoparse(x["start"].get("dateTime", x["start"].get("date"))))

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
    calendars_result = calendar_service.calendarList().list().execute()
    calendars = [
        CalendarModel(id=calendar["id"], summary=calendar["summary"])
        for calendar in calendars_result.get("items", [])
    ]
    return calendars


def get_calendar_events(id:str=os.getenv("CALENDAR_ID"), date:str=None) -> List[CalendarEvent]:
    """Fetch calendar events for the specified date (today by default).

    Args:
        id (str): Calendar ID. Defaults to 'CALENDAR_ID' found in the environment variables.
        date (datetime): Date for which to fetch events. Defaults to today.
    """
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
