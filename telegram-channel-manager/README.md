# Telegram Channel Manager

A command-line tool for creating and managing Telegram channels programmatically. This tool uses the Telegram Client API (via Telethon) to provide full control over your channels.

## Features

- **Create channels**: Programmatically create new broadcast channels or supergroups
- **Get channel info**: Retrieve detailed information about any channel
- **List channels**: View all your managed channels
- **Set usernames**: Configure public usernames (@channelname) for your channels
- **Rename channels**: Set friendly names for easier management
- **Delete channels**: Permanently remove channels from Telegram
- **JSON state storage**: All channel data persists in a local JSON file

## Prerequisites

- Python 3.11+
- A Telegram account (with phone number)
- Telegram API credentials (API ID and API Hash)

## Getting API Credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application (if you haven't already)
4. Copy your **API ID** and **API Hash**

## Installation

1. Navigate to the telegram-channel-manager directory:
```bash
cd telegram-channel-manager
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file from the example:
```bash
cp .env.example .env
```

4. Edit `.env` and add your credentials:
```bash
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
STATE_FILE=channels.json
SESSION_NAME=telegram_session
```

## First Run - Authentication

On the first run, you'll need to authenticate:

1. Run any command (e.g., `python cli.py list`)
2. You'll receive a code in your Telegram app
3. Enter the code when prompted
4. If you have 2FA enabled, enter your password when prompted
5. The session will be saved, so you won't need to authenticate again

## Usage

### Create a Channel

Create a new broadcast channel:

```bash
python cli.py create "My Channel"
python cli.py create "My Channel" --description "Updates and announcements"
```

Create a supergroup (allows more members and features):

```bash
python cli.py create "My Group" --megagroup
```

### Set Channel Username

Make your channel public with a username:

```bash
python cli.py set-username "My Channel" mychannel
# Now accessible as @mychannel or t.me/mychannel
```

### Get Channel Information

View detailed information about any channel:

```bash
python cli.py info @mychannel
python cli.py info "My Channel"
python cli.py info -1001234567890
```

### List All Managed Channels

View all channels you've created or manage:

```bash
python cli.py list
```

Filter by tags:

```bash
python cli.py list --tags light-prod
python cli.py list --tags prod,staging
```

### Manage Tags

Add tags to a channel for organization:

```bash
python cli.py add-tags @mychannel production,alerts
python cli.py add-tags "My Channel" light-prod
```

Remove tags from a channel:

```bash
python cli.py remove-tags @mychannel staging
```

### Rename a Channel

Set a friendly name for easier management:

```bash
python cli.py rename @mychannel "Production Alerts"
python cli.py rename -1001234567890 "Dev Notifications"
```

### Remove from List

Remove a channel from your managed list (doesn't delete the channel):

```bash
python cli.py remove @mychannel
python cli.py remove "Production Alerts"
```

### Delete a Channel

Permanently delete a channel from Telegram:

```bash
python cli.py delete @mychannel
python cli.py delete "My Channel" --confirm  # Skip confirmation
```

**Warning**: This permanently deletes the channel. All messages and members will be lost!

### Run Scripts

Execute bulk operations using scripts:

```bash
python cli.py script create_yasno_channels
```

This will create 13 channels for Yasno power outage groups, all tagged with `light-prod`.

See [scripts/README.md](scripts/README.md) for more information on available scripts and how to create your own.

## State File

All managed channels are stored in `channels.json`. The file structure:

```json
{
  "channels": [
    {
      "id": "1234567890",
      "access_hash": "1234567890123456789",
      "title": "My Channel",
      "username": "mychannel",
      "type": "channel",
      "description": "Updates and announcements",
      "created_at": "2025-01-15T10:30:00",
      "friendly_name": "Production Alerts",
      "tags": ["light-prod", "alerts"]
    }
  ],
  "last_updated": "2025-01-15T10:30:00"
}
```

## Session File

After first authentication, Telethon creates a session file (`telegram_session.session` by default). This file:
- Stores your authentication session
- Allows you to run commands without re-authenticating
- Should be kept secure (don't commit to git!)

Add to `.gitignore`:
```
*.session
*.session-journal
.env
channels.json
```

## Channel Types

### Broadcast Channel (default)
- One-way communication (only admins can post)
- Unlimited members
- Members can view messages
- Use for: announcements, updates, status notifications

### Supergroup (--megagroup flag)
- Two-way communication (members can chat)
- Up to 200,000 members
- More features (polls, bots, etc.)
- Use for: communities, discussions, support groups

## Integration with Light Bot

This tool can be used to manage channels for the Light Bot project:

```bash
# Create status notification channel
python cli.py create "Power Status Notifications" \
  --description "Automated power status updates"
python cli.py set-username "Power Status Notifications" lightbot_status

# Create schedule notification channel
python cli.py create "Power Outage Schedules" \
  --description "Daily power outage schedules and warnings"
python cli.py set-username "Power Outage Schedules" lightbot_schedule

# Get channel IDs for .env configuration
python cli.py info @lightbot_status
python cli.py info @lightbot_schedule
```

Then use the channel IDs in Light Bot's `.env`:
```bash
TELEGRAM_CHANNEL_ID=-1001234567890
TELEGRAM_SCHEDULE_CHANNEL_ID=-1001234567891
```

## Troubleshooting

### "Missing required environment variables"
Make sure you've created a `.env` file with all required variables. See Installation section.

### "Invalid phone number"
Use international format: `+1234567890` (include country code with +)

### "You must be an admin to..."
You can only modify channels where you are the creator or have admin rights.

### "Session file is corrupted"
Delete the `.session` file and authenticate again:
```bash
rm telegram_session.session*
```

### 2FA Authentication
If you have two-factor authentication enabled, you'll be prompted for your password after entering the code.

## Security Notes

- Keep your API credentials secure
- Don't share your `.env` file or session files
- Add `.env` and `*.session` to `.gitignore`
- The tool uses official Telegram Client API
- All communications are encrypted by Telegram

## Command Reference

| Command | Description |
|---------|-------------|
| `create <title>` | Create a new channel |
| `create <title> --megagroup` | Create a new supergroup |
| `set-username <channel> <username>` | Set public username |
| `info <channel>` | Get channel information |
| `list` | List all managed channels |
| `list --tags <tags>` | List channels filtered by tags |
| `add-tags <channel> <tags>` | Add tags to a channel |
| `remove-tags <channel> <tags>` | Remove tags from a channel |
| `rename <channel> <name>` | Set friendly name |
| `remove <channel>` | Remove from managed list |
| `delete <channel>` | Delete channel permanently |
| `script <name> [args...]` | Run a script from scripts/ directory |

## Examples

```bash
# Complete workflow
python cli.py create "Test Channel" --description "For testing"
python cli.py set-username "Test Channel" mytestchannel
python cli.py add-tags @mytestchannel test,development
python cli.py rename @mytestchannel "Test - Production"
python cli.py info @mytestchannel
python cli.py list --tags test
python cli.py delete @mytestchannel --confirm

# Bulk operations with scripts
python cli.py script create_yasno_channels
python cli.py list --tags light-prod
```

## License

Part of the Light Bot project.
