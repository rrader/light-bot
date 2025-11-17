"""
Script to create Telegram channels for Yasno power outage groups.

This script creates a channel for each power group in Kyiv, tagged with 'light-prod'.
Each channel will be used to send power outage schedules and updates for that specific group.
"""

YASNO_GROUPS = [
    {"id": "group_1_1", "group": "1.1", "city": "kyiv"},
    {"id": "group_1_2", "group": "1.2", "city": "kyiv"},
    {"id": "group_2_1", "group": "2.1", "city": "kyiv"},
    {"id": "group_2_2", "group": "2.2", "city": "kyiv"},
    {"id": "group_3_1", "group": "3.1", "city": "kyiv"},
    {"id": "group_3_2", "group": "3.2", "city": "kyiv"},
    {"id": "group_4_1", "group": "4.1", "city": "kyiv"},
    {"id": "group_4_2", "group": "4.2", "city": "kyiv"},
    {"id": "group_5_1", "group": "5.1", "city": "kyiv"},
    {"id": "group_5_2", "group": "5.2", "city": "kyiv"},
    {"id": "group_6_1", "group": "6.1", "city": "kyiv"},
    {"id": "group_6_2", "group": "6.2", "city": "kyiv"},
]


def generate_channel_name(group_info):
    """Generate a Ukrainian channel name for a power group."""
    city = "Київ"
    group = group_info["group"]
    return f"Відключення світла {city} - Група {group}"


def generate_description(group_info):
    """Generate a Ukrainian channel description for a power group."""
    city = "Київ"
    group = group_info["group"]
    return (
        f"Графіки та сповіщення про відключення електроенергії в Києві, Група {group}. "
        f"Отримуйте щоденні графіки, оновлення в режимі реального часу та попередження про заплановані відключення."
    )


async def run(manager, args):
    """
    Create channels for all Yasno power groups.

    Args:
        manager: TelegramChannelManager instance
        args: Command-line arguments (unused)
    """
    print(f"Creating channels for {len(YASNO_GROUPS)} power groups...\n")

    created = []
    failed = []
    skipped = []

    for group_info in YASNO_GROUPS:
        channel_name = generate_channel_name(group_info)
        description = generate_description(group_info)

        print(f"Creating: {channel_name} (Група {group_info['group']})")

        # Check if channel already exists
        existing_channels = await manager.list_channels(tags=["light-prod"])
        if any(
            ch.get("friendly_name") == channel_name or ch.get("title") == channel_name
            for ch in existing_channels
        ):
            print(f"  ⚠ Channel already exists, skipping")
            skipped.append(channel_name)
            continue

        # Create the channel (private, no username)
        result = await manager.create_channel(
            title=channel_name,
            description=description,
            megagroup=False,  # Broadcast channel
            tags=["light-prod"],
        )

        if result["success"]:
            channel_id = result["channel"]["id"]
            print(f"  ✓ Created with ID: {channel_id}")
            print(f"  ℹ Private channel (no public username)")
            created.append(
                {
                    "name": channel_name,
                    "username": None,
                    "id": channel_id,
                    "group": group_info["group"],
                }
            )
        else:
            print(f"  ✗ Failed: {result['message']}")
            failed.append({"name": channel_name, "error": result["message"]})

        print()

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total groups: {len(YASNO_GROUPS)}")
    print(f"Successfully created: {len(created)}")
    print(f"Skipped (already exist): {len(skipped)}")
    print(f"Failed: {len(failed)}")
    print()

    if created:
        print("Created channels:")
        for ch in created:
            print(f"  - Група {ch['group']}: {ch['name']} (ID: {ch['id']})")
        print()

    if failed:
        print("Failed channels:")
        for ch in failed:
            print(f"  - {ch['name']}: {ch['error']}")
        print()

    if skipped:
        print("Skipped channels:")
        for name in skipped:
            print(f"  - {name}")
        print()

    print("All channels are tagged with: light-prod")
    print("Use 'python cli.py list --tags light-prod' to view them")
