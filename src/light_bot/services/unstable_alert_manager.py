import logging
import threading
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from light_bot.formatters.power_status_formatter import PowerStatusFormatter
from light_bot.core.bot import get_webapp_inline_keyboard

logger = logging.getLogger(__name__)


def _now():
    return datetime.now().astimezone()


class UnstableAlertManager:
    """
    Manages delayed Telegram notifications for unstable power state.
    
    Filters out short-lived voltage spikes:
    - When power becomes 'unstable', starts a timer (default 180s = 3 min).
    - If power returns to 'on' before the timer fires: cancels timer and SUPPRESSES
      both the 'unstable' alert and the 'power on' alert (no spam for short spikes).
    - If instability persists beyond delay: selects the extreme voltage (furthest from 230V)
      observed during the entire period (both min and max) and sends Telegram alert.
    - If power turns 'off' (outage) before timer fires: cancels timer and allows normal 'off' alert.
    """

    def __init__(
        self,
        delay_seconds: int = 180,
        telegram_bot = None,
        stats_service = None,
        nominal_voltage: float = 230.0,
        frequent_threshold: int = 3,
        frequent_window_seconds: int = 3600,
        frequent_cooldown_seconds: int = 7200,
        stabilization_seconds: int = 3600
    ):
        self.delay_seconds = delay_seconds
        self._telegram_bot = telegram_bot
        self.stats_service = stats_service
        self.nominal_voltage = nominal_voltage
        self.frequent_threshold = frequent_threshold
        self.frequent_window_seconds = frequent_window_seconds
        self.frequent_cooldown_seconds = frequent_cooldown_seconds
        self.stabilization_seconds = stabilization_seconds
        self._lock = threading.Lock()
        self._states: Dict[str, dict] = {}
        self._unstable_history: Dict[str, list] = {}
        self._last_frequent_alert_sent: Dict[str, datetime] = {}
        self._stabilization_timers: Dict[str, threading.Timer] = {}

    @property
    def telegram_bot(self):
        if self._telegram_bot is not None:
            return self._telegram_bot
        try:
            import light_bot.core.server as srv
            return getattr(srv, 'telegram_bot', None)
        except Exception:
            return None

    def record_voltage(self, location_id: str, voltage: Optional[float]):
        """Record intermediate voltage readings while unstable alert is pending or active"""
        if voltage is None or voltage <= 0:
            return
        with self._lock:
            state = self._states.get(location_id)
            if not state:
                return
            min_v = state.get('min_voltage')
            max_v = state.get('max_voltage')
            state['min_voltage'] = min(min_v, voltage) if min_v is not None else voltage
            state['max_voltage'] = max(max_v, voltage) if max_v is not None else voltage
            state['latest_voltage'] = voltage

    def schedule_unstable_alert(
        self,
        location,
        timestamp: datetime,
        duration_text: Optional[str] = None,
        voltage: Optional[float] = None
    ):
        """
        Schedule a delayed notification for unstable power.
        If cutoffs reach frequent_threshold (3) within frequent_window_seconds (1h),
        send a frequent instability alert immediately (rate-limited by frequent_cooldown_seconds).
        """
        location_id = location.id
        with self._lock:
            # Any new instability interrupts the one-hour stable period.
            stabilization_timer = self._stabilization_timers.pop(location_id, None)
            if stabilization_timer:
                stabilization_timer.cancel()

            # 1. Track this cutoff in event history
            history = self._unstable_history.setdefault(location_id, [])
            history.append(timestamp)

            # Prune events older than frequent_window_seconds
            cutoff_window = timestamp - timedelta(seconds=self.frequent_window_seconds)
            history = [t for t in history if t >= cutoff_window]
            self._unstable_history[location_id] = history

            # Check DB count as well (in case service restarted)
            db_count = 0
            if self.stats_service and hasattr(self.stats_service, 'count_events'):
                try:
                    res = self.stats_service.count_events(
                        location_id, 'unstable', since=cutoff_window
                    )
                    if isinstance(res, (int, float)):
                        db_count = int(res)
                except Exception as ex:
                    logger.warning(f"Could not count unstable events from DB for {location_id}: {ex}")
            event_count = max(len(history), db_count)

            # 2. Alert once the configured count is reached (3 by default).
            frequent_triggered = False
            if event_count >= self.frequent_threshold:
                last_alert = self._last_frequent_alert_sent.get(location_id)
                if last_alert is None or (timestamp - last_alert).total_seconds() >= self.frequent_cooldown_seconds:
                    frequent_triggered = True
                    self._last_frequent_alert_sent[location_id] = timestamp

            # Cancel any existing timer for this location
            old_state = self._states.get(location_id)
            if old_state and old_state.get('timer'):
                old_state['timer'].cancel()

            state = {
                'location': location,
                'start_time': timestamp,
                'duration_text': duration_text,
                'initial_voltage': voltage,
                'latest_voltage': voltage,
                'min_voltage': voltage if (voltage and voltage > 0) else None,
                'max_voltage': voltage if (voltage and voltage > 0) else None,
                'pending': not frequent_triggered,
                'alert_sent': frequent_triggered,
                'frequent_alert_sent': frequent_triggered,
                'timer': None
            }

            if frequent_triggered:
                self._states[location_id] = state
                logger.info(
                    f"Frequent instability threshold exceeded for {location_id}: "
                    f"{event_count} cutoffs in last {self.frequent_window_seconds}s "
                    f"(threshold {self.frequent_threshold}). Sending Telegram alert immediately."
                )
                self._send_frequent_alert(location, timestamp, event_count, voltage)
            else:
                timer = threading.Timer(
                    self.delay_seconds,
                    self._on_timer_fired,
                    args=(location_id,)
                )
                timer.daemon = True
                state['timer'] = timer
                self._states[location_id] = state
                timer.start()
                logger.info(
                    f"Scheduled delayed unstable alert for {location_id} in {self.delay_seconds}s "
                    f"(cutoff {event_count}/{self.frequent_threshold} in window, initial voltage: {voltage}V)"
                )

    def schedule_stabilization_alert(
        self,
        location,
        voltage: Optional[float] = None,
        min_voltage: Optional[float] = None,
        max_voltage: Optional[float] = None
    ):
        """Send a recovery notice only after power remains stable for one hour."""
        location_id = location.id
        with self._lock:
            old_timer = self._stabilization_timers.pop(location_id, None)
            if old_timer:
                old_timer.cancel()

            timer = threading.Timer(
                self.stabilization_seconds,
                self._on_stabilization_timer_fired,
                args=(location, voltage, min_voltage, max_voltage)
            )
            timer.daemon = True
            self._stabilization_timers[location_id] = timer
            timer.start()
        logger.info(
            f"Scheduled stabilization notice for {location_id} after "
            f"{self.stabilization_seconds}s without instability"
        )

    def _on_stabilization_timer_fired(
        self,
        location,
        voltage: Optional[float],
        min_voltage: Optional[float],
        max_voltage: Optional[float]
    ):
        location_id = location.id
        with self._lock:
            self._stabilization_timers.pop(location_id, None)

        message = PowerStatusFormatter.format_power_on_message(
            _now(),
            location_name=None if location_id == 'home' else location.name,
            voltage=voltage,
            was_unstable=True,
            min_voltage=min_voltage,
            max_voltage=max_voltage
        )
        bot = self._get_bot()
        target_chat = location.channel_id or (bot.channel_id if bot else None)
        keyboard = get_webapp_inline_keyboard(location_id)
        logger.info(f"Power remained stable for one hour at {location_id}; sending recovery notice")
        self._send_telegram(message, target_chat, reply_markup=keyboard)

    def cancel_stabilization_alert(self, location_id: str):
        """Cancel a pending recovery notice when instability resumes."""
        with self._lock:
            timer = self._stabilization_timers.pop(location_id, None)
            if timer:
                timer.cancel()

    def _send_frequent_alert(
        self,
        location,
        timestamp: datetime,
        count: int,
        voltage: Optional[float] = None
    ):
        """Send Telegram notification for frequent instability/cutoffs."""
        location_id = location.id
        min_v = voltage if (voltage and voltage > 0) else None
        max_v = voltage if (voltage and voltage > 0) else None

        if self.stats_service:
            since = timestamp - timedelta(seconds=self.frequent_window_seconds)
            db_min, db_max = self.stats_service.get_voltage_extrema(location_id, since=since)
            if db_min is not None:
                min_v = min(min_v, db_min) if min_v is not None else db_min
            if db_max is not None:
                max_v = max(max_v, db_max) if max_v is not None else db_max

        extreme_voltage = self.calculate_extreme_voltage(min_v, max_v, voltage)
        loc_display_name = None if location_id == 'home' else location.name

        message = PowerStatusFormatter.format_frequent_unstable_message(
            timestamp=timestamp,
            count=count,
            window_hours=max(1, round(self.frequent_window_seconds / 3600)),
            location_name=loc_display_name,
            voltage=extreme_voltage,
            min_voltage=min_v,
            max_voltage=max_v
        )

        bot = self._get_bot()
        target_chat = location.channel_id or (bot.channel_id if bot else None)
        keyboard = get_webapp_inline_keyboard(location_id)
        logger.info(
            f"Sending frequent instability Telegram alert for {location_id}: "
            f"{count} cutoffs in 1h, extreme voltage: {extreme_voltage}V"
        )
        self._send_telegram(message, target_chat, reply_markup=keyboard)

    def _get_bot(self):
        return self.telegram_bot

    def _on_timer_fired(self, location_id: str):
        """Callback when instability persisted for delay_seconds"""
        state = None
        with self._lock:
            state = self._states.get(location_id)
            if not state or not state.get('pending'):
                return
            state['pending'] = False
            state['alert_sent'] = True

        location = state['location']
        start_time = state['start_time']
        duration_text = state['duration_text']

        # Calculate min and max from memory and database
        min_v = state.get('min_voltage')
        max_v = state.get('max_voltage')
        if self.stats_service:
            db_min, db_max = self.stats_service.get_voltage_extrema(location_id, since=start_time)
            if db_min is not None:
                min_v = min(min_v, db_min) if min_v is not None else db_min
            if db_max is not None:
                max_v = max(max_v, db_max) if max_v is not None else db_max

        # Pick the voltage furthest from nominal (230V)
        extreme_voltage = self.calculate_extreme_voltage(min_v, max_v, state.get('latest_voltage'))

        loc_display_name = None if location.id == 'home' else location.name
        message = PowerStatusFormatter.format_power_unstable_message(
            start_time,
            duration_text=duration_text,
            location_name=loc_display_name,
            voltage=extreme_voltage,
            min_voltage=min_v,
            max_voltage=max_v
        )

        bot = self._get_bot()
        target_chat = location.channel_id or (bot.channel_id if bot else None)
        logger.info(
            f"Instability persisted for {self.delay_seconds}s at {location_id}. "
            f"Sending Telegram alert with extreme voltage: {extreme_voltage}V (min={min_v}, max={max_v})"
        )
        keyboard = get_webapp_inline_keyboard(location_id)
        self._send_telegram(message, target_chat, reply_markup=keyboard)

    def calculate_extreme_voltage(
        self,
        min_v: Optional[float],
        max_v: Optional[float],
        fallback: Optional[float] = None
    ) -> Optional[float]:
        """
        Return the voltage furthest from nominal 230V.
        If |max_v - 230| >= |min_v - 230|, return max_v.
        Otherwise return min_v.
        """
        if min_v is not None and max_v is not None:
            dev_max = abs(max_v - self.nominal_voltage)
            dev_min = abs(min_v - self.nominal_voltage)
            return max_v if dev_max >= dev_min else min_v
        if max_v is not None:
            return max_v
        if min_v is not None:
            return min_v
        return fallback

    def cancel(self, location_id: str) -> Tuple[bool, Optional[float], Optional[float]]:
        """
        Cancel any pending unstable alert for the given location.
        Returns:
            Tuple[bool, Optional[float], Optional[float]]:
                (alert_was_sent, min_voltage, max_voltage)
        """
        with self._lock:
            state = self._states.pop(location_id, None)
            if not state:
                return False, None, None
            timer = state.get('timer')
            if timer:
                timer.cancel()
            was_sent = state.get('alert_sent', False)
            start_time = state.get('start_time')
            min_v = state.get('min_voltage')
            max_v = state.get('max_voltage')

        # Check DB for full window of readings
        if self.stats_service and start_time:
            db_min, db_max = self.stats_service.get_voltage_extrema(location_id, since=start_time)
            if db_min is not None:
                min_v = min(min_v, db_min) if min_v is not None else db_min
            if db_max is not None:
                max_v = max(max_v, db_max) if max_v is not None else db_max

        if not was_sent:
            logger.info(
                f"Suppressed short-lived unstable alert for {location_id} "
                f"(duration was < {self.delay_seconds}s)"
            )
        return was_sent, min_v, max_v

    def is_alert_sent(self, location_id: str) -> bool:
        """Check if an unstable alert was already sent for the given location"""
        with self._lock:
            state = self._states.get(location_id)
            return state.get('alert_sent', False) if state else False

    def is_pending(self, location_id: str) -> bool:
        """Check if an unstable alert is currently pending delay"""
        with self._lock:
            state = self._states.get(location_id)
            return state.get('pending', False) if state else False

    def _send_telegram(self, message: str, chat_id: Optional[str] = None, reply_markup=None):
        """Send message using thread's event loop"""
        bot = self._get_bot()
        if not bot:
            logger.warning("No telegram bot configured for unstable alert manager")
            return
        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            loop.run_until_complete(
                bot.send_message(message, chat_id=chat_id, reply_markup=reply_markup)
            )
        except Exception as e:
            logger.error(f"Failed to send delayed unstable alert to Telegram: {e}")
