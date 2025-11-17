"""
Script to delete all Yasno power outage channels.

This script deletes all channels tagged with 'light-prod' from Telegram and removes them
from the local database.

WARNING: This action is permanent and cannot be undone!
"""


async def run(manager, args):
    """
    Delete all light-prod channels.

    Args:
        manager: TelegramChannelManager instance
        args: Command-line arguments (unused)
    """
    print("=" * 60)
    print("DELETE ALL YASNO CHANNELS")
    print("=" * 60)
    print("⚠️  WARNING: This will permanently delete all channels!")
    print("⚠️  All messages, subscribers, and data will be lost!")
    print("=" * 60)
    print()

    # Get all light-prod channels
    channels = await manager.list_channels(tags=["light-prod"])

    if not channels:
        print("✓ No channels found with tag 'light-prod'")
        return

    print(f"Found {len(channels)} channels to delete:\n")
    for i, channel in enumerate(channels, 1):
        username_str = f"@{channel['username']}" if channel.get('username') else "(no username)"
        print(f"{i}. {channel['title']} - {username_str}")
    print()

    # Confirmation prompt
    confirm = input("Type 'DELETE ALL' to confirm deletion: ")
    if confirm != "DELETE ALL":
        print("\n✗ Cancelled. No channels were deleted.")
        return

    print("\nProceeding with deletion...\n")

    deleted = []
    failed = []

    for channel in channels:
        channel_id = channel["id"]
        title = channel.get("title", "Unknown")
        username = channel.get("username", "")

        username_str = f"@{username}" if username else f"ID: {channel_id}"
        print(f"Deleting: {title} ({username_str})")

        try:
            # Delete from Telegram
            entity = await manager.client.get_entity(int(channel_id))

            from telethon import functions
            await manager.client(
                functions.channels.DeleteChannelRequest(channel=entity)
            )
            print(f"  ✓ Deleted from Telegram")

            # Remove from local database
            for i, ch in enumerate(manager.channels):
                if ch["id"] == channel_id:
                    manager.channels.pop(i)
                    break

            print(f"  ✓ Removed from local database")

            deleted.append({
                "title": title,
                "username": username,
                "id": channel_id
            })

        except Exception as e:
            print(f"  ✗ Failed: {e}")
            failed.append({
                "title": title,
                "username": username,
                "id": channel_id,
                "error": str(e)
            })

        print()

    # Save updated state
    if deleted:
        manager._save_state()
        print("Local database updated.")
        print()

    # Print summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total channels: {len(channels)}")
    print(f"Successfully deleted: {len(deleted)}")
    print(f"Failed: {len(failed)}")
    print()

    if deleted:
        print("Deleted channels:")
        for ch in deleted:
            username_str = f"@{ch['username']}" if ch['username'] else f"ID: {ch['id']}"
            print(f"  - {ch['title']} ({username_str})")
        print()

    if failed:
        print("Failed to delete:")
        for ch in failed:
            username_str = f"@{ch['username']}" if ch['username'] else f"ID: {ch['id']}"
            print(f"  - {ch['title']} ({username_str}): {ch['error']}")
        print()

    if deleted:
        print("⚠️  Deleted channels cannot be recovered!")
