from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class PowerEvent:
    """Represents a power status change event"""
    id: int
    timestamp: datetime
    status: str
    location: str = "home"
    voltage: Optional[float] = None
    source: Optional[str] = None
    before_relay: Optional[bool] = None
    after_relay: Optional[bool] = None
