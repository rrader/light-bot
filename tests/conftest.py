import os
import pytest

# Set environment variables BEFORE any imports
os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
os.environ['TELEGRAM_CHANNEL_ID'] = '@test_channel'
os.environ['API_TOKEN'] = 'test_api_token_123'
os.environ['FLASK_PORT'] = '5000'
os.environ['POWER_STATUS_FILE'] = 'test_power_status.txt'
os.environ['LAST_STATUS_FILE'] = 'test_last_status.txt'
