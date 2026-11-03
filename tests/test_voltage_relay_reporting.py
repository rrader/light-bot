import json
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock


@pytest.fixture
def client():
    """Create Flask test client"""
    with patch('light_bot.core.server.telegram_bot') as mock_bot:
        mock_bot.send_message = AsyncMock(return_value=True)
        from light_bot.core.server import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client


class TestVoltageAndRelayReporting:
    """Test voltage and before/after relay power status reporting"""

    @pytest.fixture
    def auth_headers(self):
        return {'Authorization': 'test_api_token_123'}

    def test_both_relays_true_resolves_to_on(self, client, auth_headers):
        response = client.post(
            '/power-status',
            headers=auth_headers,
            json={
                'before_relay': True,
                'after_relay': True,
                'voltage': 230.5,
                'source': 'ha',
                'location': 'home'
            }
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert data['power_status'] == 'on'
        assert data['voltage'] == 230.5
        assert data['before_relay'] is True
        assert data['after_relay'] is True
        assert data['source'] == 'ha'

    def test_before_true_after_false_resolves_to_unstable(self, client, auth_headers):
        response = client.post(
            '/power-status',
            headers=auth_headers,
            json={
                'before_relay': True,
                'after_relay': False,
                'voltage': 260.0,
                'source': 'ha'
            }
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert data['power_status'] == 'unstable'
        assert data['voltage'] == 260.0
        assert data['before_relay'] is True
        assert data['after_relay'] is False

    def test_impossible_state_rejected(self, client, auth_headers):
        # after_relay cannot be True when before_relay is False
        response = client.post(
            '/power-status',
            headers=auth_headers,
            json={
                'before_relay': False,
                'after_relay': True,
                'source': 'ha'
            }
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert 'Impossible' in data['error']

    def test_both_relays_false_resolves_to_off(self, client, auth_headers):
        response = client.post(
            '/power-status',
            headers=auth_headers,
            json={
                'before_relay': False,
                'after_relay': False,
                'voltage': 0.0,
                'source': 'ha'
            }
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert data['power_status'] == 'off'
        assert data['before_relay'] is False
        assert data['after_relay'] is False

    def test_kebab_case_support(self, client, auth_headers):
        response = client.post(
            '/power-status',
            headers=auth_headers,
            json={
                'before-relay': True,
                'after-relay': True,
                'napruga': 225.2,
                'source': 'ha'
            }
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['power_status'] == 'on'
        assert data['voltage'] == 225.2

    def test_backward_compatibility_legacy_status(self, client, auth_headers):
        # Router sends {"status": "on"} without any relay flags
        response = client.post(
            '/power-status',
            headers=auth_headers,
            json={'status': 'on'}
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['power_status'] == 'on'

    def test_get_status_reflects_voltage_and_relays(self, client, auth_headers):
        # Report status with voltage and relay
        client.post(
            '/power-status',
            headers=auth_headers,
            json={
                'before_relay': True,
                'after_relay': True,
                'voltage': 229.4,
                'source': 'ha'
            }
        )

        # GET /power-status
        response = client.get('/power-status', headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'on'
        assert data['voltage'] == 229.4
        assert data['before_relay'] is True
        assert data['after_relay'] is True
        assert data['source'] == 'ha'

        # GET public /api/power-status
        pub_resp = client.get('/api/power-status')
        assert pub_resp.status_code == 200
        pub_data = json.loads(pub_resp.data)
        assert pub_data['status'] == 'on'
        assert pub_data['voltage'] == 229.4
        assert pub_data['before_relay'] is True
        assert pub_data['after_relay'] is True
        assert pub_data['source'] == 'ha'
