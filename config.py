import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')

# Flask Configuration
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
API_TOKEN = os.getenv('API_TOKEN')

# File Configuration
POWER_STATUS_FILE = os.getenv('POWER_STATUS_FILE', 'power_status.txt')
LAST_STATUS_FILE = os.getenv('LAST_STATUS_FILE', 'last_status.txt')

# Validate required environment variables
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

if not TELEGRAM_CHANNEL_ID:
    raise ValueError("TELEGRAM_CHANNEL_ID environment variable is not set")

if not API_TOKEN:
    raise ValueError("API_TOKEN environment variable is not set")
