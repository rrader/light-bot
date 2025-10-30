from datetime import datetime
from typing import List

from light_bot.api.yasno import YasnoScheduleResponse, PowerSlot, SlotType
from light_bot.config import TIMEZONE


class ScheduleFormatter:
    """Format Yasno power outage schedules for Telegram messages"""

    @staticmethod
    def minutes_to_time(minutes: int) -> str:
        """Convert minutes from midnight to HH:MM format"""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"

    @staticmethod
    def get_outage_slots(slots: List[PowerSlot]) -> List[PowerSlot]:
        """Filter slots to get only Definite outages"""
        return [slot for slot in slots if slot.type == SlotType.DEFINITE]

    @staticmethod
    def format_outage_slots(slots: List[PowerSlot]) -> str:
        """Format outage slots into readable time ranges"""
        outage_slots = ScheduleFormatter.get_outage_slots(slots)

        if not outage_slots:
            return "✅ Відключень немає"

        formatted = []
        for slot in outage_slots:
            start_str = ScheduleFormatter.minutes_to_time(slot.start)
            end_str = ScheduleFormatter.minutes_to_time(slot.end)
            formatted.append(f"⚡️ {start_str} - {end_str}")

        return "\n".join(formatted)

    @staticmethod
    def format_schedule_message(
        schedule_data: YasnoScheduleResponse,
        group: str,
        for_tomorrow: bool = False,
        change_detected: bool = False
    ) -> str:
        """Format complete schedule message for Telegram"""
        if not schedule_data:
            return "❌ Графік відключень наразі недоступний"

        emoji = "🔔" if change_detected else "🌙" if for_tomorrow else "☀️"
        day_label = "завтра" if for_tomorrow else "сьогодні" if not change_detected else "змінився"

        group_schedule = schedule_data.get_group(group)
        if not group_schedule:
            return f"❌ Група {group} не знайдена в графіку"

        day_schedule = group_schedule.tomorrow if for_tomorrow else group_schedule.today

        date_str = day_schedule.date.strftime('%d.%m.%Y')
        weekday_names = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця", 'Субота', 'Неділя']
        weekday = weekday_names[day_schedule.date.weekday()]

        # Handle emergency shutdowns
        if day_schedule.status == "EmergencyShutdowns":
            message = (
                f"🚨 <b>ЕКСТРЕНІ ВІДКЛЮЧЕННЯ</b> 🚨\n\n"
                f"🏠 Група: <b>{group}</b>\n"
                f"📅 {weekday}, {date_str}\n\n"
                f"⚠️ <b>Графіки не застосовуються</b>\n"
                f"Екстрені відключення через аварійні ситуації\n\n"
                f"🕐 Оновлено: {datetime.now(TIMEZONE).strftime('%H:%M:%S')}"
            )
            return message

        outages_text = ScheduleFormatter.format_outage_slots(day_schedule.slots)

        status_msg = ""
        if day_schedule.status == "WaitingForSchedule":
            status_msg = "⏳ Очікування підтвердження графіку\n\n"

        message = (
            f"{emoji} <b>Графік відключень {day_label.upper()}</b>\n\n"
            f"🏠 Група: <b>{group}</b>\n"
            f"📅 {weekday}, {date_str}\n\n"
            f"{status_msg}"
            f"<b>Планові відключення:</b>\n"
            f"{outages_text}\n\n"
            f"🕐 Оновлено: {datetime.now(TIMEZONE).strftime('%H:%M:%S')}"
        )

        return message
