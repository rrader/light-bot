from dataclasses import dataclass
from typing import Optional


@dataclass
class LocationConfig:
    """Configuration for a monitored power location."""
    id: str
    name: str
    status_file: str
    channel_id: Optional[str] = None
    yasno_group: Optional[str] = None
    ha_webhook_url: Optional[str] = None

    def __post_init__(self):
        if not self.id:
            raise ValueError("Location id cannot be empty")
        self.id = self.id.strip().lower()
        if not self.name:
            self.name = self.id.capitalize()
