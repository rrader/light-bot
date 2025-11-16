"""AI-powered schedule change explanations using OpenAI API"""
import logging
from typing import Optional
from openai import AsyncOpenAI
from openai import OpenAIError

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
            Formatted string describing the slots
        """
        if not slots:
            return "Відключень немає"

        formatted = []
        for slot in slots:
            start_h = slot['start'] // 60
            start_m = slot['start'] % 60
            end_h = slot['end'] // 60
            end_m = slot['end'] % 60
            slot_type = slot['type']
            formatted.append(f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d} ({slot_type})")

        return ", ".join(formatted)

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

        # For tomorrow's schedule, don't mention current time
        if current_time_minutes is None:
            time_context = "Це графік на ЗАВТРА"
        else:
            current_h = current_time_minutes // 60
            current_m = current_time_minutes % 60
            time_context = f"Поточний час: {current_h:02d}:{current_m:02d}"

        prompt = f"""Ти - помічник який коротко пояснює зміни в графіку відключень світла.

{time_context}
Старий графік: {old_slots_text}
Новий графік: {new_slots_text}

ВАЖЛИВО:
- Пиши ДУЖЕ коротко (1-2 речення максимум!)
- Говори просто, як друзям у месенджері
- {'Фокусуйся тільки на майбутніх відключеннях' if current_time_minutes is not None else 'Це графік на ЗАВТРА'}
- Уникай слів "зміна полягає в тому що", "це означає", просто кажи що змінилось
- Почни з емоджі:
  🎉 - якщо менше відключень (добре)
  😞 - якщо більше відключень (погано)
  🤷 - якщо просто перенесли час

КОРИСНІ ФРАЗИ (використовуй для опису часу доби):
- ранкове відключення (6:00-12:00)
- відключення вдень (12:00-18:00)
- вечірнє відключення (18:00-23:00)
- нічне відключення (23:00-6:00)
- одне з відключень вдень (коли їх декілька)

Приклади ГАРНИХ відповідей:{' (для сьогодні)' if current_time_minutes is not None else ' (для завтра)'}
{"😞 Вечірнє відключення подовжили до 20:00 (було до 18:00)" if current_time_minutes is not None else "😞 Завтра вечірнє відключення подовжили до 20:00 (було до 18:00)"}
{"🎉 Скоротили вечірнє відключення на годину!" if current_time_minutes is not None else "🎉 Завтра відключення скоротили на годину!"}
{"🤷 Перенесли з ранку на обід: тепер 14:00-16:00" if current_time_minutes is not None else "🤷 Завтра перенесли з ранку на обід: 14:00-16:00"}
{"😞 Додалось ранкове відключення 8:00-10:00" if current_time_minutes is not None else "😞 Завтра додалось ранкове відключення 8:00-10:00"}

Приклади ПОГАНИХ відповідей:
"Зміна полягає в тому що відключення було з 14:00 до 16:00, а тепер буде..." ❌ (занадто довго!)
"Це означає що час відключення збільшився..." ❌ (формально!)

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

            logger.debug("Requesting AI explanation from OpenAI...")

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Ти - помічник який пояснює зміни в графіках відключень електроенергії простою українською мовою."},
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
