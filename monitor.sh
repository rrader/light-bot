#!/bin/bash

source .env

# Configuration
SMART_SOCKET_IP="${SMART_SOCKET_IP:-192.168.4.152}"
AC1_IP="${AC1_IP:-192.168.4.77}"
AC2_IP="${AC2_IP:-192.168.4.94}"
AC3_IP="${AC3_IP:-192.168.4.206}"
TARGET_UDR_IP="${TARGET_UDR_IP:-192.168.1.10}"
API_URL_PROD="https://light.rmn.pp.ua/power-status"
API_URL_STAGING="https://light-staging.rmn.pp.ua/power-status"
API_TOKEN="${API_TOKEN:-your_api_token_here}"
UDR_API_KEY="${UDR_API_KEY:-your_udr_api_key_here}"
CHECK_INTERVAL="${CHECK_INTERVAL:-5}"  # seconds between checks
PING_TIMEOUT="${PING_TIMEOUT:-2}"      # ping timeout in seconds
PING_COUNT="${PING_COUNT:-1}"          # number of ping attempts
CONSECUTIVE_CHECKS_ON="${CONSECUTIVE_CHECKS_ON:-3}"   # checks required for ON status
CONSECUTIVE_CHECKS_OFF="${CONSECUTIVE_CHECKS_OFF:-3}"  # checks required for OFF status

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to check if any ping target is reachable
check_host() {
    for ip in "$SMART_SOCKET_IP" "$AC1_IP" "$AC2_IP" "$AC3_IP"; do
        if ping -c "$PING_COUNT" -W "$PING_TIMEOUT" "$ip" > /dev/null 2>&1; then
            return 0  # At least one host is up
        fi
    done
    return 1  # All hosts are down
}

# check_udr_host() {
#     if curl -sk -H "X-API-Key: $UDR_API_KEY" https://localhost/proxy/network/api/s/default/stat/sta | jq -e ".data[] | select(.ip==\"$TARGET_UDR_IP\")" >/dev/null 2>&1; then
#         return 0  # Host is up
#     else
#         return 1  # Host is down
#     fi
# }

# Function to send status to API
send_status() {
    local status=$1
    local success=0

    # Send to production
    response=$(curl -s -w "\n%{http_code}" -X POST "$API_URL_PROD" \
        -H "Authorization: $API_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"status\": \"$status\"}")

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" -eq 200 ]; then
        log "${GREEN}✓${NC} [PROD] Status sent successfully: $status"
        success=1
    else
        log "${RED}✗${NC} [PROD] Failed to send status. HTTP code: $http_code, Response: $body"
    fi

    # Send to staging
    response=$(curl -s -w "\n%{http_code}" -X POST "$API_URL_STAGING" \
        -H "Authorization: $API_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"status\": \"$status\"}")

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" -eq 200 ]; then
        log "${GREEN}✓${NC} [STAGING] Status sent successfully: $status"
        success=1
    else
        log "${RED}✗${NC} [STAGING] Failed to send status. HTTP code: $http_code, Response: $body"
    fi

    # Return success if at least one request succeeded
    [ $success -eq 1 ] && return 0 || return 1
}

# Main monitoring loop
main() {
    log "${YELLOW}Starting host monitoring...${NC}"
    log "Ping targets: $SMART_SOCKET_IP, $AC1_IP, $AC2_IP, $AC3_IP"
    # log "Target UDR IP: $TARGET_UDR_IP"
    log "API (Production): $API_URL_PROD"
    log "API (Staging): $API_URL_STAGING"
    log "Check interval: ${CHECK_INTERVAL}s"
    log "Ping timeout: ${PING_TIMEOUT}s"
    log "Consecutive checks for ON: $CONSECUTIVE_CHECKS_ON"
    log "Consecutive checks for OFF: $CONSECUTIVE_CHECKS_OFF"
    echo ""

    # Initialize counters
    consecutive_up=0
    consecutive_down=0

    while true; do
        # Check ping targets
        if check_host; then
            consecutive_up=$((consecutive_up + 1))
            consecutive_down=0
            status_text="${GREEN}UP${NC}"
            detail="(ping: UP)"
        else
            consecutive_down=$((consecutive_down + 1))
            consecutive_up=0
            status_text="${RED}DOWN${NC}"
            detail="(ping: DOWN)"
        fi

        log "Hosts status: $status_text $detail (up: $consecutive_up, down: $consecutive_down)"

        # Send update when required consecutive checks reached
        if [ $consecutive_up -eq $CONSECUTIVE_CHECKS_ON ]; then
            log "${GREEN}→${NC} $CONSECUTIVE_CHECKS_ON consecutive checks with at least one host UP - sending ON status"
            send_status "on"
            consecutive_up=0  # Reset counter after sending
        elif [ $consecutive_down -eq $CONSECUTIVE_CHECKS_OFF ]; then
            log "${RED}→${NC} $CONSECUTIVE_CHECKS_OFF consecutive checks with BOTH hosts DOWN - sending OFF status"
            send_status "off"
            consecutive_down=0  # Reset counter after sending
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

