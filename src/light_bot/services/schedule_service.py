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
from light_bot.core.file_utils import atomic_write_text, read_text, safe_remove, safe_rename
from light_bot.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_SCHEDULE_CHANNEL_ID,
    TIMEZONE,
    YASNO_GROUP,
    SCHEDULE_CHECK_INTERVAL,
    SCHEDULE_TODAY_START_HOUR,
    SCHEDULE_TODAY_END_HOUR,
    SCHEDULE_TOMORROW_START_HOUR,
    SCHEDULE_TOMORROW_END_HOUR,
    LAST_SCHEDULE_TODAY_HASH_FILE,
    LAST_SCHEDULE_TOMORROW_HASH_FILE,
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
        self.last_today_hash = self._read_hash_file(LAST_SCHEDULE_TODAY_HASH_FILE)
        self.last_tomorrow_hash = self._read_hash_file(LAST_SCHEDULE_TOMORROW_HASH_FILE)
        self.last_check_date = self._read_last_check_date()
        self.tomorrow_sent_date = self._read_tomorrow_sent_date()

    def _read_hash_file(self, file_path: str) -> Optional[str]:
        """Read schedule hash from file"""
        return read_text(file_path)

    def _write_hash_file(self, file_path: str, hash_value: str) -> None:
        """Write schedule hash to file atomically"""
        try:
            atomic_write_text(file_path, hash_value)
            logger.info(f"Hash saved to {file_path}: {hash_value[:8]}...")
        except Exception as e:
            logger.error(f"Error writing hash file {file_path}: {e}")
            raise

    def _read_last_check_date(self) -> Optional[datetime]:
        """Read last check date from file"""
        try:
            date_str = read_text(LAST_CHECK_DATE_FILE)
            if date_str:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception as e:
            logger.error(f"Error parsing last check date: {e}")
        return None

    def _write_last_check_date(self, date_value: datetime) -> None:
        """Write last check date to file atomically"""
        try:
            atomic_write_text(LAST_CHECK_DATE_FILE, date_value.strftime('%Y-%m-%d'))
            logger.debug(f"Last check date saved: {date_value}")
        except Exception as e:
            logger.error(f"Error writing last check date file: {e}")
            raise

    def _read_tomorrow_sent_date(self) -> Optional[datetime]:
        """Read tomorrow sent date from file"""
        try:
            date_str = read_text(TOMORROW_SENT_DATE_FILE)
            if date_str:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception as e:
            logger.error(f"Error parsing tomorrow sent date: {e}")
        return None

    def _write_tomorrow_sent_date(self, date_value: datetime) -> None:
        """Write tomorrow sent date to file atomically"""
        try:
            atomic_write_text(TOMORROW_SENT_DATE_FILE, date_value.strftime('%Y-%m-%d'))
            logger.info(f"Tomorrow sent date saved: {date_value}")
        except Exception as e:
            logger.error(f"Error writing tomorrow sent date file: {e}")
            raise

    def _compute_schedule_hash(self, schedule_data: YasnoScheduleResponse, for_tomorrow: bool = False) -> Optional[str]:
        """Compute hash of schedule to detect changes (date-independent)"""
        try:
            if not schedule_data:
                return None

            group_schedule = schedule_data.get_group(self.group)
            if not group_schedule:
                return None

            # Create hash from status and slots (without date to detect actual schedule changes)
            day_schedule = group_schedule.tomorrow if for_tomorrow else group_schedule.today
            schedule_str = f"{self.group}|{day_schedule.status}|"
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

    def _perform_midnight_rollover(self) -> None:
        """Perform midnight rollover: delete today's hash, promote tomorrow's hash to today's

        This method performs atomic file operations to ensure consistency.
        If any critical operation fails, an exception is raised to prevent
        inconsistent state.

        Raises:
            OSError: If critical file operations fail
        """
        try:
            # Step 1: Delete today's hash file (yesterday is gone)
            safe_remove(LAST_SCHEDULE_TODAY_HASH_FILE, critical=True)
            logger.info("Deleted today's hash file (yesterday)")

            # Step 2: Promote tomorrow's hash to today's hash
            if os.path.exists(LAST_SCHEDULE_TOMORROW_HASH_FILE):
                safe_rename(LAST_SCHEDULE_TOMORROW_HASH_FILE, LAST_SCHEDULE_TODAY_HASH_FILE)
                logger.info("Promoted tomorrow's hash to today's hash")

                # Update in-memory reference ONLY after successful file operation
                self.last_today_hash = self._read_hash_file(LAST_SCHEDULE_TODAY_HASH_FILE)
                self.last_tomorrow_hash = None
            else:
                logger.info("No tomorrow hash to promote")
                self.last_today_hash = None
                self.last_tomorrow_hash = None

            # Step 3: Clear tomorrow_sent_date (ready to send new tomorrow)
            safe_remove(TOMORROW_SENT_DATE_FILE, critical=False)
            logger.info("Cleared tomorrow sent date")
            self.tomorrow_sent_date = None

            logger.info("Midnight rollover completed successfully")
        except OSError:
            logger.critical("Critical error during midnight rollover - stopping monitoring")
            raise  # Re-raise to stop monitoring loop
        except Exception as e:
            logger.error(f"Unexpected error during midnight rollover: {e}")
            raise

    async def check_tomorrow_schedule(self) -> None:
        """Check if tomorrow's schedule is available and ready (not WaitingForSchedule)"""
        try:
            current_date = datetime.now(TIMEZONE).date()
            current_hour = datetime.now(TIMEZONE).hour

            # Check if we're within the monitoring window
            if current_hour < SCHEDULE_TOMORROW_START_HOUR or current_hour > SCHEDULE_TOMORROW_END_HOUR:
                logger.debug(f"Outside tomorrow monitoring window (current: {current_hour}h, window: {SCHEDULE_TOMORROW_START_HOUR}-{SCHEDULE_TOMORROW_END_HOUR}h)")
                return

            # Check if we already sent tomorrow's schedule today
            if self.tomorrow_sent_date == current_date:
                logger.debug("Tomorrow's schedule already sent today")
                return

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
            tomorrow_hash = self._compute_schedule_hash(schedule_data, for_tomorrow=True)

            if not tomorrow_hash:
                logger.warning("Could not compute tomorrow's schedule hash")
                return

            # Check if schedule has changed (or is new)
            if self.last_tomorrow_hash and tomorrow_hash == self.last_tomorrow_hash:
                logger.debug("Tomorrow's schedule unchanged")
                return

            # Check if tomorrow's schedule is confirmed (not waiting)
            if tomorrow_schedule.status != "WaitingForSchedule":
                logger.info(f"Tomorrow's schedule is ready! Status: {tomorrow_schedule.status}")

                # Send tomorrow's schedule
                change_detected = self.last_tomorrow_hash is not None and self.last_tomorrow_hash != tomorrow_hash
                await self.send_schedule(for_tomorrow=True, change_detected=change_detected)

                # Save tomorrow's hash
                self.last_tomorrow_hash = tomorrow_hash
                self._write_hash_file(LAST_SCHEDULE_TOMORROW_HASH_FILE, tomorrow_hash)
                logger.info(f"Saved tomorrow's hash: {tomorrow_hash[:8]}...")

                # Mark that we sent tomorrow's schedule today
                self.tomorrow_sent_date = current_date
                self._write_tomorrow_sent_date(current_date)
                logger.info(f"Tomorrow's schedule sent and marked for date: {current_date}")
            else:
                logger.debug(f"Tomorrow's schedule not ready yet (status: {tomorrow_schedule.status})")

        except Exception as e:
            logger.error(f"Error checking tomorrow's schedule: {e}")

    async def check_today_schedule(self):
        """Check if today's schedule has changed and notify if it has"""
        try:
            current_hour = datetime.now(TIMEZONE).hour

            # Check if we're within the monitoring window
            if current_hour < SCHEDULE_TODAY_START_HOUR or current_hour > SCHEDULE_TODAY_END_HOUR:
                logger.debug(f"Outside today monitoring window (current: {current_hour}h, window: {SCHEDULE_TODAY_START_HOUR}-{SCHEDULE_TODAY_END_HOUR}h)")
                return

            logger.info("Checking for today's schedule changes...")
            schedule_data = yasno_client.update()

            if not schedule_data:
                logger.error("Failed to fetch schedule data")
                return

            current_hash = self._compute_schedule_hash(schedule_data, for_tomorrow=False)
            if not current_hash:
                logger.warning("Could not compute today's schedule hash")
                return

            # Compare with last known hash
            if not self.last_today_hash:
                # No hash file exists - send today's schedule (morning case)
                logger.info("No today hash found - sending today's schedule")
                await self.send_schedule(for_tomorrow=False, change_detected=False)
                self.last_today_hash = current_hash
                self._write_hash_file(LAST_SCHEDULE_TODAY_HASH_FILE, current_hash)
            elif current_hash != self.last_today_hash:
                logger.info(f"Today's schedule changed! Old: {self.last_today_hash[:8]}, New: {current_hash[:8]}")

                # Send updated schedule with change flag
                await self.send_schedule(for_tomorrow=False, change_detected=True)

                # Update stored hash
                self.last_today_hash = current_hash
                self._write_hash_file(LAST_SCHEDULE_TODAY_HASH_FILE, current_hash)
            else:
                logger.debug("Today's schedule unchanged")

        except Exception as e:
            logger.error(f"Error checking today's schedule: {e}")

    async def schedule_monitoring_loop(self):
        """Main monitoring loop for scheduled messages and change detection"""
        logger.info(f"Starting schedule monitoring (check interval: {SCHEDULE_CHECK_INTERVAL}s)")
        logger.info(f"Today monitoring window: {SCHEDULE_TODAY_START_HOUR}-{SCHEDULE_TODAY_END_HOUR}h")
        logger.info(f"Tomorrow monitoring window: {SCHEDULE_TOMORROW_START_HOUR}-{SCHEDULE_TOMORROW_END_HOUR}h")
        self.monitoring = True

        while self.monitoring:
            try:
                now = datetime.now(TIMEZONE)
                current_date = now.date()

                # Check if it's a new day - perform midnight rollover
                if self.last_check_date is not None and current_date != self.last_check_date:
                    logger.info(f"New day detected! {self.last_check_date} -> {current_date}")
                    try:
                        self._perform_midnight_rollover()
                    except OSError as e:
                        logger.critical(f"Critical: Midnight rollover failed, stopping monitoring: {e}")
                        self.monitoring = False
                        raise

                # Check today's schedule for changes (independent monitoring)
                try:
                    await self.check_today_schedule()
                except Exception as e:
                    logger.error(f"Error checking today's schedule (will retry): {e}")

                # Check tomorrow's schedule (independent monitoring)
                try:
                    await self.check_tomorrow_schedule()
                except Exception as e:
                    logger.error(f"Error checking tomorrow's schedule (will retry): {e}")

                # Update the last check date
                self.last_check_date = current_date
                self._write_last_check_date(current_date)

                # Wait before next check
                await asyncio.sleep(SCHEDULE_CHECK_INTERVAL)

            except Exception as e:
                logger.critical(f"Fatal error in monitoring loop: {e}")
                self.monitoring = False
                raise

    def stop_monitoring(self):
        """Stop the monitoring loop"""
        self.monitoring = False
        logger.info("Stopping schedule monitoring")


# Global service instance
schedule_service = ScheduleService()
