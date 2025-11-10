import logging
import asyncio
import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional, Tuple
from telegram import Bot
from telegram.error import TelegramError

from light_bot.api.yasno import client as yasno_client, YasnoScheduleResponse, PowerSlot
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
    OUTAGE_WARNING_MINUTES,
    OUTAGE_WARNING_CHECK_INTERVAL,
    LAST_SCHEDULE_TODAY_HASH_FILE,
    LAST_SCHEDULE_TOMORROW_HASH_FILE,
    LAST_CHECK_DATE_FILE,
    TOMORROW_SENT_DATE_FILE,
    LAST_WARNING_SENT_FILE,
)

logger = logging.getLogger(__name__)

# Time constants for midnight boundary handling
MINUTES_PER_DAY = 1440
HOURS_PER_DAY = 24


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
        self.last_warning_sent = self._read_last_warning_sent()
        # Schedule data cache with thread safety
        self._cache_lock = asyncio.Lock()
        self._cached_schedule: Optional[YasnoScheduleResponse] = None
        self._cache_timestamp: Optional[datetime] = None

    async def _get_cached_schedule(self) -> Optional[YasnoScheduleResponse]:
        """Get cached schedule if still valid, otherwise fetch new data

        Cache is considered valid if it's less than SCHEDULE_CHECK_INTERVAL old.
        This allows multiple subsystems (schedule monitoring, warning system) to
        reuse the same API data without redundant fetches.

        Thread-safe: Uses asyncio.Lock to prevent race conditions when multiple
        async tasks check cache simultaneously. Only one task will fetch fresh
        data if cache expires, preventing cache stampede.

        Returns:
            Cached or fresh schedule data, or None if fetch fails
        """
        async with self._cache_lock:
            now = datetime.now(TIMEZONE)

            # Check if cache is still valid
            if self._cached_schedule and self._cache_timestamp:
                cache_age = (now - self._cache_timestamp).total_seconds()
                if cache_age < SCHEDULE_CHECK_INTERVAL:
                    logger.debug(f"Using cached schedule (age: {int(cache_age)}s)")
                    return self._cached_schedule

            # Fetch fresh data
            logger.debug("Fetching fresh schedule data from API")
            schedule_data = yasno_client.update()

            if schedule_data:
                self._cached_schedule = schedule_data
                self._cache_timestamp = now
                logger.debug("Schedule cache updated")
            else:
                logger.warning("Failed to fetch schedule data, cache invalidated")
                self._cached_schedule = None
                self._cache_timestamp = None

            return schedule_data

    def _invalidate_cache(self) -> None:
        """Invalidate the schedule cache (e.g., after midnight rollover)

        Note: This is a synchronous method that sets the cache timestamp to epoch,
        causing the cache to be treated as expired. This avoids needing async/await
        in the midnight rollover path while still being thread-safe.
        """
        # Set timestamp to epoch instead of None for thread-safe invalidation
        # The next call to _get_cached_schedule will see it as expired
        if self._cache_timestamp:
            self._cache_timestamp = datetime.fromtimestamp(0, TIMEZONE)
            logger.debug("Schedule cache invalidated (timestamp set to epoch)")
        else:
            logger.debug("Cache already empty")

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

    def _read_last_warning_sent(self) -> Optional[str]:
        """Read last warning identifier from file"""
        return read_text(LAST_WARNING_SENT_FILE)

    def _create_outage_datetime(self, base_date: datetime, minutes: int) -> datetime:
        """Create datetime from minutes since midnight, handling midnight boundary

        Args:
            base_date: The reference date to create time from
            minutes: Minutes since midnight (can be >= MINUTES_PER_DAY for next day)

        Returns:
            datetime with proper date adjustment for midnight boundary
        """
        hour = minutes // 60
        minute = minutes % 60

        if hour >= HOURS_PER_DAY:
            # Midnight boundary: move to next day
            return base_date.replace(hour=0, minute=minute, second=0, microsecond=0) + timedelta(days=1)
        else:
            return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _write_last_warning_sent(self, warning_id: str) -> None:
        """Write last warning identifier to file atomically"""
        try:
            atomic_write_text(LAST_WARNING_SENT_FILE, warning_id)
            logger.info(f"Last warning sent saved: {warning_id}")
        except Exception as e:
            logger.error(f"Error writing last warning file: {e}")
            raise

    def _is_continuous_outage(self, today_end_minutes: int, tomorrow_start_minutes: int) -> bool:
        """Check if today's outage ending at midnight continues into tomorrow's outage

        Args:
            today_end_minutes: End time of today's slot in minutes (e.g., 1440 for 24:00)
            tomorrow_start_minutes: Start time of tomorrow's slot in minutes (e.g., 0 for 00:00)

        Returns:
            True if outages are continuous across midnight (no gap between them)
        """
        # If today ends at midnight (24:00 = 1440) and tomorrow starts at midnight (00:00 = 0)
        # then it's one continuous outage with no gap
        return today_end_minutes >= MINUTES_PER_DAY and tomorrow_start_minutes == 0

    def _is_currently_in_outage(self, schedule_data: YasnoScheduleResponse) -> bool:
        """Check if we are currently in the middle of an outage

        Returns:
            True if current time falls within an active outage slot
        """
        try:
            now = datetime.now(TIMEZONE)
            current_minutes = now.hour * 60 + now.minute

            group_schedule = schedule_data.get_group(self.group)
            if not group_schedule:
                return False

            # Check today's schedule for current outage
            today_schedule = group_schedule.today
            outage_slots = self.formatter.get_outage_slots(today_schedule.slots)

            for slot in outage_slots:
                # Check if current time is within this outage slot
                if slot.start <= current_minutes < slot.end:
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking if currently in outage: {e}")
            return False

    def _find_next_outage(self, schedule_data: YasnoScheduleResponse) -> Optional[Tuple[datetime, datetime]]:
        """Find the next scheduled outage (start time, end time)

        Handles midnight boundary cases: slots ending at 24:00 (1440 minutes)
        are converted to 00:00 of the next day to avoid datetime errors.
        Also handles slots starting at or past midnight (>= 1440 minutes).

        Detects continuous outages across midnight: if today's outage ends at 24:00
        and tomorrow's starts at 00:00, treats them as one continuous outage.

        Returns:
            Tuple of (outage_start_datetime, outage_end_datetime) or None if no upcoming outage
        """
        try:
            now = datetime.now(TIMEZONE)
            current_minutes = now.hour * 60 + now.minute

            group_schedule = schedule_data.get_group(self.group)
            if not group_schedule:
                logger.warning(f"Group {self.group} not found in schedule")
                return None

            # Check today's schedule first
            today_schedule = group_schedule.today
            outage_slots = self.formatter.get_outage_slots(today_schedule.slots)

            for slot in outage_slots:
                if slot.start > current_minutes:
                    # Found upcoming outage today
                    start_time = self._create_outage_datetime(now, slot.start)

                    # Check if this outage continues into tomorrow
                    tomorrow_schedule = group_schedule.tomorrow
                    tomorrow_outage_slots = self.formatter.get_outage_slots(tomorrow_schedule.slots)

                    if (tomorrow_outage_slots and
                        self._is_continuous_outage(slot.end, tomorrow_outage_slots[0].start)):
                        # Continuous outage: use tomorrow's end time
                        tomorrow = now + timedelta(days=1)
                        end_time = self._create_outage_datetime(tomorrow, tomorrow_outage_slots[0].end)
                        logger.info(f"Detected continuous outage across midnight: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}")
                    else:
                        # Regular outage: use today's end time
                        end_time = self._create_outage_datetime(now, slot.end)

                    return (start_time, end_time)

            # Check tomorrow's schedule if no outage found today
            tomorrow_schedule = group_schedule.tomorrow
            tomorrow_outage_slots = self.formatter.get_outage_slots(tomorrow_schedule.slots)

            if tomorrow_outage_slots:
                # Get the first outage slot tomorrow
                slot = tomorrow_outage_slots[0]
                tomorrow = now + timedelta(days=1)
                start_time = self._create_outage_datetime(tomorrow, slot.start)
                end_time = self._create_outage_datetime(tomorrow, slot.end)
                return (start_time, end_time)

            return None

        except Exception as e:
            logger.error(f"Error finding next outage: {e}")
            return None

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
        """Fetch and send schedule to Telegram channel

        Uses cached schedule data when available to avoid redundant API calls.
        """
        try:
            logger.info(f"Fetching schedule (tomorrow={for_tomorrow})...")
            schedule_data = await self._get_cached_schedule()

            if not schedule_data:
                logger.error("Failed to get schedule data")
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

    async def send_outage_warning(self, outage_start: datetime, outage_end: datetime) -> bool:
        """Send warning about upcoming power outage"""
        try:
            message = self.formatter.format_outage_warning_message(
                outage_start,
                outage_end,
                self.group
            )

            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info(f"Warning sent for outage at {outage_start.strftime('%H:%M')}")
            return True

        except TelegramError as e:
            logger.error(f"Failed to send warning message: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending warning: {e}")
            return False

    async def check_outage_warnings(self) -> None:
        """Check if we need to send a warning about upcoming outage

        Uses cached schedule data to avoid redundant API calls.
        Cache is shared with the main schedule monitoring loop.
        """
        try:
            now = datetime.now(TIMEZONE)

            # Get schedule from cache (or fetch if needed)
            logger.debug("Checking for upcoming outages...")
            schedule_data = await self._get_cached_schedule()

            if not schedule_data:
                logger.error("Failed to get schedule data for warning check")
                return

            # Skip warning if we're currently in an outage
            if self._is_currently_in_outage(schedule_data):
                logger.debug("Currently in outage, skipping warning for next outage")
                return

            # Find next outage
            next_outage = self._find_next_outage(schedule_data)
            if not next_outage:
                logger.debug("No upcoming outages found")
                return

            outage_start, outage_end = next_outage

            # Check if we need to send warning
            time_until_outage = (outage_start - now).total_seconds() / 60  # minutes

            # Create unique warning ID (date + time to prevent duplicates)
            warning_id = outage_start.strftime('%Y-%m-%d-%H:%M')

            # Check if we should send warning
            if OUTAGE_WARNING_MINUTES - 5 <= time_until_outage <= OUTAGE_WARNING_MINUTES + 5:
                # Within warning window (±5 minutes tolerance)
                if self.last_warning_sent != warning_id:
                    logger.info(f"Sending warning for outage at {outage_start.strftime('%H:%M')} (in {int(time_until_outage)} minutes)")

                    if await self.send_outage_warning(outage_start, outage_end):
                        self.last_warning_sent = warning_id
                        self._write_last_warning_sent(warning_id)
                else:
                    logger.debug(f"Warning already sent for {warning_id}")
            else:
                logger.debug(f"Next outage at {outage_start.strftime('%H:%M')} (in {int(time_until_outage)} minutes) - outside warning window")

        except Exception as e:
            logger.error(f"Error checking outage warnings: {e}")

    async def outage_warning_loop(self):
        """Separate monitoring loop for outage warnings (runs every 5 minutes)"""
        logger.info(f"Starting outage warning monitoring (check interval: {OUTAGE_WARNING_CHECK_INTERVAL}s)")
        logger.info(f"Warning time: {OUTAGE_WARNING_MINUTES} minutes before outage")

        while self.monitoring:
            try:
                await self.check_outage_warnings()
                await asyncio.sleep(OUTAGE_WARNING_CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in outage warning loop (will retry): {e}")
                await asyncio.sleep(OUTAGE_WARNING_CHECK_INTERVAL)

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

            # Step 4: Invalidate schedule cache (new day = new data)
            self._invalidate_cache()

            logger.info("Midnight rollover completed successfully")
        except OSError:
            logger.critical("Critical error during midnight rollover - stopping monitoring")
            raise  # Re-raise to stop monitoring loop
        except Exception as e:
            logger.error(f"Unexpected error during midnight rollover: {e}")
            raise

    async def check_tomorrow_schedule(self) -> None:
        """Check if tomorrow's schedule is available and ready (not WaitingForSchedule)

        Uses cached schedule data to avoid redundant API calls.
        """
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
            schedule_data = await self._get_cached_schedule()

            if not schedule_data:
                logger.error("Failed to get schedule data")
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
        """Check if today's schedule has changed and notify if it has

        Uses cached schedule data to avoid redundant API calls.
        """
        try:
            current_hour = datetime.now(TIMEZONE).hour

            # Check if we're within the monitoring window
            if current_hour < SCHEDULE_TODAY_START_HOUR or current_hour > SCHEDULE_TODAY_END_HOUR:
                logger.debug(f"Outside today monitoring window (current: {current_hour}h, window: {SCHEDULE_TODAY_START_HOUR}-{SCHEDULE_TODAY_END_HOUR}h)")
                return

            logger.info("Checking for today's schedule changes...")
            schedule_data = await self._get_cached_schedule()

            if not schedule_data:
                logger.error("Failed to get schedule data")
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
                rollover_performed = False

                # Check if it's a new day - perform midnight rollover
                if self.last_check_date is not None and current_date != self.last_check_date:
                    logger.info(f"New day detected! {self.last_check_date} -> {current_date}")
                    try:
                        self._perform_midnight_rollover()
                        rollover_performed = True
                    except OSError as e:
                        logger.critical(f"Critical: Midnight rollover failed, stopping monitoring: {e}")
                        self.monitoring = False
                        raise

                # Skip schedule checks immediately after rollover to allow API to update
                if not rollover_performed:
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
                else:
                    logger.info("Skipping schedule checks immediately after rollover (allowing API to update)")

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
