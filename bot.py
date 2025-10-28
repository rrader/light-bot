import logging
import asyncio
from telegram import Bot
from telegram.error import TelegramError
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TelegramChannelBot:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.channel_id = TELEGRAM_CHANNEL_ID

    async def send_message(self, text: str):
        """Send a message to the channel"""
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

    async def send_photo(self, photo_url: str, caption: str = None):
        """Send a photo to the channel"""
        try:
            message = await self.bot.send_photo(
                chat_id=self.channel_id,
                photo=photo_url,
                caption=caption,
                parse_mode='HTML'
            )
            logger.info(f"Photo sent successfully: {message.message_id}")
            return True
        except TelegramError as e:
            logger.error(f"Failed to send photo: {e}")
            return False

    async def send_document(self, document_url: str, caption: str = None):
        """Send a document to the channel"""
        try:
            message = await self.bot.send_document(
                chat_id=self.channel_id,
                document=document_url,
                caption=caption,
                parse_mode='HTML'
            )
            logger.info(f"Document sent successfully: {message.message_id}")
            return True
        except TelegramError as e:
            logger.error(f"Failed to send document: {e}")
            return False


# Global bot instance
telegram_bot = TelegramChannelBot()


def send_channel_update(text: str):
    """Synchronous wrapper for sending channel updates from Flask"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, create a task
            asyncio.create_task(telegram_bot.send_message(text))
        else:
            # If no loop is running, use run_until_complete
            loop.run_until_complete(telegram_bot.send_message(text))
    except RuntimeError:
        # If no event loop exists, create a new one
        asyncio.run(telegram_bot.send_message(text))
