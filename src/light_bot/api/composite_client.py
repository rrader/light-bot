import logging
from typing import Dict, List, Optional, Tuple

from light_bot.api.yasno.models import GroupSchedule, YasnoScheduleResponse
from light_bot.api.yasno.api import client as yasno_client
from light_bot.api.voe.client import client as voe_client, VOEScheduleResponse
from light_bot.models.group_config import GroupConfig

logger = logging.getLogger(__name__)


class CompositeScheduleResponse:
    """Composite schedule response supporting multiple providers (Yasno, VOE, etc.)"""

    def __init__(self):
        # Maps (city_key, group) -> GroupSchedule
        self._schedules: Dict[Tuple[str, str], GroupSchedule] = {}
        self._yasno_response: Optional[YasnoScheduleResponse] = None
        self._voe_response: Optional[VOEScheduleResponse] = None

    def set_yasno_response(self, resp: Optional[YasnoScheduleResponse]):
        self._yasno_response = resp
        if resp:
            for g in resp.all_groups():
                sched = resp.get_group(g)
                if sched:
                    self._schedules[("kiev", g)] = sched
                    self._schedules[("kyiv", g)] = sched

    def set_voe_response(self, resp: Optional[VOEScheduleResponse]):
        self._voe_response = resp
        if resp:
            for g in resp.all_groups():
                sched = resp.get_group(g)
                if sched:
                    self._schedules[("vinnytsia", g)] = sched
                    self._schedules[("voe", g)] = sched

    def get_group(self, group: str, city: Optional[str] = None) -> Optional[GroupSchedule]:
        """Get GroupSchedule for a group, optionally filtered by city"""
        if city:
            city_key = city.lower().strip()
            if (city_key, group) in self._schedules:
                return self._schedules[(city_key, group)]
            if city_key in ("vinnytsia", "voe") and self._voe_response:
                return self._voe_response.get_group(group)
            if city_key in ("kiev", "kyiv") and self._yasno_response:
                return self._yasno_response.get_group(group)

        # Fallback without city: check Kyiv first, then Vinnytsia
        if ("kiev", group) in self._schedules:
            return self._schedules[("kiev", group)]
        if ("vinnytsia", group) in self._schedules:
            return self._schedules[("vinnytsia", group)]

        return None

    def all_groups(self) -> List[str]:
        return list(set(g for (_, g) in self._schedules.keys()))


class CompositeScheduleClient:
    """Fetches schedules across needed providers according to group configs"""

    def __init__(self, group_configs: List[GroupConfig]):
        self.group_configs = group_configs

    def update(self, force: bool = False) -> CompositeScheduleResponse:
        composite = CompositeScheduleResponse()

        needs_yasno = False
        needs_voe = False

        for config in self.group_configs:
            prov = getattr(config, 'provider', None)
            city = getattr(config, 'city', '').lower()
            if prov == 'voe' or city in ('vinnytsia', 'voe'):
                needs_voe = True
            else:
                needs_yasno = True

        if needs_yasno:
            try:
                yasno_resp = yasno_client.update(force=force)
                composite.set_yasno_response(yasno_resp)
            except Exception as e:
                logger.error(f"Error fetching Yasno schedule: {e}")

        if needs_voe:
            try:
                voe_resp = voe_client.update(force=force)
                composite.set_voe_response(voe_resp)
            except Exception as e:
                logger.error(f"Error fetching VOE schedule: {e}")

        return composite
