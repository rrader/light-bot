import pytest
import time
from datetime import datetime, timezone, timedelta
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
        alert_was_sent, min_v, max_v = manager.cancel(location.id)

        # Alert must NOT have been sent!
        assert alert_was_sent is False
        assert min_v == 265.0
        assert max_v == 265.0
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

        # Now when power recovers: cancel() returns True with recorded range
        recovery_was_sent, min_v, max_v = manager.cancel(location.id)
        assert recovery_was_sent is True
        assert min_v == 220.0
        assert max_v == 282.0


class TestFrequentCutoffInstability:
    def test_frequent_cutoffs_trigger_immediate_alert_on_fourth_cutoff(self, location, mock_bot, mock_stats_service):
        manager = UnstableAlertManager(
            delay_seconds=180,
            telegram_bot=mock_bot,
            stats_service=mock_stats_service,
            frequent_threshold=3,
            frequent_window_seconds=3600,
            frequent_cooldown_seconds=7200
        )
        base_time = datetime(2026, 11, 4, 18, 0, 0, tzinfo=timezone.utc)

        # 1st, 2nd, 3rd cutoffs (within 1 hour) are short-lived and suppressed
        for i in range(3):
            t = base_time + timedelta(minutes=i * 10)
            manager.schedule_unstable_alert(location, t, voltage=255.0)
            assert manager.is_pending(location.id) is True
            assert manager.is_alert_sent(location.id) is False
            # Normalize state
            alert_sent, _, _ = manager.cancel(location.id)
            assert alert_sent is False

        mock_bot.send_message.assert_not_called()

        # 4th cutoff within 1 hour: threshold > 3 is exceeded!
        t_4th = base_time + timedelta(minutes=35)
        manager.schedule_unstable_alert(location, t_4th, voltage=262.0)

        # Must fire immediately without waiting for delay_seconds
        assert manager.is_pending(location.id) is False
        assert manager.is_alert_sent(location.id) is True
        assert mock_bot.send_message.called
        assert mock_bot.send_message.call_count == 1

        sent_text = mock_bot.send_message.call_args[0][0]
        assert "Зафіксовано часті стрибки напруги" in sent_text
        assert "4 спрацювання реле" in sent_text
        assert "262.0" in sent_text

    def test_frequent_cutoffs_cooldown_suppresses_rapid_retrigger(self, location, mock_bot, mock_stats_service):
        manager = UnstableAlertManager(
            delay_seconds=180,
            telegram_bot=mock_bot,
            stats_service=mock_stats_service,
            frequent_threshold=3,
            frequent_window_seconds=3600,
            frequent_cooldown_seconds=7200
        )
        base_time = datetime(2026, 11, 4, 18, 0, 0, tzinfo=timezone.utc)

        # Trigger 4 cutoffs to fire the frequent alert
        for i in range(4):
            t = base_time + timedelta(minutes=i * 5)
            manager.schedule_unstable_alert(location, t, voltage=258.0)
            if i < 3:
                manager.cancel(location.id)

        assert mock_bot.send_message.call_count == 1
        mock_bot.send_message.reset_mock()

        # 5th cutoff occurs 15 minutes later (well within 2h cooldown)
        t_5th = base_time + timedelta(minutes=30)
        manager.schedule_unstable_alert(location, t_5th, voltage=260.0)

        # Should NOT fire immediately due to cooldown; instead sets up normal delayed timer
        assert mock_bot.send_message.call_count == 0
        assert manager.is_pending(location.id) is True
        assert manager.is_alert_sent(location.id) is False

        # If it normalizes quickly, cancel suppresses as normal
        alert_sent, _, _ = manager.cancel(location.id)
        assert alert_sent is False
        mock_bot.send_message.assert_not_called()

    def test_frequent_cutoffs_can_fire_again_after_cooldown_elapses(self, location, mock_bot, mock_stats_service):
        manager = UnstableAlertManager(
            delay_seconds=180,
            telegram_bot=mock_bot,
            stats_service=mock_stats_service,
            frequent_threshold=3,
            frequent_window_seconds=3600,
            frequent_cooldown_seconds=7200
        )
        base_time = datetime(2026, 11, 4, 18, 0, 0, tzinfo=timezone.utc)

        # Fire initial frequent alert at t=18:15 (4th cutoff)
        for i in range(4):
            t = base_time + timedelta(minutes=i * 5)
            manager.schedule_unstable_alert(location, t, voltage=256.0)
            if i < 3:
                manager.cancel(location.id)
        assert mock_bot.send_message.call_count == 1
        mock_bot.send_message.reset_mock()

        # 2 hours and 5 minutes later (cooldown 7200s elapsed)
        # Cluster of cutoffs occurs again
        later_base = base_time + timedelta(seconds=7500)
        for i in range(4):
            t = later_base + timedelta(minutes=i * 5)
            manager.schedule_unstable_alert(location, t, voltage=259.0)
            if i < 3:
                manager.cancel(location.id)

        # The 4th cutoff in the new window must trigger frequent alert again!
        assert mock_bot.send_message.call_count == 1
        sent_text = mock_bot.send_message.call_args[0][0]
        assert "Зафіксовано часті стрибки напруги" in sent_text

    def test_db_count_triggers_frequent_alert_after_service_restart(self, location, mock_bot, mock_stats_service):
        # In-memory history is empty, but DB has 4 records in the last hour
        mock_stats_service.count_events.return_value = 4
        manager = UnstableAlertManager(
            delay_seconds=180,
            telegram_bot=mock_bot,
            stats_service=mock_stats_service,
            frequent_threshold=3,
            frequent_window_seconds=3600,
            frequent_cooldown_seconds=7200
        )
        now = datetime.now(timezone.utc)
        manager.schedule_unstable_alert(location, now, voltage=263.0)

        # Should detect count_events=4 > 3 and trigger immediately
        assert manager.is_alert_sent(location.id) is True
        assert mock_bot.send_message.call_count == 1
        sent_text = mock_bot.send_message.call_args[0][0]
        assert "Зафіксовано часті стрибки напруги" in sent_text

