import pytest
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock
from light_bot.services.outage_alert_manager import OutageAlertManager
from light_bot.models import LocationConfig


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)
    bot.channel_id = '@test_channel'
    return bot


@pytest.fixture
def location():
    return LocationConfig(
        id='home',
        name='Паркові Озера 2',
        status_file='status.txt',
        channel_id='@test_channel'
    )


class TestOutageAlertManagerLifecycle:
    def test_short_lived_glitch_is_suppressed(self, mock_bot, location):
        """Outage lasting less than delay is cancelled without sending any message"""
        manager = OutageAlertManager(delay_seconds=2, telegram_bot=mock_bot)
        ts = datetime.now(timezone.utc)

        manager.schedule_outage_alert(location, timestamp=ts, voltage=0.0)
        assert manager.is_pending(location.id) is True
        assert manager.is_alert_sent(location.id) is False

        # Status changes back to 'on' before timer fires
        was_sent = manager.cancel(location.id)
        assert was_sent is False
        assert manager.is_pending(location.id) is False
        assert mock_bot.send_message.called is False

    def test_sustained_outage_fires_alert(self, mock_bot, location):
        """Outage lasting longer than delay fires Telegram alert with original timestamp"""
        manager = OutageAlertManager(delay_seconds=1, telegram_bot=mock_bot)
        ts = datetime.now(timezone.utc)

        manager.schedule_outage_alert(location, timestamp=ts, voltage=0.0)
        assert manager.is_pending(location.id) is True

        # Wait for delay to expire
        time.sleep(1.2)

        assert manager.is_pending(location.id) is False
        assert manager.is_alert_sent(location.id) is True
        assert mock_bot.send_message.called is True

        call_args = mock_bot.send_message.call_args
        msg = call_args[0][0]
        assert "Світло зникло" in msg

        # When status returns to on, cancel indicates alert was sent
        was_sent = manager.cancel(location.id)
        assert was_sent is True
