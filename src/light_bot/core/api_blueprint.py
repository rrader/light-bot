import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Callable
from flask import Blueprint, jsonify, request, Response

from light_bot.config import LOCATIONS, get_location_config, get_group_config, get_actual_group_number
from light_bot.formatters.duration_formatter import DurationFormatter
from light_bot.services.stats_service import StatsService

logger = logging.getLogger(__name__)

SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Light Bot API - Interactive Documentation</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  <style>
    body { margin: 0; background: #fafafa; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .topbar { display: none; }
    .swagger-ui .info { margin: 30px 0; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = function() {
      SwaggerUIBundle({
        url: "/api/openapi.json",
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout"
      });
    };
  </script>
</body>
</html>
"""

LLMS_TXT = """# Light Bot Public API
> Machine-readable documentation and discovery guide for AI agents and developer integrations.

## Overview
Light Bot tracks electrical grid availability (power on/off), outage durations, historical events, and official planned outage schedules for Kyiv (Yasno DSO 902, group 2.1) and Vinnytsia (VOE).

- Base URL: https://light.rmn.pp.ua
- Interactive Swagger UI: https://light.rmn.pp.ua/api/docs
- OpenAPI 3.1 Spec: https://light.rmn.pp.ua/api/openapi.json
- CORS: Enabled with Access-Control-Allow-Origin: https://po2.kyiv.ua (and * for standard GET requests)
- Authentication: All GET endpoints under /api/ are public and require NO token. Mutation endpoints (POST) require Bearer token.

## Endpoints

### 1. Power Status (Поточний стан)
- `GET /api/power-status`: Current power state for default location (Kyiv / home).
- `GET /api/power-status/{location_id}`: Current power state for specific location (`home`, `vinnytsia`).
- `GET /api/locations`: List of all monitored locations with status and timestamps.

Response structure:
```json
{
  "location": "home",
  "name": "Київ (Дім)",
  "status": "on",
  "last_updated": "Last updated: 2026-10-23T19:00:00+03:00",
  "timestamp": "2026-10-23T19:00:00+03:00",
  "yasno_group": "home"
}
```

### 2. Events & Outage History (Історія подій)
- `GET /api/events?limit=50&location=home`: Recent power state transition events (on/off).
- `GET /api/history?days=30`: Daily aggregated outage count and duration in seconds.
- `GET /api/stats`: Overall outage summary statistics (uptime percentage, average duration).

Response structure (`/api/events`):
```json
[
  {
    "id": 120,
    "location": "home",
    "status": "on",
    "timestamp": "2026-10-23T16:30:00+03:00"
  }
]
```

### 3. Outage Schedule (Графік)
- `GET /api/schedule/{group_id}`: Latest parsed outage schedule for today and tomorrow (`home` for Kyiv group 2.1, `vinnytsia` for Vinnytsia).
- `GET /api/schedule-history/{group_id}?limit=10`: Historical log of schedule announcements and changes.

Response structure (`/api/schedule/home`):
```json
{
  "group_id": "home",
  "timestamp": "2026-10-23T16:04:42+03:00",
  "schedule": {
    "today": {
      "date": "2026-10-23T00:00:00+03:00",
      "status": "EmergencyShutdowns",
      "slots": []
    },
    "tomorrow": {
      "date": "2026-10-24T00:00:00+03:00",
      "status": "EmergencyShutdowns",
      "slots": []
    },
    "updatedOn": "2026-10-23T11:18:02Z"
  }
}
```
"""

OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "Light Bot API",
        "version": "1.0.0",
        "description": "Public API for power status monitoring, historical outage events, and planned outage schedules for Kyiv and Vinnytsia."
    },
    "servers": [
        {
            "url": "https://light.rmn.pp.ua",
            "description": "Production server"
        }
    ],
    "paths": {
        "/api": {
            "get": {
                "summary": "API Root Directory",
                "description": "Returns metadata, documentation links, and available endpoints.",
                "responses": {
                    "200": {
                        "description": "API metadata",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"}
                            }
                        }
                    }
                }
            }
        },
        "/api/docs": {
            "get": {
                "summary": "Interactive Swagger UI Documentation",
                "responses": {
                    "200": {
                        "description": "Swagger UI HTML page",
                        "content": {
                            "text/html": {}
                        }
                    }
                }
            }
        },
        "/api/openapi.json": {
            "get": {
                "summary": "OpenAPI Specification",
                "responses": {
                    "200": {
                        "description": "OpenAPI 3.1.0 JSON Schema",
                        "content": {
                            "application/json": {}
                        }
                    }
                }
            }
        },
        "/api/llms.txt": {
            "get": {
                "summary": "LLM Agent Discovery Document",
                "responses": {
                    "200": {
                        "description": "Plain-text markdown guide for LLMs",
                        "content": {
                            "text/plain": {}
                        }
                    }
                }
            }
        },
        "/api/power-status": {
            "get": {
                "summary": "Get Default Power Status (Kyiv / Home)",
                "description": "Returns real-time power availability status for default location (Kyiv / Home). No authentication required.",
                "responses": {
                    "200": {
                        "description": "Current power status",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/PowerStatus"}
                            }
                        }
                    }
                }
            }
        },
        "/api/power-status/{location_id}": {
            "get": {
                "summary": "Get Power Status for Location",
                "description": "Returns power status for specified location ('home' or 'vinnytsia'). No authentication required.",
                "parameters": [
                    {
                        "name": "location_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "example": "home"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Current power status",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/PowerStatus"}
                            }
                        }
                    },
                    "404": {
                        "description": "Unknown location"
                    }
                }
            }
        },
        "/api/locations": {
            "get": {
                "summary": "List All Monitored Locations",
                "description": "Returns all configured locations with their current power status.",
                "responses": {
                    "200": {
                        "description": "List of locations",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "locations": {
                                            "type": "array",
                                            "items": {"$ref": "#/components/schemas/PowerStatus"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/events": {
            "get": {
                "summary": "Get Recent Power Events",
                "description": "Returns chronological log of power on/off transitions.",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 50, "maximum": 200},
                        "description": "Maximum number of events to return"
                    },
                    {
                        "name": "location",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                        "description": "Filter by location ID (e.g. 'home' or 'vinnytsia')"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "List of power events",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/PowerEvent"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/history": {
            "get": {
                "summary": "Get Daily Outage History",
                "description": "Returns aggregated daily statistics (outage count and outage duration in seconds).",
                "parameters": [
                    {
                        "name": "days",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 30, "maximum": 365},
                        "description": "Number of days of history"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Daily outage statistics",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/DailyHistory"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/stats": {
            "get": {
                "summary": "Get Summary Outage Statistics",
                "description": "Returns overall power availability, total outage count, total outage duration, and percentage.",
                "parameters": [
                    {
                        "name": "group_id",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                        "description": "Optional group ID filter"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Statistical summary",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"}
                            }
                        }
                    }
                }
            }
        },
        "/api/schedule/{group_id}": {
            "get": {
                "summary": "Get Latest Parsed Outage Schedule",
                "description": "Returns the latest published power outage schedule for the given group (e.g. 'home', 'vinnytsia') with parsed slot objects.",
                "parameters": [
                    {
                        "name": "group_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "example": "home"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Latest schedule with slots",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ParsedSchedule"}
                            }
                        }
                    },
                    "404": {
                        "description": "No schedule found for group"
                    }
                }
            }
        },
        "/api/schedule-history/{group_id}": {
            "get": {
                "summary": "Get Schedule History Entries",
                "description": "Returns historical log of schedule updates as recorded from Yasno/VOE.",
                "parameters": [
                    {
                        "name": "group_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "example": "home"
                    },
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 10, "maximum": 100}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "List of schedule history records",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/ScheduleHistoryEntry"}
                                }
                            }
                        }
                    }
                }
            }
        }
    },
    "components": {
        "schemas": {
            "PowerStatus": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "example": "home"},
                    "location": {"type": "string", "example": "home"},
                    "name": {"type": "string", "example": "Київ (Дім)"},
                    "status": {"type": "string", "enum": ["on", "off", "Unknown"], "example": "on"},
                    "last_updated": {"type": "string", "example": "Last updated: 2026-10-23T19:00:00+03:00"},
                    "timestamp": {"type": "string", "format": "date-time", "nullable": True},
                    "yasno_group": {"type": "string", "example": "home"}
                }
            },
            "PowerEvent": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 120},
                    "timestamp": {"type": "string", "format": "date-time"},
                    "status": {"type": "string", "enum": ["on", "off"]},
                    "location": {"type": "string", "example": "home"}
                }
            },
            "DailyHistory": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "example": "2026-10-23"},
                    "count": {"type": "integer", "example": 2},
                    "duration_seconds": {"type": "integer", "example": 14400}
                }
            },
            "ParsedSchedule": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "string", "example": "home"},
                    "timestamp": {"type": "string", "format": "date-time"},
                    "schedule": {
                        "type": "object",
                        "properties": {
                            "today": {"type": "object"},
                            "tomorrow": {"type": "object"},
                            "updatedOn": {"type": "string"}
                        }
                    }
                }
            },
            "ScheduleHistoryEntry": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 1236},
                    "group_id": {"type": "string", "example": "home"},
                    "schedule_text": {"type": "string"},
                    "timestamp": {"type": "string"}
                }
            }
        }
    }
}


def create_api_blueprint(stats_service: StatsService, read_power_status_fn: Callable) -> Blueprint:
    """Create comprehensive API blueprint with public endpoints, OpenAPI documentation, and CORS."""
    api_bp = Blueprint('api', __name__)

    @api_bp.after_request
    def set_cors_headers(response):
        origin = request.headers.get('Origin')
        # Allow po2.kyiv.ua, localhost for development, or wildcard for read-only GET requests
        if origin and (origin == 'https://po2.kyiv.ua' or origin == 'http://po2.kyiv.ua' or 'po2.kyiv.ua' in origin or 'localhost' in origin):
            response.headers['Access-Control-Allow-Origin'] = origin
        else:
            response.headers['Access-Control-Allow-Origin'] = 'https://po2.kyiv.ua'
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = '*'
        return response

    @api_bp.route('', methods=['GET'])
    @api_bp.route('/', methods=['GET'])
    def api_index():
        """API Root Directory with self-discovery links."""
        return jsonify({
            'name': 'Light Bot API',
            'version': '1.0.0',
            'description': 'Power availability status, event history, and power outage schedules for Kyiv and Vinnytsia',
            'documentation': {
                'interactive_ui': '/api/docs',
                'openapi_spec': '/api/openapi.json',
                'llms_txt': '/api/llms.txt'
            },
            'endpoints': {
                'power_status_default': '/api/power-status',
                'power_status_by_location': '/api/power-status/<location_id>',
                'locations': '/api/locations',
                'events': '/api/events?limit=50&location=home',
                'history': '/api/history?days=30',
                'stats': '/api/stats',
                'schedule': '/api/schedule/<group_id>',
                'schedule_history': '/api/schedule-history/<group_id>'
            },
            'monitored_locations': list(LOCATIONS.keys())
        }), 200

    @api_bp.route('/docs', methods=['GET'])
    def docs():
        """Swagger UI interactive documentation."""
        return Response(SWAGGER_HTML, mimetype='text/html')

    @api_bp.route('/openapi.json', methods=['GET'])
    def openapi():
        """OpenAPI 3.1.0 JSON specification."""
        return jsonify(OPENAPI_SPEC), 200

    @api_bp.route('/llms.txt', methods=['GET'])
    def llms_txt():
        """LLM Agent discovery document."""
        return Response(LLMS_TXT, mimetype='text/plain; charset=utf-8')

    @api_bp.route('/power-status', methods=['GET'])
    @api_bp.route('/status', methods=['GET'])
    def public_power_status_default():
        """Get current power status for default location (home / Kyiv). Public, no token required."""
        try:
            loc = get_location_config('home')
            target_file = None if not loc or loc.id == 'home' else loc.status_file
            st = read_power_status_fn(target_file)
            ts = st.get('timestamp')
            group_cfg = get_group_config(loc.yasno_group if loc else 'home')
            actual_group = group_cfg.group if group_cfg and group_cfg.group else (loc.yasno_group if loc else 'home')

            return jsonify({
                'location': loc.id if loc else 'home',
                'name': loc.name if loc else 'Дім',
                'status': st.get('status', 'Unknown'),
                'last_updated': st.get('last_updated', 'Never'),
                'timestamp': ts.isoformat() if isinstance(ts, datetime) else None,
                'group': actual_group,
                'group_id': loc.yasno_group if loc else 'home',
                'yasno_group': actual_group,
                'city': group_cfg.city if group_cfg else 'kiev'
            }), 200
        except Exception as e:
            logger.error(f"Error getting public power status: {e}")
            return jsonify({'error': str(e)}), 500

    @api_bp.route('/power-status/<location_id>', methods=['GET'])
    @api_bp.route('/status/<location_id>', methods=['GET'])
    def public_power_status_by_location(location_id: str):
        """Get current power status for specific location. Public, no token required."""
        try:
            loc = get_location_config(location_id)
            if not loc:
                return jsonify({
                    'error': f'Unknown location: {location_id}',
                    'available_locations': list(LOCATIONS.keys())
                }), 404

            target_file = None if loc.id == 'home' else loc.status_file
            st = read_power_status_fn(target_file)
            ts = st.get('timestamp')
            group_cfg = get_group_config(loc.yasno_group)
            actual_group = group_cfg.group if group_cfg and group_cfg.group else loc.yasno_group

            return jsonify({
                'location': loc.id,
                'name': loc.name,
                'status': st.get('status', 'Unknown'),
                'last_updated': st.get('last_updated', 'Never'),
                'timestamp': ts.isoformat() if isinstance(ts, datetime) else None,
                'group': actual_group,
                'group_id': loc.yasno_group,
                'yasno_group': actual_group,
                'city': group_cfg.city if group_cfg else 'kiev'
            }), 200
        except Exception as e:
            logger.error(f"Error getting public power status for {location_id}: {e}")
            return jsonify({'error': str(e)}), 500

    @api_bp.route('/locations', methods=['GET'])
    def public_locations():
        """List all monitored locations and their current status. Public, no token required."""
        try:
            result = []
            for loc in LOCATIONS.values():
                target_file = None if loc.id == 'home' else loc.status_file
                st = read_power_status_fn(target_file)
                ts = st.get('timestamp')
                group_cfg = get_group_config(loc.yasno_group)
                actual_group = group_cfg.group if group_cfg and group_cfg.group else loc.yasno_group
                result.append({
                    'id': loc.id,
                    'location': loc.id,
                    'name': loc.name,
                    'status': st.get('status', 'Unknown'),
                    'last_updated': st.get('last_updated', 'Never'),
                    'timestamp': ts.isoformat() if isinstance(ts, datetime) else None,
                    'group': actual_group,
                    'group_id': loc.yasno_group,
                    'yasno_group': actual_group,
                    'city': group_cfg.city if group_cfg else 'kiev'
                })
            return jsonify({'locations': result}), 200
        except Exception as e:
            logger.error(f"Error listing public locations: {e}")
            return jsonify({'error': str(e)}), 500

    @api_bp.route('/events', methods=['GET'])
    def public_events():
        """Get recent power events log. Public, no token required."""
        try:
            limit = request.args.get('limit', default=50, type=int)
            limit = max(1, min(limit, 200))
            location = request.args.get('location', default=None, type=str)

            events = stats_service.get_recent_events(limit=limit, location=location)
            return jsonify([
                {
                    'id': e.id,
                    'timestamp': e.timestamp.isoformat() if isinstance(e.timestamp, datetime) else str(e.timestamp),
                    'status': e.status,
                    'location': e.location
                }
                for e in events
            ]), 200
        except Exception as e:
            logger.error(f"Error getting public events: {e}")
            return jsonify({'error': str(e)}), 500

    @api_bp.route('/history', methods=['GET'])
    def public_history():
        """Get daily outage aggregated statistics. Public, no token required."""
        try:
            days = request.args.get('days', default=30, type=int)
            days = max(1, min(days, 365))
            history_data = stats_service.get_daily_history(days)
            return jsonify(history_data), 200
        except Exception as e:
            logger.error(f"Error getting public history: {e}")
            return jsonify({'error': str(e)}), 500

    def _serialize_stats(val):
        if isinstance(val, dict):
            res = {}
            for k, v in val.items():
                if isinstance(v, timedelta):
                    res[k] = {
                        'seconds': int(v.total_seconds()),
                        'human': DurationFormatter.format_duration(v)
                    }
                elif isinstance(v, (dict, list)):
                    res[k] = _serialize_stats(v)
                elif isinstance(v, datetime):
                    res[k] = v.isoformat()
                else:
                    res[k] = v
            return res
        elif isinstance(val, list):
            return [_serialize_stats(x) for x in val]
        elif isinstance(val, timedelta):
            return {
                'seconds': int(val.total_seconds()),
                'human': DurationFormatter.format_duration(val)
            }
        elif isinstance(val, datetime):
            return val.isoformat()
        return val

    @api_bp.route('/stats', methods=['GET'])
    def public_stats():
        """Get summary outage statistics. Public, no token required."""
        try:
            group_id = request.args.get('group_id', default=None, type=str)
            if group_id:
                data = stats_service.get_stats_for_group(group_id)
            else:
                data = stats_service.get_stats()
            return jsonify(_serialize_stats(data)), 200
        except Exception as e:
            logger.error(f"Error getting public stats: {e}")
            return jsonify({'error': str(e)}), 500

    @api_bp.route('/schedule/<group_id>', methods=['GET'])
    def public_schedule(group_id: str):
        """Get latest parsed outage schedule for a group. Public, no token required."""
        try:
            history = stats_service.get_schedule_history(group_id, limit=1)
            if not history:
                return jsonify({
                    'error': f'No schedule recorded for group: {group_id}',
                    'available_groups': [g.id for g in LOCATIONS.values() if g.yasno_group]
                }), 404

            latest = history[0]
            parsed_schedule = None
            try:
                parsed_schedule = json.loads(latest.schedule_text)
            except (json.JSONDecodeError, TypeError):
                parsed_schedule = {'raw': latest.schedule_text}

            ts = latest.timestamp.isoformat() if isinstance(latest.timestamp, datetime) else str(latest.timestamp)
            return jsonify({
                'group_id': latest.group_id,
                'timestamp': ts,
                'schedule': parsed_schedule
            }), 200
        except Exception as e:
            logger.error(f"Error getting public schedule for {group_id}: {e}")
            return jsonify({'error': str(e)}), 500

    @api_bp.route('/schedule-history/<group_id>', methods=['GET'])
    def public_schedule_history(group_id: str):
        """Get schedule history entries for a group. Preserves backward compatibility. Public, no token required."""
        try:
            limit = request.args.get('limit', default=10, type=int)
            limit = max(1, min(limit, 100))
            history = stats_service.get_schedule_history(group_id, limit=limit)
            return jsonify([h.__dict__ for h in history]), 200
        except Exception as e:
            logger.error(f"Error getting public schedule history for {group_id}: {e}")
            return jsonify({'error': str(e)}), 500

    return api_bp
