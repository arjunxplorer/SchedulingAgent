"""Tests for Pydantic data models."""

import pytest
from src.models import UserIntent, CalendarEvent, TaskModel, CalendarModel, TaskListModel


class TestUserIntent:
    """Tests for the UserIntent structured output model."""

    def test_create_event_intent(self):
        intent = UserIntent(
            action="create_event",
            title="Team Meeting",
            date="2025-06-15",
            start_time="14:00",
            end_time="15:00",
        )
        assert intent.action == "create_event"
        assert intent.title == "Team Meeting"
        assert intent.date == "2025-06-15"
        assert intent.start_time == "14:00"
        assert intent.end_time == "15:00"

    def test_query_intent(self):
        intent = UserIntent(action="query", query_date="this_week")
        assert intent.action == "query"
        assert intent.query_date == "this_week"

    def test_modify_intent(self):
        intent = UserIntent(
            action="modify",
            target_event="Team Meeting",
            modify_field="time",
            modify_value="15:00",
            date="2025-06-15",
        )
        assert intent.action == "modify"
        assert intent.target_event == "Team Meeting"
        assert intent.modify_field == "time"
        assert intent.modify_value == "15:00"

    def test_delete_intent(self):
        intent = UserIntent(action="delete", target_event="Team Meeting", date="2025-06-15")
        assert intent.action == "delete"
        assert intent.target_event == "Team Meeting"

    def test_create_task_intent(self):
        intent = UserIntent(action="create_task", task_title="Review PR", task_notes="Check code style")
        assert intent.action == "create_task"
        assert intent.task_title == "Review PR"
        assert intent.task_notes == "Check code style"

    def test_add_task_to_calendar_intent(self):
        intent = UserIntent(
            action="add_task_to_calendar",
            task_title="Review PR",
            title="PR Review Block",
            date="2025-06-15",
            start_time="14:00",
            end_time="14:30",
        )
        assert intent.action == "add_task_to_calendar"
        assert intent.task_title == "Review PR"
        assert intent.title == "PR Review Block"

    def test_recurrence(self):
        intent = UserIntent(
            action="create_event",
            title="Standup",
            date="2025-06-15",
            start_time="09:00",
            end_time="09:15",
            recurrence="weekdays",
        )
        assert intent.recurrence == "weekdays"

    def test_optional_fields_default_none(self):
        intent = UserIntent(action="query")
        assert intent.title is None
        assert intent.date is None
        assert intent.start_time is None
        assert intent.end_time is None
        assert intent.recurrence is None
        assert intent.query_date is None
        assert intent.modify_field is None
        assert intent.modify_value is None
        assert intent.target_event is None
        assert intent.task_title is None
        assert intent.task_notes is None
        assert intent.task_due is None


class TestCalendarEvent:
    """Tests for CalendarEvent model."""

    def test_basic_event(self):
        event = CalendarEvent(
            id="abc123",
            summary="Team Meeting",
            start="2025-06-15T14:00:00",
            end="2025-06-15T15:00:00",
        )
        assert event.id == "abc123"
        assert event.summary == "Team Meeting"

    def test_str_format(self):
        event = CalendarEvent(
            id="abc123",
            summary="Team Meeting",
            start="2025-06-15T14:00:00",
            end="2025-06-15T15:00:00",
        )
        s = str(event)
        assert "Team Meeting" in s
        assert "2025-06-15" in s


class TestTaskModel:
    """Tests for TaskModel."""

    def test_basic_task(self):
        task = TaskModel(id="t1", title="Review PR", notes="Check style", due_date="2025-06-20")
        assert task.title == "Review PR"
        assert task.notes == "Check style"
        assert task.due_date == "2025-06-20"

    def test_defaults(self):
        task = TaskModel(id="t1", title="Review PR")
        assert task.notes == ""
        assert task.due_date == "No due date"

    def test_str_with_due(self):
        task = TaskModel(id="t1", title="Review PR", due_date="2025-06-20")
        s = str(task)
        assert "Review PR" in s
        assert "2025-06-20" in s

    def test_str_without_due(self):
        task = TaskModel(id="t1", title="Review PR")
        s = str(task)
        assert "Review PR" in s
        assert "Due" not in s


class TestCalendarModel:
    def test_basic(self):
        cal = CalendarModel(id="cal1", summary="Work")
        assert cal.id == "cal1"
        assert cal.summary == "Work"
        assert "Work" in str(cal)


class TestTaskListModel:
    def test_basic(self):
        tl = TaskListModel(id="tl1", title="My Tasks")
        assert tl.id == "tl1"
        assert "My Tasks" in str(tl)
