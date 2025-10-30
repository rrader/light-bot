# Data models for Yasno Blackout API
from typing import List, Optional, Dict
from enum import Enum
from datetime import datetime
from pydantic import BaseModel
import logging

_LOGGER = logging.getLogger(__name__)


class SlotType(str, Enum):
    """Types of power slots"""
    DEFINITE = "Definite"  # Definite outage
    NOT_PLANNED = "NotPlanned"  # Power is on
    MAYBE = "Maybe"  # Possible outage


class ScheduleStatus(str, Enum):
    """Schedule status"""
    SCHEDULE_APPLIES = "ScheduleApplies"
    WAITING_FOR_SCHEDULE = "WaitingForSchedule"
    NO_OUTAGES = "NoOutages"
    EMERGENCY_SHUTDOWNS = "EmergencyShutdowns"


class PowerSlot(BaseModel):
    """A single power slot in minutes from midnight"""
    start: int  # Minutes from midnight (0-1440)
    end: int    # Minutes from midnight (0-1440)
    type: SlotType


class DaySchedule(BaseModel):
    """Schedule for a single day"""
    slots: List[PowerSlot]
    date: datetime
    status: ScheduleStatus


class GroupSchedule(BaseModel):
    """Schedule for a power group"""
    today: DaySchedule
    tomorrow: DaySchedule
    updatedOn: datetime


class YasnoScheduleResponse:
    """Full API response with all groups"""

    def __init__(self, data: Dict[str, dict]):
        """Initialize with raw dict data"""
        self._data = {}
        for group_key, group_data in data.items():
            self._data[group_key] = GroupSchedule(**group_data)

    def get_group(self, group: str) -> Optional[GroupSchedule]:
        """Get schedule for a specific group"""
        return self._data.get(group)

    def all_groups(self) -> List[str]:
        """Get list of all available group keys"""
        return list(self._data.keys())
