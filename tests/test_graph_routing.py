"""Tests for graph routing logic and node functions."""

import pytest
from src.graph_runner import route_intent, route_create_event, should_revise, default_session_state
from src.models import UserIntent


class TestRouteIntent:
    """Tests for the route_intent router function."""

    def test_route_create_event(self):
        state = {"intent": UserIntent(action="create_event", title="Meeting", date="2025-06-15")}
        assert route_intent(state) == "create_event_path"

    def test_route_add_task_to_calendar(self):
        state = {"intent": UserIntent(action="add_task_to_calendar", task_title="Review PR")}
        assert route_intent(state) == "create_event_path"

    def test_route_query(self):
        state = {"intent": UserIntent(action="query", query_date="today")}
        assert route_intent(state) == "query_path"

    def test_route_modify(self):
        state = {"intent": UserIntent(action="modify", target_event="Meeting")}
        assert route_intent(state) == "modify_path"

    def test_route_delete(self):
        state = {"intent": UserIntent(action="delete", target_event="Meeting")}
        assert route_intent(state) == "delete_path"

    def test_route_create_task(self):
        state = {"intent": UserIntent(action="create_task", task_title="Review PR")}
        assert route_intent(state) == "task_path"

    def test_route_no_intent(self):
        state = {"intent": None}
        assert route_intent(state) == "end"

    def test_route_missing_intent_key(self):
        state = {}
        assert route_intent(state) == "end"


class TestShouldRevise:
    """Tests for the should_revise conditional edge."""

    def test_no_changes_ends(self):
        state = {"feedback": "Schedule looks good.", "rewrites": 0}
        assert should_revise(state) == "end"

    def test_changes_below_limit(self):
        state = {"feedback": "Please adjust CHANGES the time slot.", "rewrites": 1}
        assert should_revise(state) == "revise"

    def test_changes_at_limit(self):
        state = {"feedback": "CHANGES needed.", "rewrites": 3}
        assert should_revise(state) == "end"

    def test_changes_above_limit(self):
        state = {"feedback": "CHANGES needed.", "rewrites": 5}
        assert should_revise(state) == "end"

    def test_empty_feedback(self):
        state = {"feedback": "", "rewrites": 0}
        assert should_revise(state) == "end"

    def test_missing_rewrites(self):
        state = {"feedback": "CHANGES needed."}
        assert should_revise(state) == "revise"


class TestDefaultSessionState:
    """Tests for the default_session_state factory."""

    def test_returns_dict(self):
        state = default_session_state()
        assert isinstance(state, dict)

    def test_has_required_keys(self):
        state = default_session_state()
        required_keys = [
            "messages", "current_time", "user_input", "intent",
            "events", "tasks", "schedule", "feedback", "rewrites",
            "calendars", "conversation_history", "last_created_event",
        ]
        for key in required_keys:
            assert key in state, f"Missing key: {key}"

    def test_initial_values(self):
        state = default_session_state()
        assert state["messages"] == []
        assert state["current_time"] == ""
        assert state["user_input"] == ""
        assert state["intent"] is None
        assert state["events"] == []
        assert state["tasks"] == []
        assert state["schedule"] == ""
        assert state["feedback"] == ""
        assert state["rewrites"] == 0
        assert state["conversation_history"] == []
        assert state["last_created_event"] is None

    def test_fresh_state_per_call(self):
        state1 = default_session_state()
        state1["feedback"] = "modified"
        state2 = default_session_state()
        assert state2["feedback"] == ""


class TestScheduleStateTypedDict:
    """Verify ScheduleState TypedDict fields match default_session_state."""

    def test_keys_match(self):
        from src.graph_runner import ScheduleState
        state = default_session_state()
        typed_keys = set(ScheduleState.__annotations__.keys())
        state_keys = set(state.keys())
        # All typed keys should be in state
        assert typed_keys.issubset(state_keys), f"Typed keys missing from state: {typed_keys - state_keys}"


class TestGraphConstruction:
    """Test that the graph builds without errors."""

    def test_build_graph_with_mock_model(self):
        """Verify build_graph compiles with a mock model."""
        from unittest.mock import MagicMock
        from src.graph_runner import build_graph

        mock_model = MagicMock()
        # Mock with_structured_output to return a mock that has invoke
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = UserIntent(action="query", query_date="today")
        mock_model.with_structured_output.return_value = mock_structured
        mock_model.invoke.return_value = MagicMock(content="No events today.")

        graph = build_graph(mock_model)
        assert graph is not None


class TestRouteCreateEvent:
    """Tests for the simple vs full create_event routing."""

    def test_simple_when_all_fields_present(self):
        intent = UserIntent(
            action="create_event", title="Meeting", date="2025-06-15",
            start_time="14:00", end_time="15:00",
        )
        assert route_create_event({"intent": intent}) == "simple_path"

    def test_simple_add_task_to_calendar(self):
        intent = UserIntent(
            action="add_task_to_calendar", task_title="Review PR",
            title="PR Block", date="2025-06-15",
            start_time="14:00", end_time="14:30",
        )
        assert route_create_event({"intent": intent}) == "simple_path"

    def test_full_when_missing_end_time(self):
        intent = UserIntent(
            action="create_event", title="Meeting", date="2025-06-15",
            start_time="14:00", end_time=None,
        )
        assert route_create_event({"intent": intent}) == "full_path"

    def test_full_when_missing_title(self):
        intent = UserIntent(
            action="create_event", title=None, date="2025-06-15",
            start_time="14:00", end_time="15:00",
        )
        assert route_create_event({"intent": intent}) == "full_path"

    def test_full_when_has_recurrence(self):
        intent = UserIntent(
            action="create_event", title="Standup", date="2025-06-15",
            start_time="09:00", end_time="09:15", recurrence="weekdays",
        )
        assert route_create_event({"intent": intent}) == "full_path"

    def test_full_when_no_intent(self):
        assert route_create_event({"intent": None}) == "full_path"

    def test_full_when_missing_date(self):
        intent = UserIntent(
            action="create_event", title="Meeting", date=None,
            start_time="14:00", end_time="15:00",
        )
        assert route_create_event({"intent": intent}) == "full_path"


class TestSimpleCreateEventNode:
    """Tests for the fast-path event creation node."""

    def test_creates_event_directly(self):
        from unittest.mock import patch, MagicMock
        from src.graph_runner import simple_create_event_node

        model = MagicMock()
        intent = UserIntent(
            action="create_event", title="Team Meeting", date="2025-06-15",
            start_time="14:00", end_time="15:00",
        )
        state = {"intent": intent, "events": [], "tasks": []}

        with patch("src.graph_runner.create_calendar_event") as mock_create:
            mock_create.invoke.return_value = {
                "formatted_response": "✅ Added Team Meeting.\n📅 Events for 2025-06-15:\n • 2:00 PM - 3:00 PM — Team Meeting",
            }
            result = simple_create_event_node(model, state)

            mock_create.invoke.assert_called_once_with({
                "summary": "Team Meeting",
                "start_time": "2025-06-15T14:00:00",
                "end_time": "2025-06-15T15:00:00",
            })
            assert "Team Meeting" in result["feedback"]
            assert result["last_created_event"]["title"] == "Team Meeting"

    def test_handles_conflict(self):
        from unittest.mock import patch, MagicMock
        from src.graph_runner import simple_create_event_node

        model = MagicMock()
        intent = UserIntent(
            action="create_event", title="Team Meeting", date="2025-06-15",
            start_time="14:00", end_time="15:00",
        )
        state = {"intent": intent, "events": [], "tasks": []}

        with patch("src.graph_runner.create_calendar_event") as mock_create:
            mock_create.invoke.return_value = {
                "error": True,
                "message": "⚠️ Time conflict detected!",
            }
            result = simple_create_event_node(model, state)
            assert "conflict" in result["feedback"].lower() or "Conflict" in result["feedback"]

    def test_add_task_to_calendar(self):
        from unittest.mock import patch, MagicMock
        from src.graph_runner import simple_create_event_node

        model = MagicMock()
        intent = UserIntent(
            action="add_task_to_calendar", task_title="Review PR",
            title="PR Block", date="2025-06-15",
            start_time="14:00", end_time="14:30",
        )
        state = {"intent": intent, "events": [], "tasks": []}

        with patch("src.graph_runner.create_calendar_event") as mock_cal, \
             patch("src.graph_runner.create_task") as mock_task:
            mock_cal.invoke.return_value = {"formatted_response": "✅ Added PR Block."}
            mock_task.invoke.return_value = {"success": True, "message": "Task created"}
            result = simple_create_event_node(model, state)

            mock_task.invoke.assert_called_once()
            assert "Review PR" in result["feedback"]
