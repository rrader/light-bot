"""
End-to-end tests for Yasno Schedule Service integration with Telegram

These tests verify the complete flow:
- Yasno API → Schedule Service → Telegram Bot
- Schedule formatting with real API data structure
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src')))


class TestScheduleServiceE2E:
    """E2E tests for schedule service with mocked Yasno API responses"""

    @pytest.fixture
    def mock_yasno_response(self):
        """Mock Yasno API response in real production format"""
        return {
            "2.1": {
                "today": {
                    "slots": [
                        {"start": 0, "end": 630, "type": "NotPlanned"},
                        {"start": 630, "end": 840, "type": "Definite"},  # 10:30-14:00
                        {"start": 840, "end": 1080, "type": "NotPlanned"},
                        {"start": 1080, "end": 1320, "type": "Definite"},  # 18:00-22:00
                        {"start": 1320, "end": 1440, "type": "NotPlanned"}
                    ],
                    "date": "2025-10-31T00:00:00+02:00",
                    "status": "ScheduleApplies"
                },
                "tomorrow": {
                    "slots": [
                        {"start": 0, "end": 540, "type": "NotPlanned"},
                        {"start": 540, "end": 780, "type": "Definite"},  # 09:00-13:00
                        {"start": 780, "end": 1440, "type": "NotPlanned"}
                    ],
                    "date": "2025-11-01T00:00:00+02:00",
                    "status": "WaitingForSchedule"
                },
                "updatedOn": "2025-10-31T04:27:19+00:00"
            },
            "3.2": {
                "today": {
                    "slots": [
                        {"start": 0, "end": 1440, "type": "NotPlanned"}
                    ],
                    "date": "2025-10-31T00:00:00+02:00",
                    "status": "ScheduleApplies"
                },
                "tomorrow": {
                    "slots": [
                        {"start": 0, "end": 1440, "type": "NotPlanned"}
                    ],
                    "date": "2025-11-01T00:00:00+02:00",
                    "status": "WaitingForSchedule"
                },
                "updatedOn": "2025-10-31T04:27:19+00:00"
            }
        }

    @pytest.mark.asyncio
    async def test_yasno_api_parsing(self, mock_yasno_response):
        """
        E2E Test: Yasno API response parsing

        Verifies YasnoScheduleResponse can parse real API format
        """
        from light_bot.api.yasno.models import YasnoScheduleResponse

        schedule = YasnoScheduleResponse(mock_yasno_response)
        assert schedule is not None

        # Get group 2.1
        group_schedule = schedule.get_group("2.1")
        assert group_schedule is not None

        # Verify today's schedule
        assert group_schedule.today is not None
        assert len(group_schedule.today.slots) == 5

        # Verify slots
        definite_slots = [s for s in group_schedule.today.slots if s.type.value == "Definite"]
        assert len(definite_slots) == 2  # Two outage periods

        # Verify tomorrow's schedule
        assert group_schedule.tomorrow is not None

    @pytest.mark.asyncio
    async def test_schedule_formatter_with_real_data(self, mock_yasno_response):
        """
        E2E Test: Schedule Formatter with real API data format

        Verifies the formatter can handle real Yasno API response structure
        """
        from light_bot.api.yasno.models import YasnoScheduleResponse
        from light_bot.formatters.schedule_formatter import ScheduleFormatter

        # Parse real API format
        schedule = YasnoScheduleResponse(mock_yasno_response)

        # Format today's schedule
        today_message = ScheduleFormatter.format_schedule_message(
            schedule, "2.1", for_tomorrow=False
        )
        assert today_message is not None
        assert len(today_message) > 0
        assert "2.1" in today_message
        assert "Графік" in today_message

        # Should contain outage times
        assert "10:30" in today_message  # First outage start
        assert "14:00" in today_message  # First outage end
        assert "18:00" in today_message  # Second outage start
        assert "22:00" in today_message  # Second outage end

        # Format tomorrow's schedule
        tomorrow_message = ScheduleFormatter.format_schedule_message(
            schedule, "2.1", for_tomorrow=True
        )
        assert tomorrow_message is not None
        assert "09:00" in tomorrow_message
        assert "13:00" in tomorrow_message

    @pytest.mark.asyncio
    async def test_empty_schedule_handling(self):
        """
        E2E Test: Handle schedule with no outages

        Verifies system handles days with no planned outages
        """
        from light_bot.api.yasno.models import YasnoScheduleResponse
        from light_bot.formatters.schedule_formatter import ScheduleFormatter

        # Schedule with no outages (all NotPlanned)
        no_outages_response = {
            "2.1": {
                "today": {
                    "slots": [
                        {"start": 0, "end": 1440, "type": "NotPlanned"}
                    ],
                    "date": "2025-10-31T00:00:00+02:00",
                    "status": "ScheduleApplies"
                },
                "tomorrow": {
                    "slots": [
                        {"start": 0, "end": 1440, "type": "NotPlanned"}
                    ],
                    "date": "2025-11-01T00:00:00+02:00",
                    "status": "WaitingForSchedule"
                },
                "updatedOn": "2025-10-31T04:27:19+00:00"
            }
        }

        schedule = YasnoScheduleResponse(no_outages_response)
        message = ScheduleFormatter.format_schedule_message(schedule, "2.1", for_tomorrow=False)

        assert message is not None
        assert "немає" in message  # Should say "no outages"

    @pytest.mark.asyncio
    async def test_yasno_api_to_telegram_flow(self, mock_yasno_response):
        """
        E2E Test: Complete flow from Yasno API to Telegram

        Simulates: Yasno API → Parse → Format → Send to Telegram
        """
        from light_bot.api.yasno.api import YasnoAPIClient
        from light_bot.api.yasno.models import YasnoScheduleResponse
        from light_bot.formatters.schedule_formatter import ScheduleFormatter

        # Mock the HTTP request to Yasno API
        with patch('light_bot.api.yasno.api.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_yasno_response
            mock_get.return_value = mock_response

            # Step 1: Fetch schedule from API
            client = YasnoAPIClient()
            schedule = client.update()

            assert schedule is not None
            assert isinstance(schedule, YasnoScheduleResponse)

            # Step 2: Format message
            message = ScheduleFormatter.format_schedule_message(
                schedule, "2.1", for_tomorrow=False
            )

            # Step 3: Verify message content
            assert "Графік відключень" in message
            assert "2.1" in message
            assert "10:30" in message
            assert "14:00" in message

            # Step 4: Would send to Telegram (mocked in unit tests)
            # In production: await schedule_bot.send_message(message)
