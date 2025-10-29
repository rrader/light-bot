from datetime import datetime


class PowerStatusFormatter:
    """Format power status messages for Telegram notifications"""

    @staticmethod
    def format_power_on_message(timestamp: datetime) -> str:
        """Format message for when power comes back on"""
        kyiv_time = timestamp.strftime('%d.%m.%Y %H:%M:%S')
        return (
            "⚡️ <b>Світло з'явилось!</b> ⚡️\n\n"
            "✅ Електропостачання відновлено\n"
            f"🕐 Час: {kyiv_time}\n\n"
            "🏠 Можна користуватись побутовими приладами"
        )

    @staticmethod
    def format_power_off_message(timestamp: datetime) -> str:
        """Format message for when power goes out"""
        kyiv_time = timestamp.strftime('%d.%m.%Y %H:%M:%S')
        return (
            "🔴 <b>Світло зникло</b> 🔴\n\n"
            "❌ Електропостачання відсутнє\n"
            f"🕐 Час: {kyiv_time}"
        )
