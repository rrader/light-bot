"""
Script to add a bot to all Yasno channels and make it admin.

This script adds @power_po2_bot to all channels tagged with 'light-prod' and grants admin rights.
"""

from telethon import functions
from telethon.tl.types import ChatAdminRights

# Bot username to add
BOT_USERNAME = "power_po2_bot"


async def run(manager, args):
    """
    Add bot to all light-prod channels and make it admin.

    Args:
        manager: TelegramChannelManager instance
        args: Command-line arguments (unused)
    """
    print(f"Adding @{BOT_USERNAME} to all light-prod channels...\n")

    # Get all light-prod channels
    channels = await manager.list_channels(tags=["light-prod"])

    if not channels:
        print("✗ No channels found with tag 'light-prod'")
        return

    print(f"Found {len(channels)} channels\n")

    # Get the bot entity
    try:
        bot = await manager.client.get_entity(BOT_USERNAME)
        print(f"✓ Found bot: @{BOT_USERNAME} (ID: {bot.id})\n")
    except Exception as e:
        print(f"✗ Failed to find bot @{BOT_USERNAME}: {e}")
        return

    added = []
    failed = []

    for channel in channels:
        channel_id = channel["id"]
        title = channel.get("title", "Unknown")

        print(f"Processing: {title}")

        try:
            # Get the channel entity
            entity = await manager.client.get_entity(int(channel_id))

            # Define admin rights
            admin_rights = ChatAdminRights(
                post_messages=True,      # Can post messages
                edit_messages=True,      # Can edit messages
                delete_messages=True,    # Can delete messages
                invite_users=False,      # Cannot invite users
                pin_messages=True,       # Can pin messages
                manage_call=False,       # Cannot manage calls
                ban_users=False,         # Cannot ban users
                add_admins=False,        # Cannot add other admins
                anonymous=False,         # Not anonymous
                change_info=False,       # Cannot change channel info
            )

            # Add bot directly as admin (bots can only be admins in channels)
            await manager.client(
                functions.channels.EditAdminRequest(
                    channel=entity,
                    user_id=bot,
                    admin_rights=admin_rights,
                    rank="Bot"
                )
            )
            print(f"  ✓ Bot added as admin")

            added.append({
                "title": title,
                "id": channel_id
            })

        except Exception as e:
            print(f"  ✗ Failed: {e}")
            failed.append({
                "title": title,
                "id": channel_id,
                "error": str(e)
            })

        print()

    # Print summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total channels: {len(channels)}")
    print(f"Successfully configured: {len(added)}")
    print(f"Failed: {len(failed)}")
    print()

    if added:
        print(f"Channels with @{BOT_USERNAME} as admin:")
        for ch in added:
            print(f"  - {ch['title']}")
        print()

    if failed:
        print("Failed channels:")
        for ch in failed:
            print(f"  - {ch['title']}: {ch['error']}")
        print()

    print(f"@{BOT_USERNAME} has been configured with the following permissions:")
    print("  ✓ Post messages")
    print("  ✓ Edit messages")
    print("  ✓ Delete messages")
    print("  ✓ Pin messages")
