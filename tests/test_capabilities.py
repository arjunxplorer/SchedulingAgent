"""Comprehensive capability tests — tests every tool and graph node with mocked Google APIs."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta
import pytz
import json

from src.graph_runner import (
    route_intent,
    should_revise,
    default_session_state,
    build_graph,
)
from src.models import UserIntent, CalendarEvent, TaskModel


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_calendar_service():
    """Provide a mock Google Calendar service."""
    with patch("src.tools.calendar_tools.get_calendar_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture
def mock_tasks_service():
    """Provide a mock Google Tasks service."""
    with patch("src.tools.calendar_tools.get_tasks_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture
def mock_auth():
    """Skip actual OAuth — always return valid creds."""
    with patch("src.tools.calendar_tools._authenticate") as mock:
        mock.return_value = MagicMock()
        yield mock


# ──────────────────────────────────────────────────────────────────────────────
# 1. create_calendar_event
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateCalendarEvent:
    """Capability: Create a calendar event."""

    def test_creates_event_successfully(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import create_calendar_event

        # Mock: no conflicts, event created
        mock_calendar_service.events().list().execute.return_value = {"items": []}
        created = {
            "id": "new1",
            "summary": "Team Meeting",
            "htmlLink": "https://calendar.google.com/event1",
            "start": {"dateTime": "2025-06-15T14:00:00"},
            "end": {"dateTime": "2025-06-15T15:00:00"},
        }
        mock_calendar_service.events().insert().execute.return_value = created

        result = create_calendar_event.invoke({
            "summary": "Team Meeting",
            "start_time": "2025-06-15T14:00:00",
            "end_time": "2025-06-15T15:00:00",
        })

        assert result["id"] == "new1"
        assert result["summary"] == "Team Meeting"
        assert "formatted_response" in result

    def test_detects_conflict(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import create_calendar_event

        # Mock: existing event overlaps (Google returns timezone-aware datetimes)
        existing = {
            "items": [{
                "id": "existing1",
                "summary": "Existing Meeting",
                "start": {"dateTime": "2025-06-15T13:00:00-05:00"},
                "end": {"dateTime": "2025-06-15T14:30:00-05:00"},
            }]
        }
        mock_calendar_service.events().list().execute.return_value = existing

        result = create_calendar_event.invoke({
            "summary": "Team Meeting",
            "start_time": "2025-06-15T14:00:00",
            "end_time": "2025-06-15T15:00:00",
        })

        assert result.get("error") is True
        assert "conflict" in result.get("message", "").lower() or "overlap" in result.get("message", "").lower()

    def test_handles_removal_via_summary(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import create_calendar_event

        # When summary starts with "remove", it delegates to find_and_delete_event
        mock_calendar_service.events().list().execute.return_value = {
            "items": [{
                "id": "del1",
                "summary": "Meeting with John",
                "start": {"dateTime": "2025-06-15T14:00:00"},
                "end": {"dateTime": "2025-06-15T15:00:00"},
            }]
        }

        result = create_calendar_event.invoke({
            "summary": "remove Meeting with John",
            "start_time": "2025-06-15T14:00:00",
            "end_time": "2025-06-15T15:00:00",
        })

        assert result.get("success") is True


# ──────────────────────────────────────────────────────────────────────────────
# 2. create_calendar_events (batch)
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateCalendarEvents:
    """Capability: Create multiple calendar events at once."""

    def test_creates_multiple_events(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import create_calendar_events

        mock_calendar_service.events().list().execute.return_value = {"items": []}
        mock_calendar_service.events().insert().execute.return_value = {
            "id": "e1", "summary": "Event", "htmlLink": "",
            "start": {"dateTime": "2025-06-15T10:00:00-05:00"},
            "end": {"dateTime": "2025-06-15T11:00:00-05:00"},
        }

        result = create_calendar_events.invoke({
            "calendar_events": [
                {"summary": "Meeting 1", "start_time": "2025-06-15T10:00:00", "end_time": "2025-06-15T11:00:00"},
                {"summary": "Meeting 2", "start_time": "2025-06-15T14:00:00", "end_time": "2025-06-15T15:00:00"},
            ]
        })

        assert len(result) == 2


# ──────────────────────────────────────────────────────────────────────────────
# 3. update_calendar_event
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdateCalendarEvent:
    """Capability: Update an existing event's title, time, or duration."""

    def test_updates_summary(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import update_calendar_event

        existing = {
            "id": "e1", "summary": "Old Title",
            "start": {"dateTime": "2025-06-15T14:00:00", "timeZone": "America/Chicago"},
            "end": {"dateTime": "2025-06-15T15:00:00", "timeZone": "America/Chicago"},
        }
        mock_calendar_service.events().get().execute.return_value = existing
        mock_calendar_service.events().update().execute.return_value = {
            **existing, "summary": "New Title", "htmlLink": "https://calendar.google.com/e1"
        }

        result = update_calendar_event.invoke({
            "event_id": "e1",
            "summary": "New Title",
        })

        assert result["success"] is True
        assert "New Title" in result["message"]

    def test_updates_start_time(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import update_calendar_event

        existing = {
            "id": "e1", "summary": "Meeting",
            "start": {"dateTime": "2025-06-15T14:00:00", "timeZone": "America/Chicago"},
            "end": {"dateTime": "2025-06-15T15:00:00", "timeZone": "America/Chicago"},
        }
        mock_calendar_service.events().get().execute.return_value = existing
        mock_calendar_service.events().update().execute.return_value = {
            **existing, "start": {"dateTime": "2025-06-15T16:00:00"}, "htmlLink": ""
        }

        result = update_calendar_event.invoke({
            "event_id": "e1",
            "start_time": "2025-06-15T16:00:00",
        })

        assert result["success"] is True


# ──────────────────────────────────────────────────────────────────────────────
# 4. find_and_delete_event
# ──────────────────────────────────────────────────────────────────────────────

class TestDeleteEvent:
    """Capability: Delete a calendar event by name and date."""

    def test_deletes_matching_event(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import find_and_delete_event

        mock_calendar_service.events().list().execute.return_value = {
            "items": [{
                "id": "del1",
                "summary": "Meeting with John",
                "start": {"dateTime": "2025-06-15T14:00:00"},
                "end": {"dateTime": "2025-06-15T15:00:00"},
            }]
        }

        success, message, remaining = find_and_delete_event(
            calendar_id="primary",
            summary="Meeting with John",
            date=datetime(2025, 6, 15),
        )

        assert success is True
        assert "Removed" in message

    def test_no_matching_event(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import find_and_delete_event

        mock_calendar_service.events().list().execute.return_value = {"items": []}

        success, message, remaining = find_and_delete_event(
            calendar_id="primary",
            summary="Nonexistent Meeting",
            date=datetime(2025, 6, 15),
        )

        assert success is False
        assert "No events found" in message


# ──────────────────────────────────────────────────────────────────────────────
# 5. search_events
# ──────────────────────────────────────────────────────────────────────────────

class TestSearchEvents:
    """Capability: Search/list events by date range and query."""

    def test_search_today(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import search_events

        mock_calendar_service.events().list().execute.return_value = {
            "items": [{
                "id": "e1",
                "summary": "Team Standup",
                "start": {"dateTime": "2025-06-15T09:00:00"},
                "end": {"dateTime": "2025-06-15T09:30:00"},
            }]
        }

        result = search_events.invoke({"query": "", "date_range": "today"})
        assert len(result) == 1
        assert result[0]["summary"] == "Team Standup"

    def test_search_this_week(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import search_events

        mock_calendar_service.events().list().execute.return_value = {
            "items": [
                {"id": "e1", "summary": "Mon Meeting", "start": {"dateTime": "2025-06-16T10:00:00"}, "end": {"dateTime": "2025-06-16T11:00:00"}},
                {"id": "e2", "summary": "Wed Meeting", "start": {"dateTime": "2025-06-18T14:00:00"}, "end": {"dateTime": "2025-06-18T15:00:00"}},
            ]
        }

        result = search_events.invoke({"query": "", "date_range": "this_week"})
        assert len(result) == 2

    def test_search_empty(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import search_events

        mock_calendar_service.events().list().execute.return_value = {"items": []}

        result = search_events.invoke({"query": "", "date_range": "tomorrow"})
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# 6. find_free_slots
# ──────────────────────────────────────────────────────────────────────────────

class TestFindFreeSlots:
    """Capability: Find available time slots on a given date."""

    def test_finds_free_slots(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import find_free_slots

        # One meeting from 10-11, rest of 8am-10pm is free
        mock_calendar_service.events().list().execute.return_value = {
            "items": [{
                "id": "e1",
                "summary": "Meeting",
                "start": {"dateTime": "2025-06-15T10:00:00"},
                "end": {"dateTime": "2025-06-15T11:00:00"},
            }]
        }

        slots = find_free_slots.invoke({"date": "2025-06-15", "duration_minutes": 60})

        assert len(slots) >= 1
        # Should have slots before and after the meeting
        starts = [s["start"] for s in slots]
        assert "08:00" in starts  # 8am-10am slot

    def test_no_free_slots(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import find_free_slots

        # Packed day: 8am-10pm all busy
        mock_calendar_service.events().list().execute.return_value = {
            "items": [{
                "id": "e1",
                "summary": "All Day",
                "start": {"dateTime": "2025-06-15T08:00:00"},
                "end": {"dateTime": "2025-06-15T22:00:00"},
            }]
        }

        slots = find_free_slots.invoke({"date": "2025-06-15", "duration_minutes": 60})
        assert slots == []

    def test_empty_day(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import find_free_slots

        mock_calendar_service.events().list().execute.return_value = {"items": []}

        slots = find_free_slots.invoke({"date": "2025-06-15", "duration_minutes": 60})
        assert len(slots) >= 1
        assert slots[0]["start"] == "08:00"


# ──────────────────────────────────────────────────────────────────────────────
# 7. suggest_alternative_times
# ──────────────────────────────────────────────────────────────────────────────

class TestSuggestAlternativeTimes:
    """Capability: Suggest alternative times when a conflict exists."""

    def test_suggests_alternatives(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import suggest_alternative_times

        # Meeting at 10-11, free at 8-10 and 11-10pm
        mock_calendar_service.events().list().execute.return_value = {
            "items": [{
                "id": "e1",
                "summary": "Meeting",
                "start": {"dateTime": "2025-06-15T10:00:00"},
                "end": {"dateTime": "2025-06-15T11:00:00"},
            }]
        }

        suggestions = suggest_alternative_times.invoke({
            "date": "2025-06-15",
            "start_time": "10:00",
            "end_time": "11:00",
        })

        assert len(suggestions) >= 1
        for s in suggestions:
            assert "start_time" in s
            assert "end_time" in s
            assert "display" in s

    def test_no_alternatives_when_full(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import suggest_alternative_times

        mock_calendar_service.events().list().execute.return_value = {
            "items": [{
                "id": "e1",
                "summary": "All Day",
                "start": {"dateTime": "2025-06-15T08:00:00"},
                "end": {"dateTime": "2025-06-15T22:00:00"},
            }]
        }

        suggestions = suggest_alternative_times.invoke({
            "date": "2025-06-15",
            "start_time": "10:00",
            "end_time": "11:00",
        })

        assert suggestions == []


# ──────────────────────────────────────────────────────────────────────────────
# 8. check_time_conflict
# ──────────────────────────────────────────────────────────────────────────────

class TestCheckTimeConflict:
    """Capability: Detect time conflicts before creating events."""

    def test_no_conflict(self, mock_calendar_service):
        from src.tools.calendar_tools import check_time_conflict

        mock_calendar_service.events().list().execute.return_value = {
            "items": [{
                "id": "e1",
                "summary": "Other Meeting",
                "start": {"dateTime": "2025-06-15T08:00:00-05:00"},
                "end": {"dateTime": "2025-06-15T09:00:00-05:00"},
            }]
        }

        has_conflict, conflicts = check_time_conflict(
            "primary", "2025-06-15T14:00:00", "2025-06-15T15:00:00",
            datetime(2025, 6, 15, tzinfo=pytz.timezone("America/Chicago")),
        )

        assert has_conflict is False
        assert conflicts == []

    def test_detects_conflict(self, mock_calendar_service):
        from src.tools.calendar_tools import check_time_conflict

        mock_calendar_service.events().list().execute.return_value = {
            "items": [{
                "id": "e1",
                "summary": "Overlapping Meeting",
                "start": {"dateTime": "2025-06-15T13:00:00-05:00"},
                "end": {"dateTime": "2025-06-15T14:30:00-05:00"},
            }]
        }

        has_conflict, conflicts = check_time_conflict(
            "primary", "2025-06-15T14:00:00", "2025-06-15T15:00:00",
            datetime(2025, 6, 15, tzinfo=pytz.timezone("America/Chicago")),
        )

        assert has_conflict is True
        assert len(conflicts) == 1
        assert conflicts[0]["summary"] == "Overlapping Meeting"


# ──────────────────────────────────────────────────────────────────────────────
# 9. create_task
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateTask:
    """Capability: Create a Google Tasks task."""

    def test_creates_task(self, mock_tasks_service, mock_auth):
        from src.tools.calendar_tools import create_task

        mock_tasks_service.tasks().insert().execute.return_value = {
            "id": "task1",
            "title": "Review PR",
        }

        result = create_task.invoke({
            "title": "Review PR",
            "notes": "Check code style",
            "due": "2025-06-20",
        })

        assert result["success"] is True
        assert "Review PR" in result["message"]

    def test_creates_task_no_due(self, mock_tasks_service, mock_auth):
        from src.tools.calendar_tools import create_task

        mock_tasks_service.tasks().insert().execute.return_value = {
            "id": "task2",
            "title": "Buy groceries",
        }

        result = create_task.invoke({
            "title": "Buy groceries",
            "notes": "",
            "due": "",
        })

        assert result["success"] is True


# ──────────────────────────────────────────────────────────────────────────────
# 10. get_tasks
# ──────────────────────────────────────────────────────────────────────────────

class TestGetTasks:
    """Capability: List incomplete tasks from Google Tasks."""

    def test_lists_tasks(self, mock_tasks_service, mock_auth):
        from src.tools.calendar_tools import get_tasks

        mock_tasks_service.tasks().list().execute.return_value = {
            "items": [
                {"id": "t1", "title": "Review PR", "notes": "Check style", "due": "2025-06-20"},
                {"id": "t2", "title": "Deploy", "notes": "", "due": ""},
            ]
        }

        tasks = get_tasks()
        assert len(tasks) == 2
        assert tasks[0].title == "Review PR"
        assert tasks[1].title == "Deploy"

    def test_empty_tasks(self, mock_tasks_service, mock_auth):
        from src.tools.calendar_tools import get_tasks

        mock_tasks_service.tasks().list().execute.return_value = {"items": []}

        tasks = get_tasks()
        assert tasks == []


# ──────────────────────────────────────────────────────────────────────────────
# 11. list_tasks (task lists)
# ──────────────────────────────────────────────────────────────────────────────

class TestListTasks:
    """Capability: List Google Tasks lists."""

    def test_lists_task_lists(self, mock_tasks_service, mock_auth):
        from src.tools.calendar_tools import list_tasks

        mock_tasks_service.tasklists().list().execute.return_value = {
            "items": [
                {"id": "tl1", "title": "My Tasks"},
                {"id": "tl2", "title": "Work"},
            ]
        }

        result = list_tasks()
        assert len(result) == 2
        assert result[0].title == "My Tasks"


# ──────────────────────────────────────────────────────────────────────────────
# 12. list_calendars
# ──────────────────────────────────────────────────────────────────────────────

class TestListCalendars:
    """Capability: List all Google Calendars."""

    def test_lists_calendars(self, mock_calendar_service, mock_auth):
        from src.tools.calendar_tools import list_calendars

        mock_calendar_service.calendarList().list().execute.return_value = {
            "items": [
                {"id": "primary", "summary": "Personal"},
                {"id": "work@company.com", "summary": "Work"},
            ]
        }

        calendars = list_calendars()
        assert len(calendars) == 2
        assert calendars[0].summary == "Personal"


# ──────────────────────────────────────────────────────────────────────────────
# 13. get_current_time
# ──────────────────────────────────────────────────────────────────────────────

class TestGetCurrentTime:
    """Capability: Get current time in ISO format."""

    def test_returns_iso_string(self):
        from src.tools.time_tools import get_current_time

        result = get_current_time.invoke({})
        assert isinstance(result, str)
        # Should be parseable as ISO datetime
        dt = datetime.fromisoformat(result)
        assert dt.year >= 2025

    def test_in_chicago_timezone(self):
        from src.tools.time_tools import get_current_time

        result = get_current_time.invoke({})
        dt = datetime.fromisoformat(result)
        # Should have timezone info
        assert dt.tzinfo is not None


# ──────────────────────────────────────────────────────────────────────────────
# 14. get_date_in_iso_format
# ──────────────────────────────────────────────────────────────────────────────

class TestGetDateInIsoFormat:
    """Capability: Convert natural language dates to ISO format."""

    def test_specific_date(self):
        from src.tools.time_tools import get_date_in_iso_format

        result = get_date_in_iso_format.invoke({"date_str": "2025-06-15"})
        assert "2025-06-15" in result

    def test_tomorrow(self):
        from src.tools.time_tools import get_date_in_iso_format

        result = get_date_in_iso_format.invoke({"date_str": "tomorrow"})
        tomorrow = datetime.now() + timedelta(days=1)
        assert tomorrow.strftime("%Y-%m-%d") in result

    def test_with_time(self):
        from src.tools.time_tools import get_date_in_iso_format

        result = get_date_in_iso_format.invoke({"date_str": "3pm today"})
        assert "15:00" in result

    def test_with_reference_date(self):
        from src.tools.time_tools import get_date_in_iso_format

        result = get_date_in_iso_format.invoke({
            "date_str": "tomorrow",
            "reference_date": "2025-06-15T10:00:00",
        })
        assert "2025-06-16" in result


# ──────────────────────────────────────────────────────────────────────────────
# 15. sum_to_date
# ──────────────────────────────────────────────────────────────────────────────

class TestSumToDate:
    """Capability: Add weeks/days/hours/minutes to a date."""

    def test_add_days(self):
        from src.tools.time_tools import sum_to_date

        result = sum_to_date.invoke({
            "date_str": "2025-06-15T10:00:00",
            "weeks": 0, "days": 3, "hours": 0, "minutes": 0,
        })
        assert "2025-06-18" in result

    def test_add_weeks(self):
        from src.tools.time_tools import sum_to_date

        result = sum_to_date.invoke({
            "date_str": "2025-06-15T10:00:00",
            "weeks": 1, "days": 0, "hours": 0, "minutes": 0,
        })
        assert "2025-06-22" in result

    def test_add_hours_and_minutes(self):
        from src.tools.time_tools import sum_to_date

        result = sum_to_date.invoke({
            "date_str": "2025-06-15T10:00:00",
            "weeks": 0, "days": 0, "hours": 2, "minutes": 30,
        })
        assert "2025-06-15T12:30:00" == result


# ──────────────────────────────────────────────────────────────────────────────
# 16. parse_iso_date
# ──────────────────────────────────────────────────────────────────────────────

class TestParseIsoDate:
    """Capability: Parse ISO 8601 dates into readable format."""

    def test_basic_parse(self):
        from src.utils.time_utils import parse_iso_date

        result = parse_iso_date("2025-06-15T14:30:00")
        assert result == "2025-06-15 14:30"

    def test_date_only(self):
        from src.utils.time_utils import parse_iso_date

        result = parse_iso_date("2025-06-15")
        assert result == "2025-06-15 00:00"


# ──────────────────────────────────────────────────────────────────────────────
# 17-18. Graph routing + intent classification
# ──────────────────────────────────────────────────────────────────────────────

class TestGraphRouting:
    """Capability: Route user intents to the correct sub-graph."""

    @pytest.mark.parametrize("action,expected_path", [
        ("create_event", "create_event_path"),
        ("add_task_to_calendar", "create_event_path"),
        ("query", "query_path"),
        ("modify", "modify_path"),
        ("delete", "delete_path"),
        ("create_task", "task_path"),
    ])
    def test_routes_all_intents(self, action, expected_path):
        state = {"intent": UserIntent(action=action)}
        assert route_intent(state) == expected_path

    def test_routes_no_intent_to_end(self):
        assert route_intent({"intent": None}) == "end"


# ──────────────────────────────────────────────────────────────────────────────
# 19-22. Graph nodes with mocked LLM
# ──────────────────────────────────────────────────────────────────────────────

class TestGraphNodes:
    """Capability: Graph nodes (planner, event_creator, reviewer, revise)."""

    def _make_mock_model(self):
        """Create a mock model that returns sensible defaults."""
        model = MagicMock()

        # For interpret_node: with_structured_output().invoke() returns a UserIntent
        structured = MagicMock()
        structured.invoke.return_value = UserIntent(
            action="create_event",
            title="Team Meeting",
            date="2025-06-15",
            start_time="14:00",
            end_time="15:00",
        )
        model.with_structured_output.return_value = structured

        # For planner/reviewer/revise: model.invoke() returns content
        model.invoke.return_value = MagicMock(
            content="**2025-06-15 14:00 - 2025-06-15 15:00**: Team Meeting"
        )
        return model

    def test_planner_node(self):
        from src.graph_runner import planner_node

        model = self._make_mock_model()
        state = {
            "intent": UserIntent(action="create_event", title="Team Meeting",
                                 date="2025-06-15", start_time="14:00", end_time="15:00"),
            "current_time": "2025-06-15T10:00:00",
            "events": [],
            "tasks": [],
            "schedule": "",
            "feedback": "",
            "rewrites": 0,
        }

        result = planner_node(model, state)
        assert "schedule" in result
        assert result["rewrites"] == 1

    def test_reviewer_node_pass(self):
        from src.graph_runner import reviewer_node

        model = self._make_mock_model()
        model.invoke.return_value = MagicMock(content="Schedule looks good. OK")

        state = {
            "events": [],
            "schedule": "**2025-06-15 14:00 - 2025-06-15 15:00**: Team Meeting",
        }

        result = reviewer_node(model, state)
        assert "feedback" in result
        assert "CHANGES" not in result["feedback"]

    def test_reviewer_node_suggests_changes(self):
        from src.graph_runner import reviewer_node

        model = self._make_mock_model()
        model.invoke.return_value = MagicMock(
            content="The meeting overlaps with an existing event. CHANGES"
        )

        state = {
            "events": [CalendarEvent(id="e1", summary="Other", start="2025-06-15T13:00:00", end="2025-06-15T14:30:00")],
            "schedule": "**2025-06-15 14:00 - 2025-06-15 15:00**: Team Meeting",
        }

        result = reviewer_node(model, state)
        assert "CHANGES" in result["feedback"]

    def test_should_revise_loops(self):
        state = {"feedback": "Move it CHANGES", "rewrites": 0}
        assert should_revise(state) == "revise"

    def test_should_revise_stops_at_limit(self):
        state = {"feedback": "CHANGES", "rewrites": 3}
        assert should_revise(state) == "end"

    def test_revise_node(self):
        from src.graph_runner import revise_node

        model = self._make_mock_model()
        model.invoke.return_value = MagicMock(
            content="**2025-06-15 15:00 - 2025-06-15 16:00**: Team Meeting"
        )

        state = {
            "schedule": "**2025-06-15 14:00 - 2025-06-15 15:00**: Team Meeting",
            "feedback": "CHANGES: Move to 3pm",
        }

        result = revise_node(model, state)
        assert "15:00" in result["schedule"]

    def test_query_node(self):
        from src.graph_runner import query_node

        model = self._make_mock_model()
        state = {
            "intent": UserIntent(action="query", query_date="today"),
        }

        with patch("src.graph_runner.search_events") as mock_search:
            mock_search.invoke.return_value = [
                {"id": "e1", "summary": "Standup", "start": "2025-06-15T09:00:00", "end": "2025-06-15T09:30:00"},
            ]
            result = query_node(model, state)
            assert "Standup" in result["feedback"]

    def test_task_node(self):
        from src.graph_runner import task_node

        model = self._make_mock_model()
        state = {
            "intent": UserIntent(action="create_task", task_title="Review PR"),
        }

        with patch("src.graph_runner.create_task") as mock_create:
            mock_create.invoke.return_value = {"success": True, "message": "Task created: Review PR"}
            result = task_node(model, state)
            assert "Review PR" in result["feedback"]


# ──────────────────────────────────────────────────────────────────────────────
# Graph construction
# ──────────────────────────────────────────────────────────────────────────────

class TestGraphConstruction:
    """Capability: Build a complete, compilable graph."""

    def test_graph_builds_with_mock(self):
        model = MagicMock()
        structured = MagicMock()
        structured.invoke.return_value = UserIntent(action="query", query_date="today")
        model.with_structured_output.return_value = structured
        model.invoke.return_value = MagicMock(content="No events.")

        graph = build_graph(model)
        assert graph is not None

    def test_session_state_has_all_keys(self):
        state = default_session_state()
        expected_keys = {
            "messages", "current_time", "user_input", "intent",
            "events", "tasks", "schedule", "feedback", "rewrites",
            "calendars", "conversation_history", "last_created_event",
        }
        assert expected_keys.issubset(set(state.keys()))
