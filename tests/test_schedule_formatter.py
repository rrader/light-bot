from datetime import datetime, timezone
import pytest
from light_bot.api.yasno.models import PowerSlot, SlotType, DaySchedule, GroupSchedule, YasnoScheduleResponse, ScheduleStatus
from light_bot.formatters.schedule_formatter import ScheduleFormatter


class TestScheduleFormatterTotalDuration:
    """Tests for ScheduleFormatter total outage time calculation and formatting"""

    def test_format_total_outage_time(self):
        """Test formatting various minute amounts into Ukrainian text"""
        assert ScheduleFormatter.format_total_outage_time(60) == "1 година"
        assert ScheduleFormatter.format_total_outage_time(120) == "2 години"
        assert ScheduleFormatter.format_total_outage_time(300) == "5 годин"
        assert ScheduleFormatter.format_total_outage_time(690) == "11 годин 30 хвилин"
        assert ScheduleFormatter.format_total_outage_time(30) == "30 хвилин"
        assert ScheduleFormatter.format_total_outage_time(1440) == "24 години"
        assert ScheduleFormatter.format_total_outage_time(0) == "0 годин"

    def test_format_outage_slots_no_outages(self):
        """Test formatting when there are no outages"""
        slots = [PowerSlot(start=0, end=1440, type=SlotType.NOT_PLANNED)]
        result = ScheduleFormatter.format_outage_slots(slots)
        assert result == "✅ Відключень немає"
        assert "Всього без світла" not in result

    def test_format_outage_slots_with_outages(self):
        """Test formatting outage slots includes total outage duration"""
        # 00:00 - 03:30 (210m), 08:00 - 12:30 (270m), 18:00 - 21:30 (210m) -> 690m = 11h 30m
        slots = [
            PowerSlot(start=0, end=210, type=SlotType.DEFINITE),
            PowerSlot(start=210, end=480, type=SlotType.NOT_PLANNED),
            PowerSlot(start=480, end=750, type=SlotType.DEFINITE),
            PowerSlot(start=750, end=1080, type=SlotType.NOT_PLANNED),
            PowerSlot(start=1080, end=1290, type=SlotType.DEFINITE),
            PowerSlot(start=1290, end=1440, type=SlotType.NOT_PLANNED),
        ]
        result = ScheduleFormatter.format_outage_slots(slots)
        assert "⚡️ 00:00 - 03:30" in result
        assert "⚡️ 08:00 - 12:30" in result
        assert "⚡️ 18:00 - 21:30" in result
        assert "⌛️ Всього без світла: <b>11 годин 30 хвилин</b>" in result

    def test_format_schedule_message_includes_total(self):
        """Test format_schedule_message displays total outage hours"""
        slots = [
            PowerSlot(start=480, end=720, type=SlotType.DEFINITE),  # 08:00 - 12:00 (4h)
            PowerSlot(start=720, end=1440, type=SlotType.NOT_PLANNED),
        ]
        today = DaySchedule(slots=slots, date=datetime(2026, 10, 8, tzinfo=timezone.utc), status=ScheduleStatus.SCHEDULE_APPLIES)
        tomorrow = DaySchedule(slots=[], date=datetime(2026, 10, 9, tzinfo=timezone.utc), status=ScheduleStatus.WAITING_FOR_SCHEDULE)
        group_sched = GroupSchedule(today=today, tomorrow=tomorrow, updatedOn=datetime.now(timezone.utc))
        
        response = YasnoScheduleResponse({"2.1": group_sched})
        msg = ScheduleFormatter.format_schedule_message(response, "2.1", city="vinnytsia")
        
        assert "Планові відключення:" in msg
        assert "⚡️ 08:00 - 12:00" in msg
        assert "⌛️ Всього без світла: <b>4 години</b>" in msg
