"""Read-only, allowlisted proxy for the nursery radiator Mini App panel."""
import logging
import os
import threading
import time
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
            states = {key: series[-1] for key, series in history.items() if key != "voltage" and series}
            result = {"available": True, "states": states, "history": history,
                      "range": {"start": start_dt.isoformat(), "end": end_dt.isoformat(), "hours": hours},
                      "updated": datetime.now(timezone.utc).isoformat()}
            with _cache_lock:
                _cache.update(key=cache_key, until=time.monotonic() + 30, value=result)
            return jsonify(result)
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.warning("Home Assistant radiator proxy unavailable: %s", type(exc).__name__)
            return jsonify({"available": False, "message": "Дані батареї тимчасово недоступні."}), 503

    return bp
