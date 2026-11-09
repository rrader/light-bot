import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from light_bot.models.power_event import PowerEvent
from light_bot.models.schedule_history import ScheduleHistory
from light_bot.config import TIMEZONE, DB_PATH

logger = logging.getLogger(__name__)

class StatsService:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH
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
                        status TEXT NOT NULL,
                        location TEXT DEFAULT 'home',
                        voltage REAL,
                        source TEXT,
                        before_relay INTEGER,
                        after_relay INTEGER
                    )
                ''')
                # Migrate existing table if columns are missing
                for col_name, col_type in [
                    ("location", "TEXT DEFAULT 'home'"),
                    ("voltage", "REAL"),
                    ("source", "TEXT"),
                    ("before_relay", "INTEGER"),
                    ("after_relay", "INTEGER"),
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE power_events ADD COLUMN {col_name} {col_type}")
                    except sqlite3.OperationalError:
                        pass

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS voltage_readings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        location TEXT NOT NULL,
                        voltage REAL,
                        before_relay INTEGER,
                        after_relay INTEGER,
                        source TEXT,
                        voltage_min REAL,
                        voltage_max REAL
                    )
                ''')
                # Migrate voltage_readings table if columns are missing
                for col_name, col_type in [
                    ("voltage_min", "REAL"),
                    ("voltage_max", "REAL"),
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE voltage_readings ADD COLUMN {col_name} {col_type}")
                    except sqlite3.OperationalError:
                        pass
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_voltage_readings_loc_ts 
                    ON voltage_readings(location, timestamp)
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS schedule_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id TEXT NOT NULL,
                        schedule_text TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS bot_channel_buttons (
                        chat_id TEXT PRIMARY KEY,
                        message_id INTEGER NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS pending_stabilization_alerts (
                        location TEXT PRIMARY KEY,
                        recovery_timestamp TEXT NOT NULL,
                        due_timestamp TEXT NOT NULL,
                        voltage REAL,
                        min_voltage REAL,
                        max_voltage REAL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS location_notification_state (
                        location TEXT PRIMARY KEY,
                        last_notified_status TEXT NOT NULL,
                        last_notified_timestamp TEXT NOT NULL,
                        last_power_on_timestamp TEXT,
                        last_power_off_timestamp TEXT,
                        updated_at TEXT NOT NULL
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    def get_last_button_message_id(self, chat_id: str | int) -> Optional[int]:
        """Get the message_id that currently has the active WebApp button for chat_id"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT message_id FROM bot_channel_buttons WHERE chat_id = ?', (str(chat_id),))
                row = cursor.fetchone()
                return int(row[0]) if row else None
        except Exception as e:
            logger.error(f"Failed to get last button message id for {chat_id}: {e}")
            return None

    def set_last_button_message_id(self, chat_id: str | int, message_id: int):
        """Update or insert the message_id having the active WebApp button"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''INSERT INTO bot_channel_buttons (chat_id, message_id, updated_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(chat_id) DO UPDATE SET message_id = excluded.message_id, updated_at = excluded.updated_at''',
                    (str(chat_id), message_id, datetime.now(TIMEZONE).isoformat())
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to set last button message id for {chat_id}: {e}")

    def record_schedule_history(self, group_id: str, schedule_text: str, timestamp: datetime):
        """Record a schedule history event"""
        try:
            timestamp_str = timestamp.isoformat()
            
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO schedule_history (group_id, schedule_text, timestamp) VALUES (?, ?, ?)',
                    (group_id, schedule_text, timestamp_str)
                )
                conn.commit()
                logger.info(f"Recorded schedule history for group {group_id} at {timestamp_str}")
        except Exception as e:
            logger.error(f"Failed to record schedule history for group {group_id}: {e}")

    def get_schedule_history(self, group_id: str, limit: int = 10) -> List[ScheduleHistory]:
        """Get recent schedule history for a group"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id, group_id, schedule_text, timestamp FROM schedule_history WHERE group_id = ? ORDER BY timestamp DESC LIMIT ?',
                    (group_id, limit)
                )
                rows = cursor.fetchall()
                
                history = []
                for row in rows:
                    try:
                        timestamp = datetime.fromisoformat(row[3])
                        if timestamp.tzinfo is None:
                            timestamp = TIMEZONE.localize(timestamp)
                        
                        history.append(ScheduleHistory(
                            id=row[0],
                            group_id=row[1],
                            schedule_text=row[2],
                            timestamp=timestamp
                        ))
                    except ValueError:
                        continue
                return history
        except Exception as e:
            logger.error(f"Failed to get schedule history for group {group_id}: {e}")
            return []

    def get_schedule_history_for_date(self, group_id: str, date_str: str) -> List[ScheduleHistory]:
        """Get the latest recorded schedule snapshot that contains the requested local date."""
        try:
            # Stored snapshots contain ISO dates in today.date / tomorrow.date. Keep the
            # timestamp cutoff inclusive of the full requested day and avoid loading the
            # entire schedule history into the web client.
            next_day = (datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
            with self._get_conn() as conn:
                row = conn.execute(
                    '''SELECT id, group_id, schedule_text, timestamp
                       FROM schedule_history
                       WHERE group_id = ?
                         AND timestamp < ?
                         AND (json_extract(schedule_text, '$.today.date') LIKE ?
                              OR json_extract(schedule_text, '$.tomorrow.date') LIKE ?)
                       ORDER BY timestamp DESC
                       LIMIT 1''',
                    (group_id, f'{next_day}T', f'{date_str}%', f'{date_str}%')
                ).fetchone()
            if not row:
                return []
            timestamp = datetime.fromisoformat(row[3])
            if timestamp.tzinfo is None:
                timestamp = TIMEZONE.localize(timestamp)
            return [ScheduleHistory(id=row[0], group_id=row[1], schedule_text=row[2], timestamp=timestamp)]
        except Exception as e:
            logger.error(f"Failed to get schedule history for {group_id} on {date_str}: {e}")
            return []

    def record_event(
        self,
        status: str,
        timestamp: datetime,
        location: str = 'home',
        voltage: Optional[float] = None,
        source: Optional[str] = None,
        before_relay: Optional[bool] = None,
        after_relay: Optional[bool] = None
    ):
        """Record a power event"""
        try:
            # Ensure timestamp is ISO format string
            timestamp_str = timestamp.isoformat()
            before_int = None if before_relay is None else (1 if before_relay else 0)
            after_int = None if after_relay is None else (1 if after_relay else 0)
            
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''INSERT INTO power_events 
                       (timestamp, status, location, voltage, source, before_relay, after_relay) 
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (timestamp_str, status, location, voltage, source, before_int, after_int)
                )
                conn.commit()
                logger.info(
                    f"Recorded power event: {status} at {timestamp_str} "
                    f"(location: {location}, voltage: {voltage}, source: {source}, "
                    f"before_relay: {before_relay}, after_relay: {after_relay})"
                )
        except Exception as e:
            logger.error(f"Failed to record power event: {e}")

    def record_reading(
        self,
        timestamp: datetime,
        location: str = 'home',
        voltage: Optional[float] = None,
        before_relay: Optional[bool] = None,
        after_relay: Optional[bool] = None,
        source: Optional[str] = None,
        voltage_min: Optional[float] = None,
        voltage_max: Optional[float] = None
    ):
        """Record a telemetry/voltage reading to voltage_readings table"""
        try:
            timestamp_str = timestamp.isoformat()
            before_int = None if before_relay is None else (1 if before_relay else 0)
            after_int = None if after_relay is None else (1 if after_relay else 0)

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''INSERT INTO voltage_readings 
                       (timestamp, location, voltage, before_relay, after_relay, source, voltage_min, voltage_max) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (timestamp_str, location, voltage, before_int, after_int, source, voltage_min, voltage_max)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to record voltage reading: {e}")

    def save_pending_stabilization_alert(
        self, location: str, recovery_timestamp: datetime, due_timestamp: datetime,
        voltage: Optional[float], min_voltage: Optional[float], max_voltage: Optional[float]
    ):
        """Persist a one-hour stability deadline so it survives process restarts."""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    '''INSERT INTO pending_stabilization_alerts
                       (location, recovery_timestamp, due_timestamp, voltage, min_voltage, max_voltage)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(location) DO UPDATE SET
                         recovery_timestamp = excluded.recovery_timestamp,
                         due_timestamp = excluded.due_timestamp,
                         voltage = excluded.voltage,
                         min_voltage = excluded.min_voltage,
                         max_voltage = excluded.max_voltage''',
                    (location, recovery_timestamp.isoformat(), due_timestamp.isoformat(),
                     voltage, min_voltage, max_voltage),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to persist stabilization alert for {location}: {e}")
            return False

    def get_pending_stabilization_alerts(self) -> List[Dict[str, Any]]:
        """Load uncompleted stability deadlines for timer restoration after startup."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    '''SELECT location, recovery_timestamp, due_timestamp, voltage, min_voltage, max_voltage
                       FROM pending_stabilization_alerts'''
                ).fetchall()
            return [
                {
                    "location": row[0],
                    "recovery_timestamp": datetime.fromisoformat(row[1]),
                    "due_timestamp": datetime.fromisoformat(row[2]),
                    "voltage": row[3],
                    "min_voltage": row[4],
                    "max_voltage": row[5],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to load pending stabilization alerts: {e}")
            return []

    def is_current_stabilization(self, location: str, recovery_timestamp: datetime) -> bool:
        """Ensure no off/unstable transition superseded the recovery event."""
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    '''SELECT status, timestamp FROM power_events
                       WHERE location = ? ORDER BY id DESC LIMIT 1''',
                    (location,),
                ).fetchone()
            return bool(
                row and row[0] == "on"
                and datetime.fromisoformat(row[1]) == recovery_timestamp
            )
        except Exception as e:
            logger.error(f"Failed to validate pending stabilization for {location}: {e}")
            return False

    def remove_pending_stabilization_alert(self, location: str):
        """Remove a completed or superseded stability deadline."""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    'DELETE FROM pending_stabilization_alerts WHERE location = ?', (location,)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to remove pending stabilization alert for {location}: {e}")

    def get_notification_state(self, location: str) -> Optional[Dict[str, Any]]:
        """Get the persisted notification state for a location, bootstrapping if needed."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''SELECT last_notified_status, last_notified_timestamp, 
                              last_power_on_timestamp, last_power_off_timestamp 
                       FROM location_notification_state WHERE location = ?''',
                    (location,)
                )
                row = cursor.fetchone()
                if row:
                    def parse_ts(val):
                        if not val:
                            return None
                        try:
                            dt = datetime.fromisoformat(val)
                            if dt.tzinfo is None:
                                dt = TIMEZONE.localize(dt)
                            return dt
                        except Exception:
                            return None

                    return {
                        'last_notified_status': row[0],
                        'last_notified_timestamp': parse_ts(row[1]),
                        'last_power_on_timestamp': parse_ts(row[2]),
                        'last_power_off_timestamp': parse_ts(row[3]),
                    }

                # Bootstrap from recent power events if table is empty
                events = self.get_recent_events(limit=50, location=location)
                if not events:
                    return None

                last_on = None
                last_off = None
                for ev in events:
                    if ev.status == 'on' and last_on is None:
                        last_on = ev.timestamp
                    elif ev.status == 'off' and last_off is None:
                        last_off = ev.timestamp
                    if last_on and last_off:
                        break

                latest_status = events[0].status
                latest_ts = events[0].timestamp
                state = {
                    'last_notified_status': latest_status,
                    'last_notified_timestamp': latest_ts,
                    'last_power_on_timestamp': last_on,
                    'last_power_off_timestamp': last_off,
                }
                self.set_notification_state(
                    location,
                    latest_status,
                    latest_ts,
                    last_power_on=last_on,
                    last_power_off=last_off
                )
                return state
        except Exception as e:
            logger.error(f"Failed to get notification state for {location}: {e}")
            return None

    def set_notification_state(
        self,
        location: str,
        status: str,
        timestamp: datetime,
        last_power_on: Optional[datetime] = None,
        last_power_off: Optional[datetime] = None
    ):
        """Update or insert the last notified state for a location."""
        try:
            if timestamp.tzinfo is None:
                timestamp = TIMEZONE.localize(timestamp)
            ts_str = timestamp.isoformat()
            now_str = datetime.now(TIMEZONE).isoformat()

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT last_power_on_timestamp, last_power_off_timestamp FROM location_notification_state WHERE location = ?',
                    (location,)
                )
                row = cursor.fetchone()
                curr_on = row[0] if row else None
                curr_off = row[1] if row else None

                if status == 'on':
                    on_str = ts_str
                    off_str = last_power_off.isoformat() if last_power_off else curr_off
                elif status == 'off':
                    on_str = last_power_on.isoformat() if last_power_on else curr_on
                    off_str = ts_str
                else:
                    on_str = last_power_on.isoformat() if last_power_on else curr_on
                    off_str = last_power_off.isoformat() if last_power_off else curr_off

                cursor.execute(
                    '''INSERT INTO location_notification_state 
                       (location, last_notified_status, last_notified_timestamp, last_power_on_timestamp, last_power_off_timestamp, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(location) DO UPDATE SET 
                           last_notified_status = excluded.last_notified_status,
                           last_notified_timestamp = excluded.last_notified_timestamp,
                           last_power_on_timestamp = excluded.last_power_on_timestamp,
                           last_power_off_timestamp = excluded.last_power_off_timestamp,
                           updated_at = excluded.updated_at''',
                    (location, status, ts_str, on_str, off_str, now_str)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to set notification state for {location}: {e}")

    def get_voltage_extrema(
        self,
        location: str,
        since: datetime,
        until: Optional[datetime] = None
    ) -> Tuple[Optional[float], Optional[float]]:
        """Return (min_voltage, max_voltage) for a location in the given time window, ignoring 0.0V"""
        try:
            since_str = since.isoformat()
            with self._get_conn() as conn:
                cursor = conn.cursor()
                if until:
                    until_str = until.isoformat()
                    cursor.execute(
                        '''SELECT MIN(voltage), MAX(voltage) FROM voltage_readings 
                           WHERE location = ? AND timestamp >= ? AND timestamp <= ? AND voltage IS NOT NULL AND voltage > 0''',
                        (location, since_str, until_str)
                    )
                else:
                    cursor.execute(
                        '''SELECT MIN(voltage), MAX(voltage) FROM voltage_readings 
                           WHERE location = ? AND timestamp >= ? AND voltage IS NOT NULL AND voltage > 0''',
                        (location, since_str)
                    )
                row = cursor.fetchone()
                if row and row[0] is not None and row[1] is not None:
                    return float(row[0]), float(row[1])
        except Exception as e:
            logger.error(f"Failed to get voltage extrema: {e}")
        return None, None

    def count_events(
        self,
        location: str,
        status: str,
        since: datetime,
        until: Optional[datetime] = None
    ) -> int:
        """Count power events of a given status for a location within a time window"""
        try:
            since_str = since.isoformat()
            with self._get_conn() as conn:
                cursor = conn.cursor()
                if until:
                    until_str = until.isoformat()
                    cursor.execute(
                        'SELECT COUNT(*) FROM power_events WHERE location = ? AND status = ? AND timestamp >= ? AND timestamp <= ?',
                        (location, status, since_str, until_str)
                    )
                else:
                    cursor.execute(
                        'SELECT COUNT(*) FROM power_events WHERE location = ? AND status = ? AND timestamp >= ?',
                        (location, status, since_str)
                    )
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            logger.error(f"Failed to count events for {location}: {e}")
            return 0

    def get_voltage_anomalies(
        self,
        location: str,
        since: datetime,
        until: Optional[datetime] = None,
        min_threshold: float = 207.0,
        max_threshold: float = 253.0
    ) -> List[Dict[str, Any]]:
        """
        Find contiguous time windows in voltage_readings where voltage was outside [min_threshold, max_threshold]
        while grid power was present (before_relay=1, after_relay=1, voltage >= 160V to exclude line disconnects).
        """
        try:
            since_str = since.isoformat()
            query = '''
                SELECT id, timestamp, voltage, voltage_min, voltage_max, before_relay, after_relay
                FROM voltage_readings
                WHERE location = ? AND timestamp >= ? AND voltage IS NOT NULL AND voltage > 0
            '''
            params = [location, since_str]
            if until:
                query += ' AND timestamp <= ?'
                params.append(until.isoformat())
            query += ' ORDER BY id'

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()

            anomalies = []
            current_group = []

            for r in rows:
                rid = r[0]
                ts_str = r[1]
                v = r[2]
                br = r[5]
                ar = r[6]
                # Voltage instability: 160 <= v < min_threshold OR v > max_threshold, while power supplied (br=1, ar=1)
                is_anom = (br == 1 and ar == 1 and ((v >= 160.0 and v < min_threshold) or v > max_threshold))
                if is_anom:
                    current_group.append(r)
                else:
                    if current_group:
                        anomalies.append(current_group)
                        current_group = []
            if current_group:
                anomalies.append(current_group)

            result = []
            for anom in anomalies:
                start_id = anom[0][0]
                start_ts_str = anom[0][1]
                end_ts_str = anom[-1][1]
                try:
                    start_dt = datetime.fromisoformat(start_ts_str)
                except Exception:
                    continue
                try:
                    end_dt = datetime.fromisoformat(end_ts_str)
                except Exception:
                    end_dt = start_dt

                all_min = []
                all_max = []
                for x in anom:
                    v_val = float(x[2])
                    vmin_val = float(x[3]) if len(x) > 3 and x[3] is not None else v_val
                    vmax_val = float(x[4]) if len(x) > 4 and x[4] is not None else v_val
                    all_min.append(vmin_val)
                    all_max.append(vmax_val)

                min_v = round(min(all_min), 1)
                max_v = round(max(all_max), 1)
                dev_min = abs(230.0 - min_v)
                dev_max = abs(max_v - 230.0)
                ext_v = max_v if dev_max >= dev_min else min_v

                dur_sec = max(20, int((end_dt - start_dt).total_seconds()) + 20)
                result.append({
                    'start_id': start_id,
                    'start_ts': start_dt,
                    'end_ts': end_dt,
                    'duration_sec': dur_sec,
                    'voltage': ext_v,
                    'voltage_min': min_v,
                    'voltage_max': max_v
                })
            return result
        except Exception as e:
            logger.error(f"Failed to get voltage anomalies for {location}: {e}")
            return []

    def get_latest_reading(self, location: str) -> Optional[Dict[str, Any]]:
        """Return the most recent telemetry reading from voltage_readings table"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''SELECT timestamp, voltage, source, before_relay, after_relay
                       FROM voltage_readings
                       WHERE location = ?
                       ORDER BY id DESC LIMIT 1''',
                    (location,)
                )
                row = cursor.fetchone()
                if row:
                    return {
                        'timestamp': row[0],
                        'voltage': row[1],
                        'source': row[2],
                        'before_relay': bool(row[3]) if row[3] is not None else None,
                        'after_relay': bool(row[4]) if row[4] is not None else None,
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting latest reading for {location}: {e}")
            return None

    def get_recent_events(self, limit: int = 10, location: Optional[str] = None) -> List[PowerEvent]:
        """Get recent power events, optionally filtered by location"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                if location:
                    cursor.execute(
                        '''SELECT id, timestamp, status, location, voltage, source, before_relay, after_relay 
                           FROM power_events WHERE location = ? ORDER BY timestamp DESC LIMIT ?''',
                        (location, limit)
                    )
                else:
                    cursor.execute(
                        '''SELECT id, timestamp, status, location, voltage, source, before_relay, after_relay 
                           FROM power_events ORDER BY timestamp DESC LIMIT ?''',
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
                        
                        loc = row[3] if len(row) > 3 and row[3] else 'home'
                        volt = row[4] if len(row) > 4 and row[4] is not None else None
                        src = row[5] if len(row) > 5 and row[5] is not None else None
                        b_rel = bool(row[6]) if len(row) > 6 and row[6] is not None else None
                        a_rel = bool(row[7]) if len(row) > 7 and row[7] is not None else None

                        events.append(PowerEvent(
                            id=row[0],
                            timestamp=timestamp,
                            status=row[2],
                            location=loc,
                            voltage=volt,
                            source=src,
                            before_relay=b_rel,
                            after_relay=a_rel
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
            
    def get_last_event(self) -> Optional[PowerEvent]:
        """Get the most recent power event"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id, timestamp, status FROM power_events ORDER BY timestamp DESC LIMIT 1'
                )
                row = cursor.fetchone()
                
                if row:
                    timestamp = datetime.fromisoformat(row[1])
                    if timestamp.tzinfo is None:
                        timestamp = TIMEZONE.localize(timestamp)
                    
                    return PowerEvent(
                        id=row[0],
                        timestamp=timestamp,
                        status=row[2]
                    )
                return None
        except Exception as e:
            logger.error(f"Failed to get last event: {e}")
            return None

    def purge_old_events(self, days_to_keep: int):
        """Purge events older than a specified number of days"""
        try:
            purge_before = datetime.now(TIMEZONE) - timedelta(days=days_to_keep)
            purge_before_str = purge_before.isoformat()
            
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'DELETE FROM power_events WHERE timestamp < ?',
                    (purge_before_str,)
                )
                conn.commit()
                logger.info(f"Purged {cursor.rowcount} events older than {days_to_keep} days")
        except Exception as e:
            logger.error(f"Failed to purge old events: {e}")

    def get_events_for_day(self, target_date: datetime) -> List[PowerEvent]:
        """Get all power events for a specific day"""
        try:
            start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            
            start_str = start_of_day.isoformat()
            end_str = end_of_day.isoformat()

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id, timestamp, status FROM power_events WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp ASC',
                    (start_str, end_str)
                )
                rows = cursor.fetchall()
                
                events = []
                for row in rows:
                    try:
                        timestamp = datetime.fromisoformat(row[1])
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
            logger.error(f"Failed to get events for day {target_date.date()}: {e}")
            return []
            
    def get_outage_periods_for_day(self, target_date: datetime) -> List[Dict]:
        """Get outage periods for a specific day"""
        events = self.get_events_for_day(target_date)
        
        # Need to check the state at the beginning of the day
        # Get the last event before the start of the day
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT status FROM power_events WHERE timestamp < ? ORDER BY timestamp DESC LIMIT 1',
                    (start_of_day.isoformat(),)
                )
                last_event_before = cursor.fetchone()
                initial_status = last_event_before[0] if last_event_before else 'on'
        except Exception as e:
            logger.error(f"Failed to get initial status for day {target_date.date()}: {e}")
            initial_status = 'on'

        periods = []
        current_outage_start = None
        
        if initial_status == 'off':
            current_outage_start = start_of_day

        for event in events:
            if event.status == 'off' and current_outage_start is None:
                current_outage_start = event.timestamp
            elif event.status == 'on' and current_outage_start is not None:
                periods.append({
                    'start': current_outage_start,
                    'end': event.timestamp,
                    'duration': (event.timestamp - current_outage_start).total_seconds()
                })
                current_outage_start = None
        
        # If outage is ongoing at the end of the day
        if current_outage_start is not None:
            end_of_day = start_of_day + timedelta(days=1)
            periods.append({
                'start': current_outage_start,
                'end': end_of_day,
                'duration': (end_of_day - current_outage_start).total_seconds()
            })
            
        return periods
        
    def get_total_outage_duration_for_day(self, target_date: datetime) -> timedelta:
        """Calculate total outage duration for a specific day"""
        periods = self.get_outage_periods_for_day(target_date)
        total_seconds = sum(p['duration'] for p in periods)
        return timedelta(seconds=total_seconds)
        
    def get_outage_free_percentage_for_day(self, target_date: datetime) -> float:
        """Calculate the percentage of time power was on for a specific day"""
        total_duration = self.get_total_outage_duration_for_day(target_date)
        total_seconds_in_day = 24 * 60 * 60
        outage_seconds = total_duration.total_seconds()
        
        on_seconds = total_seconds_in_day - outage_seconds
        return (on_seconds / total_seconds_in_day) * 100 if total_seconds_in_day > 0 else 100
        
    def get_all_events(self) -> List[PowerEvent]:
        """Get all power events (use with caution on large DBs)"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id, timestamp, status FROM power_events ORDER BY timestamp ASC')
                rows = cursor.fetchall()
                
                events = []
                for row in rows:
                    try:
                        timestamp = datetime.fromisoformat(row[1])
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
            logger.error(f"Failed to get all events: {e}")
            return []
            
    def migrate_add_group_id(self):
        """Migration to add group_id column to power_events table"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                
                # Check if column exists
                cursor.execute("PRAGMA table_info(power_events)")
                columns = [col[1] for col in cursor.fetchall()]
                
                if 'group_id' not in columns:
                    logger.info("Adding 'group_id' column to 'power_events' table...")
                    # Add column with a default value (e.g., 1, or a specific group's ID if it's the only one)
                    # Here, let's use a placeholder default like 0 or NULL, depending on requirements.
                    # Let's assume we have a default group with id 'default' or 1.
                    # For simplicity, let's use a default value of 1.
                    cursor.execute('ALTER TABLE power_events ADD COLUMN group_id INTEGER DEFAULT 1')
                    conn.commit()
                    logger.info("Column 'group_id' added successfully.")
                else:
                    logger.info("Column 'group_id' already exists.")
                    
        except Exception as e:
            logger.error(f"Failed to migrate database for group_id: {e}")
            
    def record_event_for_group(self, group_id: str, status: str, timestamp: datetime):
        """Record a power event for a specific group"""
        try:
            timestamp_str = timestamp.isoformat()
            
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO power_events (timestamp, status, group_id) VALUES (?, ?, ?)',
                    (timestamp_str, status, group_id)
                )
                conn.commit()
                logger.info(f"Recorded power event for group {group_id}: {status} at {timestamp_str}")
        except Exception as e:
            logger.error(f"Failed to record power event for group {group_id}: {e}")

    def get_last_event_for_group(self, group_id: str) -> Optional[PowerEvent]:
        """Get the most recent power event for a specific group"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id, timestamp, status FROM power_events WHERE group_id = ? ORDER BY timestamp DESC LIMIT 1',
                    (group_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    timestamp = datetime.fromisoformat(row[1])
                    if timestamp.tzinfo is None:
                        timestamp = TIMEZONE.localize(timestamp)
                    
                    return PowerEvent(
                        id=row[0],
                        timestamp=timestamp,
                        status=row[2],
                        group_id=group_id
                    )
                return None
        except Exception as e:
            logger.error(f"Failed to get last event for group {group_id}: {e}")
            return None
            
    def get_stats_for_group(self, group_id: str) -> Dict:
        """Calculate statistics for a specific group"""
        # This is a simplified version. A full implementation would be similar to get_stats but with a WHERE clause.
        # For now, let's return a placeholder.
        logger.warning("get_stats_for_group is not fully implemented and returns placeholder data.")
        return {
            'last_24h': {'count': 0, 'duration': timedelta(0)},
            'last_7d': {'count': 0, 'duration': timedelta(0)},
            'last_30d': {'count': 0, 'duration': timedelta(0)}
        }
