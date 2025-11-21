import logging
import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Tuple
from telegram import Bot
from telegram.error import TelegramError

from light_bot.api.yasno import YasnoScheduleResponse
from light_bot.formatters.schedule_formatter import ScheduleFormatter
from light_bot.core.file_utils import atomic_write_text, read_text, safe_remove, safe_rename
from light_bot.config import TIMEZONE
from light_bot.core.schedule_tools import find_next_outage, get_outage_slots, is_currently_in_outage

logger = logging.getLogger(__name__)

# Time constants for midnight boundary handling
MINUTES_PER_DAY = 1440
HOURS_PER_DAY = 24


class GroupScheduleSender:
    """Handles schedule sending, change detection, warnings, and midnight rollover for a specific Yasno group

    This class encapsulates all logic related to:
    - Schedule hash computation and change detection
    - Midnight rollover (file rotation: yesterday → today → tomorrow)
    - Outage warnings (30-minute advance notifications)
    - State persistence (hash files, data files, date tracking)
    - AI explanations for schedule changes
    - Schedule formatting and Telegram messaging

    Each instance manages its own state files passed as parameters, allowing
    multiple instances to track different groups independently.
    """

    def __init__(
        self,
        bot: Bot,
        channel_id: str | int,
        group: str,
        city: str,
        formatter: ScheduleFormatter,
        # State file paths
        today_hash_file: str,
        tomorrow_hash_file: str,
        today_data_file: str,
        tomorrow_data_file: str,
        last_check_date_file: str,
        tomorrow_sent_date_file: str,
        last_warning_sent_file: str,
        # Time windows
        today_start_hour: int,
        today_end_hour: int,
        tomorrow_start_hour: int,
        tomorrow_end_hour: int,
        # Warning configuration
        warning_minutes: int,
        warning_check_interval: int,
        # Optional AI explainer
        ai_explainer=None,
    ):
        """Initialize GroupScheduleSender

        Args:
            bot: Telegram Bot instance for sending messages
            channel_id: Telegram channel ID to send messages to (str like "@channel" or int like -123456)
            group: Yasno power group (e.g., "2.1")
            city: City name (e.g., "kiev", "lviv")
            formatter: ScheduleFormatter instance for message formatting
            today_hash_file: Path to file storing today's schedule hash
            tomorrow_hash_file: Path to file storing tomorrow's schedule hash
            today_data_file: Path to file storing today's schedule data (JSON)
            tomorrow_data_file: Path to file storing tomorrow's schedule data (JSON)
            last_check_date_file: Path to file storing last check date
            tomorrow_sent_date_file: Path to file storing date when tomorrow's schedule was sent
            last_warning_sent_file: Path to file storing last warning identifier
            today_start_hour: Start hour for today's schedule monitoring window
            today_end_hour: End hour for today's schedule monitoring window
            tomorrow_start_hour: Start hour for tomorrow's schedule monitoring window
            tomorrow_end_hour: End hour for tomorrow's schedule monitoring window
            warning_minutes: Minutes before outage to send warning
            warning_check_interval: Interval between warning checks in seconds
            ai_explainer: Optional ScheduleChangeExplainer instance for AI explanations
        """
        self.bot = bot
        self.channel_id = channel_id
        self.group = group
        self.city = city
        self.formatter = formatter

        # State file paths
        self.today_hash_file = today_hash_file
        self.tomorrow_hash_file = tomorrow_hash_file
        self.today_data_file = today_data_file
        self.tomorrow_data_file = tomorrow_data_file
        self.last_check_date_file = last_check_date_file
        self.tomorrow_sent_date_file = tomorrow_sent_date_file
        self.last_warning_sent_file = last_warning_sent_file

        # Time windows
        self.today_start_hour = today_start_hour
        self.today_end_hour = today_end_hour
        self.tomorrow_start_hour = tomorrow_start_hour
        self.tomorrow_end_hour = tomorrow_end_hour

        # Warning configuration
        self.warning_minutes = warning_minutes
        self.warning_check_interval = warning_check_interval

        # AI explainer
        self.ai_explainer = ai_explainer

        # Load state from files
        self.last_today_hash = self._read_hash_file(self.today_hash_file)
        self.last_tomorrow_hash = self._read_hash_file(self.tomorrow_hash_file)
        self.last_check_date = self._read_last_check_date()
        self.tomorrow_sent_date = self._read_tomorrow_sent_date()
        self.last_warning_sent = self._read_last_warning_sent()

    # ========== File I/O Methods ==========

    def _read_hash_file(self, file_path: str) -> Optional[str]:
        """Read schedule hash from file"""
        return read_text(file_path)

    def _write_hash_file(self, file_path: str, hash_value: str) -> None:
        """Write schedule hash to file atomically"""
        try:
            atomic_write_text(file_path, hash_value)
            logger.info(f"[{self.group}] Hash saved to {file_path}: {hash_value[:8]}...")
        except Exception as e:
            logger.error(f"[{self.group}] Error writing hash file {file_path}: {e}")
            raise

    def _read_schedule_data_file(self, file_path: str) -> Optional[dict]:
        """Read schedule data from JSON file

        Returns:
            Dict with schedule data or None if file doesn't exist or is invalid
        """
        try:
            data_str = read_text(file_path)
            if data_str:
                return json.loads(data_str)
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[{self.group}] Error parsing schedule data from {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"[{self.group}] Error reading schedule data file {file_path}: {e}")
            return None

    def _write_schedule_data_file(self, file_path: str, schedule_data: dict) -> None:
        """Write schedule data to JSON file atomically

        Args:
            file_path: Path to the JSON file
            schedule_data: Dict containing schedule information (status, date, slots)
        """
        try:
            json_str = json.dumps(schedule_data, indent=2, default=str)
            atomic_write_text(file_path, json_str)
            logger.info(f"[{self.group}] Schedule data saved to {file_path}")
        except Exception as e:
            logger.error(f"[{self.group}] Error writing schedule data file {file_path}: {e}")
            raise

    def _read_last_check_date(self) -> Optional[datetime]:
        """Read last check date from file"""
        try:
            date_str = read_text(self.last_check_date_file)
            if date_str:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception as e:
            logger.error(f"[{self.group}] Error parsing last check date: {e}")
        return None

    def _write_last_check_date(self, date_value: datetime) -> None:
        """Write last check date to file atomically"""
        try:
            atomic_write_text(self.last_check_date_file, date_value.strftime('%Y-%m-%d'))
            logger.debug(f"[{self.group}] Last check date saved: {date_value}")
        except Exception as e:
            logger.error(f"[{self.group}] Error writing last check date file: {e}")
            raise

    def _read_tomorrow_sent_date(self) -> Optional[datetime]:
        """Read tomorrow sent date from file"""
        try:
            date_str = read_text(self.tomorrow_sent_date_file)
            if date_str:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception as e:
            logger.error(f"[{self.group}] Error parsing tomorrow sent date: {e}")
        return None

    def _write_tomorrow_sent_date(self, date_value: datetime) -> None:
        """Write tomorrow sent date to file atomically"""
        try:
            atomic_write_text(self.tomorrow_sent_date_file, date_value.strftime('%Y-%m-%d'))
            logger.info(f"[{self.group}] Tomorrow sent date saved: {date_value}")
        except Exception as e:
            logger.error(f"[{self.group}] Error writing tomorrow sent date file: {e}")
            raise

    def _read_last_warning_sent(self) -> Optional[str]:
        """Read last warning identifier from file"""
        return read_text(self.last_warning_sent_file)

    def _write_last_warning_sent(self, warning_id: str) -> None:
        """Write last warning identifier to file atomically"""
        try:
            atomic_write_text(self.last_warning_sent_file, warning_id)
            logger.info(f"[{self.group}] Last warning sent saved: {warning_id}")
        except Exception as e:
            logger.error(f"[{self.group}] Error writing last warning file: {e}")
            raise

    # ========== Schedule Hash and Data Methods ==========

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
            logger.error(f"[{self.group}] Error computing schedule hash: {e}")
            return None

    def _serialize_day_schedule(self, schedule_data: YasnoScheduleResponse, for_tomorrow: bool = False) -> Optional[dict]:
        """Serialize DaySchedule to dict for JSON storage

        Args:
            schedule_data: Full schedule response from API
            for_tomorrow: Whether to serialize tomorrow's or today's schedule

        Returns:
            Dict with schedule data or None if not available
        """
        try:
            if not schedule_data:
                return None

            group_schedule = schedule_data.get_group(self.group)
            if not group_schedule:
                return None

            day_schedule = group_schedule.tomorrow if for_tomorrow else group_schedule.today

            return {
                "date": day_schedule.date.isoformat(),
                "status": day_schedule.status.value if hasattr(day_schedule.status, 'value') else str(day_schedule.status),
                "slots": [
                    {
                        "start": slot.start,
                        "end": slot.end,
                        "type": slot.type.value if hasattr(slot.type, 'value') else str(slot.type)
                    }
                    for slot in day_schedule.slots
                ]
            }
        except Exception as e:
            logger.error(f"[{self.group}] Error serializing schedule data: {e}")
            return None

    def _has_meaningful_changes(self, old_schedule_dict: dict, new_schedule_dict: dict, current_time_minutes: int) -> bool:
        """Check if schedule changes affect future or current time slots

        Args:
            old_schedule_dict: Previous schedule data (from JSON file)
            new_schedule_dict: New schedule data (from API)
            current_time_minutes: Current time in minutes since midnight (0-1439)

        Returns:
            True if there are changes in future/current slots or status changed,
            False if only past slots changed
        """
        try:
            # Status change is always meaningful (e.g., EmergencyShutdowns)
            old_status = old_schedule_dict.get('status')
            new_status = new_schedule_dict.get('status')
            if old_status != new_status:
                logger.info(f"[{self.group}] Status changed from {old_status} to {new_status} - meaningful change")
                return True

            old_slots = old_schedule_dict.get('slots', [])
            new_slots = new_schedule_dict.get('slots', [])

            # Filter to only future/current slots (slots that haven't ended yet)
            def is_future_or_current(slot: dict) -> bool:
                return slot.get('end', 0) > current_time_minutes

            old_future_slots = [s for s in old_slots if is_future_or_current(s)]
            new_future_slots = [s for s in new_slots if is_future_or_current(s)]

            # Convert to comparable format (sorted tuples)
            def slot_to_tuple(slot: dict) -> tuple:
                return (slot.get('start'), slot.get('end'), slot.get('type'))

            old_future_set = set(slot_to_tuple(s) for s in old_future_slots)
            new_future_set = set(slot_to_tuple(s) for s in new_future_slots)

            # Check if future slots differ
            if old_future_set != new_future_set:
                logger.info(f"[{self.group}] Future/current slots changed - meaningful change")
                logger.debug(f"Old future slots: {old_future_set}")
                logger.debug(f"New future slots: {new_future_set}")
                return True

            logger.info(f"[{self.group}] Changes only in past slots - not meaningful")
            return False

        except Exception as e:
            logger.error(f"[{self.group}] Error checking meaningful changes: {e}")
            # On error, default to meaningful (safer to notify)
            return True

    # ========== Midnight Rollover ==========

    def perform_midnight_rollover(self) -> None:
        """Perform midnight rollover: delete today's files, promote tomorrow's files to today's

        This method performs atomic file operations to ensure consistency.
        If any critical operation fails, an exception is raised to prevent
        inconsistent state.

        Raises:
            OSError: If critical file operations fail
        """
        try:
            # Step 1: Delete today's hash and data files (yesterday is gone)
            safe_remove(self.today_hash_file, critical=True)
            logger.info(f"[{self.group}] Deleted today's hash file (yesterday)")
            safe_remove(self.today_data_file, critical=True)
            logger.info(f"[{self.group}] Deleted today's data file (yesterday)")

            # Step 2: Promote tomorrow's hash to today's hash
            if os.path.exists(self.tomorrow_hash_file):
                safe_rename(self.tomorrow_hash_file, self.today_hash_file)
                logger.info(f"[{self.group}] Promoted tomorrow's hash to today's hash")

                # Update in-memory reference ONLY after successful file operation
                self.last_today_hash = self._read_hash_file(self.today_hash_file)
                self.last_tomorrow_hash = None
            else:
                logger.info(f"[{self.group}] No tomorrow hash to promote")
                self.last_today_hash = None
                self.last_tomorrow_hash = None

            # Step 3: Promote tomorrow's data to today's data
            if os.path.exists(self.tomorrow_data_file):
                safe_rename(self.tomorrow_data_file, self.today_data_file)
                logger.info(f"[{self.group}] Promoted tomorrow's data to today's data")
            else:
                logger.info(f"[{self.group}] No tomorrow data to promote")

            # Step 4: Clear tomorrow_sent_date (ready to send new tomorrow)
            safe_remove(self.tomorrow_sent_date_file, critical=False)
            logger.info(f"[{self.group}] Cleared tomorrow sent date")
            self.tomorrow_sent_date = None

            logger.info(f"[{self.group}] Midnight rollover completed successfully")
        except OSError:
            logger.critical(f"[{self.group}] Critical error during midnight rollover")
            raise
        except Exception as e:
            logger.error(f"[{self.group}] Unexpected error during midnight rollover: {e}")
            raise

    def check_and_perform_rollover(self, current_date: datetime) -> bool:
        """Check if midnight rollover is needed and perform it

        Args:
            current_date: Current date to compare against last check date

        Returns:
            True if rollover was performed, False otherwise

        Raises:
            OSError: If critical rollover operations fail
        """
        if self.last_check_date is not None and current_date != self.last_check_date:
            logger.info(f"[{self.group}] New day detected! {self.last_check_date} -> {current_date}")
            self.perform_midnight_rollover()
            return True
        return False

    # ========== Schedule Sending ==========

    async def send_schedule(
        self,
        schedule_data: YasnoScheduleResponse,
        for_tomorrow: bool = False,
        change_detected: bool = False,
        change_explanation: Optional[str] = None
    ) -> bool:
        """Send schedule to Telegram channel

        Args:
            schedule_data: Schedule data from API
            for_tomorrow: Whether to send tomorrow's or today's schedule
            change_detected: Whether this is a schedule change notification
            change_explanation: Optional AI-generated explanation of changes
        """
        try:
            group_schedule = schedule_data.get_group(self.group)
            if group_schedule:
                day_schedule = group_schedule.tomorrow if for_tomorrow else group_schedule.today
                outage_slots = get_outage_slots(day_schedule.slots)
                logger.info(f"[{self.group}] Schedule: {len(outage_slots)} outage slots")
                logger.info(f"[{self.group}] Date: {day_schedule.date}, Status: {day_schedule.status}")
            else:
                logger.warning(f"[{self.group}] Group not found in API response")

            message = self.formatter.format_schedule_message(
                schedule_data,
                self.group,
                city=self.city,
                for_tomorrow=for_tomorrow,
                change_detected=change_detected,
                change_explanation=change_explanation
            )

            logger.info(f"[{self.group}] Formatted message:\n{message}")

            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info(f"[{self.group}] Schedule message sent successfully")
            return True

        except TelegramError as e:
            logger.error(f"[{self.group}] Failed to send schedule message: {e}")
            return False
        except Exception as e:
            logger.error(f"[{self.group}] Error sending schedule: {e}")
            return False

    # ========== Today's Schedule Monitoring ==========

    async def check_today_schedule(self, schedule_data: YasnoScheduleResponse) -> None:
        """Check if today's schedule has changed and notify if it has

        Args:
            schedule_data: Schedule data from API (should be pre-fetched/cached)
        """
        try:
            current_hour = datetime.now(TIMEZONE).hour

            # Check if we're within the monitoring window
            if current_hour < self.today_start_hour or current_hour > self.today_end_hour:
                logger.debug(f"[{self.group}] Outside today monitoring window (current: {current_hour}h, window: {self.today_start_hour}-{self.today_end_hour}h)")
                return

            logger.info(f"[{self.group}] Checking for today's schedule changes...")

            current_hash = self._compute_schedule_hash(schedule_data, for_tomorrow=False)
            if not current_hash:
                logger.warning(f"[{self.group}] Could not compute today's schedule hash")
                return

            # Serialize current schedule data
            schedule_dict = self._serialize_day_schedule(schedule_data, for_tomorrow=False)
            if not schedule_dict:
                logger.warning(f"[{self.group}] Failed to serialize today's schedule data")

            # Compare with last known hash
            if not self.last_today_hash:
                # No hash file exists - send today's schedule (morning case)
                logger.info(f"[{self.group}] No today hash found - sending today's schedule")
                await self.send_schedule(schedule_data, for_tomorrow=False, change_detected=False)
                # Write data file first, then hash file
                if schedule_dict:
                    self._write_schedule_data_file(self.today_data_file, schedule_dict)
                self.last_today_hash = current_hash
                self._write_hash_file(self.today_hash_file, current_hash)
            elif current_hash != self.last_today_hash:
                logger.info(f"[{self.group}] Today's schedule changed! Old: {self.last_today_hash[:8]}, New: {current_hash[:8]}")

                # Check if changes are meaningful
                should_notify = True
                old_schedule_dict = self._read_schedule_data_file(self.today_data_file)

                if old_schedule_dict and schedule_dict:
                    now = datetime.now(TIMEZONE)
                    current_minutes = now.hour * 60 + now.minute
                    is_meaningful = self._has_meaningful_changes(old_schedule_dict, schedule_dict, current_minutes)
                else:
                    logger.info(f"[{self.group}] No old schedule data available - will notify")

                # Send notification only if changes are meaningful
                if is_meaningful:
                    # Generate explanation if available
                    ai_explanation = None
                    if self.ai_explainer and old_schedule_dict:
                        if old_schedule_dict.get("status") == "EmergencyShutdowns" and schedule_dict.get("status") != "EmergencyShutdowns":
                            ai_explanation = "Екстренні відключення були скасовані"
                        else:
                            try:
                                now = datetime.now(TIMEZONE)
                                current_minutes = now.hour * 60 + now.minute
                                ai_explanation = await self.ai_explainer.explain_schedule_change(
                                    old_schedule_dict,
                                    schedule_dict,
                                    current_minutes
                                )
                            except Exception as e:
                                logger.warning(f"[{self.group}] Failed to generate AI explanation: {e}")
                else:
                    ai_explanation = "¯\_(ツ)_/¯ змінили час минулих відключень, тому зміни не впливають на графік"

                await self.send_schedule(schedule_data, for_tomorrow=False, change_detected=True, change_explanation=ai_explanation)

                # ALWAYS update stored schedule data and hash
                if schedule_dict:
                    self._write_schedule_data_file(self.today_data_file, schedule_dict)
                self.last_today_hash = current_hash
                self._write_hash_file(self.today_hash_file, current_hash)
            else:
                logger.debug(f"[{self.group}] Today's schedule unchanged")

        except Exception as e:
            logger.error(f"[{self.group}] Error checking today's schedule: {e}")

    # ========== Tomorrow's Schedule Monitoring ==========

    async def check_tomorrow_schedule(self, schedule_data: YasnoScheduleResponse) -> None:
        """Check if tomorrow's schedule is ready and send it

        Args:
            schedule_data: Schedule data from API (should be pre-fetched/cached)
        """
        try:
            current_date = datetime.now(TIMEZONE).date()
            current_hour = datetime.now(TIMEZONE).hour

            # Check if we're within the monitoring window
            if current_hour < self.tomorrow_start_hour or current_hour > self.tomorrow_end_hour:
                logger.debug(f"[{self.group}] Outside tomorrow monitoring window (current: {current_hour}h, window: {self.tomorrow_start_hour}-{self.tomorrow_end_hour}h)")
                return

            # Check if we already sent tomorrow's schedule today
            if self.tomorrow_sent_date == current_date:
                logger.debug(f"[{self.group}] Tomorrow's schedule already sent today")
                return

            logger.info(f"[{self.group}] Checking if tomorrow's schedule is ready...")

            group_schedule = schedule_data.get_group(self.group)
            if not group_schedule:
                logger.warning(f"[{self.group}] Group not found in schedule")
                return

            tomorrow_schedule = group_schedule.tomorrow
            tomorrow_hash = self._compute_schedule_hash(schedule_data, for_tomorrow=True)

            if not tomorrow_hash:
                logger.warning(f"[{self.group}] Could not compute tomorrow's schedule hash")
                return

            # Check if schedule has changed (or is new)
            if self.last_tomorrow_hash and tomorrow_hash == self.last_tomorrow_hash:
                logger.debug(f"[{self.group}] Tomorrow's schedule unchanged")
                return

            # Serialize tomorrow's schedule data
            schedule_dict = self._serialize_day_schedule(schedule_data, for_tomorrow=True)
            if not schedule_dict:
                logger.warning(f"[{self.group}] Failed to serialize tomorrow's schedule data")

            # Check if tomorrow's schedule is confirmed (not waiting)
            if tomorrow_schedule.status != "WaitingForSchedule":
                logger.info(f"[{self.group}] Tomorrow's schedule is ready! Status: {tomorrow_schedule.status}")

                # Check if this is a change (not first time)
                change_detected = self.last_tomorrow_hash is not None and self.last_tomorrow_hash != tomorrow_hash

                # Generate AI explanation if this is a change
                ai_explanation = None
                if change_detected and self.ai_explainer and schedule_dict:
                    old_schedule_dict = self._read_schedule_data_file(self.tomorrow_data_file)
                    if old_schedule_dict:
                        if old_schedule_dict.get("status") == "EmergencyShutdowns" and schedule_dict.get("status") != "EmergencyShutdowns":
                            ai_explanation = "Екстренні відключення були скасовані"
                        else:
                            try:
                                # For tomorrow's schedule, don't pass current_time_minutes
                                ai_explanation = await self.ai_explainer.explain_schedule_change(
                                    old_schedule_dict,
                                    schedule_dict,
                                    current_time_minutes=None
                                )
                            except Exception as e:
                                logger.warning(f"[{self.group}] Failed to generate AI explanation for tomorrow: {e}")
                                ai_explanation = None

                # Send tomorrow's schedule
                await self.send_schedule(schedule_data, for_tomorrow=True, change_detected=change_detected, change_explanation=ai_explanation)

                # Save tomorrow's schedule data and hash
                if schedule_dict:
                    self._write_schedule_data_file(self.tomorrow_data_file, schedule_dict)
                self.last_tomorrow_hash = tomorrow_hash
                self._write_hash_file(self.tomorrow_hash_file, tomorrow_hash)
                logger.info(f"[{self.group}] Saved tomorrow's hash: {tomorrow_hash[:8]}...")

                # Mark that we sent tomorrow's schedule today
                self.tomorrow_sent_date = current_date
                self._write_tomorrow_sent_date(current_date)
                logger.info(f"[{self.group}] Tomorrow's schedule sent and marked for date: {current_date}")
            else:
                logger.debug(f"[{self.group}] Tomorrow's schedule not ready yet (status: {tomorrow_schedule.status})")

        except Exception as e:
            logger.error(f"[{self.group}] Error checking tomorrow's schedule: {e}")

    # ========== Outage Warning Methods ==========



    async def send_outage_warning(self, outage_start: datetime, outage_end: datetime) -> bool:
        """Send warning about upcoming power outage"""
        try:
            message = self.formatter.format_outage_warning_message(
                outage_start,
                outage_end,
                self.group,
                self.city
            )

            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info(f"[{self.group}] Warning sent for outage at {outage_start.strftime('%H:%M')}")
            return True

        except TelegramError as e:
            logger.error(f"[{self.group}] Failed to send warning message: {e}")
            return False
        except Exception as e:
            logger.error(f"[{self.group}] Error sending warning: {e}")
            return False

    async def check_outage_warnings(self, schedule_data: YasnoScheduleResponse) -> None:
        """Check if we need to send a warning about upcoming outage

        Args:
            schedule_data: Schedule data from API (should be pre-fetched/cached)
        """
        try:
            now = datetime.now(TIMEZONE)

            logger.debug(f"[{self.group}] Checking for upcoming outages...")

            # Skip warning if we're currently in an outage
            if is_currently_in_outage(schedule_data, self.group):
                logger.debug(f"[{self.group}] Currently in outage, skipping warning for next outage")
                return

            # Find next outage
            next_outage = find_next_outage(schedule_data, self.group)
            if not next_outage:
                logger.debug(f"[{self.group}] No upcoming outages found")
                return

            outage_start, outage_end = next_outage

            # Check if we need to send warning
            time_until_outage = (outage_start - now).total_seconds() / 60  # minutes

            # Create unique warning ID
            warning_id = outage_start.strftime('%Y-%m-%d-%H:%M')

            # Check if we should send warning
            if self.warning_minutes - 5 <= time_until_outage <= self.warning_minutes + 5:
                # Within warning window (±5 minutes tolerance)
                if self.last_warning_sent != warning_id:
                    logger.info(f"[{self.group}] Sending warning for outage at {outage_start.strftime('%H:%M')} (in {int(time_until_outage)} minutes)")

                    if await self.send_outage_warning(outage_start, outage_end):
                        self.last_warning_sent = warning_id
                        self._write_last_warning_sent(warning_id)
                else:
                    logger.debug(f"[{self.group}] Warning already sent for {warning_id}")
            else:
                logger.debug(f"[{self.group}] Next outage at {outage_start.strftime('%H:%M')} (in {int(time_until_outage)} minutes) - outside warning window")

        except Exception as e:
            logger.error(f"[{self.group}] Error checking outage warnings: {e}")

    # ========== Date Tracking ==========

    def update_last_check_date(self, current_date: datetime) -> None:
        """Update the last check date

        Args:
            current_date: Current date to save
        """
        self.last_check_date = current_date
        self._write_last_check_date(current_date)
