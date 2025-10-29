# Yasno Blackout API Client

import logging
import requests

from .models import YasnoScheduleResponse

_LOGGER = logging.getLogger(__name__)


class YasnoAPIClient:
    """
    Fetch power outage schedules from Yasno Blackout API

    API endpoint returns schedule data for Kiev region (25) and DSO (902)
    with today/tomorrow schedules for all power groups.
    """

    # Region 25 = Kiev, DSO 902 = DTEK Kyiv Energy
    _api_url = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/25/dsos/902/planned-outages"

    def update(self, force=False) -> YasnoScheduleResponse | None:
        """Fetch current power outage schedule from API"""
        _LOGGER.info("Fetching schedule from Yasno Blackout API...")
        try:
            resp = requests.get(self._api_url, timeout=30)
            if resp.status_code != 200:
                _LOGGER.error(f"API request failed: {resp.status_code} - {resp.content}")
                return None

            resp_json = resp.json()
            _LOGGER.debug(f"API response received with {len(resp_json)} groups")

            # Parse response using custom model
            schedule = YasnoScheduleResponse(resp_json)
            return schedule

        except requests.exceptions.Timeout:
            _LOGGER.error("API request timed out after 30 seconds")
            return None
        except requests.exceptions.RequestException as e:
            _LOGGER.error(f"API request failed: {e}")
            return None
        except Exception as e:
            _LOGGER.exception(f"Error parsing Yasno API response: {e}")
            return None


client = YasnoAPIClient()
