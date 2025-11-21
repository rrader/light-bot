import pytest
import sqlite3
import os
from datetime import datetime, timedelta
from light_bot.services.stats_service import StatsService
from light_bot.models.power_event import PowerEvent
from light_bot.config import TIMEZONE

@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test_stats.db"
    return str(path)

@pytest.fixture
def stats_service(db_path):
    return StatsService(db_path)

def test_init_db(stats_service, db_path):
    assert os.path.exists(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='power_events'")
        assert cursor.fetchone() is not None

def test_record_event(stats_service):
    now = datetime.now(TIMEZONE)
    stats_service.record_event('on', now)
    
    events = stats_service.get_recent_events()
    assert len(events) == 1
    assert events[0].status == 'on'
    # Compare timestamps with some tolerance or just string representation if needed
    # The service stores as ISO string, so we check if it comes back correctly
    assert abs((events[0].timestamp - now).total_seconds()) < 1

def test_get_recent_events_limit(stats_service):
    now = datetime.now(TIMEZONE)
    for i in range(15):
        stats_service.record_event('off', now + timedelta(minutes=i))
        
    events = stats_service.get_recent_events(limit=5)
    assert len(events) == 5
    # Should be the latest ones (highest timestamp)
    assert events[0].timestamp > events[-1].timestamp

def test_get_stats_empty(stats_service):
    stats = stats_service.get_stats()
    assert stats['total_outages'] == 0
    assert stats['total_outage_duration'] == timedelta(0)
    assert stats['last_24h_outage_duration'] == timedelta(0)

def test_get_stats_calculation(stats_service):
    base_time = datetime.now(TIMEZONE) - timedelta(hours=2)
    
    # Outage 1: 2 hours ago, lasted 30 mins
    stats_service.record_event('off', base_time)
    stats_service.record_event('on', base_time + timedelta(minutes=30))
    
    # Outage 2: 1 hour ago, lasted 30 mins
    stats_service.record_event('off', base_time + timedelta(hours=1))
    stats_service.record_event('on', base_time + timedelta(hours=1, minutes=30))
    
    stats = stats_service.get_stats()
    assert stats['total_outages'] == 2
    assert stats['total_outage_duration'] == timedelta(hours=1)
    assert stats['last_24h_outage_duration'] == timedelta(hours=1)

def test_get_stats_ongoing_outage(stats_service):
    base_time = datetime.now(TIMEZONE) - timedelta(minutes=30)
    
    # Outage started 30 mins ago and is still ongoing
    stats_service.record_event('off', base_time)
    
    stats = stats_service.get_stats()
    assert stats['total_outages'] == 1
    # Duration should be approx 30 mins
    assert stats['total_outage_duration'] >= timedelta(minutes=29)
    assert stats['total_outage_duration'] <= timedelta(minutes=31)
