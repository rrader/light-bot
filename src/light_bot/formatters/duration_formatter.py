from datetime import datetime, timedelta


class DurationFormatter:
    """Format time durations in Ukrainian"""

    @staticmethod
    def format_duration(duration: timedelta) -> str:
        """
        Format a timedelta into Ukrainian text representation

        Args:
            duration: timedelta object representing the duration

        Returns:
            Formatted string in Ukrainian (e.g., "2 години 15 хвилин", "3 дні 5 годин")
        """
        total_seconds = int(duration.total_seconds())

        if total_seconds < 60:
            seconds = total_seconds
            return DurationFormatter._pluralize_seconds(seconds)

        days = total_seconds // 86400
        remaining = total_seconds % 86400
        hours = remaining // 3600
        remaining = remaining % 3600
        minutes = remaining // 60

        parts = []

        if days > 0:
            parts.append(DurationFormatter._pluralize_days(days))

        if hours > 0:
            parts.append(DurationFormatter._pluralize_hours(hours))

        # Show minutes only if less than 24 hours total
        if days == 0 and minutes > 0:
            parts.append(DurationFormatter._pluralize_minutes(minutes))

        return " ".join(parts) if parts else "менше хвилини"

    @staticmethod
    def _pluralize_days(count: int) -> str:
        """Ukrainian pluralization for days"""
        if count % 10 == 1 and count % 100 != 11:
            return f"{count} день"
        elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
            return f"{count} дні"
        else:
            return f"{count} днів"

    @staticmethod
    def _pluralize_hours(count: int) -> str:
        """Ukrainian pluralization for hours"""
        if count % 10 == 1 and count % 100 != 11:
            return f"{count} година"
        elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
            return f"{count} години"
        else:
            return f"{count} годин"

    @staticmethod
    def _pluralize_minutes(count: int) -> str:
        """Ukrainian pluralization for minutes"""
        if count % 10 == 1 and count % 100 != 11:
            return f"{count} хвилина"
        elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
            return f"{count} хвилини"
        else:
            return f"{count} хвилин"

    @staticmethod
    def _pluralize_seconds(count: int) -> str:
        """Ukrainian pluralization for seconds"""
        if count % 10 == 1 and count % 100 != 11:
            return f"{count} секунда"
        elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
            return f"{count} секунди"
        else:
            return f"{count} секунд"
