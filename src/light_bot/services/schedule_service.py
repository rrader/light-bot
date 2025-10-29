import logging
import asyncio
import hashlib
import os
from datetime import datetime
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError

from light_bot.api.yasno import client as yasno_client, YasnoScheduleResponse
from light_bot.formatters.schedule_formatter import ScheduleFormatter
from light_bot.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_SCHEDULE_CHANNEL_ID,
    TIMEZONE,
    YASNO_GROUP,
    SCHEDULE_CHECK_INTERVAL,
    SCHEDULE_CHANGES_START_HOUR,
    SCHEDULE_TOMORROW_START_HOUR,
    LAST_SCHEDULE_HASH_FILE,
    LAST_CHECK_DATE_FILE,
    TOMORROW_SENT_DATE_FILE,
)

logger = logging.getLogger(__name__)


class ScheduleService:
    """Service to monitor and send power outage schedule notifications"""

    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.channel_id = TELEGRAM_SCHEDULE_CHANNEL_ID
        self.group = YASNO_GROUP
        self.formatter = ScheduleFormatter()
        self.monitoring = False
        self.last_schedule_hash = self._read_last_hash()
        self.last_check_date = self._read_last_check_date()
        self.tomorrow_sent_date = self._read_tomorrow_sent_date()

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

    def _read_last_check_date(self) -> Optional[datetime]:
        """Read last check date from file"""
        try:
            if os.path.exists(LAST_CHECK_DATE_FILE):
                with open(LAST_CHECK_DATE_FILE, 'r') as f:
                    date_str = f.read().strip()
                    if date_str:
                        return datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception as e:
            logger.error(f"Error reading last check date file: {e}")
        return None

    def _write_last_check_date(self, date_value: datetime) -> None:
        """Write last check date to file"""
        try:
            with open(LAST_CHECK_DATE_FILE, 'w') as f:
                f.write(date_value.strftime('%Y-%m-%d'))
            logger.debug(f"Last check date saved: {date_value}")
        except Exception as e:
            logger.error(f"Error writing last check date file: {e}")

    def _read_tomorrow_sent_date(self) -> Optional[datetime]:
        """Read tomorrow sent date from file"""
        try:
            if os.path.exists(TOMORROW_SENT_DATE_FILE):
                with open(TOMORROW_SENT_DATE_FILE, 'r') as f:
                    date_str = f.read().strip()
                    if date_str:
                        return datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception as e:
            logger.error(f"Error reading tomorrow sent date file: {e}")
        return None

    def _write_tomorrow_sent_date(self, date_value: datetime) -> None:
        """Write tomorrow sent date to file"""
        try:
            with open(TOMORROW_SENT_DATE_FILE, 'w') as f:
                f.write(date_value.strftime('%Y-%m-%d'))
            logger.info(f"Tomorrow sent date saved: {date_value}")
        except Exception as e:
            logger.error(f"Error writing tomorrow sent date file: {e}")

    def _compute_schedule_hash(self, schedule_data: YasnoScheduleResponse, for_tomorrow: bool = False) -> Optional[str]:
        """Compute hash of schedule to detect changes (date-independent)"""
        try:
            if not schedule_data:
                return None

            group_schedule = schedule_data.get_group(self.group)
            if not group_schedule:
                return None

            # Create hash from slots only (without date to detect actual schedule changes)
            day_schedule = group_schedule.tomorrow if for_tomorrow else group_schedule.today
            schedule_str = f"{self.group}|"
            schedule_str += "|".join([
                f"{slot.start}-{slot.end}-{slot.type}"
                for slot in day_schedule.slots
            ])

            return hashlib.sha256(schedule_str.encode()).hexdigest()
        except Exception as e:
            logger.error(f"Error computing schedule hash: {e}")
            return None

    async def send_schedule(self, for_tomorrow: bool = False, change_detected: bool = False) -> bool:
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
                for_tomorrow=for_tomorrow,
                change_detected=change_detected
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

    async def check_tomorrow_schedule(self) -> None:
        """Check if tomorrow's schedule is available and ready (not WaitingForSchedule)"""
        try:
            current_date = datetime.now(TIMEZONE).date()

            # Check if we already sent tomorrow's schedule today
            if self.tomorrow_sent_date == current_date:
                logger.debug("Tomorrow's schedule already sent today")
                return

            # Check if it's time to start checking (after SCHEDULE_TOMORROW_START_HOUR)
            current_hour = datetime.now(TIMEZONE).hour
            if current_hour < SCHEDULE_TOMORROW_START_HOUR:
                logger.debug(f"Too early to check tomorrow's schedule (current: {current_hour}h, start: {SCHEDULE_TOMORROW_START_HOUR}h)")
                return

            # Delete hash file before checking - if schedule doesn't appear, morning will send it
            if os.path.exists(LAST_SCHEDULE_HASH_FILE):
                os.remove(LAST_SCHEDULE_HASH_FILE)
                logger.info("Deleted hash file before checking tomorrow's schedule")
            self.last_schedule_hash = None

            logger.info("Checking if tomorrow's schedule is ready...")
            schedule_data = yasno_client.update()

            if not schedule_data:
                logger.error("Failed to fetch schedule data")
                return

            group_schedule = schedule_data.get_group(self.group)
            if not group_schedule:
                logger.warning(f"Group {self.group} not found in schedule")
                return

            tomorrow_schedule = group_schedule.tomorrow

            # Check if tomorrow's schedule is confirmed (not waiting)
            if tomorrow_schedule.status != "WaitingForSchedule":
                logger.info(f"Tomorrow's schedule is ready! Status: {tomorrow_schedule.status}")

                # Send tomorrow's schedule
                await self.send_schedule(for_tomorrow=True)

                # Save hash with tomorrow's schedule so morning doesn't duplicate
                tomorrow_hash = self._compute_schedule_hash(schedule_data, for_tomorrow=True)
                if tomorrow_hash:
                    self.last_schedule_hash = tomorrow_hash
                    self._write_last_hash(tomorrow_hash)
                    logger.info(f"Saved hash with tomorrow's schedule: {tomorrow_hash[:8]}... - morning won't duplicate")

                # Mark that we sent tomorrow's schedule today
                self.tomorrow_sent_date = current_date
                self._write_tomorrow_sent_date(current_date)
                logger.info(f"Tomorrow's schedule sent and marked for date: {current_date}")
            else:
                logger.info(f"Tomorrow's schedule not ready yet (status: {tomorrow_schedule.status}), hash remains deleted")

        except Exception as e:
            logger.error(f"Error checking tomorrow's schedule: {e}")

    async def check_schedule_changes(self):
        """Check if schedule has changed and notify if it has"""
        try:
            # Check if it's within the allowed time window (SCHEDULE_CHANGES_START_HOUR to SCHEDULE_TOMORROW_START_HOUR)
            current_hour = datetime.now(TIMEZONE).hour
            if current_hour < SCHEDULE_CHANGES_START_HOUR:
                logger.debug(f"Too early to check schedule changes (current: {current_hour}h, start: {SCHEDULE_CHANGES_START_HOUR}h)")
                return
            if current_hour >= SCHEDULE_TOMORROW_START_HOUR:
                logger.debug(f"Too late to check schedule changes (current: {current_hour}h, stop: {SCHEDULE_TOMORROW_START_HOUR}h)")
                return

            logger.info("Checking for schedule changes...")
            schedule_data = yasno_client.update()

            if not schedule_data:
                logger.error("Failed to fetch schedule data")
                return

            current_hash = self._compute_schedule_hash(schedule_data, for_tomorrow=False)
            if not current_hash:
                logger.warning("Could not compute schedule hash")
                return

            # Get current date
            current_date = datetime.now(TIMEZONE).date()

            # Detect if this is a new day
            is_new_day = self.last_check_date is not None and current_date != self.last_check_date

            # Compare with last known hash
            if not self.last_schedule_hash:
                # No hash file exists - send today's schedule
                logger.info("No hash file found - sending today's schedule")
                await self.send_schedule(for_tomorrow=False, change_detected=False)
                self.last_schedule_hash = current_hash
                self._write_last_hash(current_hash)
            elif current_hash != self.last_schedule_hash:
                logger.info(f"Schedule changed! Old: {self.last_schedule_hash[:8]}, New: {current_hash[:8]}")

                # If it's a new day but hash is different, it means actual schedule change
                # (not just yesterday's schedule that we already announced)
                if is_new_day:
                    logger.info("New day with different schedule - sending today's schedule")
                else:
                    logger.info("Schedule changed within the same day")

                # Send updated schedule (mark as changed only if not a new day)
                await self.send_schedule(for_tomorrow=False, change_detected=not is_new_day)

                # Update stored hash
                self.last_schedule_hash = current_hash
                self._write_last_hash(current_hash)
            else:
                logger.info("Schedule unchanged")

            # Update the last check date
            self.last_check_date = current_date
            self._write_last_check_date(current_date)

        except Exception as e:
            logger.error(f"Error checking schedule changes: {e}")

    async def schedule_monitoring_loop(self):
        """Main monitoring loop for scheduled messages and change detection"""
        logger.info(f"Starting schedule monitoring (check interval: {SCHEDULE_CHECK_INTERVAL}s)")
        self.monitoring = True

        while self.monitoring:
            try:
                now = datetime.now(TIMEZONE)
                current_date = now.date()

                # Check if tomorrow's schedule is ready (starts at SCHEDULE_TOMORROW_START_HOUR)
                # This will automatically send when status != "WaitingForSchedule"
                await self.check_tomorrow_schedule()

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
