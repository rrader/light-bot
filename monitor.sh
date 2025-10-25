#!/bin/bash

# Configuration
TARGET_IP="192.168.1.166"
API_URL="http://localhost:5000/power-status"
API_TOKEN="${API_TOKEN:-your_api_token_here}"
CHECK_INTERVAL="${CHECK_INTERVAL:-5}"  # seconds between checks
PING_TIMEOUT="${PING_TIMEOUT:-2}"      # ping timeout in seconds
PING_COUNT="${PING_COUNT:-1}"          # number of ping attempts
CONSECUTIVE_CHECKS="${CONSECUTIVE_CHECKS:-3}"  # number of consecutive checks required

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to check if host is reachable
check_host() {
    if ping -c "$PING_COUNT" -W "$PING_TIMEOUT" "$TARGET_IP" > /dev/null 2>&1; then
        return 0  # Host is up
    else
        return 1  # Host is down
    fi
}

# Function to send status to API
send_status() {
    local status=$1

    response=$(curl -s -w "\n%{http_code}" -X POST "$API_URL" \
        -H "Authorization: $API_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"status\": \"$status\"}")

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" -eq 200 ]; then
        log "${GREEN}✓${NC} Status sent successfully: $status"
        return 0
    else
        log "${RED}✗${NC} Failed to send status. HTTP code: $http_code, Response: $body"
        return 1
    fi
}

# Main monitoring loop
main() {
    log "${YELLOW}Starting host monitoring...${NC}"
    log "Target: $TARGET_IP"
    log "API: $API_URL"
    log "Check interval: ${CHECK_INTERVAL}s"
    log "Ping timeout: ${PING_TIMEOUT}s"
    log "Consecutive checks required: $CONSECUTIVE_CHECKS"
    echo ""

    # Initialize counters
    consecutive_up=0
    consecutive_down=0
    last_sent_status=""

    while true; do
        if check_host; then
            consecutive_up=$((consecutive_up + 1))
            consecutive_down=0
            current_check="up"
            status_text="${GREEN}UP${NC}"
        else
            consecutive_down=$((consecutive_down + 1))
            consecutive_up=0
            current_check="down"
            status_text="${RED}DOWN${NC}"
        fi

        log "Host $TARGET_IP is $status_text (up: $consecutive_up, down: $consecutive_down)"

        # Check if we should send status update
        should_send=false
        new_status=""

        if [ $consecutive_up -ge $CONSECUTIVE_CHECKS ] && [ "$last_sent_status" != "on" ]; then
            should_send=true
            new_status="on"
            log "${GREEN}→${NC} $CONSECUTIVE_CHECKS consecutive successful pings - sending ON status"
        elif [ $consecutive_down -ge $CONSECUTIVE_CHECKS ] && [ "$last_sent_status" != "off" ]; then
            should_send=true
            new_status="off"
            log "${RED}→${NC} $CONSECUTIVE_CHECKS consecutive failed pings - sending OFF status"
        fi

        if [ "$should_send" = true ]; then
            if send_status "$new_status"; then
                last_sent_status="$new_status"
            fi
        fi

        sleep "$CHECK_INTERVAL"
    done
}

# Check if API_TOKEN is set
if [ "$API_TOKEN" = "your_api_token_here" ]; then
    log "${RED}ERROR: API_TOKEN environment variable is not set${NC}"
    log "Usage: API_TOKEN=your_token ./monitor.sh"
    log "Or set it in your .env file and run: source .env && ./monitor.sh"
    exit 1
fi

# Run main function
main
