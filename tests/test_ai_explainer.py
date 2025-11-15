"""Tests for AI-powered schedule change explanations"""
import pytest
import os
import sys
from unittest.mock import Mock, AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from light_bot.ai.ai_explainer import ScheduleChangeExplainer


class TestScheduleChangeExplainer:
    """Test AI explainer for schedule changes"""

    @pytest.fixture
    def explainer(self):
        """Create explainer instance with mock API key"""
        return ScheduleChangeExplainer(api_key="test-api-key", model="gpt-5-nano")

    def test_format_slots_for_prompt_with_outages(self, explainer):
        """Test formatting slots into readable text"""
        slots = [
            {"start": 480, "end": 600, "type": "Definite"},   # 08:00-10:00
            {"start": 840, "end": 960, "type": "Definite"}    # 14:00-16:00
        ]

        result = explainer._format_slots_for_prompt(slots)

        assert "08:00-10:00" in result
        assert "14:00-16:00" in result
        assert "Definite" in result

    def test_format_slots_for_prompt_empty(self, explainer):
        """Test formatting empty slots"""
        result = explainer._format_slots_for_prompt([])
        assert result == "Відключень немає"

    def test_build_prompt_structure(self, explainer):
        """Test that prompt contains all necessary information"""
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 600, "type": "Definite"}
            ]
        }

        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 480, "end": 660, "type": "Definite"}
            ]
        }

        current_minutes = 720  # 12:00

        prompt = explainer._build_prompt(old_schedule, new_schedule, current_minutes)

        # Check prompt contains key information
        assert "12:00" in prompt  # Current time
        assert "08:00-10:00" in prompt  # Old schedule
        assert "08:00-11:00" in prompt  # New schedule
        assert "українською" in prompt.lower()  # Language instruction
        assert "майбутн" in prompt.lower()  # Focus on future
        assert "емоджі" in prompt.lower()  # Emoji instruction
        assert "🎉" in prompt or "😊" in prompt  # Good change emoji
        assert "😞" in prompt or "😤" in prompt  # Bad change emoji

    @pytest.mark.asyncio
    async def test_explain_schedule_change_success(self, explainer):
        """Test successful AI explanation generation"""
        old_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 960, "type": "Definite"}
            ]
        }

        new_schedule = {
            "date": "2024-01-15",
            "status": "ScheduleApplies",
            "slots": [
                {"start": 840, "end": 1080, "type": "Definite"}
            ]
        }

        # Mock OpenAI response with emoji
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "😞 Вечірнє відключення подовжено на 2 години."

        explainer.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await explainer.explain_schedule_change(old_schedule, new_schedule, 720)

        assert result == "😞 Вечірнє відключення подовжено на 2 години."
        # Should start with one of the emotional emojis
        assert any(result.startswith(emoji) for emoji in ["🎉", "😊", "😞", "😤", "🤷", "📝"])
        explainer.client.chat.completions.create.assert_called_once()

        # Check API call parameters
        call_kwargs = explainer.client.chat.completions.create.call_args.kwargs
        assert call_kwargs['model'] == 'gpt-5-nano'
        assert call_kwargs['max_tokens'] == 150
        assert call_kwargs['timeout'] == 10.0

    @pytest.mark.asyncio
    async def test_explain_schedule_change_api_error(self, explainer):
        """Test handling of OpenAI API errors"""
        from openai import OpenAIError

        old_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": []}
        new_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": []}

        # Mock API to raise error
        explainer.client.chat.completions.create = AsyncMock(side_effect=OpenAIError("API error"))

        result = await explainer.explain_schedule_change(old_schedule, new_schedule, 720)

        assert result is None  # Should return None on error, not crash

    @pytest.mark.asyncio
    async def test_explain_schedule_change_unexpected_error(self, explainer):
        """Test handling of unexpected errors"""
        old_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": []}
        new_schedule = {"date": "2024-01-15", "status": "ScheduleApplies", "slots": []}

        # Mock API to raise unexpected error
        explainer.client.chat.completions.create = AsyncMock(side_effect=ValueError("Unexpected"))

        result = await explainer.explain_schedule_change(old_schedule, new_schedule, 720)

        assert result is None  # Should handle gracefully


class TestScheduleFormatterWithAI:
    """Test integration of AI explanations with schedule formatter"""

    def test_format_message_with_ai_explanation(self):
        """Test that AI explanation is included in change notification"""
        from light_bot.formatters.schedule_formatter import ScheduleFormatter
        from light_bot.api.yasno import YasnoScheduleResponse, GroupSchedule, DaySchedule, PowerSlot, SlotType
        from datetime import datetime
        import pytz

        tz = pytz.timezone('Europe/Kyiv')
        date = datetime(2024, 1, 15, 12, 0, tzinfo=tz)

        # Create test schedule
        slots = [PowerSlot(start=840, end=960, type=SlotType.DEFINITE)]
        day_schedule = DaySchedule(slots=slots, date=date, status="ScheduleApplies")
        group_schedule = GroupSchedule(today=day_schedule, tomorrow=day_schedule, updatedOn=date)
        schedule_data = YasnoScheduleResponse({"2.1": group_schedule.model_dump()})

        formatter = ScheduleFormatter()
        ai_explanation = "😞 Вечірнє відключення подовжено на 2 години."

        message = formatter.format_schedule_message(
            schedule_data,
            "2.1",
            for_tomorrow=False,
            change_detected=True,
            change_explanation=ai_explanation
        )

        # Check AI explanation is present
        assert "💡" in message
        assert "Що змінилося:" in message
        assert "😞 Вечірнє відключення подовжено на 2 години." in message

        # Check it appears before outages list
        explanation_idx = message.index("Що змінилося:")
        outages_idx = message.index("Планові відключення:")
        assert explanation_idx < outages_idx

    def test_format_message_without_ai_explanation(self):
        """Test that message works without AI explanation"""
        from light_bot.formatters.schedule_formatter import ScheduleFormatter
        from light_bot.api.yasno import YasnoScheduleResponse, GroupSchedule, DaySchedule, PowerSlot, SlotType
        from datetime import datetime
        import pytz

        tz = pytz.timezone('Europe/Kyiv')
        date = datetime(2024, 1, 15, 12, 0, tzinfo=tz)

        slots = [PowerSlot(start=840, end=960, type=SlotType.DEFINITE)]
        day_schedule = DaySchedule(slots=slots, date=date, status="ScheduleApplies")
        group_schedule = GroupSchedule(today=day_schedule, tomorrow=day_schedule, updatedOn=date)
        schedule_data = YasnoScheduleResponse({"2.1": group_schedule.model_dump()})

        formatter = ScheduleFormatter()

        message = formatter.format_schedule_message(
            schedule_data,
            "2.1",
            for_tomorrow=False,
            change_detected=True,
            change_explanation=None  # No AI explanation
        )

        # Should NOT have AI section
        assert "💡" not in message
        assert "Що змінилося:" not in message

        # But should still have the schedule
        assert "Планові відключення:" in message
        assert "14:00 - 16:00" in message
