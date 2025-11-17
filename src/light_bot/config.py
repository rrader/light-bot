import os
import json
import pytz
from dotenv import load_dotenv
from typing import List

# Load environment variables from .env file
load_dotenv()

from light_bot.models.group_config import GroupConfig

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
TELEGRAM_SCHEDULE_CHANNEL_ID = os.getenv('TELEGRAM_SCHEDULE_CHANNEL_ID', TELEGRAM_CHANNEL_ID)
# For E2E testing with mock server (None in production = use official Telegram API)
TELEGRAM_API_BASE_URL = os.getenv('TELEGRAM_API_BASE_URL')

# Flask Configuration
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
API_TOKEN = os.getenv('API_TOKEN')

# File Configuration
WATCHDOG_STATUS_FILE = os.getenv('WATCHDOG_STATUS_FILE', 'watchdog_status.txt')

# Data Directory Configuration
# Directory for schedule state files (default: current directory)
DATA_DIR = os.getenv('DATA_DIR', '.').rstrip('/')

# Ensure data directory exists
if DATA_DIR and DATA_DIR != '.':
    os.makedirs(DATA_DIR, exist_ok=True)

# Note: Individual state file paths are no longer configured here.
# MultiGroupScheduleManager creates state files automatically with group suffix.
# Example: Group "2.1" with DATA_DIR="./data" -> ./data/last_schedule_today_hash_2_1.txt

# Timezone Configuration
TIMEZONE = pytz.timezone(os.getenv('TIMEZONE', 'Europe/Kyiv'))

# Yasno Schedule Configuration
# For E2E testing with mock server (None in production = use official Yasno API)
YASNO_API_BASE_URL = os.getenv('YASNO_API_BASE_URL')

# Parse YASNO_GROUPS configuration (JSON format)
# Default: [{"id": "home", "group": "2.1", "city": "kiev"}]
_yasno_groups_str = os.getenv('YASNO_GROUPS', '[{"id": "home", "group": "2.1", "city": "kiev"}]').strip()

try:
    _yasno_groups_data = json.loads(_yasno_groups_str)
    if not isinstance(_yasno_groups_data, list):
        raise ValueError("YASNO_GROUPS must be a JSON array")

    YASNO_GROUP_CONFIGS: List[GroupConfig] = []
    for item in _yasno_groups_data:
        if not isinstance(item, dict):
            raise ValueError(f"Each item in YASNO_GROUPS must be an object, got: {type(item)}")

        # Extract fields with validation
        group_id = item.get('id', '').strip()
        group = item.get('group', '').strip()
        city = item.get('city', '').strip()
        channel = item.get('channel', '').strip() or None
        chat_id = item.get('chat_id', '') or None
        if chat_id:
            chat_id = int(chat_id)

        if not group_id:
            raise ValueError(f"Missing 'id' field in group config: {item}")
        if not group:
            raise ValueError(f"Missing 'group' field in group config: {item}")
        if not city:
            raise ValueError(f"Missing 'city' field in group config: {item}")

        YASNO_GROUP_CONFIGS.append(GroupConfig(
            id=group_id,
            group=group,
            city=city,
            channel=channel,
            chat_id=chat_id
        ))

    print(YASNO_GROUP_CONFIGS)

    if not YASNO_GROUP_CONFIGS:
        raise ValueError("YASNO_GROUPS must contain at least one group configuration")

except json.JSONDecodeError as e:
    raise ValueError(f"YASNO_GROUPS must be valid JSON: {e}")
except Exception as e:
    raise ValueError(f"Error parsing YASNO_GROUPS: {e}")

SCHEDULE_CHECK_INTERVAL = int(os.getenv('SCHEDULE_CHECK_INTERVAL', 3600))  # Check every hour
# Today's schedule monitoring window
SCHEDULE_TODAY_START_HOUR = int(os.getenv('SCHEDULE_TODAY_START_HOUR', 0))  # Start checking today's schedule at midnight
SCHEDULE_TODAY_END_HOUR = int(os.getenv('SCHEDULE_TODAY_END_HOUR', 21))  # Stop checking today's schedule at 9 PM
# Tomorrow's schedule monitoring window
SCHEDULE_TOMORROW_START_HOUR = int(os.getenv('SCHEDULE_TOMORROW_START_HOUR', 18))  # Start checking tomorrow's schedule at 6 PM
SCHEDULE_TOMORROW_END_HOUR = int(os.getenv('SCHEDULE_TOMORROW_END_HOUR', 23))  # Stop checking tomorrow's schedule at 11 PM
# Outage warning configuration
OUTAGE_WARNING_MINUTES = int(os.getenv('OUTAGE_WARNING_MINUTES', 30))  # Send warning 30 minutes before outage
OUTAGE_WARNING_CHECK_INTERVAL = int(os.getenv('OUTAGE_WARNING_CHECK_INTERVAL', 300))  # Check every 5 minutes

# OpenAI API Configuration (optional - for AI explanations of schedule changes)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')  # Optional: OpenAI API key
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')  # OpenAI model for explanations
ENABLE_AI_EXPLANATIONS = os.getenv('ENABLE_AI_EXPLANATIONS', 'true').lower() == 'true'  # Enable/disable AI explanations

# Validate required environment variables
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

if not TELEGRAM_CHANNEL_ID:
    raise ValueError("TELEGRAM_CHANNEL_ID environment variable is not set")

if not API_TOKEN:
    raise ValueError("API_TOKEN environment variable is not set")
