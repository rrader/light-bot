import os
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
TELEGRAM_SCHEDULE_CHANNEL_ID = os.getenv('TELEGRAM_SCHEDULE_CHANNEL_ID', TELEGRAM_CHANNEL_ID)

# Flask Configuration
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
API_TOKEN = os.getenv('API_TOKEN')

# File Configuration
WATCHDOG_STATUS_FILE = os.getenv('WATCHDOG_STATUS_FILE', 'watchdog_status.txt')
LAST_SCHEDULE_HASH_FILE = os.getenv('LAST_SCHEDULE_HASH_FILE', 'last_schedule_hash.txt')

# Timezone Configuration
TIMEZONE = pytz.timezone(os.getenv('TIMEZONE', 'Europe/Kyiv'))

# Yasno Schedule Configuration
YASNO_CITY = os.getenv('YASNO_CITY', 'kiev')
YASNO_GROUP = os.getenv('YASNO_GROUP', '2.1')
SCHEDULE_CHECK_INTERVAL = int(os.getenv('SCHEDULE_CHECK_INTERVAL', 3600))  # Check every hour
SCHEDULE_EVENING_HOUR = int(os.getenv('SCHEDULE_EVENING_HOUR', 20))  # 20:00 / 8 PM
SCHEDULE_EVENING_MINUTE = int(os.getenv('SCHEDULE_EVENING_MINUTE', 0))

# Validate required environment variables
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

if not TELEGRAM_CHANNEL_ID:
    raise ValueError("TELEGRAM_CHANNEL_ID environment variable is not set")

if not API_TOKEN:
    raise ValueError("API_TOKEN environment variable is not set")
