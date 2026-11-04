import logging
import threading
import asyncio
from datetime import datetime
from typing import Optional, Dict
from light_bot.formatters.power_status_formatter import PowerStatusFormatter
from light_bot.core.bot import get_webapp_inline_keyboard

logger = logging.getLogger(__name__)


class OutageAlertManager:
    """
    Manages delayed Telegram notifications for power outages (off state).
    
    Filters out short-lived network/sensor glitches and brief sub-minute power dips:
    - When power becomes 'off', starts a timer (default 40s).
    - If power returns to 'on' before the timer fires: cancels timer and SUPPRESSES
      both the 'power off' alert and the 'power on' alert (no spam for transient glitches).
    - If outage persists beyond delay: sends the official Telegram alert with the exact
      original outage timestamp.
    - When power subsequently returns to 'on': sends the 'power on' alert with full outage duration.
    """

    def __init__(
        self,
        delay_seconds: int = 40,
        telegram_bot = None
    ):
        self.delay_seconds = delay_seconds
        self._telegram_bot = telegram_bot
        self._lock = threading.Lock()
        self._states: Dict[str, dict] = {}

    @property
    def telegram_bot(self):
        if self._telegram_bot is not None:
            return self._telegram_bot
        try:
            import light_bot.core.server as srv
            return getattr(srv, 'telegram_bot', None)
        except Exception:
            return None

    def schedule_outage_alert(
        self,
        location,
        timestamp: datetime,
        duration_text: Optional[str] = None,
        voltage: Optional[float] = None
    ):
        """Schedule a delayed notification for power outage"""
        location_id = location.id
        with self._lock:
            existing = self._states.get(location_id)
            if existing and existing.get('pending'):
                # Already pending debounce: keep original start_time
                if voltage is not None:
                    existing['latest_voltage'] = voltage
                return

            if existing and existing.get('timer'):
                existing['timer'].cancel()

            if self.delay_seconds <= 0:
                # Immediate notification mode (e.g. in tests or when delay is disabled)
                state = {
                    'location': location,
                    'start_time': timestamp,
                    'duration_text': duration_text,
                    'voltage': voltage,
                    'latest_voltage': voltage,
                    'pending': False,
                    'alert_sent': True,
                    'timer': None
                }
                self._states[location_id] = state
                self._send_alert_message(state)
                return

            state = {
                'location': location,
                'start_time': timestamp,
                'duration_text': duration_text,
                'voltage': voltage,
                'latest_voltage': voltage,
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
                f"Scheduled delayed outage alert for {location_id} in {self.delay_seconds}s "
                f"(outage timestamp: {timestamp.isoformat()})"
            )

    def _get_bot(self):
        return self.telegram_bot

    def _send_alert_message(self, state: dict):
        """Helper to format and send power off Telegram message"""
        location = state['location']
        start_time = state['start_time']
        duration_text = state['duration_text']
        voltage = state.get('latest_voltage', state.get('voltage'))

        loc_display_name = None if location.id == 'home' else location.name
        message = PowerStatusFormatter.format_power_off_message(
            start_time,
            duration_text=duration_text,
            location_name=loc_display_name,
            voltage=voltage
        )

        bot = self._get_bot()
        target_chat = location.channel_id or (bot.channel_id if bot else None)
        keyboard = get_webapp_inline_keyboard(location.id)
        self._send_telegram(message, target_chat, reply_markup=keyboard)

    def _on_timer_fired(self, location_id: str):
        """Callback when outage persisted for delay_seconds"""
        state = None
        with self._lock:
            state = self._states.get(location_id)
            if not state or not state.get('pending'):
                return
            state['pending'] = False
            state['alert_sent'] = True

        logger.info(
            f"Outage persisted for {self.delay_seconds}s at {location_id}. "
            f"Sending Telegram alert (outage time: {state['start_time']})"
        )
        self._send_alert_message(state)

    def cancel(self, location_id: str) -> bool:
        """
        Cancel any pending outage alert for the given location.
        Returns:
            bool: True if outage alert was already sent to Telegram, False if suppressed.
        """
        with self._lock:
            state = self._states.pop(location_id, None)
            if not state:
                return False
            timer = state.get('timer')
            if timer:
                timer.cancel()
            was_sent = state.get('alert_sent', False)

        if not was_sent:
            logger.info(
                f"Suppressed short-lived outage alert for {location_id} "
                f"(duration was < {self.delay_seconds}s)"
            )
        return was_sent

    def is_alert_sent(self, location_id: str) -> bool:
        """Check if an outage alert was already sent for the given location"""
        with self._lock:
            state = self._states.get(location_id)
            return state.get('alert_sent', False) if state else False

    def is_pending(self, location_id: str) -> bool:
        """Check if an outage alert is currently pending delay"""
        with self._lock:
            state = self._states.get(location_id)
            return state.get('pending', False) if state else False

    def _send_telegram(self, message: str, chat_id: Optional[str] = None, reply_markup=None):
        """Send message using thread's event loop"""
        bot = self._get_bot()
        if not bot:
            logger.warning("No telegram bot configured for outage alert manager")
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
            logger.error(f"Failed to send delayed outage alert to Telegram: {e}")
