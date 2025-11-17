"""Group configuration model for Yasno power monitoring"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class GroupConfig:
    """Configuration for a Yasno power group to monitor

    Attributes:
        id: Unique identifier for this configuration (used in filenames)
        group: Yasno power group identifier (e.g., "2.1", "3.1")
        city: City name for the power grid (e.g., "kiev", "lviv", "odessa")
        channel: Optional Telegram channel username for public channels (e.g., "@power_po2")
        chat_id: Optional Telegram chat ID for private channels (e.g., -3492454736)
    """
    id: str
    group: str
    city: str
    channel: Optional[str] = None
    chat_id: Optional[int] = None

    def __post_init__(self):
        """Validate configuration after initialization"""
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.group:
            raise ValueError("group cannot be empty")
        if not self.city:
            raise ValueError("city cannot be empty")

        # Validate id contains only safe characters for filenames
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', self.id):
            raise ValueError(f"id must contain only alphanumeric characters, underscores, and hyphens (got: {self.id})")

    @property
    def file_suffix(self) -> str:
        """Get file suffix for this group (replaces dots and spaces with underscores)

        Returns:
            Safe filename suffix (e.g., "home", "kyiv_2_1")
        """
        return self.id.replace('.', '_').replace(' ', '_')

    @property
    def target_channel(self) -> Optional[str | int]:
        """Get the target channel/chat for notifications

        Returns:
            chat_id if set (for private channels), otherwise channel (for public channels)
        """
        return self.chat_id if self.chat_id is not None else self.channel

    def __str__(self) -> str:
        """String representation for logging"""
        if self.chat_id is not None:
            channel_info = f", chat_id: {self.chat_id}"
        elif self.channel:
            channel_info = f", channel: {self.channel}"
        else:
            channel_info = ""
        return f"GroupConfig(id={self.id}, group={self.group}, city={self.city}{channel_info})"
