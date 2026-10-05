import asyncio
import logging
import os
import threading
import requests
from datetime import datetime
from functools import wraps
from typing import Optional, Tuple
from flask import Flask, request, jsonify, render_template
from light_bot.core.bot import telegram_bot
from light_bot.core.file_utils import atomic_write_text, read_text
from light_bot.formatters.power_status_formatter import PowerStatusFormatter
from light_bot.formatters.duration_formatter import DurationFormatter
from light_bot.formatters.schedule_formatter import ScheduleFormatter
from light_bot.api.yasno import YasnoScheduleResponse, SlotType, client as yasno_client
from light_bot.config import API_TOKEN, WATCHDOG_STATUS_FILE, TIMEZONE, YASNO_GROUP_CONFIGS, DB_PATH, LOCATIONS, get_location_config, HA_WEBHOOK_URL
from light_bot.core.schedule_tools import find_next_outage
from light_bot.services.stats_service import StatsService
from light_bot.core.stats_blueprint import create_stats_blueprint
from light_bot.core.schedule_history_blueprint import create_schedule_history_blueprint

logger = logging.getLogger(__name__)

app = Flask(__name__)
stats_service = StatsService(DB_PATH)
app.register_blueprint(create_stats_blueprint(stats_service))
app.register_blueprint(create_schedule_history_blueprint(stats_service), url_prefix='/api')


_loop = None


def get_or_create_eventloop():
    """Get or create event loop for async Telegram operations"""
    global _loop
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        return _loop


def require_api_token(f):
    """Decorator to require API token authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')

        if not token:
            return jsonify({'error': 'Missing Authorization header'}), 401

        # Support both "Bearer <token>" and plain token
        if token.startswith('Bearer '):
            token = token[7:]

        if token != API_TOKEN:
            return jsonify({'error': 'Invalid API token'}), 403

        return f(*args, **kwargs)

    return decorated_function


def notify_ha_webhook(loc, status: str, timestamp: datetime):
    """Notify dedicated Home Assistant webhook about power status change with low latency."""
    webhook_url = getattr(loc, 'ha_webhook_url', None)
    if not webhook_url:
        return

    def _send():
        try:
            payload = {
                'location': loc.id,
                'status': status,
                'timestamp': timestamp.isoformat()
            }
            resp = requests.post(webhook_url, json=payload, timeout=5)
            logger.info(f"HA webhook sent to dedicated {loc.id} endpoint ({status}): HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Failed to send HA webhook for {loc.id}: {e}")

    threading.Thread(target=_send, daemon=True).start()


def write_power_status(status: str, file_path: Optional[str] = None):
    """Write power status to file with timestamp in Kyiv timezone"""
    target_file = file_path or WATCHDOG_STATUS_FILE
    try:
        timestamp = datetime.now(TIMEZONE).isoformat()
        content = f"{status}\nLast updated: {timestamp}\n"
        atomic_write_text(target_file, content)
        logger.info(f"Power status written to file ({target_file}): {status}")
        return True
    except Exception as e:
        logger.error(f"Error writing power status to file ({target_file}): {e}")
        return False


def read_power_status(file_path: Optional[str] = None):
    """Read current power status from file with parsed timestamp"""
    target_file = file_path or WATCHDOG_STATUS_FILE
    try:
        content = read_text(target_file)
        if content:
            lines = content.split('\n')
            if lines:
                status = lines[0].strip()
                timestamp_line = lines[1].strip() if len(lines) > 1 else 'Unknown'

                # Parse timestamp if available
                timestamp_obj = None
                if timestamp_line.startswith('Last updated: '):
                    try:
                        timestamp_str = timestamp_line.replace('Last updated: ', '')
                        timestamp_obj = datetime.fromisoformat(timestamp_str)
                    except (ValueError, AttributeError) as e:
                        logger.warning(f"Could not parse timestamp: {e}")

                return {
                    'status': status,
                    'last_updated': timestamp_line,
                    'timestamp': timestamp_obj
                }
        return {'status': 'Unknown', 'last_updated': 'Never', 'timestamp': None}
    except Exception as e:
        logger.error(f"Error reading power status from file ({target_file}): {e}")
        return {'status': 'Error', 'last_updated': str(e), 'timestamp': None}


def find_next_outage_for_group(group_id: Optional[str] = 'home') -> Optional[Tuple[str, str, bool]]:
    """Find next scheduled outage for a specific Yasno group."""
    if not group_id:
        return None
    try:
        schedule_data = yasno_client.update()

        if schedule_data and YASNO_GROUP_CONFIGS:
            group_config = next((g for g in YASNO_GROUP_CONFIGS if g.id == group_id), None)
            if group_config and group_config.group:
                try:
                    next_outage_info = find_next_outage(schedule_data, group_config.group)
                    if not next_outage_info:
                        return None

                    start_dt, end_dt = next_outage_info
                    start_time = start_dt.strftime('%H:%M')
                    end_time = end_dt.strftime('%H:%M')
                    now = datetime.now(TIMEZONE)
                    is_today = start_dt.date() == now.date()
                    return (start_time, end_time, is_today)
                except Exception as e:
                    logger.error(f"Error finding next outage for group {group_id}: {e}")
                    return None
            else:
                logger.warning(f"No group with id='{group_id}' found in YASNO_GROUP_CONFIGS")
    except Exception as e:
        logger.warning(f"Could not fetch next outage info for group {group_id}: {e}")

    return None


def find_next_outage_home() -> Optional[Tuple[str, str, bool]]:
    """Find the next scheduled outage (home group only)"""
    return find_next_outage_for_group('home')


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200


def _handle_power_status_update(status: str, location_id: Optional[str] = None, is_legacy_post: bool = False):
    """Internal helper to process power status update for any location."""
    if status not in ['on', 'off']:
        return jsonify({'error': 'Status must be "on" or "off"'}), 400

    loc = get_location_config(location_id)
    if not loc:
        return jsonify({'error': f'Unknown location: {location_id}'}), 404

    target_file = None if loc.id == 'home' else loc.status_file

    # Check if status actually changed
    current_status = read_power_status(target_file)
    status_changed = current_status.get('status', '').lower() != status if current_status else True

    # Calculate duration if we have a previous timestamp AND status changed
    duration_text = None
    if status_changed and current_status.get('timestamp'):
        try:
            current_timestamp = datetime.now(TIMEZONE)
            previous_timestamp = current_status['timestamp']

            # Ensure both timestamps are timezone-aware
            if previous_timestamp.tzinfo is None:
                # Timestamp is naive, assume it's in our configured timezone
                previous_timestamp = TIMEZONE.localize(previous_timestamp)
            elif previous_timestamp.tzinfo != current_timestamp.tzinfo:
                # Different timezone, convert to our configured timezone
                previous_timestamp = previous_timestamp.astimezone(TIMEZONE)

            duration = current_timestamp - previous_timestamp

            # Ignore negative durations (clock skew/system time changes)
            if duration.total_seconds() < 0:
                logger.warning(f"Negative duration detected ({duration.total_seconds()}s), skipping duration display")
                duration_text = None
            else:
                duration_text = DurationFormatter.format_duration(duration)
                logger.info(f"Duration calculated for {loc.id}: {duration_text}")

        except (TypeError, ValueError) as e:
            logger.error(f"Error calculating duration (timestamp issue): {e}")
            duration_text = None
        except Exception as e:
            logger.error(f"Unexpected error calculating duration: {e}", exc_info=True)
            duration_text = None

    # Only write status to file if status changed (to preserve timestamp)
    if status_changed:
        if not write_power_status(status, target_file):
            return jsonify({'error': 'Failed to write status to file'}), 500
        
        # Record event in DB
        stats_service.record_event(status, datetime.now(TIMEZONE), location=loc.id)

    # Only send notification if status changed
    notification_sent = False
    if status_changed:
        timestamp = datetime.now(TIMEZONE)
        loc_display_name = None if loc.id == 'home' else loc.name

        if status == 'on':
            next_outage_info = find_next_outage_for_group(loc.yasno_group) if loc.yasno_group else None

            if next_outage_info:
                start_time, end_time, is_today = next_outage_info
                message = PowerStatusFormatter.format_power_on_message(
                    timestamp,
                    duration_text,
                    next_outage_start=start_time,
                    next_outage_end=end_time,
                    is_today=is_today,
                    location_name=loc_display_name
                )
            else:
                message = PowerStatusFormatter.format_power_on_message(
                    timestamp,
                    duration_text,
                    location_name=loc_display_name
                )
        else:
            message = PowerStatusFormatter.format_power_off_message(
                timestamp,
                duration_text,
                location_name=loc_display_name
            )

        loop = get_or_create_eventloop()
        if loc.channel_id and loc.channel_id != telegram_bot.channel_id:
            coro = telegram_bot.send_message(message, chat_id=loc.channel_id)
        else:
            coro = telegram_bot.send_message(message)
        loop.run_until_complete(coro)
        notification_sent = True
        logger.info(f"Status changed to {status} for {loc.id}, notification sent")

        # Notify Home Assistant dedicated webhook
        notify_ha_webhook(loc, status, timestamp)
    else:
        logger.info(f"Status unchanged ({status}) for {loc.id}, no notification sent")

    response_data = {
        'status': 'success',
        'power_status': status,
        'status_changed': status_changed,
        'notification_sent': notification_sent
    }
    if not is_legacy_post:
        response_data['location'] = loc.id

    return jsonify(response_data), 200


@app.route('/power-status', methods=['POST'])
@require_api_token
def update_power_status():
    """
    Update power status and send notification to Telegram channel

    Expected JSON body:
    {
        "status": "on" or "off",
        "location": "home" (optional)
    }

    Requires Authorization header with API token

    Note: Only sends notification if status actually changed
    """
    try:
        data = request.get_json()

        if not data or 'status' not in data:
            return jsonify({'error': 'Missing required field: status'}), 400

        status = data['status'].lower() if isinstance(data['status'], str) else str(data['status']).lower()
        loc_id = data.get('location')
        is_legacy = (loc_id is None or loc_id.lower() == 'home')

        return _handle_power_status_update(status, loc_id, is_legacy_post=is_legacy)

    except Exception as e:
        logger.error(f"Error updating power status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/power-status/<location_id>', methods=['POST'])
@require_api_token
def update_location_power_status(location_id: str):
    """
    Update power status for a specific location.

    Expected JSON body:
    {
        "status": "on" or "off"
    }
    """
    try:
        data = request.get_json()

        if not data or 'status' not in data:
            return jsonify({'error': 'Missing required field: status'}), 400

        status = data['status'].lower() if isinstance(data['status'], str) else str(data['status']).lower()

        return _handle_power_status_update(status, location_id, is_legacy_post=False)

    except Exception as e:
        logger.error(f"Error updating power status for location {location_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/power-status', methods=['GET'])
@require_api_token
def get_power_status():
    """
    Get current power status for default location (home)

    Requires Authorization header with API token
    """
    try:
        status = read_power_status()
        return jsonify(status), 200
    except Exception as e:
        logger.error(f"Error getting power status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/power-status/<location_id>', methods=['GET'])
@require_api_token
def get_location_power_status(location_id: str):
    """
    Get current power status for a specific location

    Requires Authorization header with API token
    """
    try:
        loc = get_location_config(location_id)
        if not loc:
            return jsonify({'error': f'Unknown location: {location_id}'}), 404

        target_file = None if loc.id == 'home' else loc.status_file
        status = read_power_status(target_file)
        return jsonify({
            'location': loc.id,
            'name': loc.name,
            'status': status.get('status'),
            'last_updated': status.get('last_updated'),
            'timestamp': status.get('timestamp').isoformat() if status.get('timestamp') else None
        }), 200
    except Exception as e:
        logger.error(f"Error getting power status for location {location_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/locations', methods=['GET'])
@require_api_token
def list_locations():
    """
    List all configured locations with their current status

    Requires Authorization header with API token
    """
    try:
        result = []
        for loc in LOCATIONS.values():
            target_file = None if loc.id == 'home' else loc.status_file
            st = read_power_status(target_file)
            result.append({
                'id': loc.id,
                'name': loc.name,
                'status': st.get('status'),
                'last_updated': st.get('last_updated'),
                'yasno_group': loc.yasno_group
            })
        return jsonify({'locations': result}), 200
    except Exception as e:
        logger.error(f"Error listing locations: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/schedule-history/<group_id>', methods=['GET'])
def schedule_history(group_id: str):
    """Render schedule history for a group"""
    try:
        history = stats_service.get_schedule_history(group_id)
        return render_template('schedule_history.html', history=history, group_id=group_id)
    except Exception as e:
        logger.error(f"Error getting schedule history: {e}")
        return "Error", 500


def run_server(port=5000):
    """Run the Flask server"""
    logger.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
