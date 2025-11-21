import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from light_bot.models.power_event import PowerEvent
from light_bot.config import TIMEZONE

logger = logging.getLogger(__name__)

class StatsService:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Initialize the database schema"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS power_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        status TEXT NOT NULL
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    def record_event(self, status: str, timestamp: datetime):
        """Record a power event"""
        try:
            # Ensure timestamp is ISO format string
            timestamp_str = timestamp.isoformat()
            
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO power_events (timestamp, status) VALUES (?, ?)',
                    (timestamp_str, status)
                )
                conn.commit()
                logger.info(f"Recorded power event: {status} at {timestamp_str}")
        except Exception as e:
            logger.error(f"Failed to record power event: {e}")

    def get_recent_events(self, limit: int = 10) -> List[PowerEvent]:
        """Get recent power events"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id, timestamp, status FROM power_events ORDER BY timestamp DESC LIMIT ?',
                    (limit,)
                )
                rows = cursor.fetchall()
                
                events = []
                for row in rows:
                    try:
                        timestamp = datetime.fromisoformat(row[1])
                        # Ensure timezone awareness if missing (assume config timezone)
                        if timestamp.tzinfo is None:
                            timestamp = TIMEZONE.localize(timestamp)
                        
                        events.append(PowerEvent(
                            id=row[0],
                            timestamp=timestamp,
                            status=row[2]
                        ))
                    except ValueError:
                        continue
                return events
        except Exception as e:
            logger.error(f"Failed to get recent events: {e}")
            return []

    def get_stats(self) -> Dict:
        """Calculate statistics for different time windows"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                
                now = datetime.now(TIMEZONE)
                # Look back 31 days to catch outages starting before the 30-day window
                # Assumption: Outages do not exceed 1 day
                query_start = now - timedelta(days=31)
                
                # Get events within the query window
                cursor.execute(
                    'SELECT timestamp, status FROM power_events WHERE timestamp >= ? ORDER BY timestamp ASC',
                    (query_start.isoformat(),)
                )
                rows = cursor.fetchall()
                
                windows = {
                    'last_24h': now - timedelta(hours=24),
                    'last_7d': now - timedelta(days=7),
                    'last_30d': now - timedelta(days=30)
                }
                
                stats = {
                    key: {'count': 0, 'duration': timedelta(0)} 
                    for key in windows
                }

                # Parse events
                events = []
                for ts_str, status in rows:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = TIMEZONE.localize(ts)
                        events.append((ts, status))
                    except ValueError:
                        continue

                # Calculate stats for each window
                for window_name, start_time in windows.items():
                    current_outage_start = None
                    
                    for i, (ts, status) in enumerate(events):
                        if status == 'off':
                            if current_outage_start is None:
                                # If outage started before window, clamp to window start
                                # But only if we are already inside the window or the outage overlaps
                                # Actually, simpler logic: track outage start, and when it ends (or now), add overlap with window
                                current_outage_start = ts
                                
                                # Count outage if it starts within window
                                if ts >= start_time:
                                    stats[window_name]['count'] += 1
                                    
                        elif status == 'on':
                            if current_outage_start is not None:
                                # Calculate overlap
                                outage_end = ts
                                overlap_start = max(current_outage_start, start_time)
                                overlap_end = max(outage_end, start_time) # Ensure end is also after start_time
                                
                                if overlap_end > overlap_start:
                                    stats[window_name]['duration'] += (overlap_end - overlap_start)
                                
                                # If outage started before window but ended in window, it counts as 1 outage for this window?
                                # Requirement says "total outages ... count". Usually means count of outages that *occurred* (even partially) or started?
                                # Let's stick to "started within window" for count to avoid double counting if we were aggregating, 
                                # but for "last 24h" user usually wants to know how many times lights went off.
                                # If it went off 25h ago and turned on 23h ago, it's 1 outage in last 24h context? Maybe not.
                                # Let's count if the outage has ANY overlap with the window.
                                if current_outage_start < start_time and outage_end > start_time:
                                     stats[window_name]['count'] += 1

                                current_outage_start = None

                    # Handle ongoing outage
                    if current_outage_start is not None:
                        overlap_start = max(current_outage_start, start_time)
                        overlap_end = max(now, start_time)
                        
                        if overlap_end > overlap_start:
                            stats[window_name]['duration'] += (overlap_end - overlap_start)
                            
                        if current_outage_start < start_time and now > start_time:
                             stats[window_name]['count'] += 1

                return stats

        except Exception as e:
            logger.error(f"Failed to calculate stats: {e}")
            return {}

    def get_daily_history(self, days: int = 30) -> List[Dict]:
        """Get daily outage statistics for the last N days"""
        try:
            now = datetime.now(TIMEZONE)
            start_date = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Initialize daily buckets
            daily_stats = {}
            current_day = start_date
            while current_day <= now:
                date_str = current_day.strftime('%Y-%m-%d')
                daily_stats[date_str] = {'date': date_str, 'count': 0, 'duration_seconds': 0}
                current_day += timedelta(days=1)

            with self._get_conn() as conn:
                cursor = conn.cursor()
                # Get events starting from a bit before start_date to catch ongoing outages
                query_start = (start_date - timedelta(days=1)).isoformat()
                cursor.execute(
                    'SELECT timestamp, status FROM power_events WHERE timestamp >= ? ORDER BY timestamp ASC',
                    (query_start,)
                )
                rows = cursor.fetchall()

                events = []
                for ts_str, status in rows:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = TIMEZONE.localize(ts)
                        events.append((ts, status))
                    except ValueError:
                        continue

                current_outage_start = None
                
                # We need to handle the state *before* our query window
                # Ideally we'd query the last event before query_start to know initial state
                # For now, let's assume if first event is ON, we might have missed an OFF. 
                # But simpler: just process the stream.
                
                for ts, status in events:
                    if status == 'off':
                        if current_outage_start is None:
                            current_outage_start = ts
                            
                            # Count outage for the day it started
                            # Only if it started within our requested range
                            if ts >= start_date:
                                date_key = ts.strftime('%Y-%m-%d')
                                if date_key in daily_stats:
                                    daily_stats[date_key]['count'] += 1
                                    
                    elif status == 'on':
                        if current_outage_start is not None:
                            outage_end = ts
                            
                            # Distribute duration across days
                            # Iterate days from start to end of outage
                            
                            # Clamp outage to start_date for duration calculation
                            calc_start = max(current_outage_start, start_date)
                            calc_end = outage_end # Don't clamp end yet, logic below handles it
                            
                            if calc_end > calc_start:
                                # Split by days
                                temp_curr = calc_start
                                while temp_curr < calc_end:
                                    # End of current day
                                    day_end = (temp_curr + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                                    
                                    # Segment end is min(outage_end, day_end)
                                    segment_end = min(calc_end, day_end)
                                    
                                    duration = (segment_end - temp_curr).total_seconds()
                                    date_key = temp_curr.strftime('%Y-%m-%d')
                                    
                                    if date_key in daily_stats:
                                        daily_stats[date_key]['duration_seconds'] += duration
                                    
                                    temp_curr = segment_end

                            current_outage_start = None

                # Handle ongoing outage
                if current_outage_start is not None:
                    calc_start = max(current_outage_start, start_date)
                    calc_end = now
                    
                    if calc_end > calc_start:
                        temp_curr = calc_start
                        while temp_curr < calc_end:
                            day_end = (temp_curr + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                            segment_end = min(calc_end, day_end)
                            
                            duration = (segment_end - temp_curr).total_seconds()
                            date_key = temp_curr.strftime('%Y-%m-%d')
                            
                            if date_key in daily_stats:
                                daily_stats[date_key]['duration_seconds'] += duration
                            
                            temp_curr = segment_end

            return list(daily_stats.values())

        except Exception as e:
            logger.error(f"Failed to get daily history: {e}")
            return []
