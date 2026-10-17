import os
import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz

from light_bot.api.yasno.models import (
    PowerSlot,
    DaySchedule,
    GroupSchedule,
    SlotType,
    ScheduleStatus,
)
from light_bot.config import TIMEZONE

logger = logging.getLogger(__name__)

SVITLO_PROXY_URL = os.getenv("SVITLO_PROXY_URL", "https://svitlo-proxy.svitlo-proxy.workers.dev")

VOE_JSON_URLS = [
    "https://raw.githubusercontent.com/vn-progr/gpv-voe-vinnytsia/main/data/Vinnytsiaoblenerho.json",
    "https://raw.githubusercontent.com/olnet93/gpv-voe-vinnytsia/main/data/Vinnytsiaoblenerho.json",
]


class VOEScheduleResponse:
    """VOE Schedule Response containing schedules for Vinnytsia groups"""

    def __init__(self, data: Dict[str, GroupSchedule]):
        self._data = data

    def get_group(self, group: str, city: Optional[str] = None) -> Optional[GroupSchedule]:
        # Handle 'GPV3.1' or '3.1'
        cleaned = group.replace("GPV", "").strip()
        return self._data.get(cleaned)

    def all_groups(self) -> List[str]:
        return list(self._data.keys())


class VOEAPIClient:
    """Client for Vinnytsiaoblenergo (VOE) power outage schedule data"""

    def __init__(self, urls: Optional[List[str]] = None, svitlo_proxy_url: Optional[str] = None):
        self.urls = urls or VOE_JSON_URLS
        self.svitlo_proxy_url = svitlo_proxy_url if svitlo_proxy_url is not None else SVITLO_PROXY_URL

    @staticmethod
    def _parse_halfhour_slots(slots_map: Dict[str, int]) -> List[PowerSlot]:
        """Convert 48 half-hour dictionary (e.g. '00:00': 1, '14:00': 2) into merged PowerSlot list"""
        raw_slots = []
        for half_hour in range(48):
            h = half_hour // 2
            m = 30 if (half_hour % 2 == 1) else 0
            label = f"{h:02d}:{m:02d}"
            code = int(slots_map.get(label, 0))

            is_outage = (code == 2)
            slot_type = SlotType.DEFINITE if is_outage else SlotType.NOT_PLANNED

            start_min = half_hour * 30
            end_min = (half_hour + 1) * 30

            if raw_slots and raw_slots[-1].type == slot_type:
                raw_slots[-1].end = end_min
            else:
                raw_slots.append(PowerSlot(start=start_min, end=end_min, type=slot_type))

        return raw_slots

    def _parse_svitlo_proxy(self, raw_json: dict) -> Optional[VOEScheduleResponse]:
        """Parse schedule response from Svitlo Proxy API (used by Home Assistant svitlo_live)"""
        regions = raw_json.get("regions", [])
        vn_region = next((r for r in regions if r.get("cpu") == "vinnitska-oblast"), None)
        if not vn_region:
            logger.warning("Svitlo Proxy JSON missing 'vinnitska-oblast' region")
            return None

        schedule = vn_region.get("schedule")
        if not schedule or not isinstance(schedule, dict):
            logger.warning("Svitlo Proxy JSON missing schedule for Vinnytsia")
            return None

        date_today_str = raw_json.get("date_today")
        date_tomorrow_str = raw_json.get("date_tomorrow")
        if not date_today_str or not date_tomorrow_str:
            logger.warning("Svitlo Proxy JSON missing date_today or date_tomorrow")
            return None

        now = datetime.now(TIMEZONE)
        today_dt = TIMEZONE.localize(datetime.strptime(date_today_str, "%Y-%m-%d"))
        tomorrow_dt = TIMEZONE.localize(datetime.strptime(date_tomorrow_str, "%Y-%m-%d"))

        all_queues = [
            "1.1", "1.2", "2.1", "2.2",
            "3.1", "3.2", "4.1", "4.2",
            "5.1", "5.2", "6.1", "6.2"
        ]

        groups_dict: Dict[str, GroupSchedule] = {}

        for q in all_queues:
            q_data = schedule.get(q, {})
            today_slots_map = q_data.get(date_today_str, {})
            tomorrow_slots_map = q_data.get(date_tomorrow_str, {})

            today_slots = self._parse_halfhour_slots(today_slots_map)
            has_today_outages = any(s.type == SlotType.DEFINITE for s in today_slots)
            today_status = ScheduleStatus.SCHEDULE_APPLIES if has_today_outages else ScheduleStatus.NO_OUTAGES

            tomorrow_slots = self._parse_halfhour_slots(tomorrow_slots_map)
            has_tomorrow_outages = any(s.type == SlotType.DEFINITE for s in tomorrow_slots)

            if has_tomorrow_outages:
                tomorrow_status = ScheduleStatus.SCHEDULE_APPLIES
            else:
                if not tomorrow_slots_map or all(v == 0 for v in tomorrow_slots_map.values()):
                    tomorrow_status = ScheduleStatus.WAITING_FOR_SCHEDULE
                else:
                    tomorrow_status = ScheduleStatus.NO_OUTAGES

            groups_dict[q] = GroupSchedule(
                today=DaySchedule(slots=today_slots, date=today_dt, status=today_status),
                tomorrow=DaySchedule(slots=tomorrow_slots, date=tomorrow_dt, status=tomorrow_status),
                updatedOn=now,
            )

        return VOEScheduleResponse(groups_dict)

    @staticmethod
    def _parse_group_hours_to_slots(group_hours: Dict[str, str]) -> List[PowerSlot]:
        """Convert 24-hour dictionary (keys '1'..'24') into merged PowerSlot list"""
        zero_based = "0" in group_hours

        def get_key(h: int) -> str:
            return str(h if zero_based else h + 1)

        raw_slots = []
        for half_hour in range(48):
            hour = half_hour // 2
            is_second_half = (half_hour % 2 == 1)
            st = group_hours.get(get_key(hour), "yes")

            is_outage = False
            if st in ("no", "mno"):
                is_outage = True
            elif st in ("first", "mfirst") and not is_second_half:
                is_outage = True
            elif st in ("second", "msecond") and is_second_half:
                is_outage = True

            start_min = half_hour * 30
            end_min = (half_hour + 1) * 30
            slot_type = SlotType.DEFINITE if is_outage else SlotType.NOT_PLANNED

            if raw_slots and raw_slots[-1].type == slot_type:
                raw_slots[-1].end = end_min
            else:
                raw_slots.append(PowerSlot(start=start_min, end=end_min, type=slot_type))

        return raw_slots

    @staticmethod
    def _is_tomorrow_published(queue: str) -> bool:
        """Check if tomorrow's schedule is actually published on bezsvitla.com.ua"""
        queue_slug = queue.replace(".", "-").replace("GPV", "").strip()
        url = f"https://bezsvitla.com.ua/vinnytska-oblast/cherha-{queue_slug}/grafik-na-zavtra"
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            if resp.status_code == 200:
                html = resp.text
                if "ще не опублікований" in html or "bz-schedule-empty" in html:
                    return False
                return True
        except Exception as e:
            logger.debug(f"Error checking tomorrow page for queue {queue}: {e}")
        # Default to false (waiting) if unsure
        return False

    def update(self, force: bool = False) -> Optional[VOEScheduleResponse]:
        """Fetch and parse current VOE schedule"""
        logger.info("Fetching schedule from VOE data source...")

        # 1. Try Svitlo Proxy first (same source as Home Assistant svitlo_live integration)
        if self.svitlo_proxy_url:
            try:
                resp = requests.get(self.svitlo_proxy_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                if resp.status_code == 200:
                    parsed = self._parse_svitlo_proxy(resp.json())
                    if parsed:
                        logger.info("Successfully fetched and parsed VOE schedule from Svitlo Proxy")
                        return parsed
            except Exception as e:
                logger.warning(f"Failed to fetch from Svitlo Proxy ({self.svitlo_proxy_url}): {e}")

        # 2. Fallback to legacy community JSON sources
        raw_json = None
        for url in self.urls:
            try:
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                if resp.status_code == 200:
                    raw_json = resp.json()
                    break
            except Exception as e:
                logger.warning(f"Failed to fetch from {url}: {e}")

        if not raw_json or "fact" not in raw_json:
            logger.error("Failed to fetch valid VOE schedule JSON from any source")
            return None

        fact = raw_json.get("fact", {})
        fact_data = fact.get("data", {})
        today_ts_val = fact.get("today")
        if not today_ts_val:
            logger.error("VOE JSON missing 'fact.today'")
            return None

        today_ts = str(today_ts_val)
        tomorrow_ts = str(int(today_ts_val) + 86400)

        # Normalize to midnight Kyiv time
        today_dt = datetime.fromtimestamp(int(today_ts_val), tz=TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_dt = today_dt + timedelta(days=1)
        last_updated = datetime.fromtimestamp(raw_json.get("lastUpdated", int(today_ts_val)), tz=TIMEZONE)

        today_group_data = fact_data.get(today_ts, {})
        tomorrow_group_data = fact_data.get(tomorrow_ts, {})

        all_queues = [
            "1.1", "1.2", "2.1", "2.2",
            "3.1", "3.2", "4.1", "4.2",
            "5.1", "5.2", "6.1", "6.2"
        ]

        groups_dict: Dict[str, GroupSchedule] = {}
        tomorrow_published_cache = {}

        for q in all_queues:
            gpv_key = f"GPV{q}"
            today_hours = today_group_data.get(gpv_key, {str(i): "yes" for i in range(1, 25)})
            tomorrow_hours = tomorrow_group_data.get(gpv_key, {str(i): "yes" for i in range(1, 25)})

            today_slots = self._parse_group_hours_to_slots(today_hours)
            has_today_outages = any(s.type == SlotType.DEFINITE for s in today_slots)
            today_status = ScheduleStatus.SCHEDULE_APPLIES if has_today_outages else ScheduleStatus.NO_OUTAGES

            tomorrow_slots = self._parse_group_hours_to_slots(tomorrow_hours)
            has_tomorrow_outages = any(s.type == SlotType.DEFINITE for s in tomorrow_slots)

            if has_tomorrow_outages:
                tomorrow_status = ScheduleStatus.SCHEDULE_APPLIES
            else:
                if q not in tomorrow_published_cache:
                    tomorrow_published_cache[q] = self._is_tomorrow_published(q)
                is_pub = tomorrow_published_cache[q]
                tomorrow_status = ScheduleStatus.NO_OUTAGES if is_pub else ScheduleStatus.WAITING_FOR_SCHEDULE

            groups_dict[q] = GroupSchedule(
                today=DaySchedule(slots=today_slots, date=today_dt, status=today_status),
                tomorrow=DaySchedule(slots=tomorrow_slots, date=tomorrow_dt, status=tomorrow_status),
                updatedOn=last_updated,
            )

        return VOEScheduleResponse(groups_dict)


client = VOEAPIClient()
