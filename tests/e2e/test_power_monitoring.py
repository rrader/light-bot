"""End-to-end tests for Light Bot"""
import pytest
import os
import tempfile
import time
import subprocess
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock
from light_bot.config import TIMEZONE


class TestEndToEndPowerMonitoring:
    """End-to-end tests simulating real power monitoring scenarios"""

    @pytest.fixture
    def server_setup(self):
        """Setup server with temporary status file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_e2e_power.txt') as f:
            temp_file = f.name

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_file), \
             patch('light_bot.core.server.telegram_bot') as mock_bot:

            mock_bot.send_message = AsyncMock(return_value=True)

            from light_bot.core.server import app
            app.config['TESTING'] = True

            with app.test_client() as client:
                yield client, mock_bot, temp_file

        # Cleanup
        try:
            os.unlink(temp_file)
        except:
            pass

    def test_complete_power_outage_cycle(self, server_setup):
        """
        E2E Test: Simulate a complete power outage cycle

        Scenario:
        1. Initial state: power is ON
        2. Power goes OFF (monitor detects it)
        3. Wait some time (simulated)
        4. Power comes back ON
        5. Verify duration is displayed correctly
        """
        client, mock_bot, temp_file = server_setup
        auth_header = {'Authorization': 'Bearer test_api_token_123'}

        # Step 1: Initial state - power ON
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        assert response.json['status_changed'] is True
        assert mock_bot.send_message.called

        # Verify initial message
        call_args = mock_bot.send_message.call_args
        initial_message = call_args[0][0]
        assert 'Світло з\'явилось!' in initial_message
        assert 'Відключення тривало' not in initial_message  # No previous duration

        mock_bot.send_message.reset_mock()

        # Step 2: Simulate time passing (2 hours) - modify file directly
        with open(temp_file, 'r') as f:
            lines = f.readlines()

        # Rewrite with timestamp 2 hours ago
        two_hours_ago = datetime.now(TIMEZONE) - timedelta(hours=2, minutes=15)
        with open(temp_file, 'w') as f:
            f.write("on\n")
            f.write(f"Last updated: {two_hours_ago.isoformat()}\n")

        # Step 3: Power goes OFF
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'off'})
        assert response.status_code == 200
        assert response.json['status_changed'] is True
        assert mock_bot.send_message.called

        # Verify OFF message with duration
        call_args = mock_bot.send_message.call_args
        off_message = call_args[0][0]
        assert 'Світло зникло' in off_message
        assert 'Світло було' in off_message
        assert '2 години' in off_message
        assert '15 хвилин' in off_message

        mock_bot.send_message.reset_mock()

        # Step 4: Simulate outage duration (45 minutes) - modify file
        with open(temp_file, 'r') as f:
            lines = f.readlines()

        forty_five_min_ago = datetime.now(TIMEZONE) - timedelta(minutes=45)
        with open(temp_file, 'w') as f:
            f.write("off\n")
            f.write(f"Last updated: {forty_five_min_ago.isoformat()}\n")

        # Step 5: Power comes back ON
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        assert response.json['status_changed'] is True
        assert mock_bot.send_message.called

        # Verify ON message with outage duration
        call_args = mock_bot.send_message.call_args
        on_message = call_args[0][0]
        assert 'Світло з\'явилось!' in on_message
        assert 'Відключення тривало' in on_message
        assert '45 хвилин' in on_message

    def test_multiple_rapid_status_changes(self, server_setup):
        """
        E2E Test: Multiple rapid status changes (flapping power)

        Scenario: Power flickers on/off rapidly
        Verify: Each change is tracked with correct durations
        """
        client, mock_bot, temp_file = server_setup
        auth_header = {'Authorization': 'Bearer test_api_token_123'}

        # Initial: Power ON
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        mock_bot.send_message.reset_mock()

        # Simulate 30 seconds passing
        with open(temp_file, 'r') as f:
            lines = f.readlines()
        thirty_sec_ago = datetime.now(TIMEZONE) - timedelta(seconds=30)
        with open(temp_file, 'w') as f:
            f.write("on\n")
            f.write(f"Last updated: {thirty_sec_ago.isoformat()}\n")

        # Power OFF (after 30 seconds)
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'off'})
        assert response.status_code == 200
        call_args = mock_bot.send_message.call_args
        message = call_args[0][0]
        assert 'секунд' in message  # Should show seconds
        mock_bot.send_message.reset_mock()

        # Simulate 15 seconds outage
        fifteen_sec_ago = datetime.now(TIMEZONE) - timedelta(seconds=15)
        with open(temp_file, 'w') as f:
            f.write("off\n")
            f.write(f"Last updated: {fifteen_sec_ago.isoformat()}\n")

        # Power back ON (after 15 seconds)
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        call_args = mock_bot.send_message.call_args
        message = call_args[0][0]
        assert 'Відключення тривало' in message
        assert 'секунд' in message  # Very short outage

    def test_long_outage_multi_day(self, server_setup):
        """
        E2E Test: Long multi-day power outage

        Scenario: Power is out for several days
        Verify: Duration shows days and hours (not minutes)
        """
        client, mock_bot, temp_file = server_setup
        auth_header = {'Authorization': 'Bearer test_api_token_123'}

        # Initial: Power ON
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        mock_bot.send_message.reset_mock()

        # Simulate 3 days and 5 hours passing
        three_days_ago = datetime.now(TIMEZONE) - timedelta(days=3, hours=5, minutes=30)
        with open(temp_file, 'w') as f:
            f.write("on\n")
            f.write(f"Last updated: {three_days_ago.isoformat()}\n")

        # Power goes OFF
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'off'})
        assert response.status_code == 200

        call_args = mock_bot.send_message.call_args
        message = call_args[0][0]
        assert 'Світло було' in message
        assert '3 дні' in message
        assert '5 годин' in message
        # Minutes should NOT be shown for multi-day durations
        assert 'хвилин' not in message

    def test_first_boot_scenario(self, server_setup):
        """
        E2E Test: First boot/deployment scenario

        Scenario: Bot is deployed for the first time, no previous state
        Verify: First notification has no duration
        """
        client, mock_bot, temp_file = server_setup
        auth_header = {'Authorization': 'Bearer test_api_token_123'}

        # Ensure file doesn't exist
        if os.path.exists(temp_file):
            os.unlink(temp_file)

        # First status update ever
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        assert response.json['status_changed'] is True

        call_args = mock_bot.send_message.call_args
        message = call_args[0][0]
        assert 'Світло з\'явилось!' in message
        assert 'Відключення тривало' not in message  # No previous state

    def test_monitor_script_simulation(self, server_setup):
        """
        E2E Test: Simulate monitor.sh behavior

        Scenario: Simulate how the monitoring script would call the API
        - Repeated status checks (unchanged status = no notification)
        - Status change = notification with duration
        """
        client, mock_bot, temp_file = server_setup
        auth_header = {'Authorization': 'Bearer test_api_token_123'}

        # Initial: Power ON
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        assert response.json['notification_sent'] is True
        mock_bot.send_message.reset_mock()

        # Monitor checks again (power still ON) - no notification
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        assert response.json['status_changed'] is False
        assert response.json['notification_sent'] is False
        assert not mock_bot.send_message.called

        # Monitor checks again (power still ON) - no notification
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        assert not mock_bot.send_message.called

        # Simulate 1 hour passing
        one_hour_ago = datetime.now(TIMEZONE) - timedelta(hours=1)
        with open(temp_file, 'w') as f:
            f.write("on\n")
            f.write(f"Last updated: {one_hour_ago.isoformat()}\n")

        # Power goes OFF - notification sent
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'off'})
        assert response.status_code == 200
        assert response.json['status_changed'] is True
        assert response.json['notification_sent'] is True
        assert mock_bot.send_message.called

        call_args = mock_bot.send_message.call_args
        message = call_args[0][0]
        assert '1 година' in message

    def test_realistic_daily_pattern(self, server_setup):
        """
        E2E Test: Realistic daily power pattern

        Scenario: Simulate a typical day with scheduled outages
        - Morning: Power ON (6 hours)
        - Afternoon: Power OFF (3 hours scheduled outage)
        - Evening: Power ON (5 hours)
        - Night: Power OFF (short outage, 30 min)
        - Night: Power ON
        """
        client, mock_bot, temp_file = server_setup
        auth_header = {'Authorization': 'Bearer test_api_token_123'}

        messages_sent = []

        def capture_message(*args, **kwargs):
            messages_sent.append(args[0] if args else kwargs.get('message', ''))
            return AsyncMock(return_value=True)()

        mock_bot.send_message.side_effect = capture_message

        # 06:00 - Power ON (first status)
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        assert len(messages_sent) == 1
        assert 'Світло з\'явилось!' in messages_sent[0]
        assert 'Відключення тривало' not in messages_sent[0]  # First status

        # Simulate 6 hours passing
        six_hours_ago = datetime.now(TIMEZONE) - timedelta(hours=6)
        with open(temp_file, 'w') as f:
            f.write("on\n")
            f.write(f"Last updated: {six_hours_ago.isoformat()}\n")

        # 12:00 - Power OFF (scheduled outage)
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'off'})
        assert response.status_code == 200
        assert len(messages_sent) == 2
        assert 'Світло зникло' in messages_sent[1]
        assert 'Світло було' in messages_sent[1]
        assert '6 годин' in messages_sent[1]

        # Simulate 3 hours outage
        three_hours_ago = datetime.now(TIMEZONE) - timedelta(hours=3)
        with open(temp_file, 'w') as f:
            f.write("off\n")
            f.write(f"Last updated: {three_hours_ago.isoformat()}\n")

        # 15:00 - Power back ON
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        assert len(messages_sent) == 3
        assert 'Відключення тривало' in messages_sent[2]
        assert '3 години' in messages_sent[2]

        # Simulate 5 hours
        five_hours_ago = datetime.now(TIMEZONE) - timedelta(hours=5)
        with open(temp_file, 'w') as f:
            f.write("on\n")
            f.write(f"Last updated: {five_hours_ago.isoformat()}\n")

        # 20:00 - Short power OFF (unscheduled)
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'off'})
        assert response.status_code == 200
        assert len(messages_sent) == 4
        assert '5 годин' in messages_sent[3]

        # Simulate 30 minutes
        thirty_min_ago = datetime.now(TIMEZONE) - timedelta(minutes=30)
        with open(temp_file, 'w') as f:
            f.write("off\n")
            f.write(f"Last updated: {thirty_min_ago.isoformat()}\n")

        # 20:30 - Power back ON
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        assert len(messages_sent) == 5
        assert 'Відключення тривало' in messages_sent[4]
        assert '30 хвилин' in messages_sent[4]

        # Verify we sent exactly 5 messages throughout the day
        assert len(messages_sent) == 5


class TestEndToEndErrorRecovery:
    """E2E tests for error scenarios and recovery"""

    @pytest.fixture
    def server_setup(self):
        """Setup server with temporary status file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_e2e_error.txt') as f:
            temp_file = f.name

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_file), \
             patch('light_bot.core.server.telegram_bot') as mock_bot:

            mock_bot.send_message = AsyncMock(return_value=True)

            from light_bot.core.server import app
            app.config['TESTING'] = True

            with app.test_client() as client:
                yield client, mock_bot, temp_file

        try:
            os.unlink(temp_file)
        except:
            pass

    def test_recovery_from_corrupted_state(self, server_setup):
        """
        E2E Test: Recovery from corrupted state file

        Scenario: State file gets corrupted, bot recovers gracefully
        """
        client, mock_bot, temp_file = server_setup
        auth_header = {'Authorization': 'Bearer test_api_token_123'}

        # Create corrupted state file
        with open(temp_file, 'w') as f:
            f.write("on\n")
            f.write("Last updated: CORRUPTED_TIMESTAMP\n")

        # Should still work, just without duration
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'off'})
        assert response.status_code == 200
        assert response.json['status_changed'] is True

        call_args = mock_bot.send_message.call_args
        message = call_args[0][0]
        assert 'Світло зникло' in message
        # No duration since timestamp was corrupted
        assert 'Світло було' not in message or 'години' not in message

    def test_system_clock_adjustment(self, server_setup):
        """
        E2E Test: System clock gets adjusted backward

        Scenario: System time jumps backward (DST, manual adjustment)
        Verify: Negative duration is handled gracefully
        """
        client, mock_bot, temp_file = server_setup
        auth_header = {'Authorization': 'Bearer test_api_token_123'}

        # Power ON
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'on'})
        assert response.status_code == 200
        mock_bot.send_message.reset_mock()

        # Simulate clock going FORWARD (set timestamp in the future)
        future_time = datetime.now(TIMEZONE) + timedelta(hours=1)
        with open(temp_file, 'w') as f:
            f.write("on\n")
            f.write(f"Last updated: {future_time.isoformat()}\n")

        # Power OFF - should handle negative duration
        response = client.post('/power-status',
                               headers=auth_header,
                               json={'status': 'off'})
        assert response.status_code == 200
        assert response.json['status_changed'] is True

        # Should send message but without duration (negative duration ignored)
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
        message = call_args[0][0]
        assert 'Світло зникло' in message
        # Duration should be skipped for negative duration
