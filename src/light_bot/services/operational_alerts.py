"""Low-noise operational alerts for Light Bot's external dependencies."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram import Bot

from light_bot.config import TIMEZONE, YASNO_ADDRESS_GROUP_ALERT_CHAT_ID
from light_bot.services.stats_service import StatsService

logger = logging.getLogger(__name__)


class MonitoredTelegramBot:
    """Proxy Bot that records repeated delivery errors without changing PTB internals."""

    def __init__(self, bot: Bot, alerts: "OperationalAlertMonitor"):
        self._bot = bot
        self._alerts = alerts

    def __getattr__(self, name):
        return getattr(self._bot, name)

    async def send_message(self, *args, **kwargs):
        try:
            result = await self._bot.send_message(*args, **kwargs)
        except Exception:
            self._alerts.record_telegram_failure()
            raise
        await self._alerts.record_telegram_success(self._bot.send_message)
        return result


class OperationalAlertMonitor:
    """Report sustained schedule-provider failures and stale home telemetry."""

    FAILURE_THRESHOLD = 3
    TELEMETRY_STALE_AFTER = timedelta(minutes=10)
    CHECK_INTERVAL = 60

    def __init__(self, bot: Bot, stats_service: StatsService):
        self.bot = bot
        self.stats_service = stats_service
        self.chat_id = YASNO_ADDRESS_GROUP_ALERT_CHAT_ID
        self._schedule_failures = 0
        self._schedule_missing = 0
        self._address_failures = 0
        self._active: set[str] = self.stats_service.get_active_operational_alerts()
        self._last_telemetry_check: Optional[datetime] = None
        self._telegram_failures = 0
        self._telegram_recovery_pending = False

    def record_telegram_failure(self) -> None:
        self._telegram_failures += 1
        if self._telegram_failures >= self.FAILURE_THRESHOLD:
            self._telegram_recovery_pending = True

    async def record_address_lookup(self, succeeded: bool) -> None:
        if succeeded:
            self._address_failures = 0
            await self._set_alert(
                "yasno_address_api", False,
                "✅ API адрес Yasno знову відповідає.",
            )
            return
        self._address_failures += 1
        if self._address_failures >= self.FAILURE_THRESHOLD:
            await self._set_alert(
                "yasno_address_api", True,
                "🔴 API визначення групи Yasno не відповідає "
                f"{self._address_failures} перевірки поспіль.",
            )

    async def record_telegram_success(self, send_raw) -> None:
        if self._telegram_recovery_pending and self.chat_id:
            failures = self._telegram_failures
            self._telegram_recovery_pending = False
            try:
                await send_raw(
                    chat_id=self.chat_id,
                    text="✅ Telegram-доставка Light Bot відновилася. "
                    f"Перед відновленням було щонайменше {failures} помилок надсилання.",
                )
            except Exception:
                logger.exception("Could not send Telegram delivery recovery alert")
                self._telegram_recovery_pending = True
                return
        self._telegram_failures = 0

    async def check_schedule(self, schedule_data, group_configs) -> None:
        """Check provider availability and whether configured groups are present."""
        has_configured_group = any(
            schedule_data.get_group(config.group, city=config.city)
            for config in group_configs if config.group
        )
        if has_configured_group:
            self._schedule_failures = 0
            await self._set_alert(
                "yasno_schedule", False,
                "✅ Yasno знову віддає актуальний графік для Light Bot.",
            )
        else:
            self._schedule_failures += 1
            if self._schedule_failures >= self.FAILURE_THRESHOLD:
                await self._set_alert(
                    "yasno_schedule", True,
                    "🔴 Light Bot не може отримати графік Yasno для жодної налаштованої групи "
                    f"{self._schedule_failures} перевірки поспіль. Перевір API Yasno та логи Light Bot.",
                )

        missing = [
            f"{config.id} ({config.group})" for config in group_configs
            if config.group and not schedule_data.get_group(config.group, city=config.city)
        ]
        if missing:
            self._schedule_missing += 1
            if self._schedule_missing >= self.FAILURE_THRESHOLD:
                await self._set_alert(
                    "schedule_group_missing", True,
                    "⚠️ Yasno не повертає налаштовану групу Light Bot: "
                    + ", ".join(missing) + ". Перевір конфігурацію або відповідь API.",
                )
        else:
            self._schedule_missing = 0
            await self._set_alert(
                "schedule_group_missing", False,
                "✅ Усі налаштовані групи знову присутні у графіку Yasno.",
            )

    async def check_home_telemetry(self) -> None:
        """Alert once when Home Assistant stops reporting, and report recovery."""
        now = datetime.now(TIMEZONE)
        if self._last_telemetry_check and now - self._last_telemetry_check < timedelta(seconds=self.CHECK_INTERVAL):
            return
        self._last_telemetry_check = now

        reading = self.stats_service.get_latest_reading("home")
        if not reading:
            return  # Do not alarm before the first telemetry sample exists.
        try:
            timestamp = datetime.fromisoformat(reading["timestamp"])
            if timestamp.tzinfo is None:
                timestamp = TIMEZONE.localize(timestamp)
            stale = now - timestamp > self.TELEMETRY_STALE_AFTER
            minutes = max(0, int((now - timestamp).total_seconds() // 60))
        except (KeyError, TypeError, ValueError):
            logger.warning("Cannot parse latest home telemetry timestamp")
            return

        if stale:
            await self._set_alert(
                "home_telemetry", True,
                f"🔴 Light Bot не отримував телеметрію home {minutes} хвилин. "
                "Перевір Home Assistant, мережу та інтеграцію Light Bot.",
            )
        else:
            await self._set_alert(
                "home_telemetry", False,
                "✅ Телеметрія home від Home Assistant знову надходить.",
            )

    async def _set_alert(self, key: str, active: bool, message: str) -> None:
        if active == (key in self._active):
            return
        if not self.chat_id:
            return
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=message)
        except Exception:
            logger.exception("Failed to send operational alert %s", key)
            return
        if not self.stats_service.set_operational_alert_active(key, active):
            # The Telegram transition was delivered, but retaining the old in-memory state
            # lets the next check retry persistence instead of silently forgetting it.
            logger.error("Telegram alert %s sent but state transition was not persisted", key)
            return
        if active:
            self._active.add(key)
            logger.error("Operational alert active: %s", key)
        else:
            self._active.discard(key)
            logger.info("Operational alert recovered: %s", key)

    async def run(self, is_running) -> None:
        while is_running():
            try:
                await self.check_home_telemetry()
            except Exception:
                logger.exception("Operational telemetry check failed")
            await asyncio.sleep(self.CHECK_INTERVAL)
