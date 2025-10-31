# Yasno Blackout API Client

import logging
import requests
import os

from .models import YasnoScheduleResponse

_LOGGER = logging.getLogger(__name__)


class YasnoAPIClient:
    """
    Fetch power outage schedules from Yasno Blackout API

    API endpoint returns schedule data for Kiev region (25) and DSO (902)
    with today/tomorrow schedules for all power groups.
    """

    def __init__(self, base_url=None):
        """
        Initialize Yasno API client

        Args:
            base_url: Custom base URL (for E2E testing with mock server)
        """
        # Use custom base URL if provided (from config or parameter)
        self.base_url = base_url or os.getenv('YASNO_API_BASE_URL')

        # Region 25 = Kiev, DSO 902 = DTEK Kyiv Energy
        api_path = "/api/blackout-service/public/shutdowns/regions/25/dsos/902/planned-outages"

        if self.base_url:
            # E2E testing with mock server (same API path)
            self._api_url = f"{self.base_url}{api_path}"
            _LOGGER.info(f"Using custom Yasno API URL: {self._api_url}")
        else:
            # Production API
            self._api_url = f"https://app.yasno.ua{api_path}"

    def update(self, force=False) -> YasnoScheduleResponse | None:
        """Fetch current power outage schedule from API"""
        _LOGGER.info("Fetching schedule from Yasno Blackout API...")
        try:
            resp = requests.get(self._api_url, timeout=30)
            if resp.status_code != 200:
                _LOGGER.error(f"API request failed: {resp.status_code} - {resp.content}")
                return None

            resp_json = resp.json()
            _LOGGER.debug(f"API response received")

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
