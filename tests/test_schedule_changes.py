"""Tests for schedule change detection and notification filtering"""
import pytest
import os
import sys
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from light_bot.services.schedule_service import ScheduleService


TIMEZONE = pytz.timezone('Europe/Kyiv')


class TestScheduleChangeFiltering:
    """Test that schedule changes in past slots don't trigger notifications"""

    @pytest.fixture
    def schedule_service(self):
        """Create a ScheduleService instance for testing"""
        with patch('telegram.Bot'):
            service = ScheduleService()
            return service

    def test_past_slot_change_not_meaningful(self, schedule_service):
        """Changes only in past slots should not be meaningful"""
        # Old schedule: 08:00-10:00 outage
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"}  # 08:00-10:00
            ]
        }

        # New schedule: 08:00-11:00 outage (extended past slot)
        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 660, "type": "Definite"}  # 08:00-11:00
            ]
        }

        # Current time: 12:00 (720 minutes) - both slots are in the past
        current_minutes = 720

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is False, "Changes in past slots should not be meaningful"

    def test_future_slot_change_is_meaningful(self, schedule_service):
        """Changes in future slots should be meaningful"""
        # Old schedule: 14:00-16:00 outage
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 960, "type": "Definite"}  # 14:00-16:00
            ]
        }

        # New schedule: 14:00-18:00 outage (extended future slot)
        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 1080, "type": "Definite"}  # 14:00-18:00
            ]
        }

        # Current time: 12:00 (720 minutes) - slot is in the future
        current_minutes = 720

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is True, "Changes in future slots should be meaningful"

    def test_current_slot_change_is_meaningful(self, schedule_service):
        """Changes in currently active slot should be meaningful"""
        # Old schedule: 14:00-16:00 outage
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 960, "type": "Definite"}  # 14:00-16:00
            ]
        }

        # New schedule: 14:00-18:00 outage (extended current slot)
        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 1080, "type": "Definite"}  # 14:00-18:00
            ]
        }

        # Current time: 15:00 (900 minutes) - we're in the middle of the slot
        current_minutes = 900

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is True, "Changes in current ongoing slot should be meaningful"

    def test_new_future_slot_added_is_meaningful(self, schedule_service):
        """Adding a new future slot should be meaningful"""
        # Old schedule: only morning outage
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"}  # 08:00-10:00
            ]
        }

        # New schedule: morning outage + afternoon outage
        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"},   # 08:00-10:00
                {"start": 840, "end": 960, "type": "Definite"}    # 14:00-16:00 (NEW)
            ]
        }

        # Current time: 12:00 (720 minutes)
        current_minutes = 720

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is True, "Adding new future slot should be meaningful"

    def test_future_slot_removed_is_meaningful(self, schedule_service):
        """Removing a future slot should be meaningful"""
        # Old schedule: morning + afternoon outages
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"},   # 08:00-10:00
                {"start": 840, "end": 960, "type": "Definite"}    # 14:00-16:00
            ]
        }

        # New schedule: only morning outage (future slot removed)
        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"}    # 08:00-10:00
            ]
        }

        # Current time: 12:00 (720 minutes)
        current_minutes = 720

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is True, "Removing future slot should be meaningful"

    def test_past_slot_removed_not_meaningful(self, schedule_service):
        """Removing a past slot should not be meaningful"""
        # Old schedule: morning + afternoon outages
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"},   # 08:00-10:00
                {"start": 840, "end": 960, "type": "Definite"}    # 14:00-16:00
            ]
        }

        # New schedule: only afternoon outage (past slot removed)
        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 960, "type": "Definite"}    # 14:00-16:00
            ]
        }

        # Current time: 12:00 (720 minutes)
        current_minutes = 720

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is False, "Removing past slot should not be meaningful"

    def test_status_change_always_meaningful(self, schedule_service):
        """Status changes should always be meaningful regardless of time"""
        # Old schedule: normal schedule
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"}    # 08:00-10:00
            ]
        }

        # New schedule: emergency shutdowns
        new_schedule = {
            "date": "2024-01-15",
            "status": "EmergencyShutdowns",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"}    # 08:00-10:00 (same)
            ]
        }

        # Current time: 12:00 (720 minutes) - slot is in the past
        current_minutes = 720

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is True, "Status change should always be meaningful"

    def test_mixed_changes_past_and_future(self, schedule_service):
        """If changes include both past and future slots, should be meaningful"""
        # Old schedule: two slots
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"},   # 08:00-10:00
                {"start": 840, "end": 960, "type": "Definite"}    # 14:00-16:00
            ]
        }

        # New schedule: both slots extended
        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 660, "type": "Definite"},   # 08:00-11:00 (extended past)
                {"start": 840, "end": 1080, "type": "Definite"}   # 14:00-18:00 (extended future)
            ]
        }

        # Current time: 12:00 (720 minutes)
        current_minutes = 720

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is True, "Changes including future slots should be meaningful"

    def test_slot_type_change_in_future_is_meaningful(self, schedule_service):
        """Changing slot type in future should be meaningful"""
        # Old schedule: definite outage
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 960, "type": "Definite"}    # 14:00-16:00 Definite
            ]
        }

        # New schedule: maybe outage
        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 960, "type": "Maybe"}       # 14:00-16:00 Maybe
            ]
        }

        # Current time: 12:00 (720 minutes)
        current_minutes = 720

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is True, "Type change in future slot should be meaningful"

    def test_no_changes_returns_false(self, schedule_service):
        """Identical schedules should return False"""
        schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"},
                {"start": 840, "end": 960, "type": "Definite"}
            ]
        }

        current_minutes = 720

        result = schedule_service._has_meaningful_changes(schedule, schedule, current_minutes)

        assert result is False, "Identical schedules should not be meaningful"

    def test_edge_case_slot_ending_now(self, schedule_service):
        """Slot ending exactly at current time should be considered past"""
        # Old schedule: slot ending now
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 720, "type": "Definite"}    # 08:00-12:00
            ]
        }

        # New schedule: extended to 13:00
        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 780, "type": "Definite"}    # 08:00-13:00
            ]
        }

        # Current time: 12:00 (720 minutes) - exactly at slot end
        current_minutes = 720

        result = schedule_service._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        # Slot end=720 is NOT > current_time=720, so old slot is past
        # But new slot end=780 IS > current_time=720, so new slot is future
        # Therefore there's a difference in future slots
        assert result is True, "New slot extending into future should be meaningful"

    def test_integration_past_changes_skip_notification(self, schedule_service):
        """Integration test: _has_meaningful_changes should return False for past-only changes

        This simulates what check_today_schedule does: it calls _has_meaningful_changes
        to decide whether to send a notification.
        """
        # Setup: mock schedule data
        old_schedule_dict = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"}    # 08:00-10:00
            ]
        }

        new_schedule_dict = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 660, "type": "Definite"}    # 08:00-11:00 (extended past)
            ]
        }

        # Current time: 12:00 (720 minutes) - both slots are in the past
        current_minutes = 720

        # This is what check_today_schedule would call
        should_notify = schedule_service._has_meaningful_changes(
            old_schedule_dict,
            new_schedule_dict,
            current_minutes
        )

        # Should NOT notify because changes are only in past
        assert should_notify is False, "Should not notify for past-only changes"

    def test_integration_future_changes_trigger_notification(self, schedule_service):
        """Integration test: _has_meaningful_changes should return True for future changes

        This simulates what check_today_schedule does: it calls _has_meaningful_changes
        to decide whether to send a notification.
        """
        # Setup: mock schedule data
        old_schedule_dict = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 960, "type": "Definite"}    # 14:00-16:00
            ]
        }

        new_schedule_dict = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 1080, "type": "Definite"}   # 14:00-18:00 (extended future)
            ]
        }

        # Current time: 12:00 (720 minutes) - slot is in the future
        current_minutes = 720

        # This is what check_today_schedule would call
        should_notify = schedule_service._has_meaningful_changes(
            old_schedule_dict,
            new_schedule_dict,
            current_minutes
        )

        # SHOULD notify because changes affect future slot
        assert should_notify is True, "Should notify for future changes"
