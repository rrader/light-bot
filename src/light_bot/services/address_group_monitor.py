"""Alert when Yasno changes the outage group assigned to a monitored address."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Iterable

import requests
from telegram import Bot

from light_bot.config import (
    DATA_DIR,
    YASNO_ADDRESS_GROUP_ALERT_CHAT_ID,
    YASNO_ADDRESS_GROUP_CHECK_INTERVAL,
    YASNO_ADDRESS_GROUP_MONITOR_URL,
)
from light_bot.models.group_config import GroupConfig

logger = logging.getLogger(__name__)


class AddressGroupMonitor:
    """Periodically compare Yasno's address mapping with Light Bot's group."""

    def __init__(self, bot: Bot, group_configs: Iterable[GroupConfig]):
        self.bot = bot
        self.group_configs = list(group_configs)
        self.enabled = bool(
            YASNO_ADDRESS_GROUP_MONITOR_URL
            and YASNO_ADDRESS_GROUP_ALERT_CHAT_ID
            and YASNO_ADDRESS_GROUP_CHECK_INTERVAL > 0
        )
        data_dir = Path(DATA_DIR) if DATA_DIR and DATA_DIR != '.' else Path('.')
        self.state_path = data_dir / 'yasno_address_group_last_alert.json'
        self._last_check = 0.0
        if (YASNO_ADDRESS_GROUP_MONITOR_URL or YASNO_ADDRESS_GROUP_ALERT_CHAT_ID) and not self.enabled:
            logger.warning("Yasno address group monitoring is partially configured and will remain disabled")

    async def check_if_due(self) -> None:
        """Run one check when the configured polling interval has elapsed."""
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self._last_check < YASNO_ADDRESS_GROUP_CHECK_INTERVAL:
            return
        self._last_check = now
        await self.check()

    async def check(self) -> None:
        """Fetch the address group and send at most one alert per mismatch."""
        home_config = next((config for config in self.group_configs if config.id == 'home'), None)
        if not home_config or not home_config.group:
            logger.error("Cannot check Yasno address mapping: home group is not configured")
            return

        try:
            response = await asyncio.to_thread(
                requests.get, YASNO_ADDRESS_GROUP_MONITOR_URL, timeout=15
            )
            response.raise_for_status()
            data = response.json()
            observed_group = f"{int(data['group'])}.{int(data['subgroup'])}"
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            logger.warning("Could not read Yasno address group: %s", exc)
            return

        expected_group = home_config.group
        if observed_group == expected_group:
            self._clear_previous_alert()
            logger.info("Yasno address group matches monitored home group %s", expected_group)
            return

        signature = f"{expected_group}->{observed_group}"
        if self._read_previous_alert() == signature:
            logger.info("Yasno address group mismatch %s was already reported", signature)
            return

        message = (
            "⚠️ <b>Змінилася група відключень за адресою</b>\n"
            "вул. Воскресенська, 2В, Київ\n"
            f"Light Bot стежить за групою: <b>{expected_group}</b>\n"
            f"Yasno зараз повертає: <b>{observed_group}</b>\n"
            "Перевір налаштування групи Light Bot."
        )
        try:
            await self.bot.send_message(
                chat_id=YASNO_ADDRESS_GROUP_ALERT_CHAT_ID,
                text=message,
                parse_mode='HTML',
            )
        except Exception:
            logger.exception("Failed to send Yasno address group mismatch alert")
            return

        self._write_previous_alert(signature)
        logger.warning("Reported Yasno address group mismatch %s", signature)

    def _read_previous_alert(self) -> str | None:
        try:
            state = json.loads(self.state_path.read_text(encoding='utf-8'))
            return state.get('mismatch')
        except (OSError, json.JSONDecodeError, AttributeError):
            return None

    def _write_previous_alert(self, signature: str) -> None:
        self._write_state({'mismatch': signature})

    def _clear_previous_alert(self) -> None:
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Could not clear Yasno address mismatch state")

    def _write_state(self, state: dict) -> None:
        temporary_path = self.state_path.with_suffix(self.state_path.suffix + '.tmp')
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(json.dumps(state), encoding='utf-8')
            os.replace(temporary_path, self.state_path)
        except OSError:
            logger.exception("Could not persist Yasno address mismatch state")
            try:
                temporary_path.unlink()
            except OSError:
                pass
