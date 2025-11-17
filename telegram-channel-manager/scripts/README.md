# Scripts Directory

This directory contains adhoc scripts for bulk operations on Telegram channels.

## Available Scripts

### create_yasno_channels

Creates private Telegram channels for all Yasno power outage groups in Kyiv with Ukrainian names.

**Usage:**
```bash
python cli.py script create_yasno_channels
```

**What it does:**
- Creates 13 private channels (one for each power group in Kyiv: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2)
- Uses Ukrainian titles: "Відключення світла Київ - Група X.X"
- Uses Ukrainian descriptions with schedule information
- Creates as private channels (no public username)
- Tags all channels with `light-prod`
- Skips channels that already exist

**Example output:**
```
Creating channels for 13 power groups...

Creating: Відключення світла Київ - Група 1.1 (Група 1.1)
  ✓ Created with ID: -1001234567890
  ℹ Private channel (no public username)

...

SUMMARY
============================================================
Total groups: 13
Successfully created: 13
Skipped (already exist): 0
Failed: 0

Created channels:
  - Група 1.1: Відключення світла Київ - Група 1.1 (ID: -1001234567890)
  ...

All channels are tagged with: light-prod
Use 'python cli.py list --tags light-prod' to view them
```

### update_channels_ukrainian

Updates all existing light-prod channels with Ukrainian titles and descriptions.

**Usage:**
```bash
python cli.py script update_channels_ukrainian
```

**What it does:**
- Finds all channels tagged with `light-prod`
- Matches each channel to its corresponding power group by username
- Updates channel title to Ukrainian (e.g., "Відключення світла Київ - Група 2.1")
- Updates channel description to Ukrainian
- Updates friendly name in the local database
- Preserves all other channel properties (username, tags, etc.)

**Example output:**
```
Updating channels with Ukrainian names and descriptions...

Found 9 channels to update

Updating: Power Outages Kyiv - Group 2.1 (@power_kyiv_group_2_1)
  New title: Відключення світла Київ - Група 2.1
  ✓ Title updated
  ✓ Description updated

...

SUMMARY
============================================================
Total channels: 9
Successfully updated: 9
Failed: 0

Updated channels:
  - Група 2.1: Відключення світла Київ - Група 2.1
  - Група 1.1: Відключення світла Київ - Група 1.1
  ...

All channels retain their 'light-prod' tag
Use 'python cli.py list --tags light-prod' to view them
```

### add_bot_to_channels

Adds @power_po2_bot to all light-prod channels and grants admin permissions.

**Usage:**
```bash
python cli.py script add_bot_to_channels
```

**What it does:**
- Finds all channels tagged with `light-prod`
- Adds @power_po2_bot to each channel
- Grants admin rights with specific permissions:
  - Post messages
  - Edit messages
  - Delete messages
  - Pin messages
- Skips channels where bot is already a member
- Handles errors gracefully

**Example output:**
```
Adding @power_po2_bot to all light-prod channels...

Found 13 channels

✓ Found bot: @power_po2_bot (ID: 123456789)

Processing: Відключення світла Київ - Група 1.1
  ✓ Bot added to channel
  ✓ Admin rights granted

Processing: Відключення світла Київ - Група 1.2
  ℹ Bot already in channel
  ✓ Admin rights granted

...

SUMMARY
============================================================
Total channels: 13
Successfully configured: 13
Failed: 0

Channels with @power_po2_bot as admin:
  - Відключення світла Київ - Група 1.1
  - Відключення світла Київ - Група 1.2
  ...

@power_po2_bot has been configured with the following permissions:
  ✓ Post messages
  ✓ Edit messages
  ✓ Delete messages
  ✓ Pin messages
```

**Bot Permissions:**
The bot is granted the following admin rights:
- **Post messages** - Can send messages to the channel
- **Edit messages** - Can edit its own messages
- **Delete messages** - Can delete messages in the channel
- **Pin messages** - Can pin/unpin messages

The bot does NOT have permissions to:
- Invite users
- Ban users
- Add other admins
- Change channel info
- Manage calls

### delete_all_yasno_channels

**⚠️ DESTRUCTIVE OPERATION - USE WITH CAUTION**

Deletes all channels tagged with 'light-prod' from Telegram and removes them from the local database.

**Usage:**
```bash
python cli.py script delete_all_yasno_channels
```

**What it does:**
- Finds all channels tagged with `light-prod`
- Lists all channels that will be deleted
- Requires explicit confirmation (must type "DELETE ALL")
- Permanently deletes each channel from Telegram
- Removes channels from local database
- Saves updated state

**Example output:**
```
============================================================
DELETE ALL YASNO CHANNELS
============================================================
⚠️  WARNING: This will permanently delete all channels!
⚠️  All messages, subscribers, and data will be lost!
============================================================

Found 9 channels to delete:

1. Відключення світла Київ - Група 2.1 - @power_kyiv_group_2_1
2. Відключення світла Київ - Група 1.1 - @power_kyiv_group_1_1
...

Type 'DELETE ALL' to confirm deletion: DELETE ALL

Proceeding with deletion...

Deleting: Відключення світла Київ - Група 2.1 (@power_kyiv_group_2_1)
  ✓ Deleted from Telegram
  ✓ Removed from local database

...

SUMMARY
============================================================
Total channels: 9
Successfully deleted: 9
Failed: 0

⚠️  Deleted channels cannot be recovered!
```

**Important Notes:**
- This action is **permanent** and **cannot be undone**
- All channel messages, subscribers, and history will be lost
- You must type exactly "DELETE ALL" to confirm
- Only channels tagged with `light-prod` are affected
- Use this script carefully, preferably for cleanup or testing

## Creating Your Own Scripts

Scripts should follow this structure:

```python
"""
Script description
"""

async def run(manager, args):
    """
    Main function called by the CLI.

    Args:
        manager: TelegramChannelManager instance
        args: List of command-line arguments passed to the script
    """
    # Your code here
    print("Script is running!")

    # Example: Create a channel
    result = await manager.create_channel(
        title="My Channel",
        description="Channel description",
        tags=["my-tag"]
    )

    if result["success"]:
        print(f"Created: {result['channel']['title']}")
```

**Running your script:**
```bash
python cli.py script my_script arg1 arg2
```

The script file should be named `my_script.py` and placed in this directory.

## Common Patterns

### Bulk Channel Creation

```python
async def run(manager, args):
    channels = [
        {"name": "Channel 1", "username": "channel1"},
        {"name": "Channel 2", "username": "channel2"},
    ]

    for ch in channels:
        result = await manager.create_channel(
            title=ch["name"],
            tags=["bulk-created"]
        )
        if result["success"]:
            await manager.set_channel_username(
                result["channel"]["id"],
                ch["username"]
            )
```

### Filtering by Tags

```python
async def run(manager, args):
    # Get all channels with a specific tag
    channels = await manager.list_channels(tags=["my-tag"])

    for channel in channels:
        print(f"{channel['title']}: @{channel.get('username', 'no-username')}")
```

### Batch Tag Operations

```python
async def run(manager, args):
    # Add tags to all existing channels
    channels = await manager.list_channels()

    for channel in channels:
        await manager.add_tags(channel["id"], ["archived"])
```

## Tips

- Always check if channels exist before creating them
- Use descriptive channel names and usernames
- Tag channels for easy organization
- Print progress and summary information
- Handle errors gracefully
