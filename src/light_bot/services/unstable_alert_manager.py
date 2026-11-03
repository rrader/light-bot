import logging
import threading
import asyncio
from datetime import datetime
from typing import Optional, Dict, Tuple
from light_bot.formatters.power_status_formatter import PowerStatusFormatter

logger = logging.getLogger(__name__)


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
        nominal_voltage: float = 230.0
    ):
        self.delay_seconds = delay_seconds
        self.telegram_bot = telegram_bot
        self.stats_service = stats_service
        self.nominal_voltage = nominal_voltage
        self._lock = threading.Lock()
        self._states: Dict[str, dict] = {}

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
        """Schedule a delayed notification for unstable power"""
        location_id = location.id
        with self._lock:
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
                'pending': True,
                'alert_sent': False,
                'timer': None
            }

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
                f"(initial voltage: {voltage}V)"
            )

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

        target_chat = location.channel_id or (self.telegram_bot.channel_id if self.telegram_bot else None)
        logger.info(
            f"Instability persisted for {self.delay_seconds}s at {location_id}. "
            f"Sending Telegram alert with extreme voltage: {extreme_voltage}V (min={min_v}, max={max_v})"
        )
        self._send_telegram(message, target_chat)

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

    def _send_telegram(self, message: str, chat_id: Optional[str] = None):
        """Send message using an isolated event loop for thread safety"""
        if not self.telegram_bot:
            logger.warning("No telegram bot configured for unstable alert manager")
            return
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.telegram_bot.send_message(message, chat_id=chat_id))
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Failed to send delayed unstable alert to Telegram: {e}")
