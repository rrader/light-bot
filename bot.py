import logging
import asyncio
import os
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, WATCHDOG_STATUS_FILE, BOT_LAST_NOTIFIED_STATUS_FILE, TIMEZONE

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TelegramChannelBot:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.channel_id = TELEGRAM_CHANNEL_ID
        self.last_status = None
        self.monitoring = False

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

    def read_power_status(self):
        """Read current power status from file"""
        try:
            if os.path.exists(WATCHDOG_STATUS_FILE):
                with open(WATCHDOG_STATUS_FILE, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        return lines[0].strip()
            return None
        except Exception as e:
            logger.error(f"Error reading power status file: {e}")
            return None

    def read_last_status(self):
        """Read last known status from file"""
        try:
            if os.path.exists(BOT_LAST_NOTIFIED_STATUS_FILE):
                with open(BOT_LAST_NOTIFIED_STATUS_FILE, 'r') as f:
                    return f.read().strip()
            return None
        except Exception as e:
            logger.error(f"Error reading last status file: {e}")
            return None

    def write_last_status(self, status: str):
        """Write last known status to file"""
        try:
            with open(BOT_LAST_NOTIFIED_STATUS_FILE, 'w') as f:
                f.write(status)
            logger.info(f"Last status saved to file: {status}")
        except Exception as e:
            logger.error(f"Error writing last status file: {e}")

    async def monitor_power_status(self, check_interval: int = 10):
        """Monitor power status file for changes and send updates"""
        logger.info(f"Starting power status monitoring (checking every {check_interval}s)")
        self.monitoring = True

        # Read last known status from file (for persistence across restarts)
        self.last_status = self.read_last_status()
        if self.last_status:
            logger.info(f"Restored last status from file: {self.last_status}")
        else:
            # If no last status, read current status
            self.last_status = self.read_power_status()
            if self.last_status:
                self.write_last_status(self.last_status)
            logger.info(f"Initial power status: {self.last_status}")

        while self.monitoring:
            try:
                await asyncio.sleep(check_interval)

                current_status = self.read_power_status()

                # Check if status changed
                if current_status and current_status != self.last_status:
                    logger.info(f"Power status changed: {self.last_status} -> {current_status}")

                    # Send notification
                    emoji = '🟢' if current_status.lower() == 'on' else '🔴'
                    message = (
                        f"{emoji} <b>Power Status Changed</b>\n\n"
                        f"New Status: <b>{current_status.upper()}</b>\n"
                        f"Previous Status: <b>{self.last_status.upper() if self.last_status else 'Unknown'}</b>\n"
                        f"Time: {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')}"
                    )

                    await self.send_message(message)

                    # Update and persist last status
                    self.last_status = current_status
                    self.write_last_status(current_status)

            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(check_interval)

    def stop_monitoring(self):
        """Stop the monitoring loop"""
        self.monitoring = False
        logger.info("Stopping power status monitoring")


# Global bot instance
telegram_bot = TelegramChannelBot()


def send_channel_update(text: str):
    """Synchronous wrapper for sending channel updates"""
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
