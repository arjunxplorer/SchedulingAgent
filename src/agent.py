import os
from dotenv import load_dotenv
from typing import Any, TypedDict, Annotated, Dict
import operator
from datetime import datetime

# Agent imports
from langchain_ollama import ChatOllama
from langchain_together import ChatTogether
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage, ToolMessage

# from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from langfuse import Langfuse
from langfuse.callback import CallbackHandler
from langgraph.graph.state import CompiledStateGraph
import openai

from langchain_core.messages import SystemMessage
from src.prompts import TASK_INTERPRETER_SYSTEM, TASK_INTERPRETER_PROMPT
from src.tools import create_calendar_event, get_date_in_iso_format
from src.tools import get_current_time

# Prompts
from src.prompts import (
    AGENT_SYSTEM,
    PLANNER_PROMPT,
    EVENT_CREATOR_PROMPT,
    PLANNER_SYSTEM,
    REVIEW_PROMT,
    REVIEWER_PROMPT,
    REVIEWER_SYSTEM,
)

try:
    from src.personal_prompt import PERSONAL_PROMPT
except ImportError:
    PERSONAL_PROMPT = ""

# Models imports
from src.models import (
    CalendarEvent,
    TaskListModel,
    CalendarEventList,
    TasksList,
)

# Tools imports
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
)

load_dotenv()


# GRAPH
class ScheduleState(TypedDict):
    # Processing metadata
    messages: Annotated[
        list[AnyMessage], operator.add
    ]  # Track conversation with LLM for analysis
    current_time: str

    calendars: CalendarEventList  # List of calendars
    events: list[CalendarEvent]  # List of calendar events
    tasks: list[TaskListModel]  # List of tasks
    schedule: str  # Generated schedule
    feedback: str  # Feedback of the schedule

    rewrites: int  # Number of rewrites done


class Agent:
    def __init__(self, model, tools) -> None:
        self.tools = {t.name: t for t in tools}
        self.model = model.bind_tools(tools)

    def interpret_and_create_event(self, user_input: str):
        try:
            current_iso_date = get_current_time.invoke({})
            current_date = datetime.strptime(current_iso_date.split("T")[0], '%Y-%m-%d')
            max_retries = 2
            retry_count = 0

            while retry_count < max_retries:
                try:
                    # First attempt with normal prompt
                    interpretation = self.model.invoke([
                        SystemMessage(TASK_INTERPRETER_SYSTEM),
                        HumanMessage(TASK_INTERPRETER_PROMPT.format(
                            user_request=user_input,
                            current_date=current_iso_date.split("T")[0]
                        ))
                    ])

                    if not interpretation or not interpretation.content:
                        raise ValueError("Empty response from model")

                    # Clean and validate the response
                    details = [line.strip() for line in interpretation.content.strip().split('\n') if line.strip()]

                    # Take only the first 4 non-empty lines
                    details = details[:4]

                    if len(details) != 4:
                        raise ValueError(f"Invalid response format. Expected 4 lines, got {len(details)}")

                    event_details = {}
                    for detail in details:
                        if ":" in detail:
                            key, value = detail.split(":", 1)
                            key = key.strip().lower().replace(" ", "_")
                            value = value.strip()
                            if not value:
                                raise ValueError(f"Empty value for field: {key}")
                            event_details[key] = value
                        else:
                            raise ValueError(f"Invalid line format: {detail}")

                    # Validate required fields
                    required_fields = ['title_of_event/task', 'date', 'start_time', 'end_time']
                    missing_fields = [field for field in required_fields if field not in event_details]
                    if missing_fields:
                        raise ValueError(f"Missing fields: {missing_fields}")

                    # Validate date format
                    try:
                        event_date = datetime.strptime(event_details['date'], '%Y-%m-%d')
                        # If the date is in the past, it's likely a mistake in the model's calculation
                        if event_date < current_date:
                            raise ValueError(f"Date {event_details['date']} is in the past")
                    except ValueError as e:
                        raise ValueError(f"Invalid date format: {event_details['date']}. Expected YYYY-MM-DD")

                    # Validate time format
                    for time_field in ['start_time', 'end_time']:
                        try:
                            datetime.strptime(event_details[time_field], '%H:%M')
                        except ValueError:
                            raise ValueError(f"Invalid time format: {event_details[time_field]}. Expected HH:MM")

                    # Create the event
                    start_datetime = get_date_in_iso_format.invoke({
                        "date_str": f"{event_details['date']} {event_details['start_time']}",
                        "reference_date": current_iso_date
                    })

                    end_datetime = get_date_in_iso_format.invoke({
                        "date_str": f"{event_details['date']} {event_details['end_time']}",
                        "reference_date": current_iso_date
                    })

                    event = create_calendar_event.invoke({
                        "summary": event_details['title_of_event/task'],
                        "start_time": start_datetime,
                        "end_time": end_datetime
                    })

                    if isinstance(event, dict):
                        if event.get("error"):
                            print("\n" + event["message"])
                            return None
                        elif event.get("success"):
                            print("\n" + event["message"])
                            return None

                    print("Event created successfully:", event['htmlLink'])
                    if 'formatted_response' in event:
                        print("\n" + event['formatted_response'])
                    return event

                except Exception as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        raise
                    print(f"Attempt {retry_count} failed: {str(e)}. Retrying with more explicit prompt...")
                    # Add a more explicit prompt for the retry
                    user_input = f"Please schedule this event with exact times and date: {user_input}"

        except Exception as e:
            print(f"Error creating event: {str(e)}")
            raise






def run_interactive_event_creator(agent: Agent):
    print("Enter your tasks or events (type 'exit' to stop):")
    while True:
        user_input = input("\nTask/Event: ")
        if user_input.lower() == "exit":
            break
        try:
            agent.interpret_and_create_event(user_input)
        except Exception as e:
            print("Error creating event:", e)

if __name__ == "__main__":
    # Initialize our LLM
    model = ChatTogether(model="meta-llama/Llama-3.3-70B-Instruct-Turbo-Free", temperature=0, max_tokens=4000)

    tools = [
        get_current_time,
        get_date_in_iso_format,
        create_calendar_event,
    ]
    agent = Agent(model, tools)
    run_interactive_event_creator(agent)
