"""File migration utility for schedule state files

This module handles migration of old state files (without group suffix)
to new state files (with group suffix) when upgrading to multi-group support.
"""
import os
import logging
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from light_bot.models.group_config import GroupConfig

logger = logging.getLogger(__name__)


def _make_path(data_dir: str, filename: str) -> str:
    """Create file path with data directory

    Args:
        data_dir: Data directory path (e.g., ".", "./data")
        filename: Filename to prepend with data directory

    Returns:
        Full file path
    """
    if data_dir and data_dir != '.':
        return f"{data_dir}/{filename}"
    return filename


class FileMigrator:
    """Handles migration of state files from old format to new format

    Old format (single group): last_schedule_today_hash.txt
    New format (with suffix): last_schedule_today_hash_2_1.txt
    """

    # Old filenames (without group suffix)
    OLD_FILE_PATTERNS = [
        'last_schedule_today_hash.txt',
        'last_schedule_tomorrow_hash.txt',
        'last_schedule_today_data.json',
        'last_schedule_tomorrow_data.json',
        'last_check_date.txt',
        'tomorrow_sent_date.txt',
        'last_warning_sent.txt',
    ]

    @staticmethod
    def _get_group_suffix(group: str) -> str:
        """Convert group identifier to filename suffix

        Args:
            group: Group identifier (e.g., "2.1")

        Returns:
            Filename suffix (e.g., "2_1")
        """
        return group.replace('.', '_')

    @staticmethod
    def _get_new_filename(old_filename: str, group_suffix: str) -> str:
        """Generate new filename with group suffix

        Args:
            old_filename: Old filename without suffix (e.g., "last_schedule_today_hash.txt")
            group_suffix: Group suffix (e.g., "2_1")

        Returns:
            New filename with suffix (e.g., "last_schedule_today_hash_2_1.txt")
        """
        # Split filename and extension
        name, ext = os.path.splitext(old_filename)
        return f"{name}_{group_suffix}{ext}"

    @classmethod
    def migrate_files_for_group(cls, group: str, data_dir: str = '.') -> List[str]:
        """Migrate old state files to new format for a specific group

        This function:
        1. Checks if old files exist (without group suffix) in data directory
        2. Renames them to new format (with group suffix)
        3. Logs all migrations performed

        Args:
            group: Group identifier (e.g., "2.1")
            data_dir: Data directory path (default: current directory)

        Returns:
            List of migrated files (new filenames with full path)
        """
        group_suffix = cls._get_group_suffix(group)
        migrated_files = []

        for old_filename in cls.OLD_FILE_PATTERNS:
            # Build full paths (check both current dir and data dir)
            # First check current directory for old files (pre-migration location)
            old_file_current = old_filename
            # Then check data directory for old files
            old_file_data_dir = _make_path(data_dir, old_filename)
            # New file always goes to data directory
            new_file = _make_path(data_dir, cls._get_new_filename(old_filename, group_suffix))

            # Determine which old file exists
            old_file = None
            if os.path.exists(old_file_current):
                old_file = old_file_current
            elif os.path.exists(old_file_data_dir):
                old_file = old_file_data_dir

            if old_file:
                # Only migrate if new file doesn't exist (avoid overwriting)
                if not os.path.exists(new_file):
                    try:
                        os.rename(old_file, new_file)
                        logger.info(f"Migrated: {old_file} -> {new_file}")
                        migrated_files.append(new_file)
                    except OSError as e:
                        logger.error(f"Failed to migrate {old_file} to {new_file}: {e}")
                else:
                    logger.info(f"Skipping migration: {new_file} already exists")

        if migrated_files:
            logger.info(f"Migration complete for group {group}: {len(migrated_files)} files migrated")
        else:
            logger.debug(f"No files to migrate for group {group}")

        return migrated_files

    @classmethod
    def migrate_for_first_group(cls, group_configs: List['GroupConfig'], data_dir: str = '.') -> List[str]:
        """Migrate old state files to the first group in the list

        This is useful when upgrading from single-group to multi-group mode,
        where the first group should inherit the old state.

        Args:
            group_configs: List of GroupConfig objects
            data_dir: Data directory path (default: current directory)

        Returns:
            List of migrated files
        """
        if not group_configs:
            logger.warning("No groups provided for migration")
            return []

        first_config = group_configs[0]
        # Use the file_suffix from the config (e.g., "home", "kyiv_2_1")
        first_group_id = first_config.file_suffix
        logger.info(f"Migrating old state files to first group: {first_config.id} (file_suffix: {first_group_id}, data_dir: {data_dir})")
        return cls.migrate_files_for_group(first_group_id, data_dir)
