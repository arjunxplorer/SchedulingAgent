# Agents and tools
from langchain.tools import BaseTool, StructuredTool, tool
from datetime import datetime, timedelta

import dateparser
import pytz



@tool
def get_current_time() -> str:
    """Get the current time in ISO format."""

    # Get the current time in local timezone
    local_now = datetime.now(pytz.timezone("America/Chicago"))

    return local_now.isoformat()


@tool
def get_date_in_iso_format(date_str: str, reference_date: str = None) -> str:
    """Convert natural language date/time string into ISO format (YYYY-MM-DDTHH:MM:SS).

    Args:
        date_str (str): natural language date/time string
        reference_date (str): ISO date for reference (defaults to today)

    Returns:
        ISO formatted datetime string
    """
    timezone = pytz.timezone("America/Chicago")  # Change accordingly

    # Determine the reference date
    if reference_date:
        ref_dt = datetime.fromisoformat(reference_date).astimezone(timezone)
    else:
        ref_dt = datetime.now(timezone)

    date_obj = dateparser.parse(
        date_str,
        settings={
            "TIMEZONE": str(timezone),
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": ref_dt
        }
    )

    if not date_obj:
        raise ValueError(f"Could not parse date: '{date_str}' with reference '{ref_dt}'.")

    return date_obj.isoformat()


from pydantic import BaseModel, Field


class SumToDateInput(BaseModel):
    date_str: str = Field(
        description="The date to which weeks, days, hours, and minutes will be added. Should be a string"
    )
    weeks: int = Field(description="Number of weeks to add")
    days: int = Field(description="Number of days to add")
    hours: int = Field(description="Number of hours to add")
    minutes: int = Field(description="Number of minutes to add")


@tool(args_schema=SumToDateInput)
def sum_to_date(date_str: str, weeks: int, days: int, hours: int, minutes: int) -> str:
    """Add weeks, days, hours, and minutes to a date string in ISO format.

    Args:
        date_str: The date string in ISO format
        weeks (int): the number of weeks to sum
        days (int): the number of days to sum
        hours (int): the number of hours to sum
        minutes (int): the number of minutes to sum


    Returns: The resulting date in ISO format.
    """
    date_obj = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
    return (
        date_obj + timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes)
    ).isoformat()
