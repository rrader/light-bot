from dataclasses import dataclass
from datetime import datetime

@dataclass
class ScheduleHistory:
    """Represents a schedule history entry"""
    id: int
    group_id: str
    schedule_text: str
    timestamp: datetime
