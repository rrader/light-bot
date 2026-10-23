import pytest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock

from light_bot.core.server import app, stats_service, write_power_status
from light_bot.config import TIMEZONE


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


class TestApiBlueprintEndpoints:
    def test_api_index(self, client):
        response = client.get('/api')
        assert response.status_code == 200
        data = response.get_json()
        assert data['name'] == 'Light Bot API'
        assert '/api/docs' in data['documentation']['interactive_ui']
        assert '/api/openapi.json' in data['documentation']['openapi_spec']
        assert '/api/llms.txt' in data['documentation']['llms_txt']
        assert response.headers.get('Access-Control-Allow-Origin') == 'https://po2.kyiv.ua'

    def test_api_docs_html(self, client):
        response = client.get('/api/docs')
        assert response.status_code == 200
        assert b"SwaggerUIBundle" in response.data
        assert b"/api/openapi.json" in response.data

    def test_root_docs_html(self, client):
        response = client.get('/docs')
        assert response.status_code == 200
        assert b"SwaggerUIBundle" in response.data

    def test_api_openapi_json(self, client):
        response = client.get('/api/openapi.json')
        assert response.status_code == 200
        data = response.get_json()
        assert data['openapi'] == '3.1.0'
        assert '/api/power-status' in data['paths']
        assert '/api/events' in data['paths']
        assert '/api/schedule/{group_id}' in data['paths']

    def test_root_openapi_json(self, client):
        response = client.get('/openapi.json')
        assert response.status_code == 200
        data = response.get_json()
        assert data['openapi'] == '3.1.0'

    def test_api_llms_txt(self, client):
        response = client.get('/api/llms.txt')
        assert response.status_code == 200
        assert b"# Light Bot Public API" in response.data
        assert b"https://light.rmn.pp.ua" in response.data

    def test_root_llms_txt(self, client):
        response = client.get('/llms.txt')
        assert response.status_code == 200
        assert b"# Light Bot Public API" in response.data

    def test_public_power_status_no_auth_required(self, client, tmp_path):
        test_file = str(tmp_path / "test_status.txt")
        with patch('light_bot.core.server.WATCHDOG_STATUS_FILE', test_file):
            write_power_status("on", test_file)
            response = client.get('/api/power-status')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'on'
            assert data['location'] == 'home'
            assert response.headers.get('Access-Control-Allow-Origin') == 'https://po2.kyiv.ua'

    def test_public_power_status_by_location(self, client, tmp_path):
        response = client.get('/api/power-status/home')
        assert response.status_code == 200
        data = response.get_json()
        assert data['location'] == 'home'

    def test_public_power_status_unknown_location(self, client):
        response = client.get('/api/power-status/nonexistent_location')
        assert response.status_code == 404
        data = response.get_json()
        assert 'error' in data

    def test_public_locations(self, client):
        response = client.get('/api/locations')
        assert response.status_code == 200
        data = response.get_json()
        assert 'locations' in data
        assert isinstance(data['locations'], list)
        location_ids = [l['id'] for l in data['locations']]
        assert 'home' in location_ids

    def test_public_events(self, client):
        # Record a test event
        now = datetime.now(TIMEZONE)
        stats_service.record_event('on', now, location='home')

        response = client.get('/api/events?limit=5')
        assert response.status_code == 200
        events = response.get_json()
        assert isinstance(events, list)
        if events:
            assert 'id' in events[0]
            assert 'timestamp' in events[0]
            assert 'status' in events[0]
            assert 'location' in events[0]

    def test_public_history(self, client):
        response = client.get('/api/history?days=7')
        assert response.status_code == 200
        history = response.get_json()
        assert isinstance(history, list)

    def test_public_stats(self, client):
        response = client.get('/api/stats')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    def test_public_schedule_and_history(self, client):
        now = datetime.now(TIMEZONE)
        sample_schedule = {
            "today": {"status": "Normal", "slots": []},
            "tomorrow": {"status": "Normal", "slots": []}
        }
        stats_service.record_schedule_history('home', json.dumps(sample_schedule), now)

        # Test schedule-history
        res_hist = client.get('/api/schedule-history/home')
        assert res_hist.status_code == 200
        data_hist = res_hist.get_json()
        assert isinstance(data_hist, list)
        assert len(data_hist) > 0

        # Test parsed schedule
        res_sched = client.get('/api/schedule/home')
        assert res_sched.status_code == 200
        data_sched = res_sched.get_json()
        assert data_sched['group_id'] == 'home'
        assert data_sched['schedule']['today']['status'] == 'Normal'

    def test_cors_origin_reflection_for_po2(self, client):
        response = client.get('/api/power-status', headers={'Origin': 'https://po2.kyiv.ua'})
        assert response.headers.get('Access-Control-Allow-Origin') == 'https://po2.kyiv.ua'
        assert 'GET' in response.headers.get('Access-Control-Allow-Methods', '')
