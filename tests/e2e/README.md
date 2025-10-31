# End-to-End Tests

This directory contains end-to-end tests that simulate real-world power monitoring scenarios without requiring external services.

## Test Files

### `test_power_monitoring.py` - Power Status E2E Tests (8 tests)

Simulates complete power monitoring workflows:

**Power Monitoring Scenarios:**
1. **Complete Power Outage Cycle** - Power ON → OFF → ON with duration tracking
2. **Multiple Rapid Status Changes** - Flapping power (seconds-level tracking)
3. **Long Multi-Day Outage** - Extended outages (3 days, 5 hours)
4. **First Boot Scenario** - Initial deployment with no previous state
5. **Monitor Script Simulation** - Repeated checks, notifications only on change
6. **Realistic Daily Pattern** - Full day simulation with 5 status changes

**Error Recovery:**
1. **Corrupted State Recovery** - Handles corrupted timestamp gracefully
2. **System Clock Adjustment** - Handles negative durations (DST, manual changes)

### `test_with_monitor.sh` - Real monitor.sh Integration ⭐

**Actually runs monitor.sh** against a simple test server:
- Starts minimal mock Flask server (no dependencies)
- Executes real monitor.sh script with test config
- Verifies monitor sends status updates
- Verifies server receives and records status
- Tests duration tracking with real time delays

## Running E2E Tests

### Quick Start - Run All Tests ⭐

```bash
# Single command to run ALL tests (recommended)
make test-all
```

This runs:
1. All 52 Python tests (unit + integration + e2e)
2. monitor.sh integration test
3. Total: 53 tests in ~20 seconds

### Individual Test Commands

**Python E2E Tests:**
```bash
# All Python tests (52 tests)
make test

# Just E2E Python tests (12 tests)
make test-e2e
pytest tests/e2e/ -v

# Power monitoring tests only (8 tests)
pytest tests/e2e/test_power_monitoring.py -v

# Schedule integration tests only (4 tests)
pytest tests/e2e/test_schedule_integration.py -v
```

**monitor.sh Integration:**
```bash
# Run real monitor.sh against test server
make test-monitor
# or
./tests/e2e/test_with_monitor.sh
```

**Other:**
```bash
make test-unit         # Unit tests only (13 tests)
make test-integration  # Integration tests only (27 tests)
make clean            # Clean test artifacts
```

## Test Structure

Each E2E test:
1. Sets up a test server with temporary state file
2. Simulates real monitoring scenarios by:
   - Sending HTTP POST requests to `/power-status`
   - Manipulating timestamps in the state file to simulate time passing
   - Verifying Telegram notifications are sent with correct content
3. Validates:
   - Status changes trigger notifications
   - Duration calculations are accurate
   - Ukrainian formatting is correct
   - Edge cases are handled gracefully

### `test_schedule_integration.py` - Yasno Schedule E2E Tests (4 tests)

Tests the complete Yasno schedule integration:

1. **Yasno API Parsing** - Parses real production API format
2. **Schedule Formatter with Real Data** - Formats messages from real API structure
3. **Empty Schedule Handling** - Handles days with no outages
4. **Yasno API to Telegram Flow** - Complete flow: API → Parse → Format → (Send)

## What E2E Tests Cover

**Power Monitoring:**
- ✅ Complete power monitoring workflow
- ✅ Duration tracking through multiple state changes
- ✅ Short durations (seconds), medium (hours), long (days)
- ✅ Rapid status changes (power flapping)
- ✅ First boot (no previous state)
- ✅ Monitor script behavior simulation
- ✅ Realistic daily patterns
- ✅ Corrupted state file recovery
- ✅ System clock adjustments
- ✅ Negative duration handling

**Yasno Schedule Integration:**
- ✅ Real Yasno API format parsing
- ✅ Schedule message formatting
- ✅ Outage time display (HH:MM format)
- ✅ Empty schedule handling
- ✅ Multiple power groups support
- ✅ Today/tomorrow schedule handling
