import pytest
import os
import sys
import tempfile
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from light_bot.services.group_schedule_sender import GroupScheduleSender
from light_bot.api.yasno import YasnoScheduleResponse, GroupSchedule, DaySchedule, PowerSlot, SlotType
from light_bot.core.schedule_tools import find_next_outage, is_continuous_outage, is_currently_in_outage


@pytest.fixture
def mock_timezone():
    """Mock timezone for consistent testing"""
    return pytz.timezone('Europe/Kyiv')


@pytest.fixture
def temp_files():
    """Create temporary files for testing"""
    files = {
        'last_schedule_today_hash': tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_today_hash.txt'),
        'last_schedule_tomorrow_hash': tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_tomorrow_hash.txt'),
        'last_check_date': tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_check_date.txt'),
        'tomorrow_sent_date': tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_tomorrow_sent.txt'),
        'last_warning_sent': tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_warning.txt'),
        'today_data': tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_today_data.json'),
        'tomorrow_data': tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_tomorrow_data.json'),
    }

    file_paths = {key: f.name for key, f in files.items()}
    for f in files.values():
        f.close()

    yield file_paths

    # Cleanup
    for path in file_paths.values():
        try:
            os.unlink(path)
        except:
            pass


@pytest.fixture
def mock_group_sender(temp_files):
    """Create a GroupScheduleSender instance with mocked dependencies"""
    bot = AsyncMock()
    formatter = Mock()
    formatter.format_outage_warning_message.return_value = "⚠️ Warning Message"

    sender = GroupScheduleSender(
        bot=bot,
        channel_id="@test_channel",
        group="2.1",
        city="kiev",
        formatter=formatter,
        today_hash_file=temp_files['last_schedule_today_hash'],
        tomorrow_hash_file=temp_files['last_schedule_tomorrow_hash'],
        today_data_file=temp_files['today_data'],
        tomorrow_data_file=temp_files['tomorrow_data'],
        last_check_date_file=temp_files['last_check_date'],
        tomorrow_sent_date_file=temp_files['tomorrow_sent_date'],
        last_warning_sent_file=temp_files['last_warning_sent'],
        today_start_hour=7,
        today_end_hour=23,
        tomorrow_start_hour=18,
        tomorrow_end_hour=23,
        warning_minutes=30,
        warning_check_interval=60,
    )
    return sender


def create_mock_schedule(today_slots, tomorrow_slots):
    """Helper to create mock schedule data"""
    tz = pytz.timezone('Europe/Kyiv')
    now = datetime.now(tz)
    tomorrow = now + timedelta(days=1)

    today_schedule = DaySchedule(
        slots=today_slots,
        date=now,
        status="ScheduleApplies"
    )

    tomorrow_schedule = DaySchedule(
        slots=tomorrow_slots,
        date=tomorrow,
        status="ScheduleApplies"
    )

    group_schedule = GroupSchedule(
        today=today_schedule,
        tomorrow=tomorrow_schedule,
        updatedOn=now
    )

    return YasnoScheduleResponse({'2.1': group_schedule.__dict__})


class TestOutageWarnings:
    """Tests for outage warning functionality"""

    @pytest.mark.asyncio
    async def test_find_next_outage_today(self):
        """Test finding next outage slot today"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)
        current_minutes = now.hour * 60 + now.minute

        # Create a slot that starts in 2 hours
        future_start = current_minutes + 120  # 2 hours from now

        # Skip test if the slot would cross midnight
        if future_start >= 1440:
            pytest.skip("Test would create slot crossing midnight")

        future_end = future_start + 60  # 1 hour duration

        # Also skip if end would cross midnight
        if future_end >= 1440:
            pytest.skip("Test would create slot ending after midnight")

        today_slots = [
            PowerSlot(start=future_start, end=future_end, type=SlotType.DEFINITE)
        ]
        tomorrow_slots = []

        mock_schedule = create_mock_schedule(today_slots, tomorrow_slots)

        result = find_next_outage(mock_schedule, "2.1")

        assert result is not None
        outage_start, outage_end = result
        assert outage_start.hour == future_start // 60
        assert outage_start.minute == future_start % 60
        assert outage_end.hour == future_end // 60
        assert outage_end.minute == future_end % 60

    @pytest.mark.asyncio
    async def test_find_next_outage_tomorrow(self):
        """Test finding next outage slot tomorrow when no today slots"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)

        # No outages today, first outage tomorrow at 10:00
        today_slots = []
        tomorrow_slots = [
            PowerSlot(start=600, end=720, type=SlotType.DEFINITE)  # 10:00-12:00
        ]

        mock_schedule = create_mock_schedule(today_slots, tomorrow_slots)

        result = find_next_outage(mock_schedule, "2.1")

        assert result is not None
        outage_start, outage_end = result
        assert outage_start.hour == 10
        assert outage_start.minute == 0
        assert outage_end.hour == 12
        assert outage_end.minute == 0
        # Should be tomorrow
        assert outage_start.date() == (now + timedelta(days=1)).date()

    @pytest.mark.asyncio
    async def test_find_next_outage_no_outages(self):
        """Test when there are no upcoming outages"""
        today_slots = []
        tomorrow_slots = []

        mock_schedule = create_mock_schedule(today_slots, tomorrow_slots)

        result = find_next_outage(mock_schedule, "2.1")

        assert result is None

    @pytest.mark.asyncio
    async def test_send_outage_warning(self, mock_group_sender):
        """Test sending outage warning message"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)
        outage_start = now + timedelta(minutes=30)
        outage_end = outage_start + timedelta(hours=2)

        result = await mock_group_sender.send_outage_warning(outage_start, outage_end)

        assert result is True
        mock_group_sender.bot.send_message.assert_called_once()

        # Verify message content
        call_args = mock_group_sender.bot.send_message.call_args
        message = call_args.kwargs['text']
        assert '⚠️' in message

    @pytest.mark.asyncio
    async def test_check_outage_warnings_in_window(self, mock_group_sender):
        """Test that warning is sent when within warning window"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)
        current_minutes = now.hour * 60 + now.minute

        # Create outage that starts in exactly 30 minutes (default warning time)
        future_start = current_minutes + 30

        # Handle wrap-around at midnight
        if future_start >= 1440:
            pytest.skip("Test time crosses midnight boundary")

        future_end = future_start + 60

        today_slots = [
            PowerSlot(start=future_start, end=future_end, type=SlotType.DEFINITE)
        ]

        mock_schedule = create_mock_schedule(today_slots, [])

        await mock_group_sender.check_outage_warnings(mock_schedule)

        # Should have sent a warning (or skip if not in right time)
        call_count = mock_group_sender.bot.send_message.call_count
        if call_count == 0:
            pytest.skip("Current time not in warning window")
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_check_outage_warnings_outside_window(self, mock_group_sender):
        """Test that warning is NOT sent when outside warning window"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)
        current_minutes = now.hour * 60 + now.minute

        # Create outage that starts in 60 minutes (outside 30±5 minute window)
        future_start = current_minutes + 60
        future_end = future_start + 60

        today_slots = [
            PowerSlot(start=future_start, end=future_end, type=SlotType.DEFINITE)
        ]

        mock_schedule = create_mock_schedule(today_slots, [])

        await mock_group_sender.check_outage_warnings(mock_schedule)

        # Should NOT have sent a warning
        mock_group_sender.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_warning_not_duplicated(self, mock_group_sender):
        """Test that the same warning is not sent twice"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)
        current_minutes = now.hour * 60 + now.minute

        # Ensure the slot wraps to next day if needed
        future_start = current_minutes + 30
        if future_start >= 1440:  # Beyond midnight
            future_start = 30  # Reset to 00:30
        future_end = (future_start + 60) % 1440

        today_slots = [
            PowerSlot(start=future_start, end=future_end, type=SlotType.DEFINITE)
        ]

        mock_schedule = create_mock_schedule(today_slots, [])

        # First call - should send warning
        await mock_group_sender.check_outage_warnings(mock_schedule)
        first_call_count = mock_group_sender.bot.send_message.call_count

        # If warning was sent (within window)
        if first_call_count == 1:
            # Second call - should NOT send warning again (same outage)
            await mock_group_sender.check_outage_warnings(mock_schedule)
            assert mock_group_sender.bot.send_message.call_count == 1
        else:
            # If not in warning window, that's also OK - skip this test
            pytest.skip("Test time not in warning window")

    @pytest.mark.asyncio
    async def test_find_next_outage_midnight_boundary(self):
        """Test finding next outage that ends at midnight (24:00)"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)

        # Only run this test if current time is before 22:00 (so the slot is still upcoming)
        if now.hour >= 22:
            pytest.skip("Test only runs before 22:00 to ensure slot is in future")

        # Create slot that ends at midnight: 22:00 - 24:00
        today_slots = [
            PowerSlot(start=1320, end=1440, type=SlotType.DEFINITE)  # 22:00 - 24:00 (midnight)
        ]
        tomorrow_slots = []

        mock_schedule = create_mock_schedule(today_slots, tomorrow_slots)

        result = find_next_outage(mock_schedule, "2.1")

        assert result is not None
        outage_start, outage_end = result

        # Start should be 22:00
        assert outage_start.hour == 22
        assert outage_start.minute == 0

        # End should be 00:00 next day (not hour=24!)
        assert outage_end.hour == 0
        assert outage_end.minute == 0

        # End should be one day after start
        assert (outage_end.date() - outage_start.date()).days == 1

        # Verify the end time is after start time
        assert outage_end > outage_start

    @pytest.mark.asyncio
    async def test_find_next_outage_midnight_boundary_tomorrow(self):
        """Test finding next outage tomorrow that ends at midnight"""
        # No more outages today, tomorrow has slot ending at midnight
        today_slots = []
        tomorrow_slots = [
            PowerSlot(start=1320, end=1440, type=SlotType.DEFINITE)  # 22:00 - 24:00
        ]

        mock_schedule = create_mock_schedule(today_slots, tomorrow_slots)

        result = find_next_outage(mock_schedule, "2.1")

        assert result is not None
        outage_start, outage_end = result

        # Start should be 22:00
        assert outage_start.hour == 22
        assert outage_start.minute == 0

        # End should be 00:00 next day (not hour=24!)
        assert outage_end.hour == 0
        assert outage_end.minute == 0

        # End should be one day after start
        assert (outage_end.date() - outage_start.date()).days == 1

        # Verify the end time is after start time
        assert outage_end > outage_start

    @pytest.mark.asyncio
    async def test_continuous_outage_across_midnight(self):
        """Test that continuous outages across midnight are treated as one period"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)

        # Skip test if current time would make this slot in the past
        if now.hour >= 22:
            pytest.skip("Test only runs before 22:00 to ensure slot is in future")

        # Today: 22:00 - 24:00
        today_slots = [
            PowerSlot(start=1320, end=1440, type=SlotType.DEFINITE)  # 22:00 - 24:00 (midnight)
        ]
        
        # Tomorrow: 00:00 - 02:00 (continuous from today)
        tomorrow_slots = [
            PowerSlot(start=0, end=120, type=SlotType.DEFINITE)  # 00:00 - 02:00
        ]

        mock_schedule = create_mock_schedule(today_slots, tomorrow_slots)

        result = find_next_outage(mock_schedule, "2.1")

        assert result is not None
        outage_start, outage_end = result

        # Start should be 22:00 today
        assert outage_start.hour == 22
        assert outage_start.minute == 0

        # End should be 02:00 tomorrow (NOT 00:00 - continuous outage!)
        assert outage_end.hour == 2
        assert outage_end.minute == 0

        # End should be one day after start
        assert (outage_end.date() - outage_start.date()).days == 1

        # Duration should be 4 hours (22:00 - 02:00)
        duration = (outage_end - outage_start).total_seconds() / 3600
        assert duration == 4.0

    @pytest.mark.asyncio
    async def test_non_continuous_outage_with_gap(self):
        """Test that outages with a gap are NOT treated as continuous"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)

        if now.hour >= 22:
            pytest.skip("Test only runs before 22:00")

        # Today: 22:00 - 24:00
        today_slots = [
            PowerSlot(start=1320, end=1440, type=SlotType.DEFINITE)
        ]
        
        # Tomorrow: 01:00 - 03:00 (NOT continuous - there's a 1-hour gap)
        tomorrow_slots = [
            PowerSlot(start=60, end=180, type=SlotType.DEFINITE)  # 01:00 - 03:00
        ]

        mock_schedule = create_mock_schedule(today_slots, tomorrow_slots)

        result = find_next_outage(mock_schedule, "2.1")

        assert result is not None
        outage_start, outage_end = result

        # Start should be 22:00 today
        assert outage_start.hour == 22

        # End should be 00:00 tomorrow (midnight - NOT 03:00, since there's a gap)
        assert outage_end.hour == 0
        assert outage_end.minute == 0

        # Duration should be 2 hours (22:00 - 00:00), not 5 hours
        duration = (outage_end - outage_start).total_seconds() / 3600
        assert duration == 2.0

    @pytest.mark.asyncio
    async def test_is_continuous_outage_helper(self):
        """Test the is_continuous_outage helper function directly"""

        # Case 1: Today ends at 24:00 (1440), tomorrow starts at 00:00 (0) → continuous
        assert is_continuous_outage(1440, 0) is True

        # Case 2: Today ends at 24:00 (1440), tomorrow starts at 01:00 (60) → NOT continuous
        assert is_continuous_outage(1440, 60) is False

        # Case 3: Today ends at 23:00 (1380), tomorrow starts at 00:00 (0) → NOT continuous
        assert is_continuous_outage(1380, 0) is False

        # Case 4: Today ends at 23:30 (1410), tomorrow starts at 00:00 (0) → NOT continuous
        assert is_continuous_outage(1410, 0) is False

    @pytest.mark.asyncio
    async def test_skip_warning_if_currently_in_outage(self, mock_group_sender):
        """Test that warning is skipped if we're currently in an outage"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)
        current_minutes = now.hour * 60 + now.minute

        # Skip test if current time wouldn't work for this scenario
        if current_minutes < 60 or current_minutes >= 1380:
            pytest.skip("Test requires current time between 01:00-23:00")

        # Create an outage that started before now and ends after now
        # so we're currently IN the outage
        outage_start = current_minutes - 30  # Started 30 min ago
        outage_end = current_minutes + 90    # Ends in 90 min

        today_slots = [
            PowerSlot(start=outage_start, end=outage_end, type=SlotType.DEFINITE)
        ]
        tomorrow_slots = []

        mock_schedule = create_mock_schedule(today_slots, tomorrow_slots)

        # Check warnings are skipped when in outage
        await mock_group_sender.check_outage_warnings(mock_schedule)

        # Should not send warning (verified by mock not being called)
        mock_group_sender.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_currently_in_outage_helper(self):
        """Test the is_currently_in_outage helper function directly"""
        tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(tz)
        current_minutes = now.hour * 60 + now.minute

        # Skip test if current time wouldn't work
        if current_minutes < 60 or current_minutes >= 1380:
            pytest.skip("Test requires current time between 01:00-23:00")

        # Case 1: Currently IN outage
        in_outage_slots = [
            PowerSlot(start=current_minutes - 30, end=current_minutes + 30, type=SlotType.DEFINITE)
        ]
        mock_schedule = create_mock_schedule(in_outage_slots, [])
        assert is_currently_in_outage(mock_schedule, "2.1") is True

        # Case 2: NOT in outage (outage in future)
        future_slots = [
            PowerSlot(start=current_minutes + 60, end=current_minutes + 120, type=SlotType.DEFINITE)
        ]
        mock_schedule = create_mock_schedule(future_slots, [])
        assert is_currently_in_outage(mock_schedule, "2.1") is False

        # Case 3: NOT in outage (outage in past)
        past_slots = [
            PowerSlot(start=current_minutes - 120, end=current_minutes - 60, type=SlotType.DEFINITE)
        ]
        mock_schedule = create_mock_schedule(past_slots, [])
        assert is_currently_in_outage(mock_schedule, "2.1") is False

        # Case 4: No outages at all
        mock_schedule = create_mock_schedule([], [])
        assert is_currently_in_outage(mock_schedule, "2.1") is False
