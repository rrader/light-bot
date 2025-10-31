import pytest
import json
import os
import tempfile
import sys
from unittest.mock import patch, Mock, AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


@pytest.fixture
def temp_power_file():
    """Create temporary power status file"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_power.txt') as f:
        temp_file = f.name
    yield temp_file
    try:
        os.unlink(temp_file)
    except:
        pass


@pytest.fixture
def client():
    """Create Flask test client"""
    with patch('light_bot.core.server.telegram_bot') as mock_bot:
        # Mock the bot's send_message method
        mock_bot.send_message = AsyncMock(return_value=True)

        from light_bot.core.server import app
        app.config['TESTING'] = True

        with app.test_client() as client:
            yield client


class TestHealthEndpoint:
    """Tests for health check endpoint"""

    def test_health_check(self, client):
        """Test health endpoint returns OK"""
        response = client.get('/health')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'ok'


class TestPowerStatusEndpoint:
    """Tests for power status endpoints"""

    def test_update_power_status_no_auth(self, client):
        """Test update without authentication returns 401"""
        response = client.post('/power-status',
                               json={'status': 'on'})

        assert response.status_code == 401
        data = json.loads(response.data)
        assert 'error' in data
        assert 'Authorization' in data['error']

    def test_update_power_status_invalid_token(self, client):
        """Test update with invalid token returns 403"""
        response = client.post('/power-status',
                               headers={'Authorization': 'wrong_token'},
                               json={'status': 'on'})

        assert response.status_code == 403
        data = json.loads(response.data)
        assert 'error' in data
        assert 'Invalid' in data['error']

    def test_update_power_status_missing_field(self, client):
        """Test update without status field returns 400"""
        response = client.post('/power-status',
                               headers={'Authorization': 'test_api_token_123'},
                               json={})

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert 'status' in data['error']

    def test_update_power_status_invalid_value(self, client):
        """Test update with invalid status value returns 400"""
        response = client.post('/power-status',
                               headers={'Authorization': 'test_api_token_123'},
                               json={'status': 'invalid'})

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert 'on' in data['error'] or 'off' in data['error']

    def test_update_power_status_success_on(self, client, temp_power_file):
        """Test successful power on update"""
        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.asyncio.run') as mock_run:

            response = client.post('/power-status',
                                   headers={'Authorization': 'test_api_token_123'},
                                   json={'status': 'on'})

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'success'
            assert data['power_status'] == 'on'

            # Verify file was written
            with open(temp_power_file, 'r') as f:
                content = f.read()
                assert 'on' in content

    def test_update_power_status_success_off(self, client, temp_power_file):
        """Test successful power off update"""
        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.asyncio.run') as mock_run:

            response = client.post('/power-status',
                                   headers={'Authorization': 'test_api_token_123'},
                                   json={'status': 'off'})

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'success'
            assert data['power_status'] == 'off'

    def test_update_power_status_bearer_token(self, client, temp_power_file):
        """Test authentication with Bearer token prefix"""
        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.asyncio.run') as mock_run:

            response = client.post('/power-status',
                                   headers={'Authorization': 'Bearer test_api_token_123'},
                                   json={'status': 'on'})

            assert response.status_code == 200

    def test_get_power_status_no_auth(self, client):
        """Test get status without authentication returns 401"""
        response = client.get('/power-status')

        assert response.status_code == 401

    def test_get_power_status_success(self, client, temp_power_file):
        """Test successful status retrieval"""
        # Write test data
        with open(temp_power_file, 'w') as f:
            f.write("on\n")
            f.write("Last updated: 2025-10-25T12:00:00\n")

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file):
            response = client.get('/power-status',
                                  headers={'Authorization': 'test_api_token_123'})

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'on'
            assert 'last_updated' in data

    def test_get_power_status_no_file(self, client):
        """Test status retrieval when file doesn't exist"""
        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', '/nonexistent/file.txt'):
            response = client.get('/power-status',
                                  headers={'Authorization': 'test_api_token_123'})

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'Unknown'


class TestAuthenticationDecorator:
    """Tests for API token authentication"""

    def test_auth_decorator_with_valid_token(self, client):
        """Test that decorator allows valid token"""
        response = client.post('/power-status',
                               headers={'Authorization': 'test_api_token_123'},
                               json={'status': 'on'})

        # Should not be 401 or 403
        assert response.status_code != 401
        assert response.status_code != 403

    def test_auth_decorator_case_sensitive(self, client):
        """Test that token comparison is case sensitive"""
        response = client.post('/power-status',
                               headers={'Authorization': 'TEST_API_TOKEN_123'},
                               json={'status': 'on'})

        assert response.status_code == 403


class TestFileOperations:
    """Test file write operations in server"""

    def test_write_power_status_creates_file(self, temp_power_file):
        """Test that write_power_status creates file with correct format"""
        from light_bot.core.server import write_power_status

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file):
            result = write_power_status('on')

            assert result is True
            assert os.path.exists(temp_power_file)

            with open(temp_power_file, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 2
                assert lines[0].strip() == 'on'
                assert 'Last updated:' in lines[1]

    def test_read_power_status_from_file(self, temp_power_file):
        """Test reading power status from file"""
        from light_bot.core.server import read_power_status

        # Write test data
        with open(temp_power_file, 'w') as f:
            f.write("off\n")
            f.write("Last updated: 2025-10-25T12:00:00\n")

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file):
            status = read_power_status()

            assert status['status'] == 'off'
            assert 'Last updated:' in status['last_updated']


class TestErrorHandling:
    """Test error handling in endpoints"""

    def test_malformed_json(self, client):
        """Test handling of malformed JSON"""
        response = client.post('/power-status',
                               headers={
                                   'Authorization': 'test_api_token_123',
                                   'Content-Type': 'application/json'
                               },
                               data='invalid json')

        # Should return 400 or 500
        assert response.status_code in [400, 500]

    def test_empty_request_body(self, client):
        """Test handling of empty request body"""
        response = client.post('/power-status',
                               headers={
                                   'Authorization': 'test_api_token_123',
                                   'Content-Type': 'application/json'
                               },
                               data='{}')

        assert response.status_code == 400


class TestDurationTracking:
    """Test duration tracking in power status updates"""

    def test_duration_calculated_on_status_change(self, client, temp_power_file):
        """Test that duration is calculated when status changes"""
        from datetime import datetime, timedelta
        from light_bot.config import TIMEZONE

        # Write initial state (power was off 2 hours ago)
        two_hours_ago = datetime.now(TIMEZONE) - timedelta(hours=2)
        with open(temp_power_file, 'w') as f:
            f.write("off\n")
            f.write(f"Last updated: {two_hours_ago.isoformat()}\n")

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.telegram_bot') as mock_bot:

            mock_bot.send_message = AsyncMock(return_value=True)

            response = client.post('/power-status',
                                   headers={'Authorization': 'test_api_token_123'},
                                   json={'status': 'on'})

            assert response.status_code == 200
            assert response.json['status_changed'] is True
            assert response.json['notification_sent'] is True

            # Verify send_message was called
            assert mock_bot.send_message.called

            # Verify the message contains duration information
            call_args = mock_bot.send_message.call_args
            message = call_args[0][0] if call_args[0] else call_args[1].get('message', '')
            assert 'Відключення тривало' in message
            assert 'години' in message or 'годин' in message

    def test_no_duration_on_first_update(self, client, temp_power_file):
        """Test that first update has no duration"""
        # Remove file to simulate first update
        if os.path.exists(temp_power_file):
            os.unlink(temp_power_file)

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.telegram_bot') as mock_bot:

            mock_bot.send_message = AsyncMock(return_value=True)

            response = client.post('/power-status',
                                   headers={'Authorization': 'test_api_token_123'},
                                   json={'status': 'on'})

            assert response.status_code == 200

            # Verify send_message was called
            assert mock_bot.send_message.called

            # Message should not contain duration
            call_args = mock_bot.send_message.call_args
            message = call_args[0][0] if call_args[0] else call_args[1].get('message', '')
            assert 'Відключення тривало' not in message

    def test_duration_with_naive_timestamp(self, client, temp_power_file):
        """Test handling of timezone-naive timestamp"""
        from datetime import datetime, timedelta
        from light_bot.config import TIMEZONE

        # Write timestamp without timezone info (naive datetime)
        one_hour_ago = datetime.now(TIMEZONE) - timedelta(hours=1)
        naive_timestamp = one_hour_ago.replace(tzinfo=None)

        with open(temp_power_file, 'w') as f:
            f.write("off\n")
            f.write(f"Last updated: {naive_timestamp.isoformat()}\n")

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.telegram_bot') as mock_bot:

            mock_bot.send_message = AsyncMock(return_value=True)

            response = client.post('/power-status',
                                   headers={'Authorization': 'test_api_token_123'},
                                   json={'status': 'on'})

            # Should succeed despite naive timestamp
            assert response.status_code == 200

    def test_duration_with_short_interval(self, client, temp_power_file):
        """Test duration display for very short intervals (seconds/minutes)"""
        from datetime import datetime, timedelta
        from light_bot.config import TIMEZONE

        # Power was off just 45 seconds ago
        forty_five_seconds_ago = datetime.now(TIMEZONE) - timedelta(seconds=45)

        with open(temp_power_file, 'w') as f:
            f.write("off\n")
            f.write(f"Last updated: {forty_five_seconds_ago.isoformat()}\n")

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.telegram_bot') as mock_bot:

            mock_bot.send_message = AsyncMock(return_value=True)

            response = client.post('/power-status',
                                   headers={'Authorization': 'test_api_token_123'},
                                   json={'status': 'on'})

            assert response.status_code == 200

            # Verify message contains seconds
            call_args = mock_bot.send_message.call_args
            message = call_args[0][0] if call_args[0] else call_args[1].get('message', '')
            assert 'секунд' in message

    def test_no_duration_on_unchanged_status(self, client, temp_power_file):
        """Test that no notification sent when status doesn't change"""
        from datetime import datetime, timedelta
        from light_bot.config import TIMEZONE

        # Write initial state (power is already on)
        one_hour_ago = datetime.now(TIMEZONE) - timedelta(hours=1)

        with open(temp_power_file, 'w') as f:
            f.write("on\n")
            f.write(f"Last updated: {one_hour_ago.isoformat()}\n")

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.telegram_bot') as mock_bot:

            mock_bot.send_message = AsyncMock(return_value=True)

            # Try to set status to 'on' again
            response = client.post('/power-status',
                                   headers={'Authorization': 'test_api_token_123'},
                                   json={'status': 'on'})

            assert response.status_code == 200
            assert response.json['status_changed'] is False
            assert response.json['notification_sent'] is False

            # Verify send_message was NOT called
            assert not mock_bot.send_message.called

    def test_duration_with_unparseable_timestamp(self, client, temp_power_file):
        """Test handling of unparseable/invalid timestamp"""
        # Write status file with invalid timestamp
        with open(temp_power_file, 'w') as f:
            f.write("off\n")
            f.write("Last updated: Unknown\n")

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.telegram_bot') as mock_bot:

            mock_bot.send_message = AsyncMock(return_value=True)

            response = client.post('/power-status',
                                   headers={'Authorization': 'test_api_token_123'},
                                   json={'status': 'on'})

            # Should succeed without crashing
            assert response.status_code == 200
            assert response.json['status_changed'] is True

            # Verify send_message was called (but without duration)
            assert mock_bot.send_message.called
            call_args = mock_bot.send_message.call_args
            message = call_args[0][0] if call_args[0] else call_args[1].get('message', '')
            # Should not contain duration since timestamp was unparseable
            assert 'Відключення тривало' not in message

    def test_duration_with_corrupted_file(self, client, temp_power_file):
        """Test handling of corrupted status file (missing timestamp line)"""
        # Write status file with only status, no timestamp line
        with open(temp_power_file, 'w') as f:
            f.write("off\n")
            # No timestamp line

        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', temp_power_file), \
             patch('light_bot.core.server.telegram_bot') as mock_bot:

            mock_bot.send_message = AsyncMock(return_value=True)

            response = client.post('/power-status',
                                   headers={'Authorization': 'test_api_token_123'},
                                   json={'status': 'on'})

            # Should succeed without crashing
            assert response.status_code == 200
            assert response.json['status_changed'] is True
