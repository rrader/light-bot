#!/bin/sh
# ==============================================================================
# monitor_keenetic.sh — Power status monitor for Keenetic (Entware / POSIX sh)
# Location: Vinnytsia (KN-2110)
# ==============================================================================

PATH="/opt/bin:/opt/sbin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PATH

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="/opt/var/run/power-monitor.pid"
LOGFILE="/opt/var/log/power-monitor.log"

# Load .env if present
if [ -f "$SCRIPT_DIR/.env" ]; then
    . "$SCRIPT_DIR/.env"
fi

LOCATION="${LOCATION:-vinnytsia}"
TARGET_IP="${SMART_SOCKET_IP_VINNYTSIA:-${TARGET_IP:-192.168.1.93}}"
API_URL="${API_URL_PROD:-https://light.rmn.pp.ua/power-status}"
ENDPOINT_URL="${API_URL%/}/$LOCATION"
API_TOKEN="${API_TOKEN:-your_api_token_here}"

CHECK_INTERVAL="${CHECK_INTERVAL:-5}"
PING_TIMEOUT="${PING_TIMEOUT:-2}"
PING_COUNT="${PING_COUNT:-1}"
CONSECUTIVE_CHECKS="${CONSECUTIVE_CHECKS:-3}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

check_host() {
    # BusyBox ping syntax
    ping -c "$PING_COUNT" -W "$PING_TIMEOUT" "$TARGET_IP" > /dev/null 2>&1
    return $?
}

send_status() {
    status="$1"
    log "Sending status update to $ENDPOINT_URL: status=$status"

    response=$(curl -s -w "\n%{http_code}" -X POST "$ENDPOINT_URL" \
        -H "Authorization: $API_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"status\": \"$status\"}" 2>&1)

    http_code=$(echo "$response" | tail -n 1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        log "Successfully updated status to $status (HTTP $http_code)"
        return 0
    else
        log "Failed to send status (HTTP $http_code): $body"
        return 1
    fi
}

run_daemon() {
    trap 'log "Power monitor daemon stopping..."; rm -f "$PIDFILE"; exit 0' TERM INT

    CURRENT_STATUS="unknown"
    CONSECUTIVE_SUCCESS=0
    CONSECUTIVE_FAIL=0

    log "Starting Keenetic power monitor for $LOCATION (monitoring $TARGET_IP -> $ENDPOINT_URL)..."

    while true; do
        if check_host; then
            CONSECUTIVE_FAIL=0
            CONSECUTIVE_SUCCESS=$((CONSECUTIVE_SUCCESS + 1))
            
            if [ "$CONSECUTIVE_SUCCESS" -ge "$CONSECUTIVE_CHECKS" ] && [ "$CURRENT_STATUS" != "on" ]; then
                log "Device $TARGET_IP is ONLINE (confirmed $CONSECUTIVE_SUCCESS times)"
                CURRENT_STATUS="on"
                send_status "on"
            fi
        else
            CONSECUTIVE_SUCCESS=0
            CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
            
            if [ "$CONSECUTIVE_FAIL" -ge "$CONSECUTIVE_CHECKS" ] && [ "$CURRENT_STATUS" != "off" ]; then
                log "Device $TARGET_IP is OFFLINE (confirmed $CONSECUTIVE_FAIL times)"
                CURRENT_STATUS="off"
                send_status "off"
            fi
        fi

        sleep "$CHECK_INTERVAL"
    done
}

is_running() {
    if [ -f "$PIDFILE" ]; then
        pid=$(cat "$PIDFILE" 2>/dev/null)
        if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
            return 0
        fi
    fi
    return 1
}

start() {
    if is_running; then
        echo "Power monitor is already running (PID $(cat "$PIDFILE"))"
        return 0
    fi

    mkdir -p /opt/var/run /opt/var/log
    echo "Starting power monitor..."
    start-stop-daemon -S -b -m -p "$PIDFILE" -O "$LOGFILE" -x /bin/sh -- /opt/etc/power-monitor/monitor_keenetic.sh run
    sleep 1
    if is_running; then
        echo "Started with PID $(cat "$PIDFILE")"
    else
        echo "Failed to start. Check $LOGFILE"
        return 1
    fi
}

stop() {
    if is_running; then
        echo "Stopping power monitor (PID $(cat "$PIDFILE"))..."
        start-stop-daemon -K -p "$PIDFILE" -s TERM
        for i in 1 2 3 4 5; do
            if ! is_running; then
                break
            fi
            sleep 1
        done
        rm -f "$PIDFILE"
        echo "Stopped."
    else
        echo "Power monitor is not running."
        rm -f "$PIDFILE"
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        sleep 1
        start
        ;;
    status)
        if is_running; then
            echo "Power monitor is running (PID $(cat "$PIDFILE"))"
            exit 0
        else
            echo "Power monitor is NOT running"
            exit 1
        fi
        ;;
    check)
        if ! is_running; then
            log "Watchdog: Power monitor was not running, restarting..." >> "$LOGFILE"
            start
        fi
        ;;
    once)
        if check_host; then
            send_status "on"
        else
            send_status "off"
        fi
        ;;
    run)
        run_daemon
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|check|once|run}"
        exit 1
        ;;
esac
