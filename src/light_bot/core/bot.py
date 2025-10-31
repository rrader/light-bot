import logging
from telegram import Bot
from telegram.error import TelegramError
from light_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_API_BASE_URL

logger = logging.getLogger(__name__)


class TelegramChannelBot:
    """Telegram bot wrapper for sending messages to a channel"""

    def __init__(self):
        # Use custom API URL if provided (for E2E testing), otherwise use official Telegram API
        if TELEGRAM_API_BASE_URL:
            logger.info(f"Using custom Telegram API URL: {TELEGRAM_API_BASE_URL}")
            self.bot = Bot(token=TELEGRAM_BOT_TOKEN, base_url=TELEGRAM_API_BASE_URL)
        else:
            # Production: use official Telegram API (https://api.telegram.org)
            self.bot = Bot(token=TELEGRAM_BOT_TOKEN)

        self.channel_id = TELEGRAM_CHANNEL_ID

    async def send_message(self, text: str) -> bool:
        """Send text message to the configured channel"""
        try:
            message = await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                parse_mode='HTML'
            )
            logger.info(f"Message sent successfully: {message.message_id}")
            return True
        except TelegramError as e:
            logger.error(f"Failed to send message: {e}")
            return False


telegram_bot = TelegramChannelBot()
