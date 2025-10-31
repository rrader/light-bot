import os
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
LAST_SCHEDULE_HASH_FILE = os.getenv('LAST_SCHEDULE_HASH_FILE', 'last_schedule_hash.txt')
LAST_CHECK_DATE_FILE = os.getenv('LAST_CHECK_DATE_FILE', 'last_check_date.txt')
TOMORROW_SENT_DATE_FILE = os.getenv('TOMORROW_SENT_DATE_FILE', 'tomorrow_sent_date.txt')

# Timezone Configuration
TIMEZONE = pytz.timezone(os.getenv('TIMEZONE', 'Europe/Kyiv'))

# Yasno Schedule Configuration (Kiev region only)
# For E2E testing with mock server (None in production = use official Yasno API)
YASNO_API_BASE_URL = os.getenv('YASNO_API_BASE_URL')
YASNO_GROUP = os.getenv('YASNO_GROUP', '2.1')
YASNO_CITY = os.getenv('YASNO_CITY', 'kiev')
SCHEDULE_CHECK_INTERVAL = int(os.getenv('SCHEDULE_CHECK_INTERVAL', 3600))  # Check every hour
SCHEDULE_EVENING_HOUR = int(os.getenv('SCHEDULE_EVENING_HOUR', 20))  # 20:00 / 8 PM
SCHEDULE_EVENING_MINUTE = int(os.getenv('SCHEDULE_EVENING_MINUTE', 0))
SCHEDULE_CHANGES_START_HOUR = int(os.getenv('SCHEDULE_CHANGES_START_HOUR', 8))  # Start checking for changes at 8 AM
SCHEDULE_TOMORROW_START_HOUR = int(os.getenv('SCHEDULE_TOMORROW_START_HOUR', 18))  # Start checking tomorrow's schedule at 6 PM

# Validate required environment variables
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

if not TELEGRAM_CHANNEL_ID:
    raise ValueError("TELEGRAM_CHANNEL_ID environment variable is not set")

if not API_TOKEN:
    raise ValueError("API_TOKEN environment variable is not set")
