"""Tests for schedule change detection and notification filtering"""
import asyncio
import pytest
import os
import sys
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock
import pytz
from light_bot.api.yasno.models import PowerSlot, SlotType, DaySchedule, GroupSchedule, YasnoScheduleResponse, ScheduleStatus
from light_bot.formatters.schedule_formatter import ScheduleFormatter
from light_bot.models.group_config import GroupConfig
from light_bot.services.group_schedule_sender import GroupScheduleSender

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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is False, "Changes in past slots should not be meaningful"

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_schedule_cache_during_coalescing(self, schedule_service):
        cached_schedule = object()
        latest_schedule = Mock()
        latest_schedule.get_group.return_value.model_dump.return_value = {}
        schedule_service._cached_schedule = cached_schedule
        schedule_service._cache_timestamp = datetime.now(TIMEZONE)

        with patch.object(schedule_service.composite_client, "update", return_value=latest_schedule) as update:
            result = await schedule_service._get_cached_schedule(force_refresh=True)

        assert result is latest_schedule
        update.assert_called_once_with()

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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is False, "Removing past slot should not be meaningful"

    def test_status_change_always_meaningful(self, schedule_service):
        """Emergency shutdown status changes are meaningful regardless of time"""
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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

        assert result is True, "Emergency shutdown status change should be meaningful"

    def test_non_emergency_status_change_without_future_slot_change_is_ignored(self, schedule_service):
        old_schedule = {"status": "ScheduleApplies", "slots": []}
        new_schedule = {"status": "NoOutages", "slots": []}

        assert schedule_service.group_sender._has_meaningful_changes(
            old_schedule, new_schedule, 720
        ) is False

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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

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

        result = schedule_service.group_sender._has_meaningful_changes(schedule, schedule, current_minutes)

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

        result = schedule_service.group_sender._has_meaningful_changes(old_schedule, new_schedule, current_minutes)

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
        should_notify = schedule_service.group_sender._has_meaningful_changes(
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
        should_notify = schedule_service.group_sender._has_meaningful_changes(
            old_schedule_dict,
            new_schedule_dict,
            current_minutes
        )

        # SHOULD notify because changes affect future slot
        assert should_notify is True, "Should notify for future changes"


def _schedule(slots, status=ScheduleStatus.SCHEDULE_APPLIES):
    today = DaySchedule(
        slots=[PowerSlot(**slot) for slot in slots],
        date=datetime(2026, 11, 5, tzinfo=pytz.UTC),
        status=status,
    )
    tomorrow = DaySchedule(
        slots=[],
        date=datetime(2026, 11, 6, tzinfo=pytz.UTC),
        status=ScheduleStatus.WAITING_FOR_SCHEDULE,
    )
    return YasnoScheduleResponse({
        "53.1": GroupSchedule(today=today, tomorrow=tomorrow, updatedOn=datetime.now(pytz.UTC))
    })


def _schedule_sender(tmp_path, monkeypatch, debounce_seconds=480):
    frozen_now = TIMEZONE.localize(datetime(2026, 11, 5, 12, 0))

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_now.astimezone(tz) if tz else frozen_now.replace(tzinfo=None)

    monkeypatch.setattr("light_bot.services.group_schedule_sender.datetime", FrozenDateTime)
    sender = GroupScheduleSender(
        bot=Mock(),
        channel_id="@test_channel",
        group_config=GroupConfig(id="home", group="53.1", city="kiev"),
        formatter=ScheduleFormatter(),
        today_hash_file=str(tmp_path / "today.hash"),
        today_data_file=str(tmp_path / "today.json"),
        tomorrow_hash_file=str(tmp_path / "tomorrow.hash"),
        tomorrow_data_file=str(tmp_path / "tomorrow.json"),
        today_start_hour=0,
        today_end_hour=23,
        schedule_change_debounce_seconds=debounce_seconds,
    )
    sender.send_schedule = AsyncMock(return_value=True)
    return sender


def _set_baseline(sender, schedule_data):
    schedule_hash = sender._compute_schedule_hash(schedule_data)
    schedule_dict = sender._serialize_day_schedule(schedule_data)
    sender._store_today_snapshot(schedule_dict, schedule_hash)


@pytest.mark.asyncio
async def test_past_only_schedule_change_updates_baseline_without_post(tmp_path, monkeypatch):
    sender = _schedule_sender(tmp_path, monkeypatch)
    baseline = _schedule([
        {"start": 480, "end": 600, "type": SlotType.DEFINITE},
        {"start": 840, "end": 960, "type": SlotType.DEFINITE},
    ])
    changed = _schedule([
        {"start": 480, "end": 660, "type": SlotType.DEFINITE},
        {"start": 840, "end": 960, "type": SlotType.DEFINITE},
    ])
    _set_baseline(sender, baseline)

    await sender.check_today_schedule(changed)

    sender.send_schedule.assert_not_awaited()
    assert sender.last_today_hash == sender._compute_schedule_hash(changed)
    assert sender._read_schedule_data_file(sender.today_data_file) == sender._serialize_day_schedule(changed)


@pytest.mark.asyncio
async def test_close_meaningful_changes_are_coalesced_into_latest_schedule(tmp_path, monkeypatch):
    sender = _schedule_sender(tmp_path, monkeypatch, debounce_seconds=0.01)
    baseline = _schedule([{"start": 840, "end": 960, "type": SlotType.DEFINITE}])
    first_change = _schedule([{"start": 840, "end": 1020, "type": SlotType.DEFINITE}])
    latest_change = _schedule([{"start": 840, "end": 1080, "type": SlotType.DEFINITE}])
    _set_baseline(sender, baseline)

    await sender.check_today_schedule(first_change)
    await sender.check_today_schedule(latest_change)
    sender.send_schedule.assert_not_awaited()
    assert sender.has_pending_schedule_notification
    assert sender.last_today_hash == sender._compute_schedule_hash(baseline)

    await asyncio.sleep(0.03)

    sender.send_schedule.assert_awaited_once()
    assert sender.send_schedule.await_args.args[0] is latest_change
    assert sender.last_today_hash == sender._compute_schedule_hash(latest_change)
    assert not sender.has_pending_schedule_notification


@pytest.mark.asyncio
async def test_unsent_schedule_change_is_rediscovered_after_restart(tmp_path, monkeypatch):
    first_sender = _schedule_sender(tmp_path, monkeypatch, debounce_seconds=0.01)
    baseline = _schedule([{"start": 840, "end": 960, "type": SlotType.DEFINITE}])
    changed = _schedule([{"start": 840, "end": 1020, "type": SlotType.DEFINITE}])
    _set_baseline(first_sender, baseline)

    await first_sender.check_today_schedule(changed)
    assert first_sender.has_pending_schedule_notification
    first_sender._cancel_pending_today_notification()  # Simulate process termination.

    restarted_sender = _schedule_sender(tmp_path, monkeypatch, debounce_seconds=0.01)
    assert restarted_sender.last_today_hash == first_sender._compute_schedule_hash(baseline)
    await restarted_sender.check_today_schedule(changed)
    await asyncio.sleep(0.03)

    restarted_sender.send_schedule.assert_awaited_once()
    assert restarted_sender.send_schedule.await_args.args[0] is changed
    assert restarted_sender.last_today_hash == restarted_sender._compute_schedule_hash(changed)


@pytest.mark.asyncio
async def test_schedule_reverting_to_baseline_cancels_pending_post(tmp_path, monkeypatch):
    sender = _schedule_sender(tmp_path, monkeypatch, debounce_seconds=0.01)
    baseline = _schedule([{"start": 840, "end": 960, "type": SlotType.DEFINITE}])
    changed = _schedule([{"start": 840, "end": 1020, "type": SlotType.DEFINITE}])
    _set_baseline(sender, baseline)

    await sender.check_today_schedule(changed)
    assert sender.has_pending_schedule_notification
    await sender.check_today_schedule(baseline)

    assert not sender.has_pending_schedule_notification
    sender.send_schedule.assert_not_awaited()
    await asyncio.sleep(0.03)
    sender.send_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_coalesced_post_is_retried_on_next_schedule_check(tmp_path, monkeypatch):
    sender = _schedule_sender(tmp_path, monkeypatch, debounce_seconds=0.01)
    baseline = _schedule([{"start": 840, "end": 960, "type": SlotType.DEFINITE}])
    changed = _schedule([{"start": 840, "end": 1020, "type": SlotType.DEFINITE}])
    sender.send_schedule = AsyncMock(side_effect=[False, True])
    _set_baseline(sender, baseline)

    await sender.check_today_schedule(changed)
    await asyncio.sleep(0.03)
    assert sender.has_pending_schedule_notification
    assert sender.last_today_hash == sender._compute_schedule_hash(baseline)

    await sender.check_today_schedule(changed)
    await asyncio.sleep(0.03)

    assert sender.send_schedule.await_count == 2
    assert not sender.has_pending_schedule_notification
    assert sender.last_today_hash == sender._compute_schedule_hash(changed)


@pytest.mark.asyncio
async def test_emergency_status_change_is_sent_immediately(tmp_path, monkeypatch):
    sender = _schedule_sender(tmp_path, monkeypatch, debounce_seconds=30)
    baseline = _schedule([{"start": 840, "end": 960, "type": SlotType.DEFINITE}])
    emergency = _schedule(
        [{"start": 840, "end": 960, "type": SlotType.DEFINITE}],
        status=ScheduleStatus.EMERGENCY_SHUTDOWNS,
    )
    _set_baseline(sender, baseline)

    await sender.check_today_schedule(emergency)

    sender.send_schedule.assert_awaited_once_with(
        emergency,
        for_tomorrow=False,
        change_detected=True,
        change_explanation=None,
    )
    assert not sender.has_pending_schedule_notification


@pytest.mark.asyncio
async def test_emergency_status_flushes_pending_update_immediately(tmp_path, monkeypatch):
    sender = _schedule_sender(tmp_path, monkeypatch, debounce_seconds=30)
    baseline = _schedule([{"start": 840, "end": 960, "type": SlotType.DEFINITE}])
    ordinary_update = _schedule([{"start": 840, "end": 1020, "type": SlotType.DEFINITE}])
    emergency = _schedule(
        [{"start": 840, "end": 1020, "type": SlotType.DEFINITE}],
        status=ScheduleStatus.EMERGENCY_SHUTDOWNS,
    )
    _set_baseline(sender, baseline)

    await sender.check_today_schedule(ordinary_update)
    assert sender.has_pending_schedule_notification
    await sender.check_today_schedule(emergency)

    assert not sender.has_pending_schedule_notification
    sender.send_schedule.assert_awaited_once_with(
        emergency,
        for_tomorrow=False,
        change_detected=True,
        change_explanation=None,
    )
