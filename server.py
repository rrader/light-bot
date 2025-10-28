import asyncio
import logging
import os
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify
from bot import telegram_bot
from config import API_TOKEN, WATCHDOG_STATUS_FILE, TIMEZONE

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Create a dedicated event loop for async operations
_loop = None

def get_or_create_eventloop():
    """Get or create event loop for async operations"""
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


def write_power_status(status: str):
    """Write power status to file with timestamp in Kyiv timezone"""
    try:
        timestamp = datetime.now(TIMEZONE).isoformat()
        with open(WATCHDOG_STATUS_FILE, 'w') as f:
            f.write(f"{status}\n")
            f.write(f"Last updated: {timestamp}\n")
        logger.info(f"Power status written to file: {status}")
        return True
    except Exception as e:
        logger.error(f"Error writing power status to file: {e}")
        return False


def read_power_status():
    """Read current power status from file"""
    try:
        if os.path.exists(WATCHDOG_STATUS_FILE):
            with open(WATCHDOG_STATUS_FILE, 'r') as f:
                lines = f.readlines()
                if lines:
                    return {
                        'status': lines[0].strip(),
                        'last_updated': lines[1].strip() if len(lines) > 1 else 'Unknown'
                    }
        return {'status': 'Unknown', 'last_updated': 'Never'}
    except Exception as e:
        logger.error(f"Error reading power status from file: {e}")
        return {'status': 'Error', 'last_updated': str(e)}


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200


@app.route('/power-status', methods=['POST'])
@require_api_token
def update_power_status():
    """
    Update power status and send notification to Telegram channel

    Expected JSON body:
    {
        "status": "on" or "off"
    }

    Requires Authorization header with API token

    Note: Only sends notification if status actually changed
    """
    try:
        data = request.get_json()

        if not data or 'status' not in data:
            return jsonify({'error': 'Missing required field: status'}), 400

        status = data['status'].lower()

        if status not in ['on', 'off']:
            return jsonify({'error': 'Status must be "on" or "off"'}), 400

        # Check if status actually changed
        current_status = read_power_status()
        status_changed = current_status.get('status', '').lower() != status if current_status else True

        # Write status to file
        if not write_power_status(status):
            return jsonify({'error': 'Failed to write status to file'}), 500

        # Only send notification if status changed
        notification_sent = False
        if status_changed:
            kyiv_time = datetime.now(TIMEZONE).strftime('%d.%m.%Y %H:%M:%S')

            if status == 'on':
                # Power is back
                message = (
                    "⚡️ <b>Світло з'явилось!</b> ⚡️\n\n"
                    "✅ Електропостачання відновлено\n"
                    f"🕐 Час: {kyiv_time}\n\n"
                    "🏠 Можна користуватись побутовими приладами"
                )
            else:
                # Power is out
                message = (
                    "🔴 <b>Світло зникло</b> 🔴\n\n"
                    "❌ Електропостачання відсутнє\n"
                    f"🕐 Час: {kyiv_time}"
                )

            # Use event loop to send message
            loop = get_or_create_eventloop()
            loop.run_until_complete(telegram_bot.send_message(message))
            notification_sent = True
            logger.info(f"Status changed to {status}, notification sent")
        else:
            logger.info(f"Status unchanged ({status}), no notification sent")

        return jsonify({
            'status': 'success',
            'power_status': status,
            'status_changed': status_changed,
            'notification_sent': notification_sent
        }), 200

    except Exception as e:
        logger.error(f"Error updating power status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/power-status', methods=['GET'])
@require_api_token
def get_power_status():
    """
    Get current power status

    Requires Authorization header with API token
    """
    try:
        status = read_power_status()
        return jsonify(status), 200
    except Exception as e:
        logger.error(f"Error getting power status: {e}")
        return jsonify({'error': str(e)}), 500


def run_server(port=5000):
    """Run the Flask server"""
    logger.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
