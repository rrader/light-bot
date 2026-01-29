"""Group configuration model for Yasno power monitoring"""
from dataclasses import dataclass
from typing import Optional
import requests
import logging

logger = logging.getLogger(__name__)


@dataclass
class GroupConfig:
    """Configuration for a Yasno power group to monitor

    Attributes:
        id: Unique identifier for this configuration (used in filenames)
        group: Yasno power group identifier (e.g., "2.1", "3.1") - optional if group_dynamic is set
        city: City name for the power grid (e.g., "kiev", "lviv", "odessa")
        channel: Optional Telegram channel username for public channels (e.g., "@power_po2")
        chat_id: Optional Telegram chat ID for private channels (e.g., -3492454736)
        group_dynamic: Optional URL to fetch group ID dynamically (e.g., "https://app.yasno.ua/api/...")
    """
    id: str
    city: str
    channel: Optional[str] = None
    chat_id: Optional[int] = None
    group: Optional[str] = None
    group_dynamic: Optional[str] = None

    def __post_init__(self):
        """Validate configuration after initialization"""
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.city:
            raise ValueError("city cannot be empty")
        
        # Validate that either group or group_dynamic is specified (but not both)
        if self.group and self.group_dynamic:
            raise ValueError(f"Cannot specify both 'group' and 'group_dynamic' for config '{self.id}'")
        if not self.group and not self.group_dynamic:
            raise ValueError(f"Must specify either 'group' or 'group_dynamic' for config '{self.id}'")

        # Validate id contains only safe characters for filenames
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', self.id):
            raise ValueError(f"id must contain only alphanumeric characters, underscores, and hyphens (got: {self.id})")

    def resolve_group(self) -> tuple[str, bool]:
        """Resolve and return the group ID, fetching from URL if needed
        
        Returns:
            Tuple of (group_id, changed) where changed is True if group was updated
            
        Raises:
            ValueError: If group_dynamic URL fetch fails or returns invalid data
        """
        # If group is already set (static configuration), return it
        if self.group and not self.group_dynamic:
            return (self.group, False)
        
        # Fetch dynamic group from URL
        if not self.group_dynamic:
            raise ValueError(f"No group or group_dynamic specified for config '{self.id}'")
        
        try:
            logger.info(f"[{self.id}] Fetching dynamic group from: {self.group_dynamic}")
            response = requests.get(self.group_dynamic, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Validate response format
            if not isinstance(data, dict):
                raise ValueError(f"Expected JSON object, got {type(data)}")
            
            if 'group' not in data or 'subgroup' not in data:
                raise ValueError(f"Response missing 'group' or 'subgroup' fields: {data}")
            
            # Convert to group string format (e.g., {"group":5,"subgroup":1} -> "5.1")
            group_str = f"{data['group']}.{data['subgroup']}"
            logger.info(f"[{self.id}] Resolved dynamic group: {group_str}")
            
            # Check if group changed
            changed = (self.group != group_str)
            
            # Store the resolved group for future use
            self.group = group_str
            return (group_str, changed)
            
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Failed to fetch dynamic group for '{self.id}' from {self.group_dynamic}: {e}")
        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"Invalid response format from {self.group_dynamic}: {e}")

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
