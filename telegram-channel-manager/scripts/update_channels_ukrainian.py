"""
Script to update Telegram channels with Ukrainian names and descriptions.

This script updates all existing light-prod channels with Ukrainian titles and descriptions.
"""

from telethon import functions

YASNO_GROUPS = [
    {"id": "home", "group": "2.1", "city": "kyiv"},
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


def generate_ukrainian_title(group_info):
    """Generate Ukrainian channel title."""
    city = "Київ"
    group = group_info["group"]
    return f"Відключення світла {city} - Група {group}"


def generate_ukrainian_description(group_info):
    """Generate Ukrainian channel description."""
    city = "Київ"
    group = group_info["group"]
    return (
        f"Автоматизовані графіки та сповіщення про відключення електроенергії для {city}, Група {group}. "
        f"Отримуйте щоденні графіки, оновлення в режимі реального часу та попередження про заплановані відключення."
    )


def get_username_for_group(group):
    """Generate expected username for a group."""
    return f"power_kyiv_group_{group.replace('.', '_')}"


async def run(manager, args):
    """
    Update all light-prod channels with Ukrainian names and descriptions.

    Args:
        manager: TelegramChannelManager instance
        args: Command-line arguments (unused)
    """
    print("Updating channels with Ukrainian names and descriptions...\n")

    # Get all light-prod channels
    channels = await manager.list_channels(tags=["light-prod"])

    if not channels:
        print("✗ No channels found with tag 'light-prod'")
        return

    print(f"Found {len(channels)} channels to update\n")

    updated = []
    failed = []

    for channel in channels:
        channel_id = channel["id"]
        current_title = channel.get("title", "")
        username = channel.get("username", "")

        # Find matching group by username
        group_info = None
        for group in YASNO_GROUPS:
            expected_username = get_username_for_group(group["group"])
            if username == expected_username:
                group_info = group
                break

        if not group_info:
            print(f"⚠ Skipping {current_title} - couldn't match to a group")
            continue

        new_title = generate_ukrainian_title(group_info)
        new_description = generate_ukrainian_description(group_info)

        print(f"Updating: {current_title} (@{username})")
        print(f"  New title: {new_title}")

        try:
            # Get the channel entity
            entity = await manager.client.get_entity(int(channel_id))

            # Update channel title
            await manager.client(
                functions.channels.EditTitleRequest(
                    channel=entity,
                    title=new_title
                )
            )
            print(f"  ✓ Title updated")

            # Update channel description (about)
            await manager.client(
                functions.channels.EditAboutRequest(
                    channel=entity,
                    about=new_description
                )
            )
            print(f"  ✓ Description updated")

            # Update in local state
            channel["title"] = new_title
            channel["description"] = new_description
            channel["friendly_name"] = new_title

            updated.append({
                "group": group_info["group"],
                "title": new_title,
                "username": username
            })

        except Exception as e:
            print(f"  ✗ Failed: {e}")
            failed.append({
                "title": current_title,
                "username": username,
                "error": str(e)
            })

        print()

    # Save updated state
    if updated:
        manager._save_state()

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total channels: {len(channels)}")
    print(f"Successfully updated: {len(updated)}")
    print(f"Failed: {len(failed)}")
    print()

    if updated:
        print("Updated channels:")
        for ch in updated:
            print(f"  - Група {ch['group']}: {ch['title']}")
        print()

    if failed:
        print("Failed channels:")
        for ch in failed:
            username_str = f"@{ch['username']}" if ch['username'] else "(no username)"
            print(f"  - {ch['title']} ({username_str}): {ch['error']}")
        print()

    print("All channels retain their 'light-prod' tag")
    print("Use 'python cli.py list --tags light-prod' to view them")
