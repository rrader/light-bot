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
        is_today: bool = True,
        location_name: Optional[str] = None,
        voltage: Optional[float] = None,
        was_unstable: bool = False,
        min_voltage: Optional[float] = None,
        max_voltage: Optional[float] = None
    ) -> str:
        """
        Format message for when power comes back on (or stabilizes)

        Args:
            timestamp: Current timestamp when power came on
            duration_text: Formatted duration text (e.g., "2 години 15 хвилин")
            next_outage_start: Next outage start time (e.g., "14:00")
            next_outage_end: Next outage end time (e.g., "16:00")
            is_today: Whether the next outage is today or tomorrow
            location_name: Optional location display name (e.g. "Вінниця")
            voltage: Optional line voltage reading (e.g. 228.0)
            was_unstable: Whether the previous state was 'unstable'
            min_voltage: Optional minimum voltage during instability period
            max_voltage: Optional maximum voltage during instability period
        """
        kyiv_time = timestamp.strftime('%d.%m.%Y %H:%M:%S')
        if was_unstable:
            header = f"⚡️ <b>Напруга стабілізувалась ({location_name})!</b> ⚡️" if location_name else "⚡️ <b>Напруга стабілізувалась!</b> ⚡️"
        else:
            header = f"⚡️ <b>Світло з'явилось ({location_name})!</b> ⚡️" if location_name else "⚡️ <b>Світло з'явилось!</b> ⚡️"

        message = (
            f"{header}\n\n"
            f"🕐 Час: {kyiv_time}\n"
        )

        if voltage is not None:
            if was_unstable and min_voltage is not None and max_voltage is not None and (max_voltage - min_voltage) >= 2.0:
                message += f"⚡️ Напруга в мережі: <b>{voltage:.1f} В</b> (діапазон коливань: {min_voltage:.1f}–{max_voltage:.1f} В)\n"
            else:
                message += f"⚡️ Напруга в мережі: <b>{voltage:.1f} В</b>\n"
        elif was_unstable and min_voltage is not None and max_voltage is not None and (max_voltage - min_voltage) >= 2.0:
            message += f"⚡️ Діапазон коливань напруги: <b>{min_voltage:.1f}–{max_voltage:.1f} В</b>\n"

        if duration_text:
            label = "Нестабільність тривала" if was_unstable else "Відключення тривало"
            message += f"⏱ {label}: <b>{duration_text}</b>\n"

        if next_outage_start and next_outage_end:
            day_text = "сьогодні" if is_today else "завтра"
            message += f"\n⚠️ Наступне відключення {day_text}: <b>{next_outage_start} - {next_outage_end}</b>"

        return message

    @staticmethod
    def format_power_off_message(
        timestamp: datetime,
        duration_text: Optional[str] = None,
        location_name: Optional[str] = None,
        voltage: Optional[float] = None
    ) -> str:
        """
        Format message for when power goes out

        Args:
            timestamp: Current timestamp when power went out
            duration_text: Formatted duration text (e.g., "45 хвилин")
            location_name: Optional location display name (e.g. "Вінниця")
            voltage: Optional line voltage reading
        """
        kyiv_time = timestamp.strftime('%d.%m.%Y %H:%M:%S')
        header = f"🔴 <b>Світло зникло ({location_name})</b> 🔴" if location_name else "🔴 <b>Світло зникло</b> 🔴"

        message = (
            f"{header}\n\n"
            f"🕐 Час: {kyiv_time}\n"
        )

        if voltage is not None and voltage > 0:
            message += f"⚡️ Остання напруга: <b>{voltage:.1f} В</b>\n"

        if duration_text:
            message += f"⏱ Світло було: <b>{duration_text}</b>"

        return message

    @staticmethod
    def format_power_unstable_message(
        timestamp: datetime,
        duration_text: Optional[str] = None,
        location_name: Optional[str] = None,
        voltage: Optional[float] = None,
        min_voltage: Optional[float] = None,
        max_voltage: Optional[float] = None
    ) -> str:
        """
        Format message for when grid power is unstable and relay trips

        Args:
            timestamp: Current timestamp when instability detected
            duration_text: Formatted duration text of previous state
            location_name: Optional location display name (e.g. "Вінниця")
            voltage: Extreme line voltage reading (furthest from 230V)
            min_voltage: Optional minimum voltage recorded during period
            max_voltage: Optional maximum voltage recorded during period
        """
        kyiv_time = timestamp.strftime('%d.%m.%Y %H:%M:%S')
        header = f"🟡 <b>В мережі нестабільна напруга ({location_name})!</b> 🟡" if location_name else "🟡 <b>В мережі нестабільна напруга!</b> 🟡"

        message = (
            f"{header}\n\n"
            f"🕐 Час: {kyiv_time}\n"
        )

        if voltage is not None:
            if min_voltage is not None and max_voltage is not None and (max_voltage - min_voltage) >= 5.0:
                message += f"⚡️ Напруга в мережі: <b>{voltage:.1f} В</b> (діапазон: {min_voltage:.1f}–{max_voltage:.1f} В)\n"
            else:
                message += f"⚡️ Напруга в мережі: <b>{voltage:.1f} В</b>\n"

        message += "⚠️ Реле напруги відімкнуло споживачів від мережі.\n"

        if duration_text:
            message += f"⏱ Попередній стан тривав: <b>{duration_text}</b>"

        return message

    @staticmethod
    def format_frequent_unstable_message(
        timestamp: datetime,
        count: int,
        window_hours: int = 1,
        location_name: Optional[str] = None,
        voltage: Optional[float] = None,
        min_voltage: Optional[float] = None,
        max_voltage: Optional[float] = None
    ) -> str:
        """
        Format message for when multiple instability cutoffs occur within a short window.
        """
        kyiv_time = timestamp.strftime('%d.%m.%Y %H:%M:%S')
        header = f"🟡 <b>В мережі нестабільна напруга ({location_name})!</b> 🟡" if location_name else "🟡 <b>В мережі нестабільна напруга!</b> 🟡"

        time_window_str = "за останню годину" if window_hours == 1 else f"за останні {window_hours} год"

        # Ukrainian plural for спрацювання (1 спрацювання, 2-4 спрацювання, 5-20 спрацювань)
        n_abs = abs(count)
        if 11 <= (n_abs % 100) <= 19:
            plural_cutoffs = f"{count} спрацювань"
        elif (n_abs % 10) == 1:
            plural_cutoffs = f"{count} спрацювання"
        elif 2 <= (n_abs % 10) <= 4:
            plural_cutoffs = f"{count} спрацювання"
        else:
            plural_cutoffs = f"{count} спрацювань"

        message = (
            f"{header}\n\n"
            f"🕐 Час: {kyiv_time}\n"
        )

        if voltage is not None:
            if min_voltage is not None and max_voltage is not None and (max_voltage - min_voltage) >= 2.0:
                message += f"⚡️ Напруга в мережі: <b>{voltage:.1f} В</b> (діапазон коливань: {min_voltage:.1f}–{max_voltage:.1f} В)\n"
            else:
                message += f"⚡️ Напруга в мережі: <b>{voltage:.1f} В</b>\n"
        elif min_voltage is not None and max_voltage is not None and (max_voltage - min_voltage) >= 2.0:
            message += f"⚡️ Діапазон коливань напруги: <b>{min_voltage:.1f}–{max_voltage:.1f} В</b>\n"

        message += (
            f"⚠️ Зафіксовано часті стрибки напруги (<b>{plural_cutoffs} реле</b> {time_window_str}).\n"
            f"Реле захисту повторно відмикає споживачів через коливання в електромережі."
        )

        return message
