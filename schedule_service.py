import logging
import asyncio
import hashlib
import os
from datetime import datetime, time as dt_time
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError

from yasno_hass import client as yasno_client, YasnoAPIComponent, YasnoAPIOutage, merge_intervals, YasnoOutage
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_SCHEDULE_CHANNEL_ID,
    TIMEZONE,
    YASNO_CITY,
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
    def format_outages(outages: list[YasnoAPIOutage], today: bool = True) -> str:
        """Format list of outages into readable time ranges using helper functions"""
        if not outages:
            return "✅ Немає планових відключень"

        # Sort outages by start time first (merge_intervals expects sorted input)
        sorted_outages = sorted(outages, key=lambda x: x.start)

        # Use merge_intervals helper from yasno_hass to merge consecutive intervals
        # This returns list[YasnoOutage] with datetime objects (timezone-aware)
        merged_outages = merge_intervals(sorted_outages, today=today)

        # Format merged intervals with datetime objects (already timezone-aware!)
        formatted = []
        for outage in merged_outages:
            start_str = outage.start.strftime('%H:%M')
            end_str = outage.end.strftime('%H:%M')
            formatted.append(f"⚡️ {start_str} - {end_str}")

        return "\n".join(formatted)

    @staticmethod
    def format_schedule_message(
        schedule_data: YasnoAPIComponent,
        city: str,
        group: str,
        for_tomorrow: bool = False
    ) -> str:
        """Format complete schedule message for Telegram"""
        if not schedule_data:
            return "❌ Графік відключень наразі недоступний"

        # Currently Yasno API returns weekly "schedule" with POSSIBLE_OUTAGE
        # The dailySchedule field only appears when there are DEFINITE_OUTAGE
        # For now, we show "no restrictions" message
        emoji = "🌙" if for_tomorrow else "☀️"
        day_label = "завтра" if for_tomorrow else "сьогодні"

        message = (
            f"{emoji} <b>Графік відключень {day_label.upper()}</b>\n\n"
            f"📍 Місто: <b>{city.capitalize()}</b>\n"
            f"🏠 Група: <b>{group}</b>\n\n"
            f"✅ <b>Обмежень від НЕК «Укренерго» немає</b>\n\n"
            f"Планові відключення за графіками не застосовуються.\n"
            f"Якщо у вас немає електропостачання, зверніться до вашого оператора системи розподілу.\n\n"
            f"🕐 Оновлено: {datetime.now(TIMEZONE).strftime('%H:%M:%S')}"
        )

        return message


class ScheduleService:
    """Service to check and send power outage schedules"""

    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.channel_id = TELEGRAM_SCHEDULE_CHANNEL_ID
        self.city = YASNO_CITY
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

    def _write_last_hash(self, hash_value: str):
        """Write last schedule hash to file"""
        try:
            with open(LAST_SCHEDULE_HASH_FILE, 'w') as f:
                f.write(hash_value)
            logger.info(f"Schedule hash saved: {hash_value[:8]}...")
        except Exception as e:
            logger.error(f"Error writing schedule hash file: {e}")

    def _compute_schedule_hash(self, schedule_data: YasnoAPIComponent) -> Optional[str]:
        """Compute hash of current schedule to detect changes"""
        try:
            if not schedule_data or not schedule_data.schedule:
                return None

            city_schedule = schedule_data.schedule.get(self.city)
            if not city_schedule:
                return None

            group_key = f"group_{self.group}"
            if group_key not in city_schedule:
                return None

            # Weekly schedule is a list of 7 days, each with outages
            weekly_outages = city_schedule[group_key]

            # Create a string representation of the entire weekly schedule
            schedule_str = f"{self.city}|{self.group}|"
            schedule_str += "|".join([
                str(day_outages) for day_outages in weekly_outages
            ])

            # Compute hash
            return hashlib.sha256(schedule_str.encode()).hexdigest()
        except Exception as e:
            logger.error(f"Error computing schedule hash: {e}")
            return None

    async def send_schedule(self, for_tomorrow: bool = False):
        """Fetch and send schedule to Telegram channel"""
        try:
            logger.info(f"Fetching schedule from Yasno API (tomorrow={for_tomorrow})...")
            schedule_data = yasno_client.update()

            if not schedule_data:
                logger.error("Failed to fetch schedule data from Yasno API")
                return False

            # Log the fetched schedule data
            logger.info(f"API returned: template={schedule_data.template_name}, regions={schedule_data.available_regions}")
            logger.info(f"Has schedule (weekly): {schedule_data.schedule is not None}")

            if schedule_data.schedule and self.city in schedule_data.schedule:
                city_schedule = schedule_data.schedule[self.city]
                group_key = f"group_{self.group}"
                if group_key in city_schedule:
                    logger.info(f"Weekly schedule found for group {self.group}")
                    logger.info(f"Schedule has {len(city_schedule[group_key])} days")
                else:
                    logger.info(f"Group {group_key} not found in schedule")
            else:
                logger.info("No schedule data available (API returned empty schedule)")

            message = self.formatter.format_schedule_message(
                schedule_data,
                self.city,
                self.group,
                for_tomorrow=for_tomorrow
            )

            # Print the formatted message to console
            logger.info(f"Formatted schedule message:\n{message}")

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

                # Send change alert
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
