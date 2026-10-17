import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from light_bot.api.voe.client import VOEAPIClient, VOEScheduleResponse
from light_bot.api.composite_client import CompositeScheduleClient, CompositeScheduleResponse
from light_bot.api.yasno.models import SlotType, ScheduleStatus
from light_bot.models.group_config import GroupConfig


def test_parse_group_hours_to_slots():
    # Test all on
    hours_all_yes = {str(i): "yes" for i in range(1, 25)}
    slots = VOEAPIClient._parse_group_hours_to_slots(hours_all_yes)
    assert len(slots) == 1
    assert slots[0].start == 0
    assert slots[0].end == 1440
    assert slots[0].type == SlotType.NOT_PLANNED

    # Test full hour outage in hour 14 (13:00 - 14:00)
    hours_outage = hours_all_yes.copy()
    hours_outage["14"] = "no"
    slots = VOEAPIClient._parse_group_hours_to_slots(hours_outage)
    assert len(slots) == 3
    assert slots[0].start == 0
    assert slots[0].end == 13 * 60
    assert slots[0].type == SlotType.NOT_PLANNED
    assert slots[1].start == 13 * 60
    assert slots[1].end == 14 * 60
    assert slots[1].type == SlotType.DEFINITE
    assert slots[2].start == 14 * 60
    assert slots[2].end == 1440
    assert slots[2].type == SlotType.NOT_PLANNED

    # Test half hour: first (13:00 - 13:30) and second (13:30 - 14:00)
    hours_half = hours_all_yes.copy()
    hours_half["14"] = "first"
    slots = VOEAPIClient._parse_group_hours_to_slots(hours_half)
    definite = [s for s in slots if s.type == SlotType.DEFINITE]
    assert len(definite) == 1
    assert definite[0].start == 13 * 60
    assert definite[0].end == 13 * 60 + 30

    hours_half["14"] = "second"
    slots = VOEAPIClient._parse_group_hours_to_slots(hours_half)
    definite = [s for s in slots if s.type == SlotType.DEFINITE]
    assert len(definite) == 1
    assert definite[0].start == 13 * 60 + 30
    assert definite[0].end == 14 * 60


def test_composite_schedule_response():
    composite = CompositeScheduleResponse()

    mock_yasno = MagicMock()
    mock_yasno.all_groups.return_value = ["3.1"]
    mock_yasno.get_group.return_value = MagicMock(name="kyiv_sched")

    mock_voe = MagicMock()
    mock_voe.all_groups.return_value = ["3.1"]
    mock_voe.get_group.return_value = MagicMock(name="vn_sched")

    composite.set_yasno_response(mock_yasno)
    composite.set_voe_response(mock_voe)

    # Retrieval by city
    kyiv_s = composite.get_group("3.1", city="kiev")
    assert kyiv_s == mock_yasno.get_group.return_value

    vn_s = composite.get_group("3.1", city="vinnytsia")
    assert vn_s == mock_voe.get_group.return_value


def test_group_config_provider_autodetect():
    c_kyiv = GroupConfig(id="home", group="3.1", city="kiev")
    assert c_kyiv.provider == "yasno"

    c_vn = GroupConfig(id="vinnytsia", group="3.1", city="vinnytsia")
    assert c_vn.provider == "voe"

    c_custom = GroupConfig(id="custom", group="3.1", city="kiev", provider="voe")
    assert c_custom.provider == "voe"


def test_parse_halfhour_slots():
    # All on (code 1)
    slots_map_on = {f"{h:02d}:{m:02d}": 1 for h in range(24) for m in (0, 30)}
    slots = VOEAPIClient._parse_halfhour_slots(slots_map_on)
    assert len(slots) == 1
    assert slots[0].start == 0
    assert slots[0].end == 1440
    assert slots[0].type == SlotType.NOT_PLANNED

    # Outage 14:00 - 16:00 (slots 14:00, 14:30, 15:00, 15:30 = 2)
    slots_map_outage = slots_map_on.copy()
    for t in ["14:00", "14:30", "15:00", "15:30"]:
        slots_map_outage[t] = 2
    slots = VOEAPIClient._parse_halfhour_slots(slots_map_outage)
    assert len(slots) == 3
    assert slots[0].start == 0
    assert slots[0].end == 14 * 60
    assert slots[0].type == SlotType.NOT_PLANNED

    assert slots[1].start == 14 * 60
    assert slots[1].end == 16 * 60
    assert slots[1].type == SlotType.DEFINITE

    assert slots[2].start == 16 * 60
    assert slots[2].end == 1440
    assert slots[2].type == SlotType.NOT_PLANNED


def test_parse_svitlo_proxy():
    client = VOEAPIClient()
    mock_json = {
        "date_today": "2026-10-17",
        "date_tomorrow": "2026-10-18",
        "regions": [
            {
                "cpu": "vinnitska-oblast",
                "name_ua": "Вінницька",
                "schedule": {
                    "2.1": {
                        "2026-10-17": {
                            **{f"{h:02d}:{m:02d}": 1 for h in range(24) for m in (0, 30)},
                            "14:00": 2, "14:30": 2, "15:00": 2, "15:30": 2
                        },
                        "2026-10-18": {
                            f"{h:02d}:{m:02d}": 0 for h in range(24) for m in (0, 30)
                        }
                    }
                }
            }
        ]
    }

    resp = client._parse_svitlo_proxy(mock_json)
    assert resp is not None

    g21 = resp.get_group("2.1")
    assert g21 is not None
    assert g21.today.status == ScheduleStatus.SCHEDULE_APPLIES
    assert len(g21.today.slots) == 3
    assert g21.today.slots[1].start == 14 * 60
    assert g21.today.slots[1].end == 16 * 60
    assert g21.today.slots[1].type == SlotType.DEFINITE

    # Tomorrow is all 0 -> WAITING_FOR_SCHEDULE
    assert g21.tomorrow.status == ScheduleStatus.WAITING_FOR_SCHEDULE
    assert len(g21.tomorrow.slots) == 1
    assert g21.tomorrow.slots[0].type == SlotType.NOT_PLANNED


def test_update_svitlo_proxy_priority():
    client = VOEAPIClient(svitlo_proxy_url="http://mock-proxy")
    mock_json = {
        "date_today": "2026-10-17",
        "date_tomorrow": "2026-10-18",
        "regions": [
            {
                "cpu": "vinnitska-oblast",
                "schedule": {
                    "2.1": {
                        "2026-10-17": {f"{h:02d}:{m:02d}": 1 for h in range(24) for m in (0, 30)},
                        "2026-10-18": {f"{h:02d}:{m:02d}": 0 for h in range(24) for m in (0, 30)}
                    }
                }
            }
        ]
    }

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_json
        mock_get.return_value = mock_resp

        res = client.update()
        assert res is not None
        assert res.get_group("2.1") is not None
        assert mock_get.call_count == 1
        assert mock_get.call_args[0][0] == "http://mock-proxy"

