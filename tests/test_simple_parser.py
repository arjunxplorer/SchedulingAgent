"""Tests for the simple regex-based intent parser (no AI)."""

import pytest
from datetime import datetime, timedelta
import pytz
from src.simple_parser import parse_simple_intent, _parse_date, _parse_time, _parse_duration, _extract_title


class TestParseDate:
    """Tests for natural language date parsing."""

    def test_today(self):
        today = datetime.now(pytz.timezone("America/Chicago")).strftime("%Y-%m-%d")
        assert _parse_date("today") == today

    def test_tomorrow(self):
        tomorrow = (datetime.now(pytz.timezone("America/Chicago")) + timedelta(days=1)).strftime("%Y-%m-%d")
        assert _parse_date("tomorrow") == tomorrow

    def test_specific_day(self):
        result = _parse_date("friday")
        assert result  # Should return a date string
        assert len(result) == 10  # YYYY-MM-DD

    def test_in_x_days(self):
        today = datetime.now(pytz.timezone("America/Chicago"))
        expected = (today + timedelta(days=3)).strftime("%Y-%m-%d")
        assert _parse_date("in 3 days") == expected


class TestParseTime:
    """Tests for natural language time parsing."""

    def test_2pm(self):
        assert _parse_time("at 2pm") == "14:00"

    def test_2_30pm(self):
        assert _parse_time("at 2:30pm") == "14:30"

    def test_9am(self):
        assert _parse_time("at 9am") == "09:00"

    def test_14_00(self):
        assert _parse_time("at 14:00") == "14:00"

    def test_no_time(self):
        assert _parse_time("sometime today") is None


class TestParseDuration:
    """Tests for duration parsing."""

    def test_30_minutes(self):
        assert _parse_duration("for 30 minutes") == 30

    def test_1_hour(self):
        assert _parse_duration("for 1 hour") == 60

    def test_2_hours(self):
        assert _parse_duration("for 2 hours") == 120

    def test_default(self):
        assert _parse_duration("no duration mentioned") == 60


class TestExtractTitle:
    """Tests for title extraction."""

    def test_basic(self):
        assert _extract_title("schedule a meeting with John") == "Meeting With John"

    def test_with_time(self):
        title = _extract_title("schedule a 2pm meeting with John")
        assert "Meeting" in title

    def test_with_prefix(self):
        title = _extract_title("add a workout session")
        assert "Workout" in title


class TestParseSimpleIntent:
    """Tests for the main intent parser."""

    def test_delete_specific(self):
        intent = parse_simple_intent("delete the 2pm meeting")
        assert intent is not None
        assert intent.action == "delete"
        assert "meeting" in intent.target_event.lower()

    def test_delete_all(self):
        intent = parse_simple_intent("remove all events for tomorrow")
        assert intent is not None
        assert intent.action == "delete"
        assert intent.target_event == "all"

    def test_query(self):
        intent = parse_simple_intent("what's on my calendar today")
        assert intent is not None
        assert intent.action == "query"

    def test_modify_move(self):
        intent = parse_simple_intent("move my meeting to 3pm")
        assert intent is not None
        assert intent.action == "modify"
        assert intent.modify_field == "time"

    def test_create_task(self):
        intent = parse_simple_intent("add review PR to my todo list")
        assert intent is not None
        assert intent.action == "create_task"
        assert "review pr" in intent.task_title.lower()

    def test_create_event_with_time(self):
        intent = parse_simple_intent("schedule a meeting tomorrow at 2pm for 1 hour")
        assert intent is not None
        assert intent.action == "create_event"
        assert intent.start_time == "14:00"
        assert intent.end_time == "15:00"

    def test_complex_returns_none(self):
        # Complex requests should return None (needs AI)
        assert parse_simple_intent("plan my day") is None
        assert parse_simple_intent("help me schedule my week") is None
        assert parse_simple_intent("I have a deadline Friday, plan around it") is None

    def test_delete_clear(self):
        intent = parse_simple_intent("clear my calendar for Friday")
        assert intent is not None
        assert intent.action == "delete"
        assert intent.target_event == "all"


class TestIntegrationWithGraph:
    """Integration: verify simple parser feeds into graph correctly."""

    def test_simple_intent_in_graph(self):
        from src.graph_runner import simple_intent_node

        state = {"user_input": "delete the 2pm meeting", "conversation_history": []}
        result = simple_intent_node(state)

        assert result["is_simple"] is True
        assert result["intent"].action == "delete"

    def test_complex_intent_in_graph(self):
        from src.graph_runner import simple_intent_node

        state = {"user_input": "plan my day with a study session and a workout", "conversation_history": []}
        result = simple_intent_node(state)

        assert result["is_simple"] is False
