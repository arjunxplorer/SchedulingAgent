"""Tests for time parsing and date utilities."""

import pytest
from datetime import datetime, timedelta
from src.utils.time_utils import parse_iso_date, getDateTimeFromISO8601String


class TestParseIsoDate:
    """Tests for parse_iso_date utility."""

    def test_basic_datetime(self):
        result = parse_iso_date("2025-06-15T10:30:00")
        assert result == "2025-06-15 10:30"

    def test_date_only(self):
        result = parse_iso_date("2025-06-15")
        assert result == "2025-06-15 00:00"

    def test_with_timezone(self):
        result = parse_iso_date("2025-06-15T10:30:00-05:00")
        assert "2025-06-15" in result

    def test_with_z_timezone(self):
        result = parse_iso_date("2025-06-15T15:30:00Z")
        assert "2025-06-15" in result

    def test_midnight(self):
        result = parse_iso_date("2025-06-15T00:00:00")
        assert result == "2025-06-15 00:00"

    def test_end_of_day(self):
        result = parse_iso_date("2025-06-15T23:59:59")
        assert result == "2025-06-15 23:59"

    def test_invalid_string_raises(self):
        with pytest.raises(Exception):
            parse_iso_date("not-a-date")


class TestGetDateTimeFromISO8601String:
    """Tests for the underlying ISO parser."""

    def test_returns_datetime(self):
        result = getDateTimeFromISO8601String("2025-06-15T10:30:00")
        assert isinstance(result, datetime)

    def test_date_only(self):
        result = getDateTimeFromISO8601String("2025-06-15")
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15

    def test_with_microseconds(self):
        result = getDateTimeFromISO8601String("2025-06-15T10:30:00.123456")
        assert result.microsecond == 123456


class TestTimeToolsIntegration:
    """Integration tests for time_tools module functions."""

    def test_sum_to_date_basic(self):
        from src.tools.time_tools import sum_to_date
        result = sum_to_date.invoke({"date_str": "2025-06-15T10:00:00", "weeks": 0, "days": 1, "hours": 2, "minutes": 30})
        expected = datetime(2025, 6, 16, 12, 30, 0)
        assert datetime.fromisoformat(result) == expected

    def test_sum_to_date_weeks(self):
        from src.tools.time_tools import sum_to_date
        result = sum_to_date.invoke({"date_str": "2025-06-15T10:00:00", "weeks": 2, "days": 0, "hours": 0, "minutes": 0})
        expected = datetime(2025, 6, 29, 10, 0, 0)
        assert datetime.fromisoformat(result) == expected

    def test_sum_to_date_no_change(self):
        from src.tools.time_tools import sum_to_date
        result = sum_to_date.invoke({"date_str": "2025-06-15T10:00:00", "weeks": 0, "days": 0, "hours": 0, "minutes": 0})
        expected = datetime(2025, 6, 15, 10, 0, 0)
        assert datetime.fromisoformat(result) == expected

    def test_get_date_in_iso_format_known_date(self):
        from src.tools.time_tools import get_date_in_iso_format
        result = get_date_in_iso_format.invoke({"date_str": "2025-06-15"})
        assert "2025-06-15" in result

    def test_get_date_in_iso_format_relative(self):
        from src.tools.time_tools import get_date_in_iso_format
        result = get_date_in_iso_format.invoke({"date_str": "tomorrow"})
        tomorrow = datetime.now() + timedelta(days=1)
        assert tomorrow.strftime("%Y-%m-%d") in result

    def test_get_date_in_iso_format_invalid_raises(self):
        from src.tools.time_tools import get_date_in_iso_format
        with pytest.raises(ValueError):
            get_date_in_iso_format.invoke({"date_str": "xyznotadate12345"})
