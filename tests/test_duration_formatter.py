"""Tests for DurationFormatter"""
from datetime import timedelta
import pytest
from light_bot.formatters.duration_formatter import DurationFormatter


class TestDurationFormatter:
    """Test cases for duration formatting in Ukrainian"""

    def test_format_seconds(self):
        """Test formatting of durations less than a minute"""
        assert DurationFormatter.format_duration(timedelta(seconds=1)) == "1 секунда"
        assert DurationFormatter.format_duration(timedelta(seconds=2)) == "2 секунди"
        assert DurationFormatter.format_duration(timedelta(seconds=5)) == "5 секунд"
        assert DurationFormatter.format_duration(timedelta(seconds=21)) == "21 секунда"
        assert DurationFormatter.format_duration(timedelta(seconds=45)) == "45 секунд"

    def test_format_minutes(self):
        """Test formatting of durations in minutes"""
        assert DurationFormatter.format_duration(timedelta(minutes=1)) == "1 хвилина"
        assert DurationFormatter.format_duration(timedelta(minutes=2)) == "2 хвилини"
        assert DurationFormatter.format_duration(timedelta(minutes=5)) == "5 хвилин"
        assert DurationFormatter.format_duration(timedelta(minutes=15)) == "15 хвилин"
        assert DurationFormatter.format_duration(timedelta(minutes=21)) == "21 хвилина"
        assert DurationFormatter.format_duration(timedelta(minutes=45)) == "45 хвилин"

    def test_format_hours(self):
        """Test formatting of durations in hours"""
        assert DurationFormatter.format_duration(timedelta(hours=1)) == "1 година"
        assert DurationFormatter.format_duration(timedelta(hours=2)) == "2 години"
        assert DurationFormatter.format_duration(timedelta(hours=5)) == "5 годин"
        assert DurationFormatter.format_duration(timedelta(hours=11)) == "11 годин"
        assert DurationFormatter.format_duration(timedelta(hours=21)) == "21 година"

    def test_format_days(self):
        """Test formatting of durations in days"""
        assert DurationFormatter.format_duration(timedelta(days=1)) == "1 день"
        assert DurationFormatter.format_duration(timedelta(days=2)) == "2 дні"
        assert DurationFormatter.format_duration(timedelta(days=5)) == "5 днів"
        assert DurationFormatter.format_duration(timedelta(days=11)) == "11 днів"
        assert DurationFormatter.format_duration(timedelta(days=21)) == "21 день"

    def test_format_hours_and_minutes(self):
        """Test formatting of combined hours and minutes"""
        assert DurationFormatter.format_duration(
            timedelta(hours=1, minutes=15)
        ) == "1 година 15 хвилин"

        assert DurationFormatter.format_duration(
            timedelta(hours=2, minutes=30)
        ) == "2 години 30 хвилин"

        assert DurationFormatter.format_duration(
            timedelta(hours=5, minutes=45)
        ) == "5 годин 45 хвилин"

        assert DurationFormatter.format_duration(
            timedelta(hours=23, minutes=1)
        ) == "23 години 1 хвилина"

    def test_format_days_and_hours(self):
        """Test formatting of combined days and hours (no minutes when days > 0)"""
        assert DurationFormatter.format_duration(
            timedelta(days=1, hours=2)
        ) == "1 день 2 години"

        assert DurationFormatter.format_duration(
            timedelta(days=2, hours=5)
        ) == "2 дні 5 годин"

        # Minutes should be ignored when days > 0
        assert DurationFormatter.format_duration(
            timedelta(days=1, hours=2, minutes=30)
        ) == "1 день 2 години"

    def test_format_only_days(self):
        """Test formatting when only full days"""
        assert DurationFormatter.format_duration(timedelta(days=3)) == "3 дні"
        assert DurationFormatter.format_duration(timedelta(days=7)) == "7 днів"

    def test_format_edge_cases(self):
        """Test edge cases and special numbers"""
        # 11-19 always use "днів", "годин", "хвилин"
        assert DurationFormatter.format_duration(timedelta(days=11)) == "11 днів"
        assert DurationFormatter.format_duration(timedelta(hours=11)) == "11 годин"
        assert DurationFormatter.format_duration(timedelta(minutes=11)) == "11 хвилин"

        # 111, 112, etc. should use proper forms
        assert DurationFormatter.format_duration(timedelta(days=111)) == "111 днів"
        assert DurationFormatter.format_duration(timedelta(days=121)) == "121 день"
        assert DurationFormatter.format_duration(timedelta(days=122)) == "122 дні"

    def test_format_very_short_duration(self):
        """Test very short durations"""
        assert DurationFormatter.format_duration(timedelta(seconds=0)) == "0 секунд"
        assert DurationFormatter.format_duration(timedelta(seconds=30)) == "30 секунд"

    def test_format_complex_duration(self):
        """Test complex real-world durations"""
        # 2 days, 3 hours, 45 minutes
        duration = timedelta(days=2, hours=3, minutes=45, seconds=30)
        assert DurationFormatter.format_duration(duration) == "2 дні 3 години"

        # 1 day, 1 hour (edge case with singular forms)
        duration = timedelta(days=1, hours=1)
        assert DurationFormatter.format_duration(duration) == "1 день 1 година"

    def test_pluralize_days(self):
        """Test day pluralization directly"""
        assert DurationFormatter._pluralize_days(1) == "1 день"
        assert DurationFormatter._pluralize_days(2) == "2 дні"
        assert DurationFormatter._pluralize_days(3) == "3 дні"
        assert DurationFormatter._pluralize_days(4) == "4 дні"
        assert DurationFormatter._pluralize_days(5) == "5 днів"
        assert DurationFormatter._pluralize_days(11) == "11 днів"
        assert DurationFormatter._pluralize_days(21) == "21 день"
        assert DurationFormatter._pluralize_days(22) == "22 дні"

    def test_pluralize_hours(self):
        """Test hour pluralization directly"""
        assert DurationFormatter._pluralize_hours(1) == "1 година"
        assert DurationFormatter._pluralize_hours(2) == "2 години"
        assert DurationFormatter._pluralize_hours(5) == "5 годин"
        assert DurationFormatter._pluralize_hours(11) == "11 годин"
        assert DurationFormatter._pluralize_hours(21) == "21 година"

    def test_pluralize_minutes(self):
        """Test minute pluralization directly"""
        assert DurationFormatter._pluralize_minutes(1) == "1 хвилина"
        assert DurationFormatter._pluralize_minutes(2) == "2 хвилини"
        assert DurationFormatter._pluralize_minutes(5) == "5 хвилин"
        assert DurationFormatter._pluralize_minutes(11) == "11 хвилин"
        assert DurationFormatter._pluralize_minutes(21) == "21 хвилина"
