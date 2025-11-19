"""AI-powered schedule change explanations using OpenAI API"""
import logging
from typing import Optional
from openai import AsyncOpenAI
from openai import OpenAIError
from light_bot.config import OPENAI_API_KEY, OPENAI_MODEL
import asyncio

logger = logging.getLogger(__name__)


class ScheduleChangeExplainer:
    """Generate human-readable explanations of schedule changes using OpenAI API"""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        """Initialize the explainer with OpenAI API credentials

        Args:
            api_key: OpenAI API key
            model: OpenAI model to use (default: gpt-4o-mini)
        """
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.timeout = 10.0  # seconds

    def _format_slots_for_prompt(self, slots: list) -> str:
        """Format schedule slots for the prompt

        Args:
            slots: List of slot dicts with start, end, type

        Returns:
            Formatted string describing the slots with durations
        """
        if not slots:
            return "Відключень немає (0 годин без світла)"

        formatted = []
        total_duration_minutes = 0

        for slot in slots:
            start_h = slot['start'] // 60
            start_m = slot['start'] % 60
            end_h = slot['end'] // 60
            end_m = slot['end'] % 60
            slot_type = slot['type']

            if slot_type == "NotPlanned":
                continue

            # Calculate duration for this slot
            duration_minutes = slot['end'] - slot['start']
            total_duration_minutes += duration_minutes
            duration_hours = duration_minutes / 60

            # Format hours without unnecessary decimal for whole hours
            hours_text = f"{duration_hours:.0f} годин" if duration_hours == int(duration_hours) else f"{duration_hours:.1f} годин"
            formatted.append(f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d} ({hours_text} {slot_type})")

        # Format total duration
        total_hours = total_duration_minutes / 60
        total_text = f"{total_hours:.0f} годин" if total_hours == int(total_hours) else f"{total_hours:.1f} годин"
        slots_text = ", ".join(formatted)
        
        total_slots = len(formatted)
        return f"{slots_text} | Всього: {total_text} без світла, кількість відключень: {total_slots}"
    
    def _format_slots_diff_for_prompt(self, old_slots: list, new_slots: list) -> str:
        """Format the difference between old and new slots for the prompt

        Args:
            old_slots: List of old slot dicts
            new_slots: List of new slot dicts

        Returns:
            Formatted string describing the difference between old and new slots
        """
        if not old_slots or not new_slots:
            return ""

        old_slots_count = len([slot for slot in old_slots if slot['type'] != "NotPlanned"])
        new_slots_count = len([slot for slot in new_slots if slot['type'] != "NotPlanned"])
        diff_slots_count = new_slots_count - old_slots_count
        if diff_slots_count == 0:
            diff_slots_count_text = ""
        else:
            diff_slots_count_text = f"Кількість відключень збільшилась на {diff_slots_count}" if diff_slots_count > 0 else f"Кількість відключень зменшилась на {-diff_slots_count}"

        old_slots_duration = sum([slot['end'] - slot['start'] for slot in old_slots if slot['type'] != "NotPlanned"]) / 60
        new_slots_duration = sum([slot['end'] - slot['start'] for slot in new_slots if slot['type'] != "NotPlanned"]) / 60
        diff_slots_duration = new_slots_duration - old_slots_duration
        if diff_slots_duration == 0:
            diff_slots_duration_text = "Тривалість відключень не змінилась"
        else:
            diff_slots_duration_text = f"Тривалість відключень збільшилась на {diff_slots_duration} годин" if diff_slots_duration > 0 else f"Тривалість відключень зменшилась на {-diff_slots_duration} годин"

        return f"{diff_slots_count_text}\n{diff_slots_duration_text}"

    def _build_prompt(self, old_schedule: dict, new_schedule: dict, current_time_minutes: Optional[int] = None) -> str:
        """Build the prompt for OpenAI API

        Args:
            old_schedule: Previous schedule data
            new_schedule: New schedule data
            current_time_minutes: Current time in minutes since midnight (None for tomorrow's schedule)

        Returns:
            Formatted prompt string
        """
        old_slots_text = self._format_slots_for_prompt(old_schedule.get('slots', []))
        new_slots_text = self._format_slots_for_prompt(new_schedule.get('slots', []))
        diff_text = self._format_slots_diff_for_prompt(old_schedule.get('slots', []), new_schedule.get('slots', []))

        # For tomorrow's schedule, don't mention current time
        if current_time_minutes is None:
            time_context = "Це графік на ЗАВТРА"
        else:
            current_h = current_time_minutes // 60
            current_m = current_time_minutes % 60
            time_context = f"Поточний час: {current_h:02d}:{current_m:02d}"

        prompt = f"""Ти - помічник який коротко пояснює зміни в графіку відключень світла.

ВАЖЛИВО:
- Пиши ДУЖЕ коротко (1-2 речення максимум!)
- Говори просто, як друзям у месенджері
- Уникай слів "зміна полягає в тому що", "це означає", просто кажи що змінилось
- Почни з емоджі:
  🎉 - якщо менше відключень або коротші (добре для людей)
  😞 - якщо більше відключень або довші (погано для людей)
  🤷 - якщо просто перенесли час

КОРИСНІ ФРАЗИ (використовуй для опису часу доби):
- ранкове відключення (6:00-12:00)
- відключення вдень (12:00-18:00)
- вечірнє відключення (18:00-23:00)
- нічне відключення (23:00-6:00)
- одне з відключень вдень (коли їх декілька)

Приклади ГАРНИХ відповідей:{' (для сьогодні)' if current_time_minutes is not None else ' (для завтра)'}
{"😞 Вечірнє відключення подовжили до 20:00 (було до 18:00)" if current_time_minutes is not None else "😞 Завтрашнє вечірнє відключення подовжили до 20:00 (було до 18:00)"}
{"🎉 Скоротили вечірнє відключення на пів години!" if current_time_minutes is not None else "🎉 Скоротили вечірнє відключення завтра на пів години!"}
{"🤷 Перенесли відключення з ранку на обід: тепер БЕЗ світла 14:00-16:00 замість 12:00-14:00" if current_time_minutes is not None else "🤷 Перенесли відключення з завтрашнього ранку на обід: 14:00-16:00 замість 12:00-14:00"}
{"😞 Додалось ранкове відключення 8:00-10:00, ще 2 години без світла." if current_time_minutes is not None else "😞 На завтра додалось ранкове відключення 8:00-10:00, ще 2 години без світла."}
{"🎉 Скоротили ранкове відключення: 08:00-9:30 замість 07:00-9:30. На 1 годину менше без світла!" if current_time_minutes is not None else "🎉 Скоротили завтрашнє ранкове відключення: 08:00-9:30 замість 07:00-9:30. На 1 годину менше без світла!"}
{"🎉 Відмінили нічне відключення 02:00-04:00!" if current_time_minutes is not None else "🎉 Відмінили завтрашнє нічне відключення 02:00-04:00!"}

Приклади ПОГАНИХ відповідей:
"Зміна полягає в тому що відключення було з 14:00 до 16:00, а тепер буде..." ❌ (занадто довго!)
"Це означає що час відключення збільшився..." ❌ (формально!)

{time_context}

ЦЕ ГРАФІКИ ВІДКЛЮЧЕНЬ (коли світла немає):
Старий графік: {old_slots_text}
Новий графік: {new_slots_text}

Зміни: {diff_text}

Твоя відповідь (лише емоджі + коротке пояснення):"""

        return prompt

    async def explain_schedule_change(
        self,
        old_schedule: dict,
        new_schedule: dict,
        current_time_minutes: Optional[int] = None
    ) -> Optional[str]:
        """Generate AI explanation of schedule changes

        Args:
            old_schedule: Previous schedule data (from JSON file)
            new_schedule: New schedule data (from API)
            current_time_minutes: Current time in minutes since midnight (None for tomorrow's schedule)

        Returns:
            Human-readable explanation in Ukrainian, or None if API fails
        """
        try:
            prompt = self._build_prompt(old_schedule, new_schedule, current_time_minutes)
            logger.info(f"Prompt: {prompt}")

            logger.debug("Requesting AI explanation from OpenAI...")

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Ти - помічник який пояснює зміни в графіках відключень електроенергії простою українською мовою. ВАЖЛИВО: графіки показують періоди ВІДКЛЮЧЕННЯ (коли світла НЕМАЄ)!"},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=150,
                timeout=self.timeout
            )

            explanation = response.choices[0].message.content.strip()

            logger.info(f"AI explanation generated successfully ({len(explanation)} chars)")
            logger.debug(f"AI explanation: {explanation}")

            return explanation

        except OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error generating AI explanation: {e}")
            return None


def main():
    """Main function to test the explainer"""
    explainer = ScheduleChangeExplainer(api_key=OPENAI_API_KEY, model=OPENAI_MODEL)
    old_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": [
    {
      "start": 0,
      "end": 150,
      "type": "NotPlanned"
    },
    {
      "start": 150,
      "end": 390,
      "type": "Definite"
    },
    {
      "start": 390,
      "end": 780,
      "type": "NotPlanned"
    },
    {
      "start": 780,
      "end": 1020,
      "type": "Definite"
    },
    {
      "start": 1020,
      "end": 1410,
      "type": "NotPlanned"
    },
    {
      "start": 1410,
      "end": 1440,
      "type": "Definite"
    }]}
    new_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": [
    {
      "start": 0,
      "end": 150,
      "type": "NotPlanned"
    },
    {
      "start": 150,
      "end": 360,
      "type": "Definite"
    },
    {
      "start": 360,
      "end": 780,
      "type": "NotPlanned"
    },
    {
      "start": 780,
      "end": 1020,
      "type": "Definite"
    },
    {
      "start": 1020,
      "end": 1410,
      "type": "NotPlanned"
    },
    {
      "start": 1410,
      "end": 1440,
      "type": "Definite"
    }]}
    result = asyncio.run(explainer.explain_schedule_change(old_schedule, new_schedule, 10))
    print(result)

    print("================================================")

    old_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": [
    {
      "start": 0,
      "end": 150,
      "type": "NotPlanned"
    },
    {
      "start": 150,
      "end": 390,
      "type": "Definite"
    },
    {
      "start": 390,
      "end": 780,
      "type": "NotPlanned"
    },
    {
      "start": 780,
      "end": 1020,
      "type": "Definite"
    },
    {
      "start": 1020,
      "end": 1410,
      "type": "NotPlanned"
    },
    {
      "start": 1410,
      "end": 1440,
      "type": "Definite"
    }]}
    new_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": [
    {
      "start": 0,
      "end": 150,
      "type": "NotPlanned"
    },
    {
      "start": 150,
      "end": 360,
      "type": "Definite"
    },
    {
      "start": 360,
      "end": 780,
      "type": "NotPlanned"
    },
    {
      "start": 780,
      "end": 1300,
      "type": "NotPlanned"
    },
    {
      "start": 1300,
      "end": 1440,
      "type": "Definite"
    }]}
    result = asyncio.run(explainer.explain_schedule_change(old_schedule, new_schedule, 1110))
    print(result)

    print("================================================")

    old_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": [
    {
      "start": 0,
      "end": 150,
      "type": "NotPlanned"
    },
    {
      "start": 150,
      "end": 390,
      "type": "Definite"
    },
    {
      "start": 390,
      "end": 780,
      "type": "NotPlanned"
    },
    {
      "start": 780,
      "end": 1020,
      "type": "Definite"
    },
    {
      "start": 1020,
      "end": 1410,
      "type": "NotPlanned"
    },
    {
      "start": 1410,
      "end": 1440,
      "type": "Definite"
    }]}
    new_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": [
    {
      "start": 0,
      "end": 150,
      "type": "NotPlanned"
    },
    {
      "start": 150,
      "end": 390,
      "type": "Definite"
    },
    {
      "start": 390,
      "end": 780,
      "type": "NotPlanned"
    },
    {
      "start": 780,
      "end": 1020,
      "type": "Definite"
    },
    {
      "start": 1020,
      "end": 1090,
      "type": "NotPlanned"
    },

    {
      "start": 1090,
      "end": 1210,
      "type": "Definite"
    },

    {
      "start": 1210,
      "end": 1410,
      "type": "NotPlanned"
    },
    {
      "start": 1410,
      "end": 1440,
      "type": "Definite"
    }]}
    result = asyncio.run(explainer.explain_schedule_change(old_schedule, new_schedule, 1110))
    print(result)
    

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
