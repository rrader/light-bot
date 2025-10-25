# Telegram Channel Bot with Flask Server

A Telegram bot that posts power status updates to a channel, with a Flask server running in a separate thread to handle secure API requests.

## Features

- Track power status (on/off) and write to file
- Send automated notifications to Telegram channel when power status changes
- Secure API with token authentication
- Flask REST API protected with API token
- Multi-threaded architecture (Flask server runs in separate thread)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHANNEL_ID=@your_channel_username_or_id
FLASK_PORT=5000
API_TOKEN=your_secure_api_token_here
POWER_STATUS_FILE=power_status.txt
```

**Important:**
- Generate a secure API token: `openssl rand -hex 32`
- The router script needs the API_TOKEN and the remote server URL
- Use the same API_TOKEN in both router script and server `.env`

### 3. Create Telegram Bot and Channel

1. Create a bot with [@BotFather](https://t.me/BotFather) on Telegram
2. Copy the bot token to your `.env` file
3. Create a Telegram channel
4. Add your bot as an administrator to the channel
5. Copy the channel username (e.g., `@mychannel`) or ID to your `.env` file

## Deployment

### Remote Server Setup (Bot + API)

The bot and API server run on a remote server (VPS, cloud instance, etc.).

**Using Docker (Recommended):**

1. Clone repository on remote server
2. Configure `.env` with your credentials
3. Start the service:

```bash
docker-compose up -d
```

4. View logs:

```bash
docker-compose logs -f
```

5. Verify it's running:

```bash
curl http://localhost:5000/health
```

**Using Python Directly:**

```bash
source venv/bin/activate
python main.py
```

The Flask server will start on port 5000 (or your configured port).

### Local Router Setup (Monitoring Script)

The monitoring script runs on your local router/device that can ping the target host.

1. Copy `monitor.sh` to your router device

2. Make it executable:

```bash
chmod +x monitor.sh
```

3. Configure environment variables:

```bash
export API_TOKEN=your_api_token_here
export API_URL=https://your-server.com:5000/power-status
export TARGET_IP=192.168.1.166
export CHECK_INTERVAL=5
export CONSECUTIVE_CHECKS=3
```

4. Run the script:

```bash
./monitor.sh
```

5. Or run as a systemd service (see Host Monitoring Script section below)

**Note:** Ensure your remote server is accessible from the router device (open firewall port 5000 or use reverse proxy with HTTPS).

## API Endpoints

All endpoints (except `/health`) require an `Authorization` header with your API token.

### Health Check

```bash
GET /health
```

Response:
```json
{
  "status": "ok"
}
```

### Update Power Status

Updates the power status (on/off), writes it to file, and sends a notification to the Telegram channel.

```bash
POST /power-status
Authorization: your_api_token_here
Content-Type: application/json

{
  "status": "on"
}
```

Example with curl:
```bash
curl -X POST http://localhost:5000/power-status \
  -H "Authorization: your_api_token_here" \
  -H "Content-Type: application/json" \
  -d '{"status": "on"}'
```

Response:
```json
{
  "status": "success",
  "power_status": "on",
  "message": "Status updated and notification sent"
}
```

### Get Power Status

Retrieves the current power status from the file.

```bash
GET /power-status
Authorization: your_api_token_here
```

Example with curl:
```bash
curl -X GET http://localhost:5000/power-status \
  -H "Authorization: your_api_token_here"
```

Response:
```json
{
  "status": "on",
  "last_updated": "Last updated: 2025-10-25T12:34:56.789012"
}
```

## Project Structure

```
.
├── main.py              # Entry point - starts Flask server and monitoring threads
├── bot.py               # Telegram bot implementation with file monitoring
├── server.py            # Flask server with API endpoints
├── config.py            # Configuration and environment variables
├── monitor.sh           # Bash script to ping host and update API
├── requirements.txt     # Python dependencies
├── pytest.ini           # Pytest configuration
├── Dockerfile           # Docker image definition
├── docker-compose.yml   # Docker Compose configuration
├── tests/               # Test suite
│   ├── __init__.py
│   ├── conftest.py      # Pytest fixtures and configuration
│   ├── test_bot.py      # Tests for bot.py
│   └── test_server.py   # Tests for server.py
├── venv/                # Virtual environment (not in git)
├── .env                 # Environment variables (not in git)
├── .env.example         # Example environment variables
├── .gitignore           # Git ignore rules
└── README.md            # This file
```

## Architecture

### Overview

```
┌─────────────────┐      HTTP API        ┌──────────────────┐      Telegram API
│  Router Device  │ ──────────────────> │  Remote Server   │ ──────────────────> │ Telegram │
│                 │  (monitor.sh pings  │                  │   (bot sends msg)     │ Channel  │
│  - monitor.sh   │   host & calls API) │  - Flask API     │                       └──────────┘
│  - Pings host   │                      │  - Bot code      │
│  - 3 consecutive│                      │  - File storage  │
│    checks       │                      │                  │
└─────────────────┘                      └──────────────────┘
```

### Components

**Local Router Device:**
- Runs `monitor.sh` script
- Pings target host (192.168.1.166) every 5 seconds
- Requires 3 consecutive successes/failures before reporting
- Sends status update to remote API via HTTP

**Remote Server:**
- **Flask API** (single daemon thread): Receives status updates via REST API
- **Status Check**: Compares new status with current to detect changes
- **File Storage**: Persists status to file for history/recovery
- **Telegram Bot**: Sends notifications ONLY when status changes
- **Simplified**: No file monitoring thread (API directly sends notifications)

### Key Design Decisions

1. **No duplicate notifications**: API checks if status changed before sending notification
2. **3-ping threshold**: Router script prevents false positives from network glitches
3. **Direct notification**: API immediately sends to Telegram (no file monitoring loop)
4. **File persistence**: Status saved to file for recovery after restarts
5. **Stateless API**: Each request is independent, status determined by file comparison

## Authentication

The API uses token-based authentication. Include your API token in the `Authorization` header:

```
Authorization: your_api_token_here
```

Or with Bearer prefix:

```
Authorization: Bearer your_api_token_here
```

## Security

- Keep your API token secure and never commit it to version control
- Use strong, randomly generated tokens (e.g., `openssl rand -hex 32`)
- The API token is validated on every protected endpoint request
- Unauthorized requests return `401` or `403` status codes

## Error Handling

All endpoints return appropriate HTTP status codes:
- `200`: Success
- `400`: Bad request (missing required fields or invalid status value)
- `401`: Unauthorized (missing Authorization header)
- `403`: Forbidden (invalid API token)
- `500`: Server error

Error response format:
```json
{
  "error": "Error description"
}
```

## Power Status File

The power status is persisted to a file (default: `power_status.txt`) with the following format:

```
on
Last updated: 2025-10-25T12:34:56.789012
```

This file can be read by other applications or scripts to check the current power status.

## Docker Volume

When running with Docker, the power status file is stored in a named volume `power-data`, which persists across container restarts. You can inspect the volume with:

```bash
docker volume inspect light-bot_power-data
```

To backup the power status:

```bash
docker cp light-bot:/data/power_status.txt ./backup.txt
```

## Host Monitoring Script

The included `monitor.sh` script continuously pings a host and automatically updates the power status via the API.

### Features

- Continuously pings target host (default: 192.168.1.166)
- Requires 3 consecutive successful/failed pings before sending status update (prevents false positives)
- Only sends updates when status changes (on → off or off → on)
- Configurable ping interval, timeout, and consecutive check threshold
- Colored console output with timestamps showing consecutive ping counts
- Error handling and automatic retries

### Usage

1. Make sure the API token is set:

```bash
export API_TOKEN=your_api_token_here
```

Or source your .env file:

```bash
source .env
```

2. Run the monitoring script:

```bash
./monitor.sh
```

### Configuration

You can configure the script using environment variables:

```bash
# Set custom API token
export API_TOKEN=your_api_token_here

# Set custom target IP (default: 192.168.1.166)
export TARGET_IP=192.168.1.100

# Set custom API URL (default: http://localhost:5000/power-status)
export API_URL=http://your-server:5000/power-status

# Set check interval in seconds (default: 5)
export CHECK_INTERVAL=10

# Set ping timeout in seconds (default: 2)
export PING_TIMEOUT=3

# Set ping count (default: 1)
export PING_COUNT=2

# Set number of consecutive checks required (default: 3)
export CONSECUTIVE_CHECKS=5
```

**Note:** With default settings (CHECK_INTERVAL=5s, CONSECUTIVE_CHECKS=3), it takes 15 seconds (3 checks × 5 seconds) to confirm a status change.

### Running as a Service

To run the monitor script as a background service (systemd example):

Create `/etc/systemd/system/light-bot-monitor.service`:

```ini
[Unit]
Description=Light Bot Host Monitor
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/light-bot
Environment="API_TOKEN=your_api_token_here"
Environment="TARGET_IP=192.168.1.166"
Environment="API_URL=http://localhost:5000/power-status"
Environment="CHECK_INTERVAL=5"
Environment="CONSECUTIVE_CHECKS=3"
ExecStart=/path/to/light-bot/monitor.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable light-bot-monitor
sudo systemctl start light-bot-monitor
sudo systemctl status light-bot-monitor
```

View logs:

```bash
journalctl -u light-bot-monitor -f
```

## Testing

The project includes a comprehensive test suite with 29 tests covering both the bot and server functionality.

### Running Tests

1. Create and activate virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run all tests:

```bash
pytest tests/ -v
```

4. Run specific test file:

```bash
pytest tests/test_bot.py -v
pytest tests/test_server.py -v
```

5. Run with coverage report:

```bash
pytest tests/ --cov=. --cov-report=html
```

### Test Coverage

**bot.py tests** (12 tests):
- Bot initialization
- Message, photo, and document sending (success/failure)
- File operations (read/write power status and last status)
- Power status monitoring and change detection
- Monitoring start/stop functionality

**server.py tests** (17 tests):
- Health check endpoint
- Authentication (token validation, missing/invalid tokens)
- Power status updates (on/off with validation)
- Status retrieval from file
- File write/read operations
- Error handling (malformed JSON, empty requests)
- Bearer token support

All tests use mocking to avoid requiring actual Telegram credentials or network connectivity.

## Technical Notes

### Why No File Monitoring?

Earlier versions included a file monitoring thread that watched `power_status.txt` for changes. This was removed because:

1. **Duplicate Notifications**: Both the API endpoint AND file monitor would send notifications
2. **Unnecessary Complexity**: The router script is the ONLY writer to the file via API
3. **Direct Flow**: Router → API → Telegram is simpler and faster than Router → API → File → Monitor → Telegram

File monitoring would only be useful if:
- Multiple independent services wrote to the status file
- You wanted to detect manual file edits
- The file was modified by external processes

In our architecture, the file is ONLY written by the API endpoint, so monitoring it would just be watching our own writes.

### Thread Architecture

**Current (Simplified):**
- Main thread (keeps process alive)
- Flask API thread (daemon) - handles HTTP requests

**Previous (Removed):**
- ~~File monitoring thread~~ - caused duplicate notifications

### Status Change Detection

The API implements smart status change detection:
1. Before writing new status, reads current status from file
2. Compares new vs. current status
3. Only sends Telegram notification if status CHANGED
4. Always writes to file for persistence
5. Returns `status_changed` and `notification_sent` in response

This means:
- Router can send status on every check (no need to track state)
- API handles deduplication
- Single source of truth for status changes
