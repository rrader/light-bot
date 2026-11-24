"""Read-only, allowlisted proxy for the nursery radiator Mini App panel."""
import logging
import os
import threading
import time
import math
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

ENTITIES = {
    "temperature": "sensor.nursery_temperatura_batarei_v_ditiachii_temperatura",
    "heating": "binary_sensor.nursery_radiator_heating",
    "trend": "sensor.nursery_radiator_trend",
    "voltage": "sensor.hallway_voltmetr_u_shchitku_napruga",
}
_cache_lock = threading.Lock()
_cache = {"until": 0.0, "value": None}


def _voltage_excursions(points, start, end):
    """Project meter history down to only out-of-range intervals and extrema."""
    result, current = [], None
    def flush():
        nonlocal current
        if current and current["end"] > current["start"]:
            result.append(current)
        current = None
    parsed = []
    for point in points:
        try:
            value = float(point["state"])
            stamp = datetime.fromisoformat(point["time"].replace("Z", "+00:00")).timestamp()
            if math.isfinite(value):
                parsed.append((stamp, value))
        except (TypeError, ValueError, KeyError):
            continue
    # Bridge brief returns to the normal band so noisy meter samples do not
    # split one mains event into a stack of nearly identical labels.
    merge_gap = 180
    for index, (stamp, value) in enumerate(parsed):
        next_stamp = parsed[index + 1][0] if index + 1 < len(parsed) else end
        stop = min(next_stamp, stamp + 180, end)
        left = max(stamp, start)
        side = "low" if 0 < value < 207 else "high" if value > 253 else None
        if not side or stop <= left:
            # Zero means power is absent, so it closes an excursion without
            # being shown as an undervoltage marker. Bridge only ordinary
            # positive in-range readings for the same side.
            if value <= 0 or not (current and left - current["end"] <= merge_gap):
                flush()
            continue
        if current and current["side"] == side and left - current["end"] <= merge_gap:
            current["end"] = stop
            current["extreme"] = min(current["extreme"], value) if side == "low" else max(current["extreme"], value)
        else:
            flush()
            current = {"start": max(left, start), "end": stop, "side": side, "extreme": value}
        if stop < next_stamp:
            flush()
    flush()
    return [
        {"start": datetime.fromtimestamp(x["start"], timezone.utc).isoformat(),
         "end": datetime.fromtimestamp(x["end"], timezone.utc).isoformat(),
         "side": x["side"], "extreme": round(x["extreme"], 1)}
        for x in result if x["end"] > start and x["start"] < end
    ]


def create_nursery_radiator_blueprint():
    bp = Blueprint("nursery_radiator", __name__)

    @bp.route("/nursery-radiator", methods=["GET"])
    def nursery_radiator():
        """Return only radiator states and a bounded 26-hour history."""
        from flask import request

        hours = min(48, max(6, request.args.get("hours", default=26, type=int)))
        end_ts = request.args.get("end", default=None, type=float)
        custom_start_ts = request.args.get("start", default=None, type=float)
        end_dt = datetime.fromtimestamp(end_ts, timezone.utc) if end_ts else datetime.now(timezone.utc)
        query_start_dt = datetime.fromtimestamp(custom_start_ts, timezone.utc) if custom_start_ts else end_dt - timedelta(hours=hours)
        if query_start_dt >= end_dt or end_dt - query_start_dt > timedelta(hours=48):
            return jsonify({"available": False, "message": "Оберіть проміжок не довший за 48 годин."}), 400
        start_dt = query_start_dt
        cache_key = f"{hours}:{int(end_dt.timestamp() // 60)}:{int(query_start_dt.timestamp() // 60)}"
        now = time.monotonic()
        with _cache_lock:
            if _cache.get("key") == cache_key and _cache["value"] is not None and now < _cache["until"]:
                return jsonify(_cache["value"])

        base_url = os.getenv("HA_API_URL", "https://ha.rmn.pp.ua").rstrip("/")
        token = os.getenv("HA_API_TOKEN")
        if not token:
            return jsonify({"available": False, "message": "Дані батареї тимчасово недоступні."}), 503

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            response = requests.get(
                f"{base_url}/api/history/period/{start_dt.isoformat()}",
                params={"filter_entity_id": ",".join(ENTITIES.values()), "end_time": end_dt.isoformat(), "minimal_response": "1", "no_attributes": "1"},
                headers=headers,
                timeout=(3, 12),
            )
            response.raise_for_status()
            raw_history = response.json()
            history = {key: [] for key in ENTITIES}
            for entity_states in raw_history:
                if not entity_states:
                    continue
                entity_id = entity_states[0].get("entity_id")
                key = next((k for k, v in ENTITIES.items() if v == entity_id), None)
                if key is None:
                    continue
                for item in entity_states:
                    stamp = item.get("last_changed") or item.get("last_updated")
                    if stamp:
                        history[key].append({"state": item.get("state"), "time": stamp})
            if not history["temperature"] or not history["heating"] or not history["trend"]:
                raise ValueError("Required radiator history missing")
            if not custom_start_ts:
                # Match the chart sent by Home Assistant: show two hours before
                # the latest cooling interval, with a 24-hour fallback.
                search_start = end_dt - timedelta(hours=max(0, hours - 2))
                cooling = []
                previous_trend = None
                for point in history["trend"]:
                    stamp = datetime.fromisoformat(point["time"].replace("Z", "+00:00"))
                    if point["state"] == "Охолоджується" and previous_trend != "Охолоджується" and search_start <= stamp <= end_dt:
                        cooling.append(stamp)
                    previous_trend = point["state"]
                start_dt = max(query_start_dt, cooling[-1] - timedelta(hours=2)) if cooling else end_dt - timedelta(hours=min(24, hours))
                for key in history:
                    before = [point for point in history[key] if datetime.fromisoformat(point["time"].replace("Z", "+00:00")) < start_dt]
                    within = [point for point in history[key] if datetime.fromisoformat(point["time"].replace("Z", "+00:00")) >= start_dt]
                    history[key] = ([before[-1]] if before else []) + within
            voltage_excursions = _voltage_excursions(history["voltage"], start_dt.timestamp(), end_dt.timestamp())
            history.pop("voltage", None)
            states = {key: series[-1] for key, series in history.items() if series}
            result = {"available": True, "states": states, "history": history,
                      "voltage_excursions": voltage_excursions,
                      "range": {"start": start_dt.isoformat(), "end": end_dt.isoformat(), "hours": hours},
                      "updated": datetime.now(timezone.utc).isoformat()}
            with _cache_lock:
                _cache.update(key=cache_key, until=time.monotonic() + 30, value=result)
            return jsonify(result)
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.warning("Home Assistant radiator proxy unavailable: %s", type(exc).__name__)
            return jsonify({"available": False, "message": "Дані батареї тимчасово недоступні."}), 503

    return bp
