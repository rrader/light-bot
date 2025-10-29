import logging
from telegram import Bot
from telegram.error import TelegramError
from light_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID

logger = logging.getLogger(__name__)


class TelegramChannelBot:
    """Telegram bot wrapper for sending messages to a channel"""

    def __init__(self):
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
