from datetime import datetime, timezone

from light_bot.core.nursery_radiator_blueprint import _voltage_excursions


def point(time, voltage):
    return {"time": datetime.fromtimestamp(time, timezone.utc).isoformat(), "state": str(voltage)}


def test_voltage_noise_cluster_merges_and_keeps_extreme():
    points = [
        point(0, 255), point(180, 252), point(205, 256),
        point(400, 251), point(500, 257), point(700, 254),
    ]
    result = _voltage_excursions(points, 0, 1000)
    assert len(result) == 1
    assert result[0]["side"] == "high"
    assert result[0]["extreme"] == 257


def test_voltage_zero_is_absence_and_breaks_an_excursion():
    points = [point(0, 256), point(60, 0), point(90, 255)]
    result = _voltage_excursions(points, 0, 300)
    assert len(result) == 2
    assert all(item["extreme"] > 253 for item in result)


def test_voltage_events_separate_after_five_minutes_or_side_change():
    points = [point(0, 256), point(500, 257), point(520, 202)]
    result = _voltage_excursions(points, 0, 1000)
    assert [(item["side"], item["extreme"]) for item in result] == [("high", 256), ("high", 257), ("low", 202)]
