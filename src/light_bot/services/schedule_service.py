import logging
import asyncio
import json
from datetime import datetime
from typing import Optional
from telegram import Bot

from light_bot.api.yasno import client as yasno_client, YasnoScheduleResponse
from light_bot.formatters.schedule_formatter import ScheduleFormatter
from light_bot.services.multi_group_schedule_manager import MultiGroupScheduleManager
from light_bot.services.stats_service import StatsService
from light_bot.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_SCHEDULE_CHANNEL_ID,
    TIMEZONE,
    YASNO_GROUP_CONFIGS,
    SCHEDULE_CHECK_INTERVAL,
    SCHEDULE_TODAY_START_HOUR,
    SCHEDULE_TODAY_END_HOUR,
    SCHEDULE_TOMORROW_START_HOUR,
    SCHEDULE_TOMORROW_END_HOUR,
    OUTAGE_WARNING_MINUTES,
    OUTAGE_WARNING_CHECK_INTERVAL,
    GROUP_RESOLUTION_INTERVAL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    ENABLE_AI_EXPLANATIONS,
)

logger = logging.getLogger(__name__)


class ScheduleService:
    """Service to monitor and send power outage schedule notifications

    This service coordinates schedule monitoring by:
    1. Managing a shared schedule data cache to avoid redundant API calls
    2. Creating and managing MultiGroupScheduleManager for one or more groups
    3. Running monitoring loops for schedule changes and outage warnings

    Supports monitoring single or multiple groups via YASNO_GROUPS configuration.
    """

    def __init__(self, stats_service: StatsService):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.formatter = ScheduleFormatter()
        self.monitoring = False
        self.stats_service = stats_service

        # Schedule data cache with thread safety
        self._cache_lock = asyncio.Lock()
        self._cached_schedule: Optional[YasnoScheduleResponse] = None
        self._cache_timestamp: Optional[datetime] = None

        # Group resolution tracking
        self._last_resolution_time: Optional[datetime] = None

        # Initialize AI explainer if enabled and API key is available
        self.ai_explainer = None
        if ENABLE_AI_EXPLANATIONS and OPENAI_API_KEY:
            try:
                from light_bot.ai.ai_explainer import ScheduleChangeExplainer
                self.ai_explainer = ScheduleChangeExplainer(OPENAI_API_KEY, OPENAI_MODEL)
                logger.info(f"AI explanations enabled (model: {OPENAI_MODEL})")
            except Exception as e:
                logger.warning(f"Failed to initialize AI explainer: {e}")
                self.ai_explainer = None
        else:
            logger.info("AI explanations disabled (no API key or disabled in config)")

        logger.info(f"Monitoring {len(YASNO_GROUP_CONFIGS)} group(s): {', '.join(str(c) for c in YASNO_GROUP_CONFIGS)}")
        self.multi_group_manager = MultiGroupScheduleManager(
            bot=self.bot,
            formatter=self.formatter,
            group_configs=YASNO_GROUP_CONFIGS,
            ai_explainer=self.ai_explainer,
            stats_service=self.stats_service,
        )

        # For backward compatibility, expose the first group sender
        self.group_sender = self.multi_group_manager.get_sender(YASNO_GROUP_CONFIGS[0].id)

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
                for group_config in YASNO_GROUP_CONFIGS:
                    if group_config.id == "home":
                        # Serialize schedule data to JSON
                        # YasnoScheduleResponse is not a Pydantic model, so we need to manually serialize
                        group_schedule = schedule_data.get_group(group_config.group)
                        if group_schedule:
                            # GroupSchedule is a Pydantic model, so we can use model_dump()
                            schedule_dict = group_schedule.model_dump(mode='json')
                            schedule_json = json.dumps(schedule_dict, default=str)
                        else:
                            schedule_json = json.dumps({"error": "group not found"})
                        
                        self.stats_service.record_schedule_history(
                            group_id=group_config.id,
                            schedule_text=schedule_json,
                            timestamp=now,
                        )
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

    # ========== Public API Methods (for backward compatibility and external API) ==========

    async def send_schedule(self, for_tomorrow: bool = False, change_detected: bool = False, change_explanation: Optional[str] = None) -> bool:
        """Fetch and send schedule to Telegram channel

        Args:
            for_tomorrow: Whether to send tomorrow's or today's schedule
            change_detected: Whether this is a schedule change notification
            change_explanation: Optional AI-generated explanation of changes
        """
        schedule_data = await self._get_cached_schedule()
        if not schedule_data:
            logger.error("Failed to get schedule data")
            return False
        return await self.group_sender.send_schedule(schedule_data, for_tomorrow, change_detected, change_explanation)

    # ========== Monitoring Loops ==========

    async def outage_warning_loop(self):
        """Separate monitoring loop for outage warnings (runs every N minutes)"""
        logger.info(f"Starting outage warning monitoring (check interval: {OUTAGE_WARNING_CHECK_INTERVAL}s)")
        logger.info(f"Warning time: {OUTAGE_WARNING_MINUTES} minutes before outage")

        while self.monitoring:
            try:
                schedule_data = await self._get_cached_schedule()
                if schedule_data:
                    await self.multi_group_manager.check_outage_warnings(schedule_data)
                await asyncio.sleep(OUTAGE_WARNING_CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in outage warning loop (will retry): {e}")
                await asyncio.sleep(OUTAGE_WARNING_CHECK_INTERVAL)

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
                try:
                    if self.multi_group_manager.check_and_perform_rollover(current_date):
                        rollover_performed = True
                        self._invalidate_cache()
                except OSError as e:
                    logger.critical(f"Critical: Midnight rollover failed, stopping monitoring: {e}")
                    self.monitoring = False
                    raise

                # Skip schedule checks immediately after rollover to allow API to update
                if not rollover_performed:
                    # Fetch schedule data once for both checks
                    schedule_data = await self._get_cached_schedule()

                    if schedule_data:
                        # Check all groups
                        try:
                            await self.multi_group_manager.check_today_schedules(schedule_data)
                        except Exception as e:
                            logger.error(f"Error checking today's schedules (will retry): {e}")

                        try:
                            await self.multi_group_manager.check_tomorrow_schedules(schedule_data)
                        except Exception as e:
                            logger.error(f"Error checking tomorrow's schedules (will retry): {e}")
                    else:
                        logger.error("Failed to get schedule data")
                else:
                    logger.info("Skipping schedule checks immediately after rollover (allowing API to update)")

                # Update the last check date
                self.multi_group_manager.update_last_check_dates(current_date)

                # Check if we need to re-resolve dynamic groups
                if GROUP_RESOLUTION_INTERVAL > 0:
                    now = datetime.now(TIMEZONE)
                    should_resolve = False
                    
                    if self._last_resolution_time is None:
                        # First time - resolve immediately
                        should_resolve = True
                    else:
                        # Check if interval has passed
                        time_since_resolution = (now - self._last_resolution_time).total_seconds()
                        if time_since_resolution >= GROUP_RESOLUTION_INTERVAL:
                            should_resolve = True
                    
                    if should_resolve:
                        logger.info("Re-resolving dynamic groups...")
                        try:
                            if self.multi_group_manager.resolve_dynamic_groups():
                                logger.info("Dynamic group changes detected")
                                # Invalidate cache to fetch fresh schedule for new groups
                                self._invalidate_cache()
                            else:
                                logger.debug("No dynamic group changes detected")
                            self._last_resolution_time = now
                        except Exception as e:
                            logger.error(f"Error re-resolving dynamic groups: {e}")

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
schedule_service: Optional[ScheduleService] = None

def get_schedule_service(stats_service: StatsService) -> ScheduleService:
    global schedule_service
    if schedule_service is None:
        schedule_service = ScheduleService(stats_service)
    return schedule_service
