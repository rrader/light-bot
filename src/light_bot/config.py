import os
import json
import pytz
from dotenv import load_dotenv
from typing import List, Dict, Optional

# Load environment variables from .env file
load_dotenv()

from light_bot.models import GroupConfig, LocationConfig

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
TELEGRAM_SCHEDULE_CHANNEL_ID = os.getenv('TELEGRAM_SCHEDULE_CHANNEL_ID', TELEGRAM_CHANNEL_ID)
# For E2E testing with mock server (None in production = use official Telegram API)
TELEGRAM_API_BASE_URL = os.getenv('TELEGRAM_API_BASE_URL')

# Flask Configuration
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
API_TOKEN = os.getenv('API_TOKEN')

# Home Assistant Webhook Configuration
HA_WEBHOOK_URL = os.getenv('HA_WEBHOOK_URL')

# File Configuration
WATCHDOG_STATUS_FILE = os.getenv('WATCHDOG_STATUS_FILE', 'watchdog_status.txt')
DB_PATH = os.getenv('DB_PATH', 'light_bot.db')

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

# Multi-Location Power Monitoring Configuration
_locations_str = os.getenv('LOCATIONS', '').strip()
LOCATIONS: Dict[str, LocationConfig] = {}

if _locations_str:
    try:
        _loc_data = json.loads(_locations_str)
        if isinstance(_loc_data, list):
            for item in _loc_data:
                if isinstance(item, dict) and item.get('id'):
                    lid = item['id'].strip().lower()
                    loc = LocationConfig(
                        id=lid,
                        name=item.get('name', lid.capitalize()),
                        status_file=item.get('status_file') or (WATCHDOG_STATUS_FILE if lid == 'home' else os.path.join(DATA_DIR, f"watchdog_status_{lid}.txt") if DATA_DIR != '.' else f"watchdog_status_{lid}.txt"),
                        channel_id=item.get('channel_id') or TELEGRAM_CHANNEL_ID,
                        yasno_group=item.get('yasno_group'),
                        ha_webhook_url=item.get('ha_webhook_url')
                    )
                    LOCATIONS[lid] = loc
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error parsing LOCATIONS: {e}")

# Default fallback locations
if 'home' not in LOCATIONS:
    LOCATIONS['home'] = LocationConfig(
        id='home',
        name=os.getenv('LOCATION_NAME_HOME', 'Дім'),
        status_file=WATCHDOG_STATUS_FILE,
        channel_id=TELEGRAM_CHANNEL_ID,
        yasno_group='home',
        ha_webhook_url=os.getenv('HA_WEBHOOK_URL_HOME') or os.getenv('HA_WEBHOOK_URL_KYIV') or os.getenv('HA_WEBHOOK_URL')
    )

if 'vinnytsia' not in LOCATIONS:
    _vn_status_file = os.getenv(
        'WATCHDOG_STATUS_FILE_VINNYTSIA',
        os.path.join(DATA_DIR, 'watchdog_status_vinnytsia.txt') if DATA_DIR != '.' else 'watchdog_status_vinnytsia.txt'
    )
    _vn_channel = os.getenv('TELEGRAM_CHANNEL_ID_VINNYTSIA') or TELEGRAM_CHANNEL_ID
    LOCATIONS['vinnytsia'] = LocationConfig(
        id='vinnytsia',
        name=os.getenv('LOCATION_NAME_VINNYTSIA', 'Вінниця'),
        status_file=_vn_status_file,
        channel_id=_vn_channel,
        yasno_group=os.getenv('SCHEDULE_GROUP_VINNYTSIA', 'vinnytsia'),
        ha_webhook_url=os.getenv('HA_WEBHOOK_URL_VINNYTSIA')
    )


def get_location_config(location_id: Optional[str]) -> Optional[LocationConfig]:
    """Get LocationConfig by id, handling aliases (home/kyiv/default)."""
    if not location_id or location_id.lower() in ('home', 'kyiv', 'default'):
        return LOCATIONS.get('home')
    return LOCATIONS.get(location_id.lower())

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
        group = item.get('group', '').strip() or None  # Convert empty string to None
        group_dynamic = item.get('group_dynamic', '').strip() or None  # Convert empty string to None
        city = item.get('city', '').strip()
        channel = item.get('channel', '').strip() or None
        provider = item.get('provider', '').strip() or None
        chat_id = item.get('chat_id', '') or None
        if chat_id:
            chat_id = int(chat_id)

        if not group_id:
            raise ValueError(f"Missing 'id' field in group config: {item}")
        if not city:
            raise ValueError(f"Missing 'city' field in group config: {item}")

        # Create GroupConfig (validation happens in __post_init__)
        config = GroupConfig(
            id=group_id,
            group=group,
            group_dynamic=group_dynamic,
            city=city,
            channel=channel,
            chat_id=chat_id,
            provider=provider
        )
        
        # Resolve dynamic groups immediately at startup
        _, _ = config.resolve_group()  # Unpack tuple, ignore change status at startup
        
        YASNO_GROUP_CONFIGS.append(config)

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

# Group Resolution Configuration
# How often to re-resolve dynamic groups (in seconds)
# Default: 21600 (6 hours), Set to 0 to disable periodic resolution
GROUP_RESOLUTION_INTERVAL = int(os.getenv('GROUP_RESOLUTION_INTERVAL', 21600))

# OpenAI API Configuration (optional - for AI explanations of schedule changes)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')  # Optional: OpenAI API key
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-6-luna')  # OpenAI model for explanations
ENABLE_AI_EXPLANATIONS = os.getenv('ENABLE_AI_EXPLANATIONS', 'true').lower() == 'true'  # Enable/disable AI explanations

# Validate required environment variables
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

if not TELEGRAM_CHANNEL_ID:
    raise ValueError("TELEGRAM_CHANNEL_ID environment variable is not set")

if not API_TOKEN:
    raise ValueError("API_TOKEN environment variable is not set")
