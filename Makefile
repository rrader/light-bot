.PHONY: test test-unit test-integration test-e2e test-monitor test-all clean help

# Default target
help:
	@echo "Light Bot - Test Commands"
	@echo ""
	@echo "Usage:"
	@echo "  make test          - Run all Python tests (unit + integration + e2e)"
	@echo "  make test-all      - Run ALL tests including monitor.sh integration"
	@echo "  make test-unit     - Run only unit tests"
	@echo "  make test-integration - Run only integration tests"
	@echo "  make test-e2e      - Run only E2E Python tests"
	@echo "  make test-monitor  - Run monitor.sh integration test"
	@echo "  make clean         - Clean up test artifacts"
	@echo ""

# Run all Python tests (unit + integration + e2e)
test:
	@echo "Running all Python tests..."
	@pytest tests/ -v --tb=short

# Run only unit tests
test-unit:
	@echo "Running unit tests..."
	@pytest tests/test_*.py -v --tb=short

# Run only integration tests
test-integration:
	@echo "Running integration tests..."
	@pytest tests/test_server.py tests/test_bot.py -v --tb=short

# Run only E2E Python tests
test-e2e:
	@echo "Running E2E Python tests..."
	@pytest tests/e2e/ -v --tb=short

# Run monitor.sh integration test
test-monitor:
	@echo "Running monitor.sh integration test..."
	@./tests/e2e/test_with_monitor.sh

# Run ALL tests (Python + monitor.sh integration)
test-all:
	@echo "========================================"
	@echo "Running COMPLETE Test Suite"
	@echo "========================================"
	@echo ""
	@echo "Step 1: Python tests (unit + integration + e2e)..."
	@pytest tests/ -v --tb=line
	@echo ""
	@echo "Step 2: monitor.sh integration test..."
	@./tests/e2e/test_with_monitor.sh
	@echo ""
	@echo "========================================"
	@echo "ALL TESTS COMPLETED SUCCESSFULLY!"
	@echo "========================================"

# Clean up test artifacts
clean:
	@echo "Cleaning test artifacts..."
	@rm -rf .pytest_cache
	@rm -rf tests/__pycache__
	@rm -rf tests/*/__pycache__
	@rm -rf tests/e2e/__pycache__
	@rm -f /tmp/e2e_*.log /tmp/e2e_*.txt /tmp/e2e_*.sh
	@rm -rf test-data test-data-e2e
	@echo "✓ Cleaned"
