import logging
from typing import List, Dict
from telegram import Bot

from light_bot.api.yasno import YasnoScheduleResponse
from light_bot.formatters.schedule_formatter import ScheduleFormatter
from light_bot.models.group_config import GroupConfig
from light_bot.services.group_schedule_sender import GroupScheduleSender
from light_bot.services.file_migrator import FileMigrator
from light_bot.config import (
    SCHEDULE_TODAY_START_HOUR,
    SCHEDULE_TODAY_END_HOUR,
    SCHEDULE_TOMORROW_START_HOUR,
    SCHEDULE_TOMORROW_END_HOUR,
    OUTAGE_WARNING_MINUTES,
    OUTAGE_WARNING_CHECK_INTERVAL,
    DATA_DIR,
)

logger = logging.getLogger(__name__)


class MultiGroupScheduleManager:
    """Manages schedule monitoring for multiple Yasno power groups

    This class creates and coordinates GroupScheduleSender instances for multiple
    power groups. Each group:
    - Has its own set of state files (with group name suffix)
    - Can send notifications to a specific Telegram channel
    - Monitors schedules independently

    All groups share the same monitoring windows and warning configuration.
    """

    def __init__(
        self,
        bot: Bot,
        formatter: ScheduleFormatter,
        group_configs: List[GroupConfig],
        ai_explainer=None,
    ):
        """Initialize MultiGroupScheduleManager

        Args:
            bot: Telegram Bot instance
            formatter: ScheduleFormatter instance for message formatting
            group_configs: List of GroupConfig objects defining groups to monitor
            ai_explainer: Optional ScheduleChangeExplainer instance
        """
        self.bot = bot
        self.formatter = formatter
        self.group_configs = group_configs
        self.ai_explainer = ai_explainer

        # Migrate old state files to first group (for backward compatibility)
        # This ensures smooth upgrade from single-group to multi-group mode
        FileMigrator.migrate_for_first_group(group_configs, DATA_DIR)

        # Create GroupScheduleSender for each group
        self.group_senders: Dict[str, GroupScheduleSender] = {}

        # Helper to create file path with data directory
        def make_path(filename: str) -> str:
            return f"{DATA_DIR}/{filename}" if DATA_DIR != '.' else filename

        for config in group_configs:
            logger.info(f"Initializing schedule monitoring: {config}")

            # Get file suffix from config (already validated to be filename-safe)
            file_suffix = config.file_suffix

            self.group_senders[config.id] = GroupScheduleSender(
                bot=bot,
                channel_id=config.target_channel,
                group_config=config,
                formatter=formatter,
                # State files with config ID suffix in data directory
                today_hash_file=make_path(f"last_schedule_today_hash_{file_suffix}.txt"),
                tomorrow_hash_file=make_path(f"last_schedule_tomorrow_hash_{file_suffix}.txt"),
                today_data_file=make_path(f"last_schedule_today_data_{file_suffix}.json"),
                tomorrow_data_file=make_path(f"last_schedule_tomorrow_data_{file_suffix}.json"),
                last_check_date_file=make_path(f"last_check_date_{file_suffix}.txt"),
                tomorrow_sent_date_file=make_path(f"tomorrow_sent_date_{file_suffix}.txt"),
                last_warning_sent_file=make_path(f"last_warning_sent_{file_suffix}.txt"),
                # Shared configuration
                today_start_hour=SCHEDULE_TODAY_START_HOUR,
                today_end_hour=SCHEDULE_TODAY_END_HOUR,
                tomorrow_start_hour=SCHEDULE_TOMORROW_START_HOUR,
                tomorrow_end_hour=SCHEDULE_TOMORROW_END_HOUR,
                warning_minutes=OUTAGE_WARNING_MINUTES,
                warning_check_interval=OUTAGE_WARNING_CHECK_INTERVAL,
                ai_explainer=ai_explainer,
            )

        group_ids = [c.id for c in group_configs]
        logger.info(f"MultiGroupScheduleManager initialized with {len(self.group_senders)} groups: {', '.join(group_ids)}")

    async def check_today_schedules(self, schedule_data: YasnoScheduleResponse) -> None:
        """Check today's schedule for all groups

        Args:
            schedule_data: Schedule data from API (shared across all groups)
        """
        for group, sender in self.group_senders.items():
            try:
                await sender.check_today_schedule(schedule_data)
            except Exception as e:
                logger.error(f"Error checking today's schedule for group {group}: {e}")

    async def check_tomorrow_schedules(self, schedule_data: YasnoScheduleResponse) -> None:
        """Check tomorrow's schedule for all groups

        Args:
            schedule_data: Schedule data from API (shared across all groups)
        """
        for group, sender in self.group_senders.items():
            try:
                await sender.check_tomorrow_schedule(schedule_data)
            except Exception as e:
                logger.error(f"Error checking tomorrow's schedule for group {group}: {e}")

    async def check_outage_warnings(self, schedule_data: YasnoScheduleResponse) -> None:
        """Check for upcoming outage warnings for all groups

        Args:
            schedule_data: Schedule data from API (shared across all groups)
        """
        for group, sender in self.group_senders.items():
            try:
                await sender.check_outage_warnings(schedule_data)
            except Exception as e:
                logger.error(f"Error checking outage warnings for group {group}: {e}")

    def check_and_perform_rollover(self, current_date) -> bool:
        """Perform midnight rollover for all groups

        Args:
            current_date: Current date to check against

        Returns:
            True if any rollover was performed, False otherwise

        Raises:
            OSError: If critical rollover operations fail for any group
        """
        rollover_performed = False

        for group, sender in self.group_senders.items():
            try:
                if sender.check_and_perform_rollover(current_date):
                    rollover_performed = True
                    logger.info(f"Midnight rollover completed for group {group}")
            except OSError as e:
                logger.critical(f"Critical error during midnight rollover for group {group}: {e}")
                raise  # Re-raise to stop monitoring
            except Exception as e:
                logger.error(f"Unexpected error during rollover for group {group}: {e}")
                raise

        return rollover_performed

    def update_last_check_dates(self, current_date) -> None:
        """Update last check date for all groups

        Args:
            current_date: Current date to save
        """
        for group, sender in self.group_senders.items():
            try:
                sender.update_last_check_date(current_date)
            except Exception as e:
                logger.error(f"Error updating last check date for group {group}: {e}")

    def get_sender(self, group: str) -> GroupScheduleSender:
        """Get GroupScheduleSender for a specific group

        Args:
            group: Group identifier (e.g., "2.1")

        Returns:
            GroupScheduleSender instance for the group

        Raises:
            KeyError: If group is not being monitored
        """
        return self.group_senders[group]

    def resolve_dynamic_groups(self) -> bool:
        """Re-resolve all dynamic groups and detect changes
        
        This method re-resolves all GroupConfig instances that have group_dynamic set.
        Individual group changes are logged as they occur.
        
        Returns:
            True if any group changed, False otherwise
        """
        any_changed = False
        
        for config in self.group_configs:
            if config.group_dynamic:
                try:
                    _, changed = config.resolve_group()
                    if changed:
                        any_changed = True
                        logger.info(f"Group changed for '{config.id}': {config.group}")
                except Exception as e:
                    logger.error(f"Failed to re-resolve dynamic group for '{config.id}': {e}")
        
        return any_changed

    @property
    def group_count(self) -> int:
        """Get the number of groups being monitored"""
        return len(self.group_senders)
