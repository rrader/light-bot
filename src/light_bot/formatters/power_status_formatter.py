from datetime import datetime
from typing import Optional


class PowerStatusFormatter:
    """Format power status messages for Telegram notifications"""

    @staticmethod
    def format_power_on_message(timestamp: datetime, duration_text: Optional[str] = None) -> str:
        """
        Format message for when power comes back on

        Args:
            timestamp: Current timestamp when power came on
            duration_text: Formatted duration text (e.g., "2 години 15 хвилин")
        """
        kyiv_time = timestamp.strftime('%d.%m.%Y %H:%M:%S')

        message = (
            "⚡️ <b>Світло з'явилось!</b> ⚡️\n\n"
            "✅ Електропостачання відновлено\n"
            f"🕐 Час: {kyiv_time}\n"
        )

        if duration_text:
            message += f"⏱ Відключення тривало: <b>{duration_text}</b>\n"

        message += "\n🏠 Можна користуватись побутовими приладами"

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
            "❌ Електропостачання відсутнє\n"
            f"🕐 Час: {kyiv_time}\n"
        )

        if duration_text:
            message += f"⏱ Світло було: <b>{duration_text}</b>"

        return message
