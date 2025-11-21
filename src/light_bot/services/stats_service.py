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
        """Calculate statistics"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                
                # Get all events ordered by time
                cursor.execute('SELECT timestamp, status FROM power_events ORDER BY timestamp ASC')
                rows = cursor.fetchall()
                
                if not rows:
                    return {
                        'total_outages': 0,
                        'total_outage_duration': timedelta(0),
                        'last_24h_outage_duration': timedelta(0)
                    }

                total_outages = 0
                total_outage_duration = timedelta(0)
                last_24h_outage_duration = timedelta(0)
                
                now = datetime.now(TIMEZONE)
                last_24h = now - timedelta(hours=24)

                # Process events to calculate durations
                # This is a simplified calculation assuming alternating ON/OFF
                # For more robustness, we might need more complex logic
                
                current_outage_start = None
                
                for i in range(len(rows)):
                    ts_str, status = rows[i]
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = TIMEZONE.localize(ts)
                    except ValueError:
                        continue

                    if status == 'off':
                        if current_outage_start is None:
                            current_outage_start = ts
                            total_outages += 1
                    elif status == 'on':
                        if current_outage_start is not None:
                            duration = ts - current_outage_start
                            total_outage_duration += duration
                            
                            # Calculate overlap with last 24h
                            # Case 1: Outage entirely within last 24h
                            if current_outage_start >= last_24h:
                                last_24h_outage_duration += duration
                            # Case 2: Outage started before last 24h but ended after
                            elif ts > last_24h:
                                last_24h_outage_duration += (ts - last_24h)
                            
                            current_outage_start = None

                # Handle ongoing outage
                if current_outage_start is not None:
                    duration = now - current_outage_start
                    total_outage_duration += duration
                    
                    if current_outage_start >= last_24h:
                        last_24h_outage_duration += duration
                    elif now > last_24h:
                        last_24h_outage_duration += (now - last_24h)

                return {
                    'total_outages': total_outages,
                    'total_outage_duration': total_outage_duration,
                    'last_24h_outage_duration': last_24h_outage_duration
                }

        except Exception as e:
            logger.error(f"Failed to calculate stats: {e}")
            return {}
