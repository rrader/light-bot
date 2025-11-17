"""
Script to generate .env configuration for all Yasno channels.

This script reads all light-prod channels and generates environment variable
configuration that can be added to the production .env file.
"""

YASNO_GROUPS = [
    {"id": "group_1_1", "group": "1.1"},
    {"id": "group_1_2", "group": "1.2"},
    {"id": "group_2_1", "group": "2.1"},
    {"id": "group_2_2", "group": "2.2"},
    {"id": "group_3_1", "group": "3.1"},
    {"id": "group_3_2", "group": "3.2"},
    {"id": "group_4_1", "group": "4.1"},
    {"id": "group_4_2", "group": "4.2"},
    {"id": "group_5_1", "group": "5.1"},
    {"id": "group_5_2", "group": "5.2"},
    {"id": "group_6_1", "group": "6.1"},
    {"id": "group_6_2", "group": "6.2"},
]


def get_channel_for_group(channels, group):
    """Find the channel matching a specific group."""
    expected_title = f"Відключення світла Київ - Група {group}"

    for channel in channels:
        if channel.get("title") == expected_title:
            return channel

    return None


async def run(manager, args):
    """
    Generate .env configuration for all Yasno channels.

    Args:
        manager: TelegramChannelManager instance
        args: Command-line arguments (unused)
    """
    print("Generating .env configuration for Yasno channels...\n")

    # Get all light-prod channels
    channels = await manager.list_channels(tags=["light-prod"])

    if not channels:
        print("✗ No channels found with tag 'light-prod'")
        return

    print(f"Found {len(channels)} channels\n")
    print("=" * 70)
    print("ENVIRONMENT VARIABLES FOR PRODUCTION .env")
    print("=" * 70)
    print()

    # Generate env vars for each group
    found = []
    missing = []

    for group_info in YASNO_GROUPS:
        group = group_info["group"]
        var_name = f"TELEGRAM_CHANNEL_GROUP_{group.replace('.', '_')}"

        channel = get_channel_for_group(channels, group)

        if channel:
            # Channel ID needs to be negative for private channels
            channel_id = channel["id"]
            print(f"{var_name}=-{channel_id}")
            found.append({
                "group": group,
                "id": channel_id,
                "title": channel["title"]
            })
        else:
            print(f"# {var_name}=  # NOT FOUND")
            missing.append(group)

    print()
    print("=" * 70)
    print()

    # Print summary
    print("SUMMARY")
    print("-" * 70)
    print(f"Total groups: {len(YASNO_GROUPS)}")
    print(f"Channels found: {len(found)}")
    print(f"Channels missing: {len(missing)}")
    print()

    if missing:
        print("⚠️  Missing channels for groups:")
        for group in missing:
            print(f"  - Group {group}")
        print()

    if found:
        print("✓ Configuration generated for groups:")
        for ch in found:
            print(f"  - Group {ch['group']}: {ch['title']} (ID: -{ch['id']})")
        print()

    print("=" * 70)
    print("USAGE INSTRUCTIONS")
    print("=" * 70)
    print()
    print("1. Copy the environment variables above")
    print("2. Add them to your production .env file in the light-bot directory")
    print("3. The bot will use these channel IDs to send notifications to each group")
    print()
    print("Example .env structure:")
    print("  TELEGRAM_BOT_TOKEN=your_bot_token")
    print("  TELEGRAM_CHANNEL_GROUP_1_1=-1001234567890")
    print("  TELEGRAM_CHANNEL_GROUP_1_2=-1001234567891")
    print("  ...")
    print()
    print("Note: Channel IDs are negative for private channels")
