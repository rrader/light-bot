#!/usr/bin/env python3
"""
monitor.py — Multi-location ping watchdog for light-bot

Pings one or more target IP addresses (e.g. smart socket, ACs, router)
and sends power status updates ("on" / "off") to the Light Bot API.

Usage:
    # Run for default home location:
    python3 monitor.py

    # Run for Vinnytsia:
    python3 monitor.py --location vinnytsia --targets 192.168.1.93

    # Run once (check & report single state):
    python3 monitor.py --location vinnytsia --targets 192.168.1.93 --once

Environment variables:
    API_TOKEN               - Light Bot API token
    API_URL                 - Base API URL (default: https://light.rmn.pp.ua/power-status)
    LOCATION                - Location identifier (default: home)
    PING_TARGETS            - Space-separated list of target IPs to ping
    CHECK_INTERVAL          - Seconds between ping checks (default: 5)
    CONSECUTIVE_CHECKS_ON   - Required consecutive successful pings for ON (default: 3)
    CONSECUTIVE_CHECKS_OFF  - Required consecutive failed pings for OFF (default: 3)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('light_bot_monitor')


def ping_host(ip: str, timeout: int = 2) -> bool:
    """Ping a single IP address once. Returns True if host is reachable."""
    # Determine ping options based on OS
    if sys.platform == "win32":
        cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), ip]
    elif sys.platform == "darwin":
        cmd = ["ping", "-c", "1", "-W", str(timeout * 1000), ip]
    else:
        # Linux / router
        cmd = ["ping", "-c", "1", "-W", str(timeout), ip]

    try:
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0
    except Exception as e:
        logger.debug(f"Ping execution error for {ip}: {e}")
        return False


def check_targets(targets: list[str], timeout: int = 2) -> bool:
    """Returns True if AT LEAST ONE target IP is reachable."""
    for ip in targets:
        if ping_host(ip, timeout):
            return True
    return False


def send_status(api_url: str, token: str, location: str, status: str) -> bool:
    """Send power status update to Light Bot API."""
    # Construct target URL
    clean_url = api_url.rstrip('/')
    if location and location != 'home':
        target_url = f"{clean_url}/{location}"
    else:
        target_url = clean_url

    headers = {
        'Authorization': f'Bearer {token}' if not token.startswith('Bearer ') else token,
        'Content-Type': 'application/json',
        'User-Agent': f'LightBotMonitor/2.0 ({location})'
    }

    payload = json.dumps({'status': status}).encode('utf-8')
    req = urllib.request.Request(target_url, data=payload, headers=headers, method='POST')

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('utf-8')
            logger.info(f"✓ [{location.upper()}] Status '{status}' sent successfully ({resp.status}): {data}")
            return True
    except urllib.error.HTTPError as e:
        logger.error(f"✗ [{location.upper()}] HTTP Error {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        logger.error(f"✗ [{location.upper()}] Failed to send status: {e}")

    return False


def parse_args():
    parser = argparse.ArgumentParser(description="Light Bot Multi-Location Power Watchdog")
    parser.add_argument('--location', '-l', default=os.getenv('LOCATION', 'home'),
                        help="Location ID (e.g. 'home', 'vinnytsia')")
    parser.add_argument('--targets', '-t', nargs='+',
                        default=os.getenv('PING_TARGETS', '').split() if os.getenv('PING_TARGETS') else None,
                        help="Target IP address(es) to ping")
    parser.add_argument('--api-url', default=os.getenv('API_URL', 'https://light.rmn.pp.ua/power-status'),
                        help="Light Bot API endpoint")
    parser.add_argument('--token', default=os.getenv('API_TOKEN'),
                        help="Light Bot API token")
    parser.add_argument('--interval', type=int, default=int(os.getenv('CHECK_INTERVAL', 5)),
                        help="Check interval in seconds (default: 5)")
    parser.add_argument('--consecutive-on', type=int, default=int(os.getenv('CONSECUTIVE_CHECKS_ON', 3)),
                        help="Consecutive checks required for ON status (default: 3)")
    parser.add_argument('--consecutive-off', type=int, default=int(os.getenv('CONSECUTIVE_CHECKS_OFF', 3)),
                        help="Consecutive checks required for OFF status (default: 3)")
    parser.add_argument('--once', action='store_true',
                        help="Run a single check and exit")
    parser.add_argument('--dry-run', action='store_true',
                        help="Check targets without sending API requests")
    return parser.parse_args()


def main():
    args = parse_args()

    # Load targets defaults by location if none provided
    if not args.targets:
        if args.location == 'vinnytsia':
            args.targets = ['192.168.1.93']
        else:
            args.targets = ['192.168.1.152', '192.168.1.77', '192.168.1.94', '192.168.1.206']

    if not args.token and not args.dry_run:
        logger.error("API_TOKEN is required. Pass --token or set API_TOKEN in environment.")
        sys.exit(1)

    logger.info(f"Starting Light Bot Monitor for [{args.location}]")
    logger.info(f"Targets: {', '.join(args.targets)}")
    logger.info(f"API URL: {args.api_url}")
    logger.info(f"Check interval: {args.interval}s (ON: {args.consecutive_on}, OFF: {args.consecutive_off})")

    if args.once:
        is_up = check_targets(args.targets)
        status = 'on' if is_up else 'off'
        logger.info(f"Single check: hosts are {'UP' if is_up else 'DOWN'} -> status: {status}")
        if not args.dry_run:
            send_status(args.api_url, args.token, args.location, status)
        return

    consecutive_up = 0
    consecutive_down = 0

    while True:
        try:
            is_up = check_targets(args.targets)
            if is_up:
                consecutive_up += 1
                consecutive_down = 0
                logger.info(f"Hosts status: UP (up: {consecutive_up}, down: {consecutive_down})")
            else:
                consecutive_down += 1
                consecutive_up = 0
                logger.info(f"Hosts status: DOWN (up: {consecutive_up}, down: {consecutive_down})")

            if consecutive_up == args.consecutive_on:
                logger.info(f"→ Reached {args.consecutive_on} consecutive UP checks. Sending 'on'...")
                if not args.dry_run:
                    send_status(args.api_url, args.token, args.location, 'on')
                consecutive_up = 0

            elif consecutive_down == args.consecutive_off:
                logger.info(f"→ Reached {args.consecutive_off} consecutive DOWN checks. Sending 'off'...")
                if not args.dry_run:
                    send_status(args.api_url, args.token, args.location, 'off')
                consecutive_down = 0

            time.sleep(args.interval)

        except KeyboardInterrupt:
            logger.info("Monitor stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected loop error: {e}", exc_info=True)
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
