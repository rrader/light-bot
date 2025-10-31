#!/usr/bin/env python3
"""
Simple mock server for testing monitor.sh

This is a minimal Flask server that just captures power status updates.
No Telegram, no Yasno, no dependencies - just the /power-status endpoint.
"""

from flask import Flask, request, jsonify
from datetime import datetime
import pytz
import sys

app = Flask(__name__)

# Store status updates
status_history = []
current_status = None
last_timestamp = None

TIMEZONE = pytz.timezone('Europe/Kyiv')
API_TOKEN = "test_e2e_api_token_12345"


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200


@app.route('/power-status', methods=['POST'])
def update_power_status():
    """Receive power status from monitor.sh"""
    global current_status, last_timestamp

    # Check auth
    token = request.headers.get('Authorization', '')
    if token.startswith('Bearer '):
        token = token[7:]

    if token != API_TOKEN:
        return jsonify({'error': 'Invalid token'}), 403

    data = request.get_json()
    if not data or 'status' not in data:
        return jsonify({'error': 'Missing status'}), 400

    status = data['status'].lower()
    if status not in ['on', 'off']:
        return jsonify({'error': 'Status must be on or off'}), 400

    # Calculate duration if we have previous timestamp
    duration_seconds = None
    duration_text = None
    if last_timestamp and current_status and current_status != status:
        now = datetime.now(TIMEZONE)
        duration = now - last_timestamp
        duration_seconds = duration.total_seconds()
        duration_text = f"{int(duration_seconds)} seconds"
        print(f"[{now.strftime('%H:%M:%S')}] Duration calculated: {duration_text}", file=sys.stderr)

    status_changed = current_status != status

    # Update state
    now = datetime.now(TIMEZONE)
    current_status = status
    last_timestamp = now

    # Record in history
    status_history.append({
        'status': status,
        'timestamp': now.isoformat(),
        'duration_seconds': duration_seconds,
        'status_changed': status_changed
    })

    print(f"[{now.strftime('%H:%M:%S')}] Status: {status.upper()} (changed: {status_changed})", file=sys.stderr)

    return jsonify({
        'status': 'success',
        'power_status': status,
        'status_changed': status_changed,
        'notification_sent': status_changed,
        'duration_seconds': duration_seconds
    }), 200


@app.route('/power-status', methods=['GET'])
def get_power_status():
    """Get current power status"""
    token = request.headers.get('Authorization', '')
    if token.startswith('Bearer '):
        token = token[7:]

    if token != API_TOKEN:
        return jsonify({'error': 'Invalid token'}), 403

    return jsonify({
        'status': current_status or 'Unknown',
        'last_updated': last_timestamp.isoformat() if last_timestamp else 'Never'
    }), 200


@app.route('/test/history', methods=['GET'])
def get_history():
    """Get all status updates (for test verification)"""
    return jsonify({
        'count': len(status_history),
        'current_status': current_status,
        'history': status_history
    })


@app.route('/test/clear', methods=['POST'])
def clear_history():
    """Clear history (for test setup)"""
    global status_history, current_status, last_timestamp
    status_history = []
    current_status = None
    last_timestamp = None
    return jsonify({'status': 'cleared'})


if __name__ == '__main__':
    print("Starting simple mock server on port 5558", file=sys.stderr)
    print(f"API Token: {API_TOKEN}", file=sys.stderr)
    app.run(host='0.0.0.0', port=5558, debug=False)
