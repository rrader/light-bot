"""Telegram Channel Manager - Core functionality for managing Telegram channels using Telethon."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from telethon import TelegramClient, functions, types
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
)


class TelegramChannelManager:
    """Manages Telegram channels using Telethon and persists state to JSON file."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        state_file: str = "channels.json",
        session_name: str = "telegram_session",
    ):
        """
        Initialize the channel manager.

        Args:
            api_id: Telegram API ID from https://my.telegram.org/apps
            api_hash: Telegram API hash from https://my.telegram.org/apps
            phone: Phone number associated with Telegram account
            state_file: Path to JSON file for storing channel state
            session_name: Name for the Telethon session file
        """
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.phone = phone
        self.state_file = Path(state_file)
        self.channels: List[Dict] = []
        self._load_state()

    def _load_state(self) -> None:
        """Load channel state from JSON file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.channels = data.get("channels", [])
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load state file: {e}")
                self.channels = []
        else:
            self.channels = []

    def _save_state(self) -> None:
        """Save channel state to JSON file."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "channels": self.channels,
                        "last_updated": datetime.now().isoformat(),
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except IOError as e:
            print(f"Error: Could not save state file: {e}")
            raise

    async def connect(self) -> None:
        """Connect to Telegram and authenticate if necessary."""
        await self.client.connect()

        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.phone)
            print(
                f"A code has been sent to {self.phone}. Please check your Telegram app."
            )
            code = input("Enter the code you received: ")

            try:
                await self.client.sign_in(self.phone, code)
            except Exception:
                # If 2FA is enabled, request password
                password = input("Two-factor authentication enabled. Enter your password: ")
                await self.client.sign_in(password=password)

        print("Successfully authenticated!")

    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        await self.client.disconnect()

    async def create_channel(
        self, title: str, description: str = "", megagroup: bool = False, tags: List[str] = None
    ) -> Dict:
        """
        Create a new Telegram channel.

        Args:
            title: Channel title
            description: Channel description (optional)
            megagroup: If True, creates a supergroup instead of a broadcast channel
            tags: List of tags to categorize the channel (optional)

        Returns:
            Dict with channel information

        Raises:
            Exception: If channel creation fails
        """
        try:
            result = await self.client(
                functions.channels.CreateChannelRequest(
                    title=title, about=description, megagroup=megagroup
                )
            )

            # Extract channel information
            channel = result.chats[0]
            channel_data = {
                "id": str(channel.id),
                "access_hash": str(channel.access_hash),
                "title": channel.title,
                "username": getattr(channel, "username", None) or "",
                "type": "megagroup" if megagroup else "channel",
                "description": description,
                "created_at": datetime.now().isoformat(),
                "friendly_name": title,
                "tags": tags or [],
            }

            # Add to managed channels
            self.channels.append(channel_data)
            self._save_state()

            return {
                "success": True,
                "channel": channel_data,
                "message": f"Successfully created channel: {title}",
            }

        except Exception as e:
            return {"success": False, "message": f"Failed to create channel: {e}"}

    async def get_channel_info(self, identifier: str) -> Optional[Dict]:
        """
        Get information about a channel.

        Args:
            identifier: Channel ID, username, or friendly name

        Returns:
            Dict with channel information or None if not found
        """
        # Try to find in local state first
        local_channel = None
        for channel in self.channels:
            if (
                channel["id"] == identifier
                or channel.get("username", "").lower() == identifier.lstrip("@").lower()
                or channel.get("friendly_name", "") == identifier
            ):
                local_channel = channel
                break

        # Try to get fresh info from Telegram
        try:
            if local_channel:
                # Use stored access_hash for better reliability
                entity = await self.client.get_entity(int(local_channel["id"]))
            else:
                entity = await self.client.get_entity(identifier)

            # Get full channel info
            full_channel = await self.client(
                functions.channels.GetFullChannelRequest(channel=entity)
            )

            participants_count = full_channel.full_chat.participants_count

            info = {
                "id": str(entity.id),
                "access_hash": str(entity.access_hash),
                "title": entity.title,
                "username": getattr(entity, "username", None) or "",
                "about": full_channel.full_chat.about or "",
                "participants_count": participants_count,
                "type": "megagroup" if entity.megagroup else "channel",
                "created_at": local_channel.get("created_at", "") if local_channel else "",
                "friendly_name": local_channel.get("friendly_name", "")
                if local_channel
                else "",
                "managed": local_channel is not None,
            }

            return info

        except (ChannelInvalidError, ChannelPrivateError, ValueError) as e:
            # If we can't fetch from Telegram, return local data if available
            if local_channel:
                return local_channel
            print(f"Error fetching channel info: {e}")
            return None

    async def list_channels(self, tags: List[str] = None) -> List[Dict]:
        """
        List all managed channels, optionally filtered by tags.

        Args:
            tags: Filter channels by tags (returns channels with ANY of these tags)

        Returns:
            List of channel information dictionaries
        """
        if not tags:
            return self.channels

        # Return channels that have at least one of the specified tags
        return [
            channel for channel in self.channels
            if any(tag in channel.get("tags", []) for tag in tags)
        ]

    async def remove_channel(self, identifier: str) -> Dict:
        """
        Remove a channel from managed channels (doesn't delete the actual channel).

        Args:
            identifier: Channel ID, username, or friendly name

        Returns:
            Dict with operation result
        """
        for i, channel in enumerate(self.channels):
            if (
                channel["id"] == identifier
                or channel.get("username", "").lower() == identifier.lstrip("@").lower()
                or channel.get("friendly_name", "") == identifier
            ):
                removed = self.channels.pop(i)
                self._save_state()
                return {"success": True, "message": f"Removed channel: {removed['title']}"}

        return {"success": False, "message": f"Channel not found: {identifier}"}

    async def update_channel_name(self, identifier: str, new_name: str) -> Dict:
        """
        Update the friendly name of a managed channel.

        Args:
            identifier: Channel ID, username, or current friendly name
            new_name: New friendly name

        Returns:
            Dict with operation result
        """
        for channel in self.channels:
            if (
                channel["id"] == identifier
                or channel.get("username", "").lower() == identifier.lstrip("@").lower()
                or channel.get("friendly_name", "") == identifier
            ):
                old_name = channel.get("friendly_name", "")
                channel["friendly_name"] = new_name
                self._save_state()
                return {
                    "success": True,
                    "message": f"Updated channel name from '{old_name}' to '{new_name}'",
                }

        return {"success": False, "message": f"Channel not found: {identifier}"}

    async def set_channel_username(self, identifier: str, username: str) -> Dict:
        """
        Set or update the username (public link) for a channel.

        Args:
            identifier: Channel ID or friendly name
            username: New username (without @)

        Returns:
            Dict with operation result
        """
        try:
            # Find the channel
            channel_info = None
            for channel in self.channels:
                if (
                    channel["id"] == identifier
                    or channel.get("friendly_name", "") == identifier
                ):
                    channel_info = channel
                    break

            if not channel_info:
                return {"success": False, "message": f"Channel not found: {identifier}"}

            # Get the entity
            entity = await self.client.get_entity(int(channel_info["id"]))

            # Update username
            username = username.lstrip("@")
            await self.client(
                functions.channels.UpdateUsernameRequest(channel=entity, username=username)
            )

            # Update local state
            channel_info["username"] = username
            self._save_state()

            return {
                "success": True,
                "message": f"Successfully set username to @{username}",
            }

        except ChatAdminRequiredError:
            return {
                "success": False,
                "message": "You must be an admin to change the channel username",
            }
        except Exception as e:
            return {"success": False, "message": f"Failed to set username: {e}"}

    async def delete_channel(self, identifier: str) -> Dict:
        """
        Delete a channel permanently from Telegram.

        Args:
            identifier: Channel ID, username, or friendly name

        Returns:
            Dict with operation result
        """
        try:
            # Find the channel
            channel_info = None
            channel_index = None
            for i, channel in enumerate(self.channels):
                if (
                    channel["id"] == identifier
                    or channel.get("username", "").lower()
                    == identifier.lstrip("@").lower()
                    or channel.get("friendly_name", "") == identifier
                ):
                    channel_info = channel
                    channel_index = i
                    break

            if not channel_info:
                # Try to get from Telegram directly
                entity = await self.client.get_entity(identifier)
            else:
                entity = await self.client.get_entity(int(channel_info["id"]))

            # Delete the channel
            await self.client(functions.channels.DeleteChannelRequest(channel=entity))

            # Remove from managed channels if it was there
            if channel_index is not None:
                removed = self.channels.pop(channel_index)
                self._save_state()
                return {
                    "success": True,
                    "message": f"Successfully deleted channel: {removed['title']}",
                }

            return {"success": True, "message": "Successfully deleted channel"}

        except ChatAdminRequiredError:
            return {
                "success": False,
                "message": "You must be the channel creator to delete it",
            }
        except Exception as e:
            return {"success": False, "message": f"Failed to delete channel: {e}"}

    async def add_tags(self, identifier: str, tags: List[str]) -> Dict:
        """
        Add tags to a channel.

        Args:
            identifier: Channel ID, username, or friendly name
            tags: List of tags to add

        Returns:
            Dict with operation result
        """
        for channel in self.channels:
            if (
                channel["id"] == identifier
                or channel.get("username", "").lower() == identifier.lstrip("@").lower()
                or channel.get("friendly_name", "") == identifier
            ):
                existing_tags = set(channel.get("tags", []))
                existing_tags.update(tags)
                channel["tags"] = list(existing_tags)
                self._save_state()
                return {
                    "success": True,
                    "message": f"Added tags to channel: {', '.join(tags)}",
                    "tags": channel["tags"]
                }

        return {"success": False, "message": f"Channel not found: {identifier}"}

    async def remove_tags(self, identifier: str, tags: List[str]) -> Dict:
        """
        Remove tags from a channel.

        Args:
            identifier: Channel ID, username, or friendly name
            tags: List of tags to remove

        Returns:
            Dict with operation result
        """
        for channel in self.channels:
            if (
                channel["id"] == identifier
                or channel.get("username", "").lower() == identifier.lstrip("@").lower()
                or channel.get("friendly_name", "") == identifier
            ):
                existing_tags = set(channel.get("tags", []))
                existing_tags.difference_update(tags)
                channel["tags"] = list(existing_tags)
                self._save_state()
                return {
                    "success": True,
                    "message": f"Removed tags from channel: {', '.join(tags)}",
                    "tags": channel["tags"]
                }

        return {"success": False, "message": f"Channel not found: {identifier}"}
