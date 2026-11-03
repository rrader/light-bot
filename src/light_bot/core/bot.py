import logging
from typing import Optional
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError
from light_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_API_BASE_URL

logger = logging.getLogger(__name__)


def get_webapp_inline_keyboard(location_id: Optional[str] = 'home') -> InlineKeyboardMarkup:
    """Get inline keyboard with Web App direct link for channel posts"""
    loc = (location_id or 'home').lower()
    if loc in ['vinnytsia', 'vinnitsa', 'vn']:
        app_url = "https://t.me/power_po2_bot/app?startapp=vinnytsia"
    else:
        app_url = "https://t.me/power_po2_bot/app?startapp=home"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="⚡️ Графік та статус", url=app_url)]
    ])


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

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> bool:
        """Send text message to the configured channel or specified chat_id with optional inline keyboard"""
        target = chat_id or self.channel_id
        try:
            kwargs = {
                'chat_id': target,
                'text': text,
                'parse_mode': 'HTML'
            }
            if reply_markup is not None:
                kwargs['reply_markup'] = reply_markup
            message = await self.bot.send_message(**kwargs)
            logger.info(f"Message sent successfully to {target}: {message.message_id}")
            return True
        except TelegramError as e:
            logger.error(f"Failed to send message to {target}: {e}")
            return False


telegram_bot = TelegramChannelBot()
