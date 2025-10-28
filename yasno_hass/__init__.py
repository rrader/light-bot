"""Yasno Power Outage API Client"""
import logging
import pytz
from datetime import datetime, timedelta

from .api import YasnoAPIClient, client
from .models import (
    YasnoAPIComponent,
    YasnoAPIResponse,
    YasnoDailySchedule,
    YasnoDailyScheduleEntity,
    YasnoAPIOutage,
    YasnoOutageType,
    YasnoOutage,
    DailyGroupSchedule,
    SensorEntityData,
)

_LOGGER = logging.getLogger(__name__)

# Kyiv timezone for all datetime operations
KYIV_TZ = pytz.timezone('Europe/Kyiv')

__all__ = [
    "YasnoAPIClient",
    "client",
    "YasnoAPIComponent",
    "YasnoAPIResponse",
    "YasnoDailySchedule",
    "YasnoDailyScheduleEntity",
    "YasnoAPIOutage",
    "YasnoOutageType",
    "YasnoOutage",
    "DailyGroupSchedule",
    "SensorEntityData",
    "merge_intervals",
    "to_datetime",
    "to_outage",
]


def to_datetime(val: float) -> datetime:
    """Convert float time (e.g., 12.5 = 12:30) to datetime in Kyiv timezone"""
    time_parts = [int(i) for i in str(val).split(".")]
    assert len(time_parts) == 2, "Incorrect time input."

    # Get current date in Kyiv timezone
    now_kyiv = datetime.now(KYIV_TZ)

    if time_parts[0] == 24:
        return now_kyiv.replace(
            hour=23, minute=59, second=59, microsecond=0
        )

    return now_kyiv.replace(
        hour=time_parts[0], minute=30 if time_parts[1] else 0, second=0, microsecond=0
    )


def to_outage(
    start: float, end: float, today: bool, outage_type: YasnoOutageType
) -> YasnoOutage:
    """Convert float time ranges to YasnoOutage with datetime objects"""
    start_dt = to_datetime(start)
    end_dt = to_datetime(end)
    if not today:
        start_dt += timedelta(days=1)
        end_dt += timedelta(days=1)
    return YasnoOutage(
        start=start_dt,
        end=end_dt,
        type=outage_type,
    )


def merge_intervals(
    group_schedule: list[YasnoAPIOutage], today: bool
) -> list[YasnoOutage]:
    """
    Merge sequential intervals into one.
    Combines adjacent time slots for the same outage type.
    """
    merged_schedules = []
    start, end, last_type = None, None, None

    for item in group_schedule:
        if item.start == end:  # next item to be merged
            end = item.end
            last_type = item.type
        else:
            if start is not None and end is not None:
                merged_schedules.append(
                    to_outage(start=start, end=end, today=today, outage_type=last_type)
                )
            start, end, last_type = item.start, item.end, item.type

    # Add the last interval
    if start is not None and end is not None:
        merged_schedules.append(
            to_outage(start=start, end=end, today=today, outage_type=last_type)
        )

    return merged_schedules
