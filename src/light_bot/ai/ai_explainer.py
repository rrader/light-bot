"""AI-powered schedule change explanations using OpenAI API"""
import logging
from typing import Optional
from openai import AsyncOpenAI
from openai import OpenAIError

logger = logging.getLogger(__name__)


class ScheduleChangeExplainer:
    """Generate human-readable explanations of schedule changes using OpenAI API"""

    def __init__(self, api_key: str, model: str = "gpt-5-nano"):
        """Initialize the explainer with OpenAI API credentials

        Args:
            api_key: OpenAI API key
            model: OpenAI model to use (default: gpt-5-nano)
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

    def _build_prompt(self, old_schedule: dict, new_schedule: dict, current_time_minutes: int) -> str:
        """Build the prompt for OpenAI API

        Args:
            old_schedule: Previous schedule data
            new_schedule: New schedule data
            current_time_minutes: Current time in minutes since midnight

        Returns:
            Formatted prompt string
        """
        current_h = current_time_minutes // 60
        current_m = current_time_minutes % 60

        old_slots_text = self._format_slots_for_prompt(old_schedule.get('slots', []))
        new_slots_text = self._format_slots_for_prompt(new_schedule.get('slots', []))

        prompt = f"""Ти - асистент який пояснює зміни в графіку відключень електроенергії українською мовою.

Поточний час: {current_h:02d}:{current_m:02d}

Старий графік: {old_slots_text}
Новий графік: {new_slots_text}

Завдання:
1. Поясни що змінилося простими словами
2. Фокусуйся на майбутніх відключеннях (які ще не відбулись)
3. Використовуй розмовну українську мову
4. Максимум 2-3 короткі речення
5. Будь конкретним: вкажи час та що саме змінилось (подовжили, скоротили, додали, прибрали)
6. Додай емоджі на початку залежно від змін:
   - 🎉 або 😊 якщо відключень стало менше або їх скоротили (добра зміна)
   - 😞 або 😤 якщо відключень стало більше або їх подовжили (погана зміна)
   - 🤷 або 📝 якщо зміни нейтральні (перенесли час, але загальна тривалість однакова)

Приклади гарних відповідей:
- "😞 Вечірнє відключення подовжено на 2 години - тепер світло буде вимкнено до 20:00 замість 18:00. Ранкові відключення залишились без змін."
- "🎉 Вечірнє відключення скоротили на годину - світло дадуть о 19:00 замість 20:00!"
- "🤷 Відключення перенесли на пізніший час: тепер 16:00-18:00 замість 14:00-16:00."

Відповідь (лише текст пояснення з емоджі на початку):"""

        return prompt

    async def explain_schedule_change(
        self,
        old_schedule: dict,
        new_schedule: dict,
        current_time_minutes: int
    ) -> Optional[str]:
        """Generate AI explanation of schedule changes

        Args:
            old_schedule: Previous schedule data (from JSON file)
            new_schedule: New schedule data (from API)
            current_time_minutes: Current time in minutes since midnight

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
                max_tokens=150,
                temperature=0.7,
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
