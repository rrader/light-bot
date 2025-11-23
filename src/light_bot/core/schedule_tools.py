import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, List

from light_bot.api.yasno import YasnoScheduleResponse, PowerSlot, SlotType
from light_bot.api.yasno.models import ScheduleStatus
from light_bot.config import TIMEZONE

logger = logging.getLogger(__name__)

# Time constants for midnight boundary handling
MINUTES_PER_DAY = 1440
HOURS_PER_DAY = 24


def get_outage_slots(slots: List[PowerSlot]) -> List[PowerSlot]:
    """Filter slots to get only Definite outages"""
    return [slot for slot in slots if slot.type == SlotType.DEFINITE]


def create_outage_datetime(base_date: datetime, minutes: int) -> datetime:
    """Create datetime from minutes since midnight, handling midnight boundary

    Args:
        base_date: The reference date to create time from
        minutes: Minutes since midnight (can be >= MINUTES_PER_DAY for next day)

    Returns:
        datetime with proper date adjustment for midnight boundary
    """
    hour = minutes // 60
    minute = minutes % 60

    if hour >= HOURS_PER_DAY:
        # Midnight boundary: move to next day
        return base_date.replace(hour=0, minute=minute, second=0, microsecond=0) + timedelta(days=1)
    else:
        return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)


def is_continuous_outage(today_end_minutes: int, tomorrow_start_minutes: int) -> bool:
    """Check if today's outage ending at midnight continues into tomorrow's outage

    Args:
        today_end_minutes: End time of today's slot in minutes (e.g., 1440 for 24:00)
        tomorrow_start_minutes: Start time of tomorrow's slot in minutes (e.g., 0 for 00:00)

    Returns:
        True if outages are continuous across midnight (no gap between them)
    """
    return today_end_minutes >= MINUTES_PER_DAY and tomorrow_start_minutes == 0


def find_next_outage(schedule_data: YasnoScheduleResponse, group: str) -> Optional[Tuple[datetime, datetime]]:
    """Find the next scheduled outage (start time, end time)

    Handles midnight boundary cases and continuous outages across midnight.

    Args:
        schedule_data: Schedule data from Yasno API
        group: Power group (e.g., "2.1")

    Returns:
        Tuple of (outage_start_datetime, outage_end_datetime) or None if no upcoming outage
    """
    try:
        if not schedule_data:
            return None

        now = datetime.now(TIMEZONE)
        current_minutes = now.hour * 60 + now.minute

        group_schedule = schedule_data.get_group(group)
        if not group_schedule:
            logger.warning(f"Group {group} not found in schedule")
            return None

        # Check today's schedule first
        today_schedule = group_schedule.today
        outage_slots = get_outage_slots(today_schedule.slots)

        for slot in outage_slots:
            if slot.start > current_minutes:
                # Found upcoming outage today
                start_time = create_outage_datetime(now, slot.start)

                # Check if this outage continues into tomorrow
                tomorrow_schedule = group_schedule.tomorrow
                if tomorrow_schedule.status == ScheduleStatus.WAITING_FOR_SCHEDULE:
                    end_time = create_outage_datetime(now, slot.end)
                    return (start_time, end_time)

                tomorrow_outage_slots = get_outage_slots(tomorrow_schedule.slots)

                if (tomorrow_outage_slots and
                    is_continuous_outage(slot.end, tomorrow_outage_slots[0].start)):
                    # Continuous outage: use tomorrow's end time
                    tomorrow = now + timedelta(days=1)
                    end_time = create_outage_datetime(tomorrow, tomorrow_outage_slots[0].end)
                    logger.info(f"[{group}] Detected continuous outage across midnight: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}")
                else:
                    # Regular outage: use today's end time
                    end_time = create_outage_datetime(now, slot.end)

                return (start_time, end_time)

        # Check tomorrow's schedule if no outage found today
        tomorrow_schedule = group_schedule.tomorrow
        if tomorrow_schedule.status != ScheduleStatus.WAITING_FOR_SCHEDULE:
            tomorrow_outage_slots = get_outage_slots(tomorrow_schedule.slots)

            if tomorrow_outage_slots:
                slot = tomorrow_outage_slots[0]
                tomorrow = now + timedelta(days=1)
                start_time = create_outage_datetime(tomorrow, slot.start)
                end_time = create_outage_datetime(tomorrow, slot.end)
                return (start_time, end_time)

        return None

    except Exception as e:
        logger.error(f"Error finding next outage: {e}")
        return None


def is_currently_in_outage(schedule_data: YasnoScheduleResponse, group: str) -> bool:
    """Check if the group is currently in the middle of an outage

    Args:
        schedule_data: Schedule data from Yasno API
        group: Power group (e.g., "2.1")

    Returns:
        True if current time falls within an active outage slot
    """
    try:
        now = datetime.now(TIMEZONE)
        current_minutes = now.hour * 60 + now.minute

        group_schedule = schedule_data.get_group(group)
        if not group_schedule:
            return False

        # Check today's schedule for current outage
        today_schedule = group_schedule.today
        outage_slots = get_outage_slots(today_schedule.slots)

        for slot in outage_slots:
            if slot.start <= current_minutes < slot.end:
                return True

        return False

    except Exception as e:
        logger.error(f"Error checking if currently in outage: {e}")
        return False
