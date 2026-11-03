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

    def __init__(self, stats_service=None):
        # Use custom API URL if provided (for E2E testing), otherwise use official Telegram API
        if TELEGRAM_API_BASE_URL:
            logger.info(f"Using custom Telegram API URL: {TELEGRAM_API_BASE_URL}")
            self.bot = Bot(token=TELEGRAM_BOT_TOKEN, base_url=TELEGRAM_API_BASE_URL)
        else:
            # Production: use official Telegram API (https://api.telegram.org)
            self.bot = Bot(token=TELEGRAM_BOT_TOKEN)

        self.channel_id = TELEGRAM_CHANNEL_ID
        self.stats_service = stats_service

    def set_stats_service(self, stats_service):
        self.stats_service = stats_service

    async def strip_previous_button(self, chat_id: str | int):
        """Remove inline button from previous message in this chat/channel to keep only the latest message with a button"""
        if not self.stats_service:
            return
        try:
            prev_msg_id = self.stats_service.get_last_button_message_id(chat_id)
            if prev_msg_id:
                await self.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=prev_msg_id,
                    reply_markup=None
                )
                logger.info(f"Removed inline button from previous message {prev_msg_id} in {chat_id}")
        except TelegramError as e:
            # Message might be too old (> 48h) or already deleted - ignore safely
            logger.debug(f"Could not remove reply markup from previous message in {chat_id}: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error stripping button from {chat_id}: {e}")

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> bool:
        """Send text message to the configured channel or specified chat_id with optional inline keyboard"""
        target = chat_id or self.channel_id
        try:
            # If a new button is attached, strip the button from the previous message first
            if reply_markup is not None:
                await self.strip_previous_button(target)

            kwargs = {
                'chat_id': target,
                'text': text,
                'parse_mode': 'HTML'
            }
            if reply_markup is not None:
                kwargs['reply_markup'] = reply_markup
            message = await self.bot.send_message(**kwargs)
            logger.info(f"Message sent successfully to {target}: {message.message_id}")

            # Remember this message as having the active button
            if reply_markup is not None and self.stats_service and message:
                self.stats_service.set_last_button_message_id(target, message.message_id)

            return True
        except TelegramError as e:
            logger.error(f"Failed to send message to {target}: {e}")
            return False


telegram_bot = TelegramChannelBot()
