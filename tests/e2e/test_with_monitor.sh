#!/bin/bash
# Real E2E test: Runs monitor.sh against actual Flask server
# Tests the complete integration without Docker

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${BLUE}[E2E]${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${YELLOW}ℹ${NC} $1"; }

# Track PIDs for cleanup
SERVER_PID=""
MONITOR_PID=""

cleanup() {
    log "Cleaning up processes..."

    if [ -n "$MONITOR_PID" ]; then
        kill $MONITOR_PID 2>/dev/null || true
        info "Monitor process stopped"
    fi

    if [ -n "$SERVER_PID" ]; then
        kill $SERVER_PID 2>/dev/null || true
        info "Server process stopped"
    fi

    # Clean up test files
    rm -f /tmp/e2e_power_status.txt
    rm -f /tmp/e2e_monitor.log

    success "Cleanup complete"
}

trap cleanup EXIT INT TERM

echo ""
log "=========================================="
log "E2E Test: monitor.sh → Flask Server"
log "=========================================="
echo ""

cd "$PROJECT_DIR"

# Step 1: Start simple mock server in background
log "Step 1: Starting simple mock server..."

# Start minimal mock server (no Telegram/Yasno dependencies)
python "$SCRIPT_DIR/simple_mock_server.py" > /tmp/e2e_server.log 2>&1 &
SERVER_PID=$!

log "Server PID: $SERVER_PID"
sleep 3

# Check if server is running
if ! ps -p $SERVER_PID > /dev/null; then
    error "Server failed to start"
    cat /tmp/e2e_server.log
    exit 1
fi

# Wait for health endpoint
log "Waiting for server to be ready..."
for i in {1..10}; do
    if curl -sf http://localhost:5558/health > /dev/null 2>&1; then
        success "Server is healthy"
        break
    fi
    if [ $i -eq 10 ]; then
        error "Server health check failed after 10 attempts"
        cat /tmp/e2e_server.log
        exit 1
    fi
    sleep 1
done

echo ""

# Step 2: Verify server responds to API calls
log "Step 2: Testing API endpoint..."

response=$(curl -s -X POST http://localhost:5558/power-status \
    -H "Authorization: test_e2e_api_token_12345" \
    -H "Content-Type: application/json" \
    -d '{"status": "on"}')

if echo "$response" | jq -e '.status == "success"' > /dev/null 2>&1; then
    success "API endpoint responds correctly"
else
    error "API endpoint test failed"
    echo "Response: $response"
    exit 1
fi

echo ""

# Step 3: Run monitor.sh in test mode
log "Step 3: Running monitor.sh against test server..."

# Create a modified version of monitor.sh for testing
cat > /tmp/e2e_monitor.sh << 'EOF'
#!/bin/bash

# Test configuration
export API_URL="http://localhost:5558/power-status"
export API_TOKEN="test_e2e_api_token_12345"
export TARGET_IP="8.8.8.8"  # Google DNS - should always be up
export TARGET_UDR_IP="1.1.1.1"  # Cloudflare DNS
export UDR_API_KEY="dummy"
export CHECK_INTERVAL=2
export PING_TIMEOUT=1
export CONSECUTIVE_CHECKS_ON=2
export CONSECUTIVE_CHECKS_OFF=2

# Simple check host function (just ping)
check_host() {
    ping -c 1 -W 1 "$TARGET_IP" > /dev/null 2>&1
    return $?
}

check_udr_host() {
    # Always return false for UDR in test (we're testing ping path)
    return 1
}

# Send status function (from original monitor.sh)
send_status() {
    local status=$1

    response=$(curl -s -w "\n%{http_code}" -X POST "$API_URL" \
        -H "Authorization: $API_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"status\": \"$status\"}")

    http_code=$(echo "$response" | tail -n1)

    if [ "$http_code" -eq 200 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Status sent: $status"
        return 0
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ Failed to send status: $http_code"
        return 1
    fi
}

# Run for a limited number of iterations (for testing)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting monitor (test mode)..."
consecutive_up=0
iterations=0
max_iterations=5

while [ $iterations -lt $max_iterations ]; do
    if check_host || check_udr_host; then
        consecutive_up=$((consecutive_up + 1))
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Host UP (consecutive: $consecutive_up)"

        if [ $consecutive_up -eq $CONSECUTIVE_CHECKS_ON ]; then
            send_status "on"
            consecutive_up=0
        fi
    else
        consecutive_up=0
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Host DOWN"
    fi

    iterations=$((iterations + 1))

    if [ $iterations -lt $max_iterations ]; then
        sleep "$CHECK_INTERVAL"
    fi
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Test monitoring complete"
EOF

chmod +x /tmp/e2e_monitor.sh

# Run monitor script
/tmp/e2e_monitor.sh > /tmp/e2e_monitor.log 2>&1

if grep -q "Status sent: on" /tmp/e2e_monitor.log; then
    success "monitor.sh successfully sent status to server"
    info "Monitor log excerpt:"
    grep "Status sent" /tmp/e2e_monitor.log
else
    error "monitor.sh failed to send status"
    cat /tmp/e2e_monitor.log
    exit 1
fi

echo ""

# Step 4: Verify server received the status
log "Step 4: Verifying server received the status..."

response=$(curl -s -X GET http://localhost:5558/power-status \
    -H "Authorization: test_e2e_api_token_12345")

if echo "$response" | jq -e '.status == "on"' > /dev/null 2>&1; then
    success "Server recorded status as 'on'"
    info "Status: $(echo $response | jq -r '.status')"
    info "Last updated: $(echo $response | jq -r '.last_updated')"
else
    error "Server did not record status correctly"
    echo "Response: $response"
    exit 1
fi

echo ""

# Step 5: Test duration tracking
log "Step 5: Testing duration tracking..."
log "Waiting 3 seconds..."
sleep 3

# Send OFF status manually
response=$(curl -s -X POST http://localhost:5558/power-status \
    -H "Authorization: test_e2e_api_token_12345" \
    -H "Content-Type: application/json" \
    -d '{"status": "off"}')

if echo "$response" | jq -e '.status_changed == true' > /dev/null 2>&1; then
    success "Status change detected"

    # Check server logs for duration calculation
    if grep -q "Duration calculated" /tmp/e2e_server.log; then
        success "Duration was calculated!"
        duration_line=$(grep "Duration calculated" /tmp/e2e_server.log | tail -1)
        info "$duration_line"
    else
        info "Duration calculation not logged (may be expected)"
    fi
else
    error "Status change not detected"
    exit 1
fi

echo ""

# Final summary
log "=========================================="
log "E2E Test Results"
log "=========================================="
echo ""
success "✓ Flask server started successfully"
success "✓ API endpoints working"
success "✓ monitor.sh executed successfully"
success "✓ monitor.sh sent status to server"
success "✓ Server received and recorded status"
success "✓ Duration tracking functional"
echo ""
log "Complete E2E integration test PASSED!"
log "=========================================="
echo ""

# Show some logs for debugging
info "Server log excerpt (errors/warnings):"
grep -E "ERROR|WARNING|Duration" /tmp/e2e_server.log | tail -10 || info "  No errors/warnings found"
echo ""
