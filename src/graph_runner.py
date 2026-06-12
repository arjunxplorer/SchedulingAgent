"""Graph builder and runner — shared by CLI (agent.py) and API (api.py)."""

import os
import asyncio
import copy
from dotenv import load_dotenv
from typing import TypedDict, Annotated, AsyncGenerator
import operator
from datetime import datetime, timedelta
from functools import partial
import pytz

from langchain_together import ChatTogether
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent

from src.prompts import (
    TASK_INTERPRETER_SYSTEM,
    TASK_INTERPRETER_PROMPT,
    PLANNER_PROMPT,
    PLANNER_SYSTEM,
    EVENT_CREATOR_PROMPT,
    REVIEWER_PROMPT,
    REVIEWER_SYSTEM,
    AGENT_SYSTEM,
    REVIEW_REWRITE_PROMPT,
)
from src.models import (
    CalendarEvent,
    TaskListModel,
    CalendarEventList,
    TasksList,
    UserIntent,
)
from src.tools import (
    create_calendar_event,
    create_calendar_events,
    list_calendars,
    get_calendar_events,
    list_tasks,
    get_tasks,
    get_current_time,
    get_date_in_iso_format,
    sum_to_date,
    clear_calendar_events,
    find_free_slots,
    create_task,
    delete_task,
    suggest_alternative_times,
    update_calendar_event,
    search_events,
    find_and_delete_event,
)

load_dotenv()

try:
    from src.personal_prompt import PERSONAL_PROMPT
except ImportError:
    PERSONAL_PROMPT = ""


# ── Graph State ──────────────────────────────────────────────────────────────

class ScheduleState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    current_time: str
    user_input: str

    intent: UserIntent | None
    is_simple: bool
    calendars: CalendarEventList
    events: list[CalendarEvent]
    tasks: list[TaskListModel]
    schedule: str
    feedback: str
    rewrites: int

    # Conversation persistence
    conversation_history: list[dict]  # [{"user": str, "response": str}, ...]
    last_created_event: dict | None


def default_session_state() -> dict:
    """Return a fresh session state dict."""
    return {
        "messages": [],
        "current_time": "",
        "user_input": "",
        "intent": None,
        "is_simple": False,
        "events": [],
        "tasks": [],
        "schedule": "",
        "feedback": "",
        "rewrites": 0,
        "calendars": None,
        "conversation_history": [],
        "last_created_event": None,
    }


# ── Graph Nodes ──────────────────────────────────────────────────────────────

def simple_intent_node(state: ScheduleState) -> dict:
    """Try to parse user input with regex (no AI). Returns intent if simple, None if complex."""
    from src.simple_parser import parse_simple_intent

    result = parse_simple_intent(state["user_input"])
    if result:
        # Convert SimpleIntent to UserIntent-compatible dict
        intent_data = {
            "action": result.action,
            "title": getattr(result, "title", None),
            "date": getattr(result, "date", None),
            "start_time": getattr(result, "start_time", None),
            "end_time": getattr(result, "end_time", None),
            "target_event": getattr(result, "target_event", None),
            "modify_field": getattr(result, "modify_field", None),
            "modify_value": getattr(result, "modify_value", None),
            "query_date": getattr(result, "query_date", None),
            "task_title": getattr(result, "task_title", None),
            "task_notes": getattr(result, "task_notes", None),
            "task_due": getattr(result, "task_due", None),
            "recurrence": getattr(result, "recurrence", None),
        }
        intent = UserIntent(**{k: v for k, v in intent_data.items() if v is not None})
        return {"intent": intent, "is_simple": True}
    return {"is_simple": False}


def interpret_node(model, state: ScheduleState) -> dict:
    """Parse user input into a structured UserIntent using with_structured_output."""
    structured_model = model.with_structured_output(UserIntent)

    # Build conversation context from history
    history = state.get("conversation_history", [])
    if history:
        context_lines = ["Previous conversation:"]
        for turn in history[-5:]:  # Last 5 turns
            context_lines.append(f"User: {turn['user']}")
            context_lines.append(f"Assistant: {turn['response']}")
        conversation_context = "\n".join(context_lines)
    else:
        conversation_context = ""

    result = structured_model.invoke([
        SystemMessage(TASK_INTERPRETER_SYSTEM),
        HumanMessage(TASK_INTERPRETER_PROMPT.format(
            user_request=state["user_input"],
            current_date=state["current_time"].split("T")[0],
            conversation_context=conversation_context,
        )),
    ])

    return {"intent": result}


def get_schedule_data(state: ScheduleState) -> dict:
    """Fetch today's calendar events and tasks."""
    events = []
    tasks = []
    try:
        events = get_calendar_events()
    except Exception:
        pass  # Not authenticated or API error — continue without events
    try:
        tasks = get_tasks()
    except Exception:
        pass
    return {"events": events, "tasks": tasks}


def router_node(state: ScheduleState) -> dict:
    """Pass-through node — the conditional edge does the routing."""
    return {}


def route_intent(state: ScheduleState) -> str:
    """Route to the appropriate sub-graph based on the classified intent."""
    intent = state.get("intent")
    if not intent:
        return "end"

    action = intent.action
    if action == "create_event" or action == "add_task_to_calendar":
        return "create_event_path"
    elif action == "query":
        return "query_path"
    elif action == "modify":
        return "modify_path"
    elif action == "delete":
        return "delete_path"
    elif action == "create_task":
        return "task_path"
    elif action == "plan_schedule":
        return "plan_schedule_path"
    else:
        return "end"


def route_create_event(state: ScheduleState) -> str:
    """Decide between fast single-event creation and full schedule planning.

    Fast path (1 LLM call): user has all fields (title, date, start, end).
    Full path (4-5 LLM calls): complex requests like "plan my whole day".
    """
    import re
    intent = state.get("intent")
    if not intent:
        return "full_path"

    # Validate time format — must be HH:MM (e.g., "14:00", "9:30")
    time_pattern = re.compile(r"^\d{1,2}:\d{2}$")
    times_valid = (
        intent.start_time and intent.end_time
        and time_pattern.match(intent.start_time)
        and time_pattern.match(intent.end_time)
    )

    # Multi-activity titles (containing commas, "and", or "/" between activities)
    # should always go through the planner to get individual time slots
    is_multi_activity = intent.title and (
        ", " in intent.title
        or " and " in intent.title.lower()
        or " / " in intent.title
    )

    print(f"[ROUTE] title={intent.title!r}, times_valid={times_valid}, is_multi={is_multi_activity}, date={intent.date}, start={intent.start_time}, end={intent.end_time}")

    is_simple = times_valid and intent.title and intent.date and not intent.recurrence and not is_multi_activity

    if is_simple:
        return "simple_path"
    return "full_path"


# ── Create Event Path ───────────────────────────────────────────────────────

def simple_create_event_node(model, state: ScheduleState) -> dict:
    """Fast path: create a single event directly from intent fields.

    Skips planner, reviewer, and revise loop. Used when the user has
    provided all required fields (title, date, start_time, end_time).
    """
    import traceback
    import re
    intent = state["intent"]
    print(f"[SIMPLE_CREATE] title={intent.title!r}, date={intent.date}, start={intent.start_time}, end={intent.end_time}")

    # Validate time fields — must be HH:MM format
    time_pattern = re.compile(r"^\d{1,2}:\d{2}$")
    if not intent.start_time or not intent.end_time or not time_pattern.match(intent.start_time) or not time_pattern.match(intent.end_time):
        return {"feedback": f"❌ Could not parse time fields (start={intent.start_time}, end={intent.end_time}). Please try again with a specific time like '2pm'."}

    # Build ISO timestamps
    start_time = f"{intent.date}T{intent.start_time}:00"
    end_time = f"{intent.date}T{intent.end_time}:00"

    try:
        result = create_calendar_event.invoke({
            "summary": intent.title,
            "start_time": start_time,
            "end_time": end_time,
        })
    except Exception as e:
        traceback.print_exc()
        return {"feedback": f"❌ Error creating event: {e}"}

    # Build feedback message
    if result.get("error"):
        feedback = result.get("message", "Failed to create event.")
    elif result.get("formatted_response"):
        feedback = result["formatted_response"]
    else:
        feedback = f"✅ Created event: {intent.title} on {intent.date} from {intent.start_time} to {intent.end_time}"

    # Handle add_task_to_calendar
    if intent.action == "add_task_to_calendar" and intent.task_title:
        create_task.invoke({
            "title": intent.task_title,
            "notes": intent.task_notes or "",
            "due": intent.date or "",
        })
        feedback += f"\n✅ Also created task: {intent.task_title}"

    last_event = {
        "title": intent.title,
        "date": intent.date,
        "start_time": intent.start_time,
        "end_time": intent.end_time,
    }

    return {"feedback": feedback, "last_created_event": last_event}


def planner_node(model, state: ScheduleState) -> dict:
    """Generate or update a daily schedule incorporating the user's request."""
    intent = state["intent"]
    event_lines = [str(e) for e in state.get("events", [])]
    events_text = "\n".join(event_lines) if event_lines else "No existing events."

    # Only include tasks if the user explicitly asked to schedule tasks
    # or is doing vague planning (e.g., "plan my day").
    # For specific requests like "schedule study, workout, nap" — only schedule what was asked.
    include_tasks = (
        intent.action == "add_task_to_calendar"
        or (intent.title and "task" in intent.title.lower())
        or (intent.title and intent.title.lower() in ("daily plan", "day plan", "my day"))
    )
    if include_tasks:
        task_lines = [str(t) for t in state.get("tasks", [])]
        tasks_text = "\n".join(task_lines) if task_lines else "No tasks."
    else:
        tasks_text = "No tasks."

    print(f"[PLANNER] include_tasks={include_tasks}, title={intent.title!r}")

    user_request = (
        f"Event to schedule: {intent.title} on {intent.date} "
        f"from {intent.start_time} to {intent.end_time}"
    )
    if intent.recurrence:
        user_request += f"\nRecurrence: {intent.recurrence}"

    if intent.action == "add_task_to_calendar" and intent.task_title:
        user_request += f"\nAlso create task: {intent.task_title}"
        if intent.task_notes:
            user_request += f" (notes: {intent.task_notes})"

    if state.get("feedback"):
        user_request += f"\n\nFeedback from review:\n{state['feedback']}"

    response = model.invoke([
        SystemMessage(PLANNER_SYSTEM + "\n" + PERSONAL_PROMPT),
        HumanMessage(PLANNER_PROMPT.format(
            current_time=state["current_time"],
            events=events_text,
            tasks=tasks_text,
        ) + "\n\n" + user_request),
    ])

    return {"schedule": response.content, "rewrites": state.get("rewrites", 0) + 1}


def event_creator_node(model, state: ScheduleState) -> dict:
    """Create calendar events from the schedule using the react agent."""
    creator = create_react_agent(
        model,
        [create_calendar_events, get_current_time, get_date_in_iso_format],
    )

    creator.invoke({
        "messages": [HumanMessage(EVENT_CREATOR_PROMPT.format(schedule=state["schedule"]))],
    })

    last_event = None
    if state.get("intent") and state["intent"].title:
        last_event = {
            "title": state["intent"].title,
            "date": state["intent"].date,
            "start_time": state["intent"].start_time,
            "end_time": state["intent"].end_time,
        }

    intent = state.get("intent")
    if intent and intent.action == "add_task_to_calendar" and intent.task_title:
        create_task.invoke({
            "title": intent.task_title,
            "notes": intent.task_notes or "",
            "due": intent.date or "",
        })

    return {"last_created_event": last_event}


def reviewer_node(model, state: ScheduleState) -> dict:
    """Review the schedule for correctness."""
    events_text = "\n".join(str(e) for e in state.get("events", []))

    response = model.invoke([
        SystemMessage(REVIEWER_SYSTEM),
        HumanMessage(REVIEWER_PROMPT.format(
            events=events_text,
            schedule=state["schedule"],
        )),
    ])

    return {"feedback": response.content}


def should_revise(state: ScheduleState) -> str:
    """Route to revision loop if reviewer suggests changes, otherwise end."""
    feedback = state.get("feedback", "")
    if "CHANGES" in feedback and state.get("rewrites", 0) < 3:
        return "revise"
    return "end"


def revise_node(model, state: ScheduleState) -> dict:
    """Rewrite the schedule based on reviewer feedback."""
    events_text = "\n".join(str(e) for e in state.get("events", [])) or "No existing events."

    response = model.invoke([
        SystemMessage(PLANNER_SYSTEM),
        HumanMessage(REVIEW_REWRITE_PROMPT.format(
            events=events_text,
            schedule=state["schedule"],
            feedback=state["feedback"],
        )),
    ])

    return {"schedule": response.content}


# ── Query Path ──────────────────────────────────────────────────────────────

def query_node(model, state: ScheduleState) -> dict:
    """Handle calendar queries: list events, check availability, find free slots."""
    intent = state["intent"]
    query_date = intent.query_date or "today"

    events = search_events.invoke({"query": "", "date_range": query_date})

    # For single-day queries, also fetch free slots
    free_slots_text = ""
    is_single_day = query_date not in ("this_week", "next_week")
    if is_single_day:
        try:
            tz = pytz.timezone("America/Chicago")
            if query_date == "today":
                slot_date = datetime.now(tz).strftime("%Y-%m-%d")
            elif query_date == "tomorrow":
                slot_date = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                slot_date = query_date
            free = find_free_slots.invoke({"date": slot_date, "duration_minutes": 60})
            if free:
                free_lines = []
                for slot in free:
                    dur = slot["duration_minutes"]
                    hours = dur // 60
                    mins = dur % 60
                    dur_str = f"{hours}h{mins}m" if mins else f"{hours}h"
                    free_lines.append(f"  • {slot['start']} - {slot['end']} ({dur_str})")
                free_slots_text = "\n\n🕐 Free slots:\n" + "\n".join(free_lines)
        except Exception:
            pass

    # Check if the user is asking for suggestions (not just listing events)
    user_input_lower = state.get("user_input", "").lower()
    is_suggestion_query = any(word in user_input_lower for word in [
        "good time", "best time", "when should", "when can", "suggest",
        "recommend", "available", "free", "fit in",
    ])

    if not events and not free_slots_text:
        response_text = f"No events found for {query_date}."
    elif is_suggestion_query and (free_slots_text or events):
        # Use AI to generate a helpful suggestion
        events_summary = "\n".join(
            f"  • {ev['summary']} ({ev.get('start', '?')} - {ev.get('end', '?')})"
            for ev in events
        ) if events else "No events."

        ai_response = model.invoke([
            SystemMessage("You are a scheduling assistant. Given a user's question about their calendar, provide a helpful, concise suggestion. Be specific about times."),
            HumanMessage(
                f"User asked: {state['user_input']}\n\n"
                f"Events on {query_date}:\n{events_summary}\n"
                f"{free_slots_text}\n\n"
                f"Suggest a good time for what the user wants to do. Be specific and brief."
            ),
        ])
        response_text = ai_response.content
    elif is_single_day:
        # Single-day: list events + free slots
        lines = [f"📅 Events for {query_date}:"]
        if events:
            for ev in events:
                start = ev["start"]
                end = ev["end"]
                try:
                    s = datetime.fromisoformat(start)
                    e = datetime.fromisoformat(end)
                    time_str = f"{s.strftime('%I:%M %p').lstrip('0')} - {e.strftime('%I:%M %p').lstrip('0')}"
                except (ValueError, AttributeError):
                    time_str = "All day"
                lines.append(f" • {time_str} — {ev['summary']}")
        else:
            lines.append("  No events.")
        if free_slots_text:
            lines.append(free_slots_text.strip())
        response_text = "\n".join(lines)
    else:
        # Multi-day: group events by date
        events_by_date: dict[str, list[str]] = {}
        for ev in events:
            start = ev["start"]
            end = ev["end"]
            try:
                s = datetime.fromisoformat(start)
                e = datetime.fromisoformat(end)
                day_label = s.strftime("%a %m/%d")
                time_str = f"{s.strftime('%I:%M %p').lstrip('0')} - {e.strftime('%I:%M %p').lstrip('0')}"
            except (ValueError, AttributeError):
                day_label = "Unknown"
                time_str = "All day"
            events_by_date.setdefault(day_label, []).append(f"  • {time_str} — {ev['summary']}")
        lines = [f"📅 Events for {query_date}:"]
        for day_label, event_lines in events_by_date.items():
            lines.append(f"\n{day_label}:")
            lines.extend(event_lines)
        response_text = "\n".join(lines)

    return {"feedback": response_text}


# ── Plan Schedule Path ──────────────────────────────────────────────────────

def plan_schedule_node(model, state: ScheduleState) -> dict:
    """Show events + free slots for a date range, then ask what to schedule."""
    intent = state["intent"]
    query_date = intent.query_date or "next_week"

    tz = pytz.timezone("America/Chicago")
    now = datetime.now(tz)

    # Resolve date range to list of (date_obj, day_label) tuples
    if query_date == "next_week":
        days_since_monday = now.weekday()
        next_monday = now + timedelta(days=7 - days_since_monday)
        dates = [(next_monday + timedelta(days=i), (next_monday + timedelta(days=i)).strftime("%a %m/%d")) for i in range(7)]
        range_label = "Next Week"
    elif query_date == "this_week":
        days_since_monday = now.weekday()
        monday = now - timedelta(days=days_since_monday)
        dates = [(monday + timedelta(days=i), (monday + timedelta(days=i)).strftime("%a %m/%d")) for i in range(7)]
        range_label = "This Week"
    else:
        # Single date
        try:
            d = datetime.fromisoformat(query_date).replace(tzinfo=tz)
            dates = [(d, d.strftime("%a %m/%d"))]
            range_label = d.strftime("%A %m/%d")
        except ValueError:
            dates = [(now, now.strftime("%a %m/%d"))]
            range_label = "Today"

    # Fetch events for the whole range
    events = search_events.invoke({"query": "", "date_range": query_date})

    # Group events by date string (YYYY-MM-DD)
    events_by_date: dict[str, list[dict]] = {}
    for ev in events:
        try:
            s = datetime.fromisoformat(ev["start"])
            day_key = s.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            continue
        events_by_date.setdefault(day_key, []).append(ev)

    lines = [f"📅 {range_label} Overview:\n"]

    for date_obj, day_label in dates:
        day_key = date_obj.strftime("%Y-%m-%d")
        day_events = events_by_date.get(day_key, [])

        lines.append(f"{day_label}:")

        if day_events:
            lines.append("  Events:")
            for ev in day_events:
                try:
                    s = datetime.fromisoformat(ev["start"])
                    e = datetime.fromisoformat(ev["end"])
                    time_str = f"{s.strftime('%I:%M %p').lstrip('0')} - {e.strftime('%I:%M %p').lstrip('0')}"
                except (ValueError, AttributeError):
                    time_str = "All day"
                lines.append(f"    • {time_str} — {ev['summary']}")
        else:
            lines.append("  Events: None")

        # Find free slots for this day
        try:
            free = find_free_slots.invoke({"date": day_key, "duration_minutes": 60})
            if free:
                lines.append("  Free slots:")
                for slot in free:
                    start_h = slot["start"]
                    end_h = slot["end"]
                    dur = slot["duration_minutes"]
                    hours = dur // 60
                    mins = dur % 60
                    dur_str = f"{hours}h{mins}m" if mins else f"{hours}h"
                    lines.append(f"    • {start_h} - {end_h} ({dur_str})")
            else:
                lines.append("  Free slots: None")
        except Exception:
            lines.append("  Free slots: Unable to compute")

        lines.append("")

    lines.append("What would you like to schedule?")
    response_text = "\n".join(lines)

    return {"feedback": response_text}


# ── Modify Path ─────────────────────────────────────────────────────────────

def modify_node(model, state: ScheduleState) -> dict:
    """Handle event modifications: reschedule, rename, change duration."""
    intent = state["intent"]

    events = search_events.invoke({
        "query": intent.target_event or "",
        "date_range": "this_week",
    })

    if not events:
        return {"feedback": f"❌ Could not find an event matching '{intent.target_event}'."}

    target = events[0]
    update_args = {"event_id": target["id"]}

    if intent.modify_field == "title":
        update_args["summary"] = intent.modify_value
    elif intent.modify_field == "time":
        try:
            new_date = intent.date or target["start"].split("T")[0]
            new_time = intent.modify_value
            new_start = f"{new_date}T{new_time}:00"
            orig_start = datetime.fromisoformat(target["start"])
            orig_end = datetime.fromisoformat(target["end"])
            duration = orig_end - orig_start
            new_start_dt = datetime.fromisoformat(new_start)
            new_end_dt = new_start_dt + duration
            update_args["start_time"] = new_start_dt.isoformat()
            update_args["end_time"] = new_end_dt.isoformat()
        except (ValueError, TypeError) as e:
            return {"feedback": f"❌ Could not parse the new time: {e}"}
    elif intent.modify_field == "duration":
        try:
            orig_start = datetime.fromisoformat(target["start"])
            value = intent.modify_value or ""
            if "hour" in value:
                hours = int("".join(filter(str.isdigit, value)) or "1")
                new_end = orig_start + timedelta(hours=hours)
            elif "min" in value:
                minutes = int("".join(filter(str.isdigit, value)) or "30")
                new_end = orig_start + timedelta(minutes=minutes)
            else:
                return {"feedback": f"❌ Could not parse duration: '{value}'. Use '1 hour' or '30 minutes'."}
            update_args["start_time"] = target["start"]
            update_args["end_time"] = new_end.isoformat()
        except (ValueError, TypeError) as e:
            return {"feedback": f"❌ Could not adjust duration: {e}"}

    result = update_calendar_event.invoke(update_args)

    if result.get("success"):
        return {"feedback": f"✅ {result['message']}"}
    else:
        return {"feedback": f"❌ Failed to update event: {result}"}


# ── Delete Path ─────────────────────────────────────────────────────────────

def delete_node(model, state: ScheduleState) -> dict:
    """Handle deletion — events or tasks."""
    intent = state["intent"]
    user_input_lower = state.get("user_input", "").lower()
    target = intent.target_event or intent.title or ""

    # Check if user wants to delete a TASK (not a calendar event)
    is_task_delete = (
        "task" in user_input_lower
        or intent.action == "delete_task"
    )

    if is_task_delete and target:
        result = delete_task.invoke({"title": target})
        return {"feedback": result.get("message", "Done.")}

    date_range = intent.date or "today"

    events = search_events.invoke({
        "query": "" if intent.target_event == "all" else (intent.target_event or ""),
        "date_range": date_range,
    })

    if not events:
        return {"feedback": f"❌ No events found for {date_range}."}

    # Bulk delete: remove all events
    if intent.target_event == "all":
        calendar_id = os.getenv("CALENDAR_ID", "primary")
        deleted = []
        failed = []

        for ev in events:
            event_date = datetime.fromisoformat(ev["start"].split("T")[0])
            success, message, _ = find_and_delete_event(
                calendar_id=calendar_id,
                summary=ev["summary"],
                date=event_date,
            )
            if success:
                deleted.append(ev["summary"])
            else:
                failed.append(ev["summary"])

        parts = []
        if deleted:
            parts.append(f"✅ Removed {len(deleted)} event(s): {', '.join(deleted)}")
        if failed:
            parts.append(f"❌ Failed to remove: {', '.join(failed)}")
        return {"feedback": "\n".join(parts) if parts else f"❌ No events found for {date_range}."}

    # Single delete: remove first matching event
    target = events[0]
    event_date = datetime.fromisoformat(target["start"].split("T")[0])

    success, message, remaining = find_and_delete_event(
        calendar_id=os.getenv("CALENDAR_ID", "primary"),
        summary=target["summary"],
        date=event_date,
    )

    if success:
        return {"feedback": message}
    else:
        return {"feedback": f"❌ {message}"}


# ── Task Path ───────────────────────────────────────────────────────────────

def task_node(model, state: ScheduleState) -> dict:
    """Handle task creation (standalone, without calendar event)."""
    intent = state["intent"]

    result = create_task.invoke({
        "title": intent.task_title or intent.title or "Untitled task",
        "notes": intent.task_notes or "",
        "due": intent.task_due or intent.date or "",
    })

    if result.get("success"):
        return {"feedback": result["message"]}
    else:
        return {"feedback": f"❌ Failed to create task: {result}"}


# ── Build Graph ──────────────────────────────────────────────────────────────

def route_simple_or_complex(state: ScheduleState) -> str:
    """Route to direct execution (simple) or AI path (complex)."""
    if state.get("is_simple"):
        return "simple_route"
    return "ai_route"


def build_graph(model):
    """Build and compile the scheduling LangGraph graph.

    Architecture:
    - Simple tasks (delete, query, modify, create with time) → regex parser → direct execution (0 AI calls)
    - Complex tasks (plan day, multi-activity, ambiguous) → AI interpreter → reasoning → execution
    """
    graph = StateGraph(ScheduleState)

    # Entry point: try regex parser first (no AI)
    graph.add_node("simple_intent", simple_intent_node)

    # Simple path: direct execution (0 AI calls)
    graph.add_node("get_schedule_data", get_schedule_data)
    graph.add_node("router", router_node)
    graph.add_node("simple_create", partial(simple_create_event_node, model))
    graph.add_node("query", partial(query_node, model))
    graph.add_node("plan_schedule", partial(plan_schedule_node, model))
    graph.add_node("modify", partial(modify_node, model))
    graph.add_node("delete", partial(delete_node, model))
    graph.add_node("task", partial(task_node, model))

    # AI path: complex tasks only (1+ AI calls)
    graph.add_node("interpret", partial(interpret_node, model))
    graph.add_node("ai_get_schedule_data", get_schedule_data)
    graph.add_node("ai_router", router_node)
    graph.add_node("planner", partial(planner_node, model))
    graph.add_node("event_creator", partial(event_creator_node, model))
    graph.add_node("reviewer", partial(reviewer_node, model))
    graph.add_node("revise", partial(revise_node, model))

    # ── Entry: try simple parser first ────────────────────────────────────
    graph.set_entry_point("simple_intent")
    graph.add_conditional_edges("simple_intent", route_simple_or_complex, {
        "simple_route": "get_schedule_data",
        "ai_route": "interpret",
    })

    # ── Simple path: direct execution (no AI) ─────────────────────────────
    graph.add_edge("get_schedule_data", "router")
    graph.add_conditional_edges("router", route_intent, {
        "create_event_path": "create_event_router",
        "query_path": "query",
        "plan_schedule_path": "plan_schedule",
        "modify_path": "modify",
        "delete_path": "delete",
        "task_path": "task",
        "end": END,
    })

    graph.add_node("create_event_router", router_node)
    graph.add_conditional_edges("create_event_router", route_create_event, {
        "simple_path": "simple_create",
        "full_path": "planner",
    })

    graph.add_edge("simple_create", END)
    graph.add_edge("query", END)
    graph.add_edge("plan_schedule", END)
    graph.add_edge("modify", END)
    graph.add_edge("delete", END)
    graph.add_edge("task", END)

    # ── AI path: complex tasks with reasoning ─────────────────────────────
    graph.add_edge("interpret", "ai_get_schedule_data")
    graph.add_edge("ai_get_schedule_data", "ai_router")
    graph.add_conditional_edges("ai_router", route_intent, {
        "create_event_path": "create_event_router",
        "query_path": "query",
        "plan_schedule_path": "plan_schedule",
        "modify_path": "modify",
        "delete_path": "delete",
        "task_path": "task",
        "end": END,
    })

    graph.add_edge("planner", "event_creator")
    graph.add_edge("event_creator", "reviewer")
    graph.add_conditional_edges("reviewer", should_revise, {"revise": "revise", "end": END})
    graph.add_edge("revise", "planner")

    return graph.compile()


# ── Convenience ──────────────────────────────────────────────────────────────

def create_default_model():
    """Create the LLM model based on MODEL_PROVIDER env var.

    Providers:
        - "together" (default): TogetherAI Llama 3.3 70B
        - "mimo": Xiaomi MiMo v2.5 Pro via OpenAI-compatible API
        - "anthropic": Claude via Anthropic API (uses ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL)
    """
    provider = os.environ.get("MODEL_PROVIDER", "together").lower()

    if provider.startswith("mimo"):
        return ChatOpenAI(
            model="mimo-v2.5-pro",
            openai_api_key=os.environ.get("MIMO_API_KEY"),
            openai_api_base="https://api.xiaomimimo.com/v1",
            temperature=1.0,
            max_tokens=1024,
            model_kwargs={
                "top_p": 0.95,
                "extra_body": {"thinking": {"type": "disabled"}},
            },
        )

    if provider.startswith("anthropic"):
        return ChatAnthropic(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            temperature=0,
            max_tokens=8192,
            top_p=0.95,
            thinking={"type": "disabled"},
        )

    # Default: TogetherAI
    return ChatTogether(
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        temperature=0,
        max_tokens=4000,
    )


async def run_graph_async(graph, user_input: str, session_state: dict) -> dict:
    """Run the graph with the given input and updated session state. Returns the result dict."""
    loop = asyncio.get_running_loop()

    session_state["user_input"] = user_input
    session_state["current_time"] = await loop.run_in_executor(None, lambda: get_current_time.invoke({}))
    session_state["intent"] = None
    session_state["schedule"] = ""
    session_state["feedback"] = ""
    session_state["rewrites"] = 0

    result = await loop.run_in_executor(None, lambda: graph.invoke(session_state))

    # Persist state
    session_state.update(result)

    # Track conversation history
    response_text = result.get("feedback", "")
    session_state["conversation_history"].append({
        "user": user_input,
        "response": response_text,
    })

    return result


async def stream_graph_events(graph, user_input: str, session_state: dict) -> AsyncGenerator[dict, None]:
    """Run the graph and yield SSE-compatible event dicts as nodes execute.

    The synchronous graph.stream() iterator is consumed in a background thread
    so it never blocks the FastAPI event loop.
    """
    loop = asyncio.get_running_loop()

    session_state["user_input"] = user_input
    session_state["current_time"] = await loop.run_in_executor(None, lambda: get_current_time.invoke({}))
    session_state["intent"] = None
    session_state["schedule"] = ""
    session_state["feedback"] = ""
    session_state["rewrites"] = 0

    # Map node names to human-readable status
    status_messages = {
        "simple_intent": "Understanding your request...",
        "interpret": "Analyzing your request...",
        "get_schedule_data": "Fetching your calendar...",
        "ai_get_schedule_data": "Fetching your calendar...",
        "router": "Routing...",
        "ai_router": "Routing...",
        "create_event_router": "Routing...",
        "simple_create": "Creating event...",
        "planner": "Planning your schedule...",
        "event_creator": "Creating events...",
        "reviewer": "Reviewing the result...",
        "revise": "Revising based on feedback...",
        "query": "Searching your calendar...",
        "plan_schedule": "Planning your schedule...",
        "modify": "Updating event...",
        "delete": "Deleting event...",
        "task": "Creating task...",
    }

    response_text = ""

    try:
        # Run the synchronous graph.stream() in a background thread
        # and consume events through an async queue
        event_queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def _consume_sync_stream():
            try:
                for event in graph.stream(session_state):
                    loop.call_soon_threadsafe(event_queue.put_nowait, copy.deepcopy(event))
            except Exception as e:
                loop.call_soon_threadsafe(event_queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(event_queue.put_nowait, sentinel)

        stream_thread = asyncio.get_event_loop().run_in_executor(
            None, _consume_sync_stream
        )

        final_result = None
        while True:
            event = await event_queue.get()
            if event is sentinel:
                break
            if isinstance(event, Exception):
                raise event

            node_name = list(event.keys())[0]
            node_result = event[node_name]

            yield {
                "type": "status",
                "node": node_name,
                "message": status_messages.get(node_name, f"Running {node_name}..."),
            }

            # Emit intent details after interpretation
            if node_name == "interpret" and node_result and node_result.get("intent"):
                intent = node_result["intent"]
                yield {
                    "type": "intent",
                    "action": intent.action,
                    "title": intent.title,
                    "date": intent.date,
                }

            final_result = event

        # Ensure thread completed
        await stream_thread

        # Persist final state
        if final_result:
            for node_result in final_result.values():
                if isinstance(node_result, dict):
                    session_state.update(node_result)

        response_text = session_state.get("feedback", "")
        if not response_text:
            intent = session_state.get("intent")
            if intent and intent.title:
                response_text = f"✅ Done. Let me know if you need any changes."
            else:
                # Use AI for conversational fallback
                try:
                    fallback_model = create_default_model()
                    ai_resp = fallback_model.invoke([
                        SystemMessage("You are a friendly scheduling assistant. The user said something that isn't a direct scheduling command. Respond helpfully and conversationally. If they seem confused, gently suggest what they can ask you to do. Keep it brief (1-3 sentences)."),
                        HumanMessage(user_input),
                    ])
                    response_text = ai_resp.content
                except Exception:
                    response_text = "I'm not sure what you'd like me to do. Try something like:\n• \"Schedule a meeting tomorrow at 2pm\"\n• \"What's on my calendar today?\"\n• \"Add buy groceries to my list\""
        session_state["conversation_history"].append({
            "user": user_input,
            "response": response_text,
        })

    except Exception as e:
        response_text = f"Error: {e}"
        yield {"type": "error", "message": str(e)}

    yield {"type": "message", "content": response_text}
    yield {"type": "done"}
