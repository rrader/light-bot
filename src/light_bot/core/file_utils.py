"""
Atomic file operation utilities for safe persistent storage.

This module provides atomic file write operations that prevent data corruption
from crashes, disk full errors, or concurrent access issues.
"""
import os
import tempfile
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def atomic_write_text(file_path: str, content: str) -> None:
    """Write text content to file atomically.

    Uses the write-to-temp-then-rename pattern to ensure atomic updates:
    1. Write content to temporary file in same directory
    2. Flush and fsync to ensure data is written to disk
    3. Atomically rename temp file to target file

    This guarantees that:
    - No partial writes occur if process crashes
    - Readers never see incomplete data
    - Old file remains unchanged if operation fails

    Args:
        file_path: Target file path to write to
        content: Text content to write

    Raises:
        OSError: If file operations fail (permissions, disk full, etc.)
    """
    temp_path = None
    try:
        # Write to temporary file in same directory (ensures same filesystem)
        dir_name = os.path.dirname(file_path) or '.'
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=dir_name,
            delete=False,
            suffix='.tmp'
        ) as f:
            temp_path = f.name
            f.write(content)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk

        # Atomic rename (replaces old file if exists)
        os.replace(temp_path, file_path)
        logger.debug(f"Atomically wrote to {file_path}")

    except Exception as e:
        logger.error(f"Error writing to {file_path}: {e}")
        # Clean up temp file if it exists
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass  # Best effort cleanup
        raise


def read_text(file_path: str) -> Optional[str]:
    """Read text content from file.

    Args:
        file_path: Path to file to read

    Returns:
        File content as string, or None if file doesn't exist or read fails
    """
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return f.read().strip()
    except Exception as e:
        logger.error(f"Error reading {file_path}: {e}")
    return None


def safe_remove(file_path: str, critical: bool = True) -> None:
    """Safely remove a file with error handling.

    Args:
        file_path: Path to file to remove
        critical: If True, raises exception on failure. If False, logs warning.

    Raises:
        OSError: If critical=True and removal fails
    """
    if not os.path.exists(file_path):
        return

    try:
        os.remove(file_path)
        logger.debug(f"Removed file: {file_path}")
    except OSError as e:
        if critical:
            logger.error(f"Failed to remove {file_path}: {e}")
            raise
        else:
            logger.warning(f"Failed to remove {file_path}: {e}")


def safe_rename(src_path: str, dst_path: str) -> None:
    """Safely rename a file with error handling.

    Args:
        src_path: Source file path
        dst_path: Destination file path

    Raises:
        OSError: If rename operation fails
    """
    try:
        os.rename(src_path, dst_path)
        logger.debug(f"Renamed {src_path} -> {dst_path}")
    except OSError as e:
        logger.error(f"Failed to rename {src_path} to {dst_path}: {e}")
        raise
