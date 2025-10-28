import logging
import asyncio
import hashlib
import os
from datetime import datetime, time as dt_time, timedelta
from typing import Optional, List
from telegram import Bot
from telegram.error import TelegramError

from yasno_hass import client as yasno_client, YasnoScheduleResponse, PowerSlot, SlotType
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_SCHEDULE_CHANNEL_ID,
    TIMEZONE,
    YASNO_GROUP,
    SCHEDULE_CHECK_INTERVAL,
    SCHEDULE_EVENING_HOUR,
    SCHEDULE_EVENING_MINUTE,
    LAST_SCHEDULE_HASH_FILE,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class ScheduleFormatter:
    """Format Yasno power outage schedules for Telegram messages"""

    @staticmethod
    def minutes_to_time(minutes: int) -> str:
        """Convert minutes from midnight to HH:MM format"""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"

    @staticmethod
    def get_outage_slots(slots: List[PowerSlot]) -> List[PowerSlot]:
        """Filter slots to get only Definite outages"""
        return [slot for slot in slots if slot.type == SlotType.DEFINITE]

    @staticmethod
    def format_outage_slots(slots: List[PowerSlot]) -> str:
        """Format outage slots into readable time ranges"""
        outage_slots = ScheduleFormatter.get_outage_slots(slots)

        if not outage_slots:
            return "✅ Відключень немає"

        formatted = []
        for slot in outage_slots:
            start_str = ScheduleFormatter.minutes_to_time(slot.start)
            end_str = ScheduleFormatter.minutes_to_time(slot.end)
            formatted.append(f"⚡️ {start_str} - {end_str}")

        return "\n".join(formatted)

    @staticmethod
    def format_schedule_message(
        schedule_data: YasnoScheduleResponse,
        group: str,
        for_tomorrow: bool = False
    ) -> str:
        """Format complete schedule message for Telegram"""
        if not schedule_data:
            return "❌ Графік відключень наразі недоступний"

        emoji = "🌙" if for_tomorrow else "☀️"
        day_label = "завтра" if for_tomorrow else "сьогодні"

        # Get group schedule
        group_schedule = schedule_data.get_group(group)
        if not group_schedule:
            return f"❌ Група {group} не знайдена в графіку"

        # Get day schedule
        day_schedule = group_schedule.tomorrow if for_tomorrow else group_schedule.today

        # Format the date
        date_str = day_schedule.date.strftime('%d.%m.%Y')
        weekday_names = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця", 'Субота', 'Неділя']
        weekday = weekday_names[day_schedule.date.weekday()]

        # Format outages
        outages_text = ScheduleFormatter.format_outage_slots(day_schedule.slots)

        # Determine status message
        status_msg = ""
        if day_schedule.status == "WaitingForSchedule":
            status_msg = "⏳ Очікування підтвердження графіку\n\n"

        message = (
            f"{emoji} <b>Графік відключень {day_label.upper()}</b>\n\n"
            f"🏠 Група: <b>{group}</b>\n"
            f"📅 {weekday}, {date_str}\n\n"
            f"{status_msg}"
            f"<b>Планові відключення:</b>\n"
            f"{outages_text}\n\n"
            f"🕐 Оновлено: {datetime.now(TIMEZONE).strftime('%H:%M:%S')}"
        )

        return message


class ScheduleService:
    """Service to check and send power outage schedules"""

    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.channel_id = TELEGRAM_SCHEDULE_CHANNEL_ID
        self.group = YASNO_GROUP
        self.formatter = ScheduleFormatter()
        self.monitoring = False
        self.last_schedule_hash = self._read_last_hash()

    def _read_last_hash(self) -> Optional[str]:
        """Read last schedule hash from file"""
        try:
            if os.path.exists(LAST_SCHEDULE_HASH_FILE):
                with open(LAST_SCHEDULE_HASH_FILE, 'r') as f:
                    return f.read().strip()
        except Exception as e:
            logger.error(f"Error reading schedule hash file: {e}")
        return None

    def _write_last_hash(self, hash_value: str) -> None:
        """Write last schedule hash to file"""
        try:
            with open(LAST_SCHEDULE_HASH_FILE, 'w') as f:
                f.write(hash_value)
            logger.info(f"Schedule hash saved: {hash_value[:8]}...")
        except Exception as e:
            logger.error(f"Error writing schedule hash file: {e}")

    def _compute_schedule_hash(self, schedule_data: YasnoScheduleResponse) -> Optional[str]:
        """Compute hash of current schedule to detect changes"""
        try:
            if not schedule_data:
                return None

            group_schedule = schedule_data.get_group(self.group)
            if not group_schedule:
                return None

            # Create hash from today's slots
            schedule_str = f"{self.group}|{group_schedule.today.date}|"
            schedule_str += "|".join([
                f"{slot.start}-{slot.end}-{slot.type}"
                for slot in group_schedule.today.slots
            ])

            return hashlib.sha256(schedule_str.encode()).hexdigest()
        except Exception as e:
            logger.error(f"Error computing schedule hash: {e}")
            return None

    async def send_schedule(self, for_tomorrow: bool = False) -> bool:
        """Fetch and send schedule to Telegram channel"""
        try:
            logger.info(f"Fetching schedule (tomorrow={for_tomorrow})...")
            schedule_data = yasno_client.update()

            if not schedule_data:
                logger.error("Failed to fetch schedule data from Yasno API")
                return False

            # Log the fetched data
            group_schedule = schedule_data.get_group(self.group)
            if group_schedule:
                day_schedule = group_schedule.tomorrow if for_tomorrow else group_schedule.today
                outage_slots = self.formatter.get_outage_slots(day_schedule.slots)
                logger.info(f"Schedule for group {self.group}: {len(outage_slots)} outage slots")
                logger.info(f"Date: {day_schedule.date}, Status: {day_schedule.status}")
            else:
                logger.warning(f"Group {self.group} not found in API response")

            message = self.formatter.format_schedule_message(
                schedule_data,
                self.group,
                for_tomorrow=for_tomorrow
            )

            # Print the formatted message
            logger.info(f"Formatted message:\n{message}")

            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info("Schedule message sent successfully")
            return True

        except TelegramError as e:
            logger.error(f"Failed to send schedule message: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending schedule: {e}")
            return False

    async def check_schedule_changes(self):
        """Check if schedule has changed and notify if it has"""
        try:
            logger.info("Checking for schedule changes...")
            schedule_data = yasno_client.update()

            if not schedule_data:
                logger.error("Failed to fetch schedule data")
                return

            current_hash = self._compute_schedule_hash(schedule_data)
            if not current_hash:
                logger.warning("Could not compute schedule hash")
                return

            # Compare with last known hash
            if self.last_schedule_hash and current_hash != self.last_schedule_hash:
                logger.info(f"Schedule changed! Old: {self.last_schedule_hash[:8]}, New: {current_hash[:8]}")

                # Send notification about change
                change_message = (
                    "🔔 <b>ГРАФІК ВІДКЛЮЧЕНЬ ЗМІНИВСЯ!</b>\n\n"
                    "Оновлений графік на сьогодні:\n"
                )

                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=change_message,
                    parse_mode='HTML'
                )

                # Send updated schedule
                await self.send_schedule(for_tomorrow=False)

                # Update stored hash
                self.last_schedule_hash = current_hash
                self._write_last_hash(current_hash)
            else:
                logger.info("Schedule unchanged")
                # Update hash even if unchanged (first time setup)
                if not self.last_schedule_hash:
                    self.last_schedule_hash = current_hash
                    self._write_last_hash(current_hash)

        except Exception as e:
            logger.error(f"Error checking schedule changes: {e}")

    async def schedule_monitoring_loop(self):
        """Main monitoring loop for scheduled messages and change detection"""
        logger.info(f"Starting schedule monitoring (check interval: {SCHEDULE_CHECK_INTERVAL}s)")
        self.monitoring = True

        evening_time = dt_time(SCHEDULE_EVENING_HOUR, SCHEDULE_EVENING_MINUTE)
        last_evening_send_date = None

        while self.monitoring:
            try:
                now = datetime.now(TIMEZONE)
                current_time = now.time()
                current_date = now.date()

                # Check if it's time to send evening schedule (tomorrow's schedule)
                if (current_time.hour == evening_time.hour and
                    current_time.minute == evening_time.minute and
                    last_evening_send_date != current_date):

                    logger.info("Sending evening schedule (tomorrow)...")
                    await self.send_schedule(for_tomorrow=True)
                    last_evening_send_date = current_date

                # Check for schedule changes (every SCHEDULE_CHECK_INTERVAL)
                await self.check_schedule_changes()

                # Wait before next check
                await asyncio.sleep(SCHEDULE_CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(SCHEDULE_CHECK_INTERVAL)

    def stop_monitoring(self):
        """Stop the monitoring loop"""
        self.monitoring = False
        logger.info("Stopping schedule monitoring")


# Global service instance
schedule_service = ScheduleService()
