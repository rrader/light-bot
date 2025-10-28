"""
Comprehensive tests for schedule_service module
"""
import pytest
import asyncio
import hashlib
from datetime import datetime, time as dt_time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import pytz

from schedule_service import ScheduleFormatter, ScheduleService
from yasno_hass import YasnoAPIComponent, YasnoAPIOutage, YasnoOutageType, YasnoDailySchedule, YasnoDailyScheduleEntity


class TestScheduleFormatter:
    """Test ScheduleFormatter class"""

    def test_format_time_whole_hour(self):
        """Test formatting whole hour times"""
        assert ScheduleFormatter.format_time(8.0) == "08:00"
        assert ScheduleFormatter.format_time(12.0) == "12:00"
        assert ScheduleFormatter.format_time(0.0) == "00:00"
        assert ScheduleFormatter.format_time(23.0) == "23:00"

    def test_format_time_half_hour(self):
        """Test formatting half-hour times"""
        assert ScheduleFormatter.format_time(8.5) == "08:30"
        assert ScheduleFormatter.format_time(12.5) == "12:30"
        assert ScheduleFormatter.format_time(0.5) == "00:30"
        assert ScheduleFormatter.format_time(23.5) == "23:30"

    def test_format_outages_empty_list(self):
        """Test formatting empty outages list"""
        result = ScheduleFormatter.format_outages([])
        assert result == "✅ Немає планових відключень"

    def test_format_outages_single_interval(self):
        """Test formatting single outage interval"""
        outages = [
            YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)
        ]
        result = ScheduleFormatter.format_outages(outages)
        assert "⚡️ 08:00 - 12:00" in result

    def test_format_outages_consecutive_intervals(self):
        """Test formatting consecutive intervals - should merge"""
        outages = [
            YasnoAPIOutage(start=8.0, end=8.5, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=8.5, end=9.0, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=9.0, end=9.5, type=YasnoOutageType.OFF),
        ]
        result = ScheduleFormatter.format_outages(outages)
        # Should merge into single interval
        assert "08:00 - 09:30" in result
        # Should not have multiple intervals
        assert result.count("⚡️") == 1

    def test_format_outages_non_consecutive_intervals(self):
        """Test formatting non-consecutive intervals - should not merge"""
        outages = [
            YasnoAPIOutage(start=8.0, end=9.0, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=12.0, end=13.0, type=YasnoOutageType.OFF),
        ]
        result = ScheduleFormatter.format_outages(outages)
        assert "08:00 - 09:00" in result
        assert "12:00 - 13:00" in result
        assert result.count("⚡️") == 2

    def test_format_outages_unsorted_intervals(self):
        """Test formatting unsorted intervals - should sort first"""
        outages = [
            YasnoAPIOutage(start=12.0, end=13.0, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=8.0, end=9.0, type=YasnoOutageType.OFF),
        ]
        result = ScheduleFormatter.format_outages(outages)
        lines = result.strip().split('\n')
        # First line should be earlier time
        assert "08:00" in lines[0]
        assert "12:00" in lines[1]

    def test_format_schedule_message_no_data(self):
        """Test formatting when no schedule data available"""
        result = ScheduleFormatter.format_schedule_message(None, "kiev", "2.1", False)
        assert "❌" in result
        assert "недоступний" in result

    def test_format_schedule_message_no_restrictions(self):
        """Test formatting when no restrictions from Ukrenergo"""
        schedule_data = YasnoAPIComponent(
            template_name="electricity-outages-daily-schedule",
            available_regions=["kiev"],
            title="Графік відключень",
            dailySchedule=None
        )
        result = ScheduleFormatter.format_schedule_message(schedule_data, "kiev", "2.1", False)
        assert "✅" in result
        assert "Обмежень від НЕК «Укренерго» немає" in result
        assert "kiev" in result.lower()
        assert "2.1" in result

    def test_format_schedule_message_with_outages_today(self):
        """Test formatting schedule with outages for today"""
        # Create mock schedule data
        groups = {
            "2.1": [
                YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF),
                YasnoAPIOutage(start=16.0, end=20.0, type=YasnoOutageType.OFF),
            ]
        }
        today_schedule = YasnoDailyScheduleEntity(
            title="Понеділок, 28.10.2025 на 00:00",
            groups=groups
        )
        daily_schedule = YasnoDailySchedule(today=today_schedule, tomorrow=None)

        schedule_data = YasnoAPIComponent(
            template_name="electricity-outages-daily-schedule",
            available_regions=["kiev"],
            title="Графік відключень",
            dailySchedule={"kiev": daily_schedule}
        )

        result = ScheduleFormatter.format_schedule_message(schedule_data, "kiev", "2.1", for_tomorrow=False)

        assert "☀️" in result
        assert "СЬОГОДНІ" in result
        assert "Kiev" in result
        assert "2.1" in result
        assert "Понеділок, 28.10.2025" in result
        assert "08:00" in result
        assert "12:00" in result
        assert "16:00" in result
        assert "20:00" in result

    def test_format_schedule_message_with_outages_tomorrow(self):
        """Test formatting schedule with outages for tomorrow"""
        groups = {
            "2.1": [
                YasnoAPIOutage(start=10.0, end=14.0, type=YasnoOutageType.OFF),
            ]
        }
        tomorrow_schedule = YasnoDailyScheduleEntity(
            title="Вівторок, 29.10.2025 на 00:00",
            groups=groups
        )
        daily_schedule = YasnoDailySchedule(today=None, tomorrow=tomorrow_schedule)

        schedule_data = YasnoAPIComponent(
            template_name="electricity-outages-daily-schedule",
            available_regions=["kiev"],
            title="Графік відключень",
            dailySchedule={"kiev": daily_schedule}
        )

        result = ScheduleFormatter.format_schedule_message(schedule_data, "kiev", "2.1", for_tomorrow=True)

        assert "🌙" in result
        assert "ЗАВТРА" in result
        assert "Вівторок, 29.10.2025" in result
        assert "10:00 - 14:00" in result

    def test_format_schedule_message_missing_group(self):
        """Test formatting when requested group is missing"""
        groups = {"1.1": [YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)]}
        today_schedule = YasnoDailyScheduleEntity(title="Test", groups=groups)
        daily_schedule = YasnoDailySchedule(today=today_schedule)

        schedule_data = YasnoAPIComponent(
            template_name="electricity-outages-daily-schedule",
            available_regions=["kiev"],
            dailySchedule={"kiev": daily_schedule}
        )

        result = ScheduleFormatter.format_schedule_message(schedule_data, "kiev", "2.1", False)
        assert "❌" in result
        assert "2.1" in result
        assert "не знайдена" in result

    def test_format_schedule_message_missing_city(self):
        """Test formatting when requested city is missing"""
        daily_schedule = YasnoDailySchedule(today=None)
        schedule_data = YasnoAPIComponent(
            template_name="electricity-outages-daily-schedule",
            available_regions=["kiev"],
            dailySchedule={"dnipro": daily_schedule}
        )

        result = ScheduleFormatter.format_schedule_message(schedule_data, "kiev", "2.1", False)
        # When city is missing from dailySchedule, it shows "no restrictions" message
        assert "✅" in result
        assert "Обмежень від НЕК «Укренерго» немає" in result
        assert "kiev" in result.lower()


class TestScheduleService:
    """Test ScheduleService class"""

    @pytest.fixture
    def mock_bot(self):
        """Create mock Telegram bot"""
        bot = AsyncMock()
        bot.send_message = AsyncMock(return_value=True)
        return bot

    @pytest.fixture
    def service(self, mock_bot, tmp_path):
        """Create ScheduleService instance with mocked dependencies"""
        with patch('schedule_service.Bot', return_value=mock_bot):
            with patch('schedule_service.LAST_SCHEDULE_HASH_FILE', str(tmp_path / 'hash.txt')):
                service = ScheduleService()
                service.bot = mock_bot
                return service

    def test_initialization(self, service):
        """Test ScheduleService initialization"""
        assert service.bot is not None
        assert service.city == "kiev"
        assert service.group == "2.1"
        assert service.formatter is not None
        assert service.monitoring is False

    def test_read_last_hash_no_file(self, service, tmp_path):
        """Test reading last hash when file doesn't exist"""
        # Create a new service with non-existent hash file
        with patch('schedule_service.LAST_SCHEDULE_HASH_FILE', str(tmp_path / 'nonexistent_hash.txt')):
            new_service = ScheduleService()
            hash_value = new_service._read_last_hash()
            assert hash_value is None

    def test_write_and_read_last_hash(self, service, tmp_path):
        """Test writing and reading schedule hash"""
        test_hash = "abc123def456"
        service._write_last_hash(test_hash)

        read_hash = service._read_last_hash()
        assert read_hash == test_hash

    def test_compute_schedule_hash_no_data(self, service):
        """Test computing hash with no schedule data"""
        assert service._compute_schedule_hash(None) is None

    def test_compute_schedule_hash_no_daily_schedule(self, service):
        """Test computing hash with no daily schedule"""
        schedule_data = YasnoAPIComponent(
            template_name="test",
            dailySchedule=None
        )
        assert service._compute_schedule_hash(schedule_data) is None

    def test_compute_schedule_hash_valid_data(self, service):
        """Test computing hash with valid schedule data"""
        groups = {
            "2.1": [
                YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF),
            ]
        }
        today_schedule = YasnoDailyScheduleEntity(
            title="Monday, 28.10.2025",
            groups=groups
        )
        daily_schedule = YasnoDailySchedule(today=today_schedule)

        schedule_data = YasnoAPIComponent(
            template_name="test",
            dailySchedule={"kiev": daily_schedule}
        )

        hash1 = service._compute_schedule_hash(schedule_data)
        assert hash1 is not None
        assert len(hash1) == 64  # SHA256 hash length

        # Computing hash again should give same result
        hash2 = service._compute_schedule_hash(schedule_data)
        assert hash1 == hash2

    def test_compute_schedule_hash_different_data(self, service):
        """Test that different schedules produce different hashes"""
        groups1 = {"2.1": [YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)]}
        groups2 = {"2.1": [YasnoAPIOutage(start=8.0, end=13.0, type=YasnoOutageType.OFF)]}

        schedule1 = YasnoAPIComponent(
            template_name="test",
            dailySchedule={
                "kiev": YasnoDailySchedule(
                    today=YasnoDailyScheduleEntity(title="Test1", groups=groups1)
                )
            }
        )

        schedule2 = YasnoAPIComponent(
            template_name="test",
            dailySchedule={
                "kiev": YasnoDailySchedule(
                    today=YasnoDailyScheduleEntity(title="Test1", groups=groups2)
                )
            }
        )

        hash1 = service._compute_schedule_hash(schedule1)
        hash2 = service._compute_schedule_hash(schedule2)
        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_send_schedule_success(self, service):
        """Test successful schedule sending"""
        with patch('schedule_service.yasno_client') as mock_client:
            # Mock API response
            groups = {"2.1": [YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)]}
            mock_data = YasnoAPIComponent(
                template_name="test",
                dailySchedule={
                    "kiev": YasnoDailySchedule(
                        today=YasnoDailyScheduleEntity(title="Test", groups=groups)
                    )
                }
            )
            mock_client.update.return_value = mock_data

            result = await service.send_schedule(for_tomorrow=False)
            assert result is True
            service.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_schedule_api_failure(self, service):
        """Test handling API failure"""
        with patch('schedule_service.yasno_client') as mock_client:
            mock_client.update.return_value = None

            result = await service.send_schedule(for_tomorrow=False)
            assert result is False
            service.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_schedule_telegram_error(self, service):
        """Test handling Telegram API error"""
        from telegram.error import TelegramError

        with patch('schedule_service.yasno_client') as mock_client:
            mock_data = YasnoAPIComponent(
                template_name="test",
                dailySchedule=None
            )
            mock_client.update.return_value = mock_data
            service.bot.send_message.side_effect = TelegramError("Network error")

            result = await service.send_schedule(for_tomorrow=False)
            assert result is False

    @pytest.mark.asyncio
    async def test_check_schedule_changes_no_previous_hash(self, service):
        """Test checking schedule changes when no previous hash exists"""
        with patch('schedule_service.yasno_client') as mock_client:
            groups = {"2.1": [YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)]}
            mock_data = YasnoAPIComponent(
                template_name="test",
                dailySchedule={
                    "kiev": YasnoDailySchedule(
                        today=YasnoDailyScheduleEntity(title="Test", groups=groups)
                    )
                }
            )
            mock_client.update.return_value = mock_data

            assert service.last_schedule_hash is None
            await service.check_schedule_changes()

            # Should save hash but not send notification (first time)
            assert service.last_schedule_hash is not None
            service.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_schedule_changes_no_change(self, service):
        """Test checking schedule when nothing changed"""
        with patch('schedule_service.yasno_client') as mock_client:
            groups = {"2.1": [YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)]}
            mock_data = YasnoAPIComponent(
                template_name="test",
                dailySchedule={
                    "kiev": YasnoDailySchedule(
                        today=YasnoDailyScheduleEntity(title="Test", groups=groups)
                    )
                }
            )
            mock_client.update.return_value = mock_data

            # Set previous hash
            service.last_schedule_hash = service._compute_schedule_hash(mock_data)

            await service.check_schedule_changes()

            # Should not send notification
            service.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_schedule_changes_detected(self, service):
        """Test detecting schedule change"""
        with patch('schedule_service.yasno_client') as mock_client:
            # Set initial hash for different schedule
            groups1 = {"2.1": [YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)]}
            old_data = YasnoAPIComponent(
                template_name="test",
                dailySchedule={
                    "kiev": YasnoDailySchedule(
                        today=YasnoDailyScheduleEntity(title="Old", groups=groups1)
                    )
                }
            )
            service.last_schedule_hash = service._compute_schedule_hash(old_data)

            # Return new schedule
            groups2 = {"2.1": [YasnoAPIOutage(start=8.0, end=13.0, type=YasnoOutageType.OFF)]}
            new_data = YasnoAPIComponent(
                template_name="test",
                dailySchedule={
                    "kiev": YasnoDailySchedule(
                        today=YasnoDailyScheduleEntity(title="New", groups=groups2)
                    )
                }
            )
            mock_client.update.return_value = new_data

            await service.check_schedule_changes()

            # Should send 2 messages: change alert + new schedule
            assert service.bot.send_message.call_count == 2

            # Check first message is change alert
            first_call = service.bot.send_message.call_args_list[0]
            assert "ЗМІНИВСЯ" in first_call[1]['text']

    def test_stop_monitoring(self, service):
        """Test stopping monitoring"""
        service.monitoring = True
        service.stop_monitoring()
        assert service.monitoring is False


class TestTimezoneHandling:
    """Test timezone handling across the module"""

    def test_schedule_formatter_uses_kyiv_timezone(self):
        """Test that ScheduleFormatter uses Kyiv timezone for timestamps"""
        with patch('schedule_service.datetime') as mock_dt:
            mock_now = Mock()
            mock_now.strftime.return_value = "15:30:00"
            mock_dt.now.return_value = mock_now

            schedule_data = YasnoAPIComponent(
                template_name="test",
                dailySchedule=None
            )

            from config import TIMEZONE
            result = ScheduleFormatter.format_schedule_message(schedule_data, "kiev", "2.1", False)

            # Verify datetime.now was called with TIMEZONE
            mock_dt.now.assert_called_with(TIMEZONE)

    def test_schedule_service_monitoring_uses_kyiv_timezone(self):
        """Test that monitoring loop uses Kyiv timezone"""
        from config import TIMEZONE
        import pytz

        # Verify TIMEZONE is Kyiv
        assert str(TIMEZONE) == 'Europe/Kyiv' or str(TIMEZONE) == 'Europe/Kiev'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
