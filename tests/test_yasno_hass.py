"""
Comprehensive tests for yasno_hass module
"""
import pytest
from datetime import datetime, timedelta
import pytz

from yasno_hass import (
    YasnoAPIClient,
    client,
    to_datetime,
    to_outage,
    merge_intervals,
    YasnoAPIComponent,
    YasnoAPIOutage,
    YasnoOutageType,
    KYIV_TZ,
)


class TestTimezoneConstants:
    """Test timezone configuration"""

    def test_kyiv_timezone_defined(self):
        """Test that KYIV_TZ is properly defined"""
        assert KYIV_TZ is not None
        assert str(KYIV_TZ) in ['Europe/Kyiv', 'Europe/Kiev']

    def test_kyiv_timezone_is_utc_plus_2_or_3(self):
        """Test that Kyiv timezone has correct UTC offset"""
        now = datetime.now(KYIV_TZ)
        offset_hours = now.utcoffset().total_seconds() / 3600
        # Kyiv is UTC+2 (winter) or UTC+3 (summer DST)
        assert offset_hours in [2, 3]


class TestToDatetimeFunction:
    """Test to_datetime utility function"""

    def test_to_datetime_whole_hour(self):
        """Test converting whole hour float to datetime"""
        result = to_datetime(8.0)

        assert result.hour == 8
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 0
        assert result.tzinfo is not None

    def test_to_datetime_half_hour(self):
        """Test converting half hour float to datetime"""
        result = to_datetime(12.5)

        assert result.hour == 12
        assert result.minute == 30
        assert result.second == 0
        assert result.microsecond == 0

    def test_to_datetime_various_times(self):
        """Test converting various time values"""
        test_cases = [
            (0.0, 0, 0),
            (0.5, 0, 30),
            (6.0, 6, 0),
            (6.5, 6, 30),
            (12.0, 12, 0),
            (12.5, 12, 30),
            (18.0, 18, 0),
            (18.5, 18, 30),
            (23.0, 23, 0),
            (23.5, 23, 30),
        ]

        for time_float, expected_hour, expected_minute in test_cases:
            result = to_datetime(time_float)
            assert result.hour == expected_hour, f"Failed for {time_float}"
            assert result.minute == expected_minute, f"Failed for {time_float}"

    def test_to_datetime_24_hour(self):
        """Test converting 24.0 (end of day) to datetime"""
        result = to_datetime(24.0)

        # 24:00 should be converted to 23:59:59
        assert result.hour == 23
        assert result.minute == 59
        assert result.second == 59

    def test_to_datetime_has_timezone(self):
        """Test that returned datetime has Kyiv timezone"""
        result = to_datetime(12.0)

        assert result.tzinfo is not None
        assert str(result.tzinfo) in ['Europe/Kyiv', 'Europe/Kiev']

    def test_to_datetime_preserves_date(self):
        """Test that to_datetime preserves current date"""
        result = to_datetime(10.0)
        now = datetime.now(KYIV_TZ)

        assert result.year == now.year
        assert result.month == now.month
        assert result.day == now.day


class TestToOutageFunction:
    """Test to_outage utility function"""

    def test_to_outage_today(self):
        """Test creating outage for today"""
        outage = to_outage(8.0, 12.0, today=True, outage_type=YasnoOutageType.OFF)

        assert isinstance(outage.start, datetime)
        assert isinstance(outage.end, datetime)
        assert outage.start.hour == 8
        assert outage.end.hour == 12
        assert outage.type == YasnoOutageType.OFF
        assert outage.start.tzinfo is not None
        assert outage.end.tzinfo is not None

    def test_to_outage_tomorrow(self):
        """Test creating outage for tomorrow"""
        outage = to_outage(8.0, 12.0, today=False, outage_type=YasnoOutageType.OFF)

        now = datetime.now(KYIV_TZ)
        tomorrow = now + timedelta(days=1)

        assert outage.start.day == tomorrow.day
        assert outage.end.day == tomorrow.day

    def test_to_outage_half_hours(self):
        """Test creating outage with half-hour times"""
        outage = to_outage(8.5, 12.5, today=True, outage_type=YasnoOutageType.OFF)

        assert outage.start.hour == 8
        assert outage.start.minute == 30
        assert outage.end.hour == 12
        assert outage.end.minute == 30

    def test_to_outage_span_calculation(self):
        """Test that outage duration is calculated correctly"""
        outage = to_outage(8.0, 12.0, today=True, outage_type=YasnoOutageType.OFF)

        duration = outage.end - outage.start
        expected_duration = timedelta(hours=4)

        assert duration == expected_duration


class TestMergeIntervalsFunction:
    """Test merge_intervals utility function"""

    def test_merge_intervals_empty_list(self):
        """Test merging empty list"""
        result = merge_intervals([], today=True)
        assert result == []

    def test_merge_intervals_single_interval(self):
        """Test merging single interval"""
        intervals = [
            YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)
        ]

        result = merge_intervals(intervals, today=True)

        assert len(result) == 1
        assert result[0].start.hour == 8
        assert result[0].end.hour == 12

    def test_merge_intervals_consecutive(self):
        """Test merging consecutive intervals"""
        intervals = [
            YasnoAPIOutage(start=8.0, end=8.5, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=8.5, end=9.0, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=9.0, end=9.5, type=YasnoOutageType.OFF),
        ]

        result = merge_intervals(intervals, today=True)

        # Should merge into single interval
        assert len(result) == 1
        assert result[0].start.hour == 8
        assert result[0].start.minute == 0
        assert result[0].end.hour == 9
        assert result[0].end.minute == 30

    def test_merge_intervals_non_consecutive(self):
        """Test merging non-consecutive intervals"""
        intervals = [
            YasnoAPIOutage(start=8.0, end=9.0, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=12.0, end=13.0, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=16.0, end=17.0, type=YasnoOutageType.OFF),
        ]

        result = merge_intervals(intervals, today=True)

        # Should not merge
        assert len(result) == 3

    def test_merge_intervals_mixed(self):
        """Test merging mix of consecutive and non-consecutive intervals"""
        intervals = [
            YasnoAPIOutage(start=8.0, end=8.5, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=8.5, end=9.0, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=12.0, end=13.0, type=YasnoOutageType.OFF),
        ]

        result = merge_intervals(intervals, today=True)

        # Should merge first two, keep third separate
        assert len(result) == 2
        assert result[0].start.hour == 8
        assert result[0].end.hour == 9
        assert result[1].start.hour == 12
        assert result[1].end.hour == 13

    def test_merge_intervals_preserves_timezone(self):
        """Test that merged intervals preserve timezone"""
        intervals = [
            YasnoAPIOutage(start=8.0, end=8.5, type=YasnoOutageType.OFF),
            YasnoAPIOutage(start=8.5, end=9.0, type=YasnoOutageType.OFF),
        ]

        result = merge_intervals(intervals, today=True)

        assert result[0].start.tzinfo is not None
        assert result[0].end.tzinfo is not None

    def test_merge_intervals_tomorrow_flag(self):
        """Test that tomorrow flag correctly adds one day"""
        intervals = [
            YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)
        ]

        result_today = merge_intervals(intervals, today=True)
        result_tomorrow = merge_intervals(intervals, today=False)

        # Tomorrow's date should be one day ahead
        date_diff = (result_tomorrow[0].start - result_today[0].start).days
        assert date_diff == 1


class TestYasnoAPIClient:
    """Test YasnoAPIClient class"""

    def test_client_singleton_exists(self):
        """Test that global client instance exists"""
        assert client is not None
        assert isinstance(client, YasnoAPIClient)

    def test_api_url_is_correct(self):
        """Test that API URL is configured correctly"""
        expected_url = "https://api.yasno.com.ua/api/v1/pages/home/schedule-turn-off-electricity"
        assert client._api_url == expected_url

    def test_template_name_is_correct(self):
        """Test that template name is configured correctly"""
        assert client._TEMPLATE_NAME == "electricity-outages-daily-schedule"

    @pytest.mark.integration
    def test_update_returns_data_or_none(self):
        """Integration test: API call returns either data or None"""
        result = client.update()

        # Should return either YasnoAPIComponent or None
        assert result is None or isinstance(result, YasnoAPIComponent)

    @pytest.mark.integration
    def test_update_structure_when_successful(self):
        """Integration test: Check response structure when API succeeds"""
        result = client.update()

        if result is not None:
            assert hasattr(result, 'template_name')
            assert hasattr(result, 'available_regions')
            assert hasattr(result, 'dailySchedule')
            assert isinstance(result.available_regions, list)


class TestYasnoAPIOutage:
    """Test YasnoAPIOutage model"""

    def test_yasno_api_outage_creation(self):
        """Test creating YasnoAPIOutage instance"""
        outage = YasnoAPIOutage(
            start=8.0,
            end=12.0,
            type=YasnoOutageType.OFF
        )

        assert outage.start == 8.0
        assert outage.end == 12.0
        assert outage.type == YasnoOutageType.OFF

    def test_yasno_outage_type_enum(self):
        """Test YasnoOutageType enum values"""
        assert YasnoOutageType.OFF.value == "DEFINITE_OUTAGE"

    def test_yasno_api_outage_validation(self):
        """Test Pydantic validation for YasnoAPIOutage"""
        # Should accept valid data
        outage = YasnoAPIOutage(start=8.0, end=12.0, type=YasnoOutageType.OFF)
        assert outage is not None

        # Should raise error for invalid data
        with pytest.raises(Exception):
            YasnoAPIOutage(start="invalid", end=12.0, type=YasnoOutageType.OFF)


class TestYasnoAPIComponent:
    """Test YasnoAPIComponent model"""

    def test_component_creation_minimal(self):
        """Test creating component with minimal data"""
        component = YasnoAPIComponent(
            template_name="test-template"
        )

        assert component.template_name == "test-template"
        assert component.available_regions == []
        assert component.dailySchedule is None
        assert component.schedule is None

    def test_component_creation_full(self):
        """Test creating component with full data"""
        from yasno_hass.models import YasnoDailySchedule

        component = YasnoAPIComponent(
            template_name="electricity-outages-daily-schedule",
            available_regions=["kiev", "dnipro"],
            title="Графік відключень",
            lastRegistryUpdateTime=1234567890,
            dailySchedule={"kiev": YasnoDailySchedule()}
        )

        assert component.template_name == "electricity-outages-daily-schedule"
        assert len(component.available_regions) == 2
        assert "kiev" in component.available_regions
        assert component.title == "Графік відключень"

    def test_component_date_title_extraction(self):
        """Test extracting date from title"""
        from yasno_hass.models import YasnoDailySchedule, YasnoDailyScheduleEntity

        today_entity = YasnoDailyScheduleEntity(
            title="Понеділок, 28.10.2025 на 00:00",
            groups={}
        )

        component = YasnoAPIComponent(
            template_name="test",
            dailySchedule={
                "kiev": YasnoDailySchedule(today=today_entity)
            }
        )

        date = component.date_title_today
        assert date is not None
        assert date.day == 28
        assert date.month == 10
        assert date.year == 2025


class TestIntegration:
    """Integration tests for the whole module"""

    @pytest.mark.integration
    def test_full_workflow_with_real_api(self):
        """Test complete workflow: API call -> merge intervals -> format"""
        # This test requires network access
        schedule_data = client.update()

        if schedule_data and schedule_data.dailySchedule:
            city_schedule = schedule_data.dailySchedule.get("kiev")
            if city_schedule and city_schedule.today:
                groups = city_schedule.today.groups
                if "2.1" in groups:
                    outages = groups["2.1"]
                    merged = merge_intervals(outages, today=True)

                    # Verify merged intervals are valid
                    assert all(isinstance(o.start, datetime) for o in merged)
                    assert all(isinstance(o.end, datetime) for o in merged)
                    assert all(o.start.tzinfo is not None for o in merged)

    def test_module_exports(self):
        """Test that all expected functions/classes are exported"""
        from yasno_hass import __all__

        expected_exports = [
            "YasnoAPIClient",
            "client",
            "YasnoAPIComponent",
            "YasnoAPIResponse",
            "YasnoDailySchedule",
            "YasnoAPIOutage",
            "YasnoOutageType",
            "YasnoOutage",
            "DailyGroupSchedule",
            "SensorEntityData",
            "merge_intervals",
            "to_datetime",
            "to_outage",
        ]

        for export in expected_exports:
            assert export in __all__, f"{export} not in __all__"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
