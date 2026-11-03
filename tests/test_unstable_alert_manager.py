import pytest
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from light_bot.models import LocationConfig
from light_bot.services.unstable_alert_manager import UnstableAlertManager


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.channel_id = "@test_channel"
    bot.send_message = AsyncMock(return_value=True)
    return bot


@pytest.fixture
def mock_stats_service():
    service = MagicMock()
    service.get_voltage_extrema.return_value = (None, None)
    return service


@pytest.fixture
def location():
    return LocationConfig(
        id='home',
        name='Дім',
        status_file='test_watchdog.txt',
        channel_id='@test_channel'
    )


class TestExtremeVoltageCalculation:
    def test_overvoltage_furthest(self):
        manager = UnstableAlertManager(nominal_voltage=230.0)
        # min 225 (-5), max 278 (+48) -> 278
        assert manager.calculate_extreme_voltage(min_v=225.0, max_v=278.0) == 278.0

    def test_undervoltage_furthest(self):
        manager = UnstableAlertManager(nominal_voltage=230.0)
        # min 160 (-70), max 235 (+5) -> 160
        assert manager.calculate_extreme_voltage(min_v=160.0, max_v=235.0) == 160.0

    def test_undervoltage_larger_than_overvoltage(self):
        manager = UnstableAlertManager(nominal_voltage=230.0)
        # min 170 (-60), max 270 (+40) -> 170
        assert manager.calculate_extreme_voltage(min_v=170.0, max_v=270.0) == 170.0

    def test_equal_deviation_favors_max(self):
        manager = UnstableAlertManager(nominal_voltage=230.0)
        # min 210 (-20), max 250 (+20) -> 250
        assert manager.calculate_extreme_voltage(min_v=210.0, max_v=250.0) == 250.0

    def test_only_one_voltage_present(self):
        manager = UnstableAlertManager(nominal_voltage=230.0)
        assert manager.calculate_extreme_voltage(min_v=None, max_v=260.0) == 260.0
        assert manager.calculate_extreme_voltage(min_v=190.0, max_v=None) == 190.0
        assert manager.calculate_extreme_voltage(min_v=None, max_v=None, fallback=230.0) == 230.0


class TestUnstableAlertManagerLifecycle:
    def test_short_lived_spike_is_suppressed(self, location, mock_bot, mock_stats_service):
        manager = UnstableAlertManager(
            delay_seconds=2,
            telegram_bot=mock_bot,
            stats_service=mock_stats_service
        )
        now = datetime.now(timezone.utc)
        manager.schedule_unstable_alert(location, now, duration_text="1h", voltage=265.0)

        assert manager.is_pending(location.id) is True
        assert manager.is_alert_sent(location.id) is False

        # Status normalizes within 0.1s (< 2s)
        time.sleep(0.1)
        alert_was_sent = manager.cancel(location.id)

        # Alert must NOT have been sent!
        assert alert_was_sent is False
        assert manager.is_pending(location.id) is False
        mock_bot.send_message.assert_not_called()

    def test_sustained_instability_fires_with_extreme_voltage(self, location, mock_bot, mock_stats_service):
        mock_stats_service.get_voltage_extrema.return_value = (220.0, 282.0)
        manager = UnstableAlertManager(
            delay_seconds=0.2,  # fast delay for test
            telegram_bot=mock_bot,
            stats_service=mock_stats_service
        )
        now = datetime.now(timezone.utc)
        manager.schedule_unstable_alert(location, now, duration_text="30m", voltage=260.0)
        manager.record_voltage(location.id, 275.0)

        # Wait for timer to fire
        time.sleep(0.35)

        assert manager.is_pending(location.id) is False
        assert manager.is_alert_sent(location.id) is True
        assert mock_bot.send_message.called

        # Verify extreme voltage (282.0 V, max deviation) was included in message
        call_args = mock_bot.send_message.call_args[0]
        sent_text = call_args[0]
        assert "282.0" in sent_text
        assert "нестабільна напруга" in sent_text

        # Now when power recovers: cancel() returns True so recovery alert is sent
        recovery_was_sent = manager.cancel(location.id)
        assert recovery_was_sent is True
