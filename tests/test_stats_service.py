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
    for window in ['last_24h', 'last_7d', 'last_30d']:
        assert stats[window]['count'] == 0
        assert stats[window]['duration'] == timedelta(0)

def test_get_stats_calculation(stats_service):
    base_time = datetime.now(TIMEZONE)
    
    # Outage 1: 2 hours ago, lasted 30 mins (in 24h, 7d, 30d)
    stats_service.record_event('off', base_time - timedelta(hours=2))
    stats_service.record_event('on', base_time - timedelta(hours=1, minutes=30))
    
    # Outage 2: 2 days ago, lasted 1 hour (in 7d, 30d, NOT 24h)
    stats_service.record_event('off', base_time - timedelta(days=2))
    stats_service.record_event('on', base_time - timedelta(days=2, hours=-1)) # -1 hour from start = +1 hour duration? No, wait.
    # timedelta(days=2, hours=-1) is 1 day, 23 hours ago. 
    # Start: 2 days ago. End: 1 day 23 hours ago. Duration: 1 hour. Correct.
    
    # Let's be more explicit
    outage2_start = base_time - timedelta(days=2)
    outage2_end = base_time - timedelta(days=2) + timedelta(hours=1)
    stats_service.record_event('off', outage2_start)
    stats_service.record_event('on', outage2_end)

    # Outage 3: 10 days ago, lasted 2 hours (in 30d, NOT 7d, NOT 24h)
    outage3_start = base_time - timedelta(days=10)
    outage3_end = base_time - timedelta(days=10) + timedelta(hours=2)
    stats_service.record_event('off', outage3_start)
    stats_service.record_event('on', outage3_end)
    
    stats = stats_service.get_stats()
    
    # Check 24h
    assert stats['last_24h']['count'] == 1
    assert stats['last_24h']['duration'] == timedelta(minutes=30)
    
    # Check 7d (includes outage 1 and 2)
    assert stats['last_7d']['count'] == 2
    assert stats['last_7d']['duration'] == timedelta(hours=1, minutes=30)
    
    # Check 30d (includes outage 1, 2, and 3)
    assert stats['last_30d']['count'] == 3
    assert stats['last_30d']['duration'] == timedelta(hours=3, minutes=30)

def test_get_stats_ongoing_outage(stats_service):
    base_time = datetime.now(TIMEZONE) - timedelta(minutes=30)
    
    # Outage started 30 mins ago and is still ongoing
    stats_service.record_event('off', base_time)
    
    stats = stats_service.get_stats()
    
    for window in ['last_24h', 'last_7d', 'last_30d']:
        assert stats[window]['count'] == 1
        # Duration should be approx 30 mins
        assert stats[window]['duration'] >= timedelta(minutes=29)
        assert stats[window]['duration'] <= timedelta(minutes=31)

def test_get_daily_history(stats_service):
    base_time = datetime.now(TIMEZONE).replace(hour=12, minute=0, second=0, microsecond=0)
    
    # Day 1 (Today): 1 outage, 1 hour
    stats_service.record_event('off', base_time)
    stats_service.record_event('on', base_time + timedelta(hours=1))
    
    # Day 2 (Yesterday): 2 outages, 30 mins each
    yesterday = base_time - timedelta(days=1)
    stats_service.record_event('off', yesterday)
    stats_service.record_event('on', yesterday + timedelta(minutes=30))
    stats_service.record_event('off', yesterday + timedelta(hours=2))
    stats_service.record_event('on', yesterday + timedelta(hours=2, minutes=30))
    
    # Day 3 (2 days ago): No outages
    
    # Day 4 (3 days ago): Outage spanning into Day 3
    # Starts Day 4 23:00, Ends Day 3 01:00
    day4 = base_time - timedelta(days=3)
    stats_service.record_event('off', day4.replace(hour=23))
    stats_service.record_event('on', day4.replace(hour=23) + timedelta(hours=2))
    
    history = stats_service.get_daily_history(days=5)
    
    # Convert to dict for easier lookup
    history_map = {d['date']: d for d in history}
    
    today_str = base_time.strftime('%Y-%m-%d')
    yesterday_str = yesterday.strftime('%Y-%m-%d')
    day3_str = (base_time - timedelta(days=2)).strftime('%Y-%m-%d')
    day4_str = day4.strftime('%Y-%m-%d')
    
    # Check Today
    assert history_map[today_str]['count'] == 1
    assert abs(history_map[today_str]['duration_seconds'] - 3600) < 1
    
    # Check Yesterday
    assert history_map[yesterday_str]['count'] == 2
    assert abs(history_map[yesterday_str]['duration_seconds'] - 3600) < 1
    
    # Check Day 3 (Part of spanning outage)
    # Count should be 0 because outage started on Day 4
    # Duration should be 1 hour (00:00 to 01:00)
    assert history_map[day3_str]['count'] == 0
    assert abs(history_map[day3_str]['duration_seconds'] - 3600) < 1
    
    # Check Day 4 (Start of spanning outage)
    # Count should be 1
    # Duration should be 1 hour (23:00 to 00:00)
    assert history_map[day4_str]['count'] == 1
    assert abs(history_map[day4_str]['duration_seconds'] - 3600) < 1

def test_get_stats_initial_state_off(stats_service):
    """Test that stats are correct when the window starts during an outage"""
    now = datetime.now(TIMEZONE)
    
    # Outage started 30.5 days ago (just before 30d window)
    # This respects the assumption that outages are < 1 day
    start_time = now - timedelta(days=30, hours=12)
    stats_service.record_event('off', start_time)
    
    # Power came back 29.5 days ago (inside 30d window)
    end_time = now - timedelta(days=29, hours=12)
    stats_service.record_event('on', end_time)
    
    stats = stats_service.get_stats()
    
    # 30d stats:
    # Window starts at -30d.
    # Outage ends at -29.5d.
    # Overlap: 0.5 days (12 hours).
    # Count: 1 (because it overlaps)
    
    assert stats['last_30d']['count'] == 1
    # Duration should be approx 12 hours
    duration_hours = stats['last_30d']['duration'].total_seconds() / 3600
    assert 11.9 <= duration_hours <= 12.1
    
    # 7d stats:
    # Window starts at -7d.
    # Outage ended way before.
    # Count: 0
    # Duration: 0
    assert stats['last_7d']['count'] == 0
    assert stats['last_7d']['duration'].total_seconds() == 0
