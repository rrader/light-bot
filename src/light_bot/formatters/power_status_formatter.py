from datetime import datetime
from typing import Optional


class PowerStatusFormatter:
    """Format power status messages for Telegram notifications"""

    @staticmethod
    def format_power_on_message(
        timestamp: datetime,
        duration_text: Optional[str] = None,
        next_outage_start: Optional[str] = None,
        next_outage_end: Optional[str] = None,
        is_today: bool = True
    ) -> str:
        """
        Format message for when power comes back on

        Args:
            timestamp: Current timestamp when power came on
            duration_text: Formatted duration text (e.g., "2 години 15 хвилин")
            next_outage_start: Next outage start time (e.g., "14:00")
            next_outage_end: Next outage end time (e.g., "16:00")
            is_today: Whether the next outage is today or tomorrow
        """
        kyiv_time = timestamp.strftime('%d.%m.%Y %H:%M:%S')

        message = (
            "⚡️ <b>Світло з'явилось!</b> ⚡️\n\n"
            f"🕐 Час: {kyiv_time}\n"
        )

        if duration_text:
            message += f"⏱ Відключення тривало: <b>{duration_text}</b>\n"

        if next_outage_start and next_outage_end:
            day_text = "сьогодні" if is_today else "завтра"
            message += f"\n⚠️ Наступне відключення {day_text}: <b>{next_outage_start} - {next_outage_end}</b>"

        return message

    @staticmethod
    def format_power_off_message(timestamp: datetime, duration_text: Optional[str] = None) -> str:
        """
        Format message for when power goes out

        Args:
            timestamp: Current timestamp when power went out
            duration_text: Formatted duration text (e.g., "45 хвилин")
        """
        kyiv_time = timestamp.strftime('%d.%m.%Y %H:%M:%S')

        message = (
            "🔴 <b>Світло зникло</b> 🔴\n\n"
            f"🕐 Час: {kyiv_time}\n"
        )

        if duration_text:
            message += f"⏱ Світло було: <b>{duration_text}</b>"

        return message
