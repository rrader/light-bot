from datetime import datetime, timedelta
from typing import List, Optional

from light_bot.api.yasno import YasnoScheduleResponse, PowerSlot, SlotType
from light_bot.config import TIMEZONE
from light_bot.core.schedule_tools import get_outage_slots


class ScheduleFormatter:
    """Format Yasno power outage schedules for Telegram messages"""

    @staticmethod
    def minutes_to_time(minutes: int) -> str:
        """Convert minutes from midnight to HH:MM format"""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"

    @staticmethod
    def format_outage_slots(slots: List[PowerSlot]) -> str:
        """Format outage slots into readable time ranges"""
        outage_slots = get_outage_slots(slots)

        if not outage_slots:
            return "✅ Відключень немає"

        formatted = []
        for slot in outage_slots:
            start_str = ScheduleFormatter.minutes_to_time(slot.start)
            end_str = ScheduleFormatter.minutes_to_time(slot.end)
            formatted.append(f"⚡️ {start_str} - {end_str}")

        return "\n".join(formatted)

    @staticmethod
    def _format_city_name(city: str) -> str:
        """Format city name for display in Ukrainian

        Args:
            city: City name in English (e.g., "kiev", "dnipro")

        Returns:
            City name in Ukrainian (e.g., "Київ", "Дніпро")
        """
        city_map = {
            "kiev": "Київ",
            "kyiv": "Київ",
            "dnipro": "Дніпро",
        }
        return city_map.get(city.lower(), city.capitalize())

    @staticmethod
    def format_schedule_message(
        schedule_data: YasnoScheduleResponse,
        group: str,
        city: str = "kiev",
        for_tomorrow: bool = False,
        change_detected: bool = False,
        change_explanation: Optional[str] = None
    ) -> str:
        """Format complete schedule message for Telegram

        Args:
            schedule_data: Schedule data from API
            group: Power group number
            city: City name (e.g., "kiev", "lviv")
            for_tomorrow: Whether this is tomorrow's schedule
            change_detected: Whether this is a change notification
            change_explanation: Optional AI-generated explanation of changes
        """
        if not schedule_data:
            return "❌ Графік відключень наразі недоступний"

        # Determine day context
        day_word = "завтра" if for_tomorrow else "сьогодні"

        group_schedule = schedule_data.get_group(group)
        if not group_schedule:
            return f"❌ Група {group} не знайдена в графіку"

        day_schedule = group_schedule.tomorrow if for_tomorrow else group_schedule.today

        date_str = day_schedule.date.strftime('%d.%m.%Y')
        weekday_names = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця", 'Субота', 'Неділя']
        weekday = weekday_names[day_schedule.date.weekday()]

        # Format city name
        city_name = ScheduleFormatter._format_city_name(city)

        # Handle emergency shutdowns
        if day_schedule.status == "EmergencyShutdowns":
            message = (
                f"🚨 <b>ЕКСТРЕНІ ВІДКЛЮЧЕННЯ</b> 🚨\n\n"
                f"🏠 Група: <b>{group}</b> ({city_name})\n"
                f"📅 {weekday}, {date_str}\n\n"
                f"⚠️ <b>Графіки не застосовуються</b>\n\n"
                f"🕐 Оновлено: {datetime.now(TIMEZONE).strftime('%H:%M:%S')}\n\n"
                f"🤖 @power_po2"
            )
            return message

        outages_text = ScheduleFormatter.format_outage_slots(day_schedule.slots)

        status_msg = ""
        if day_schedule.status == "WaitingForSchedule":
            status_msg = "⏳ Очікування підтвердження графіку\n\n"

        # Set emoji and title based on change status
        if change_detected:
            emoji = "🔔"
            # Add AI explanation inline after colon if available
            if change_explanation:
                # Ensure first letter (after any emojis/spaces) starts with lowercase
                # Find the first alphabetic character and lowercase it
                explanation_text = ""
                first_letter_found = False
                for i, char in enumerate(change_explanation):
                    if not first_letter_found and char.isalpha():
                        explanation_text += char.lower()
                        first_letter_found = True
                    else:
                        explanation_text += char

                title = f"Графік на <b>{day_word}</b> змінився: {explanation_text}"
            else:
                title = f"Графік на <b>{day_word}</b> змінився"
        else:
            emoji = "🌙" if for_tomorrow else "☀️"
            title = f"Графік відключень на <b>{day_word}</b>"

        message = (
            f"{emoji} <b>{title}</b>\n\n"
            f"🏠 Група: <b>{group}</b> ({city_name})\n"
            f"📅 {weekday}, {date_str}\n\n"
            f"{status_msg}"
            f"<b>Планові відключення:</b>\n"
            f"{outages_text}\n\n"
            f"🕐 Оновлено: {datetime.now(TIMEZONE).strftime('%H:%M:%S')}\n\n"
            f"🤖 @power_po2"
        )

        return message

    @staticmethod
    def format_outage_warning_message(
        outage_start: datetime,
        outage_end: datetime,
        group: str,
        city: str = "kiev"
    ) -> str:
        """Format outage warning message for Telegram"""
        start_str = outage_start.strftime('%H:%M')
        end_str = outage_end.strftime('%H:%M')
        city_name = ScheduleFormatter._format_city_name(city)

        # Always show "30 minutes" for consistency (warning is sent at 30±5 min window)
        now = datetime.now(TIMEZONE)

        message = (
            f"⚠️ <b>Наближається відключення за 30 хвилин</b>\n\n"
            f"🏠 Група: <b>{group}</b> ({city_name})\n\n"
            f"<b>Час відключення:</b> {start_str}\n"
            f"<b>Заплановане включення:</b> {end_str}\n\n"
            f"⚡️ З обережністю користуйтесь ліфтами та зарядіть пристрої\n\n"
            f"🕐 Надіслано: {now.strftime('%H:%M:%S')}\n\n"
            f"🤖 @power_po2"
        )

        return message
