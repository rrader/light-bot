# Light Bot - Power Status Monitoring System

## Project Overview
Light Bot is a distributed power status monitoring system that tracks host availability and sends Telegram notifications when status changes. It consists of a remote Flask API server and a local bash monitoring script.

## Purpose
1. **Power Status Monitoring**: Track remote host(s) availability and notify a Telegram channel of power status changes (on/off)
2. **Daily Schedule Notifications**: Automatically send daily power outage schedules from Yasno API
3. **Schedule Change Detection**: Monitor and notify about changes to power outage schedules during the day
4. **Outage Warnings**: Send advance warnings 30 minutes before scheduled power outages with expected restoration time

## Tech Stack
- **Backend**: Python 3.11, Flask, python-telegram-bot
- **Infrastructure**: Docker, Docker Compose
- **Monitoring**: Bash script (monitor.sh) with ping-based detection
- **Testing**: pytest with async support

## Architecture
- **Remote Server**:
  - Flask API + Telegram bot (receives status updates, sends power status notifications)
  - Multi-Provider Schedule Service (supports both Yasno for Kyiv and VOE for Vinnytsia)
  - Composite client coordinates schedules across regions and routes notifications to respective channels
- **Local Routers**:
  - Kyiv: UDR7 router running `monitor.sh`
  - Vinnytsia: Keenetic Duo router running `monitor_keenetic.sh`
- **Communication**: HTTP POST with Bearer token authentication
- **Storage**: File-based persistence with timestamp in Kyiv timezone, SQLite history
- **Schedule Notifications**:
  - Evening (18:00–23:00): Tomorrow's power outage schedule as soon as published
  - Hourly checks: Detect and notify about schedule changes during the day
  - Advance warnings: 30-minute advance notice before scheduled outages
  - Power restoration info: includes next scheduled outage time on power-on alerts

## Key Files
- `main.py` - Entry point, starts Flask server and schedule monitoring
- `src/light_bot/core/bot.py` - TelegramChannelBot class for channel messaging
- `src/light_bot/core/server.py` - Flask API endpoints with token auth and multi-location power status
- `src/light_bot/services/schedule_service.py` - Coordinates schedule monitoring loops and composite client
- `src/light_bot/services/multi_group_schedule_manager.py` - Coordinates per-group senders
- `src/light_bot/services/group_schedule_sender.py` - Handles change detection, rollover and warnings per group
- `src/light_bot/api/yasno/` - Yasno Power Outage API client (Kyiv / DSO 902)
- `src/light_bot/api/voe/` - Vinnytsiaoblenergo (VOE) schedule client (parses GPV format from community data)
- `src/light_bot/api/composite_client.py` - Composite client aggregating schedules across providers by city/group
- `src/light_bot/formatters/schedule_formatter.py` - Formats schedule and warning messages with per-city and channel footers
- `src/light_bot/formatters/power_status_formatter.py` - Formats power status change messages
- `monitor.sh` - UDR monitoring script (Kyiv)
- `scripts/monitor_keenetic.sh` - Keenetic monitoring script (Vinnytsia)
- `config.py` - Environment variable management and location/group configurations
- `tests/` - Comprehensive unit tests

## Running the Project
- **Local Monitor**: `./monitor.sh` (with API_TOKEN env var set)
- **Local Dev / Standalone**: `docker compose up -d` or `python main.py`

## Production Deployment on Monica

In production on `monica`, `light-bot` runs as part of the unified `/root/services` Docker Compose stack under the `prod-public` profile. It must be connected to the `services_default` network so that Caddy reverse-proxy can reach it on port 5000:

- **Correct deploy / restart command:**
  ```bash
  cd /root/services && docker compose --profile prod-public up -d --build light-bot
  ```
- **Volume mount:** Always uses the host bind mount `/root/services/light-bot/data:/data` (or `./data:/data`) to preserve persistent state files across container recreations (`watchdog_status_vinnytsia.txt`, hashes, and sqlite db).
- **Network caveat:** NEVER run standalone `docker compose up -d` solely inside `/root/services/light-bot` without `--project-directory /root/services` — otherwise it spawns in isolated `light-bot_default` network, Caddy fails with `502 Bad Gateway`, and Home Assistant's REST poller mistakenly reports an outage.

## Testing
- `pytest tests/ -v` - Run all tests
- `pytest tests/test_bot.py -v` - Test Telegram integration
- `pytest tests/test_server.py -v` - Test API endpoints

## Configuration
Key environment variables in `.env`:
- `TELEGRAM_BOT_TOKEN` - Bot token for posting updates
- `TELEGRAM_CHANNEL_ID` - Default channel for Kyiv power status notifications
- `TELEGRAM_CHANNEL_ID_VINNYTSIA` - Channel for Vinnytsia power status notifications (`@vinnytsia_kalichanska_4`)
- `TELEGRAM_SCHEDULE_CHANNEL_ID` - Channel for schedule notifications (can be same as status channel)
- `YASNO_CITY` - City for schedules (default: kiev)
- `YASNO_GROUP` - Power group to monitor (default: 2.1)
- `SCHEDULE_CHECK_INTERVAL` - How often to check for changes in seconds (default: 3600)
- `SCHEDULE_EVENING_HOUR` - Hour to send tomorrow's schedule (default: 20)
- `OUTAGE_WARNING_MINUTES` - Minutes before outage to send warning (default: 30)
- `OUTAGE_WARNING_CHECK_INTERVAL` - How often to check for upcoming outages in seconds (default: 300)

### Home Assistant Instant Webhook Updates (Zero-Polling)
To eliminate latency from HA poll intervals, `light-bot` triggers HA webhooks upon status changes:
- `HA_WEBHOOK_URL_KYIV` (or `HA_WEBHOOK_URL_HOME`) - Webhook for Kyiv power status updates (`https://ha.rmn.pp.ua/api/webhook/power_status_update_kyiv_89a1c4`).
- `HA_WEBHOOK_URL_VINNYTSIA` - Webhook for Vinnytsia power status updates (`https://ha.rmn.pp.ua/api/webhook/power_status_update_vinnytsia_3b7e92`).

**Strict Webhook Isolation Rule:** Never combine or route multiple locations through a single webhook URL. Each location MUST have its own independent webhook ID and HA automation to prevent crosstalk or invalid state overwrites.

## UDR Credentials

UDR SSH credentials are stored encrypted in `.udr-credentials.enc` (committed to git).
The plaintext `.udr-credentials` is gitignored.

To decrypt:
```bash
openssl rsautl -decrypt -inkey ~/.ssh/personal -in .udr-credentials.enc -out .udr-credentials
```

Or with the newer syntax:
```bash
openssl pkeyutl -decrypt -inkey ~/.ssh/personal -in .udr-credentials.enc -out .udr-credentials
```

Then `source .udr-credentials` to load `UDR_HOST`, `UDR_USER`, `UDR_PASSWORD`.

## Deploying monitor.sh to the Router

The script runs on the UDR managed by systemd service `light-bot-monitor.service`.
- Script location: `/config/monitor.sh`
- Service file: `/etc/systemd/system/light-bot-monitor.service`
- The service sets env vars (`SMART_SOCKET_IP`, `AC1_IP`, etc.) that override script defaults.

```bash
# Load credentials
source .udr-credentials

# Upload the script and service file
sshpass -p "$UDR_PASSWORD" scp -o StrictHostKeyChecking=no monitor.sh ${UDR_USER}@${UDR_HOST}:/config/monitor.sh
sshpass -p "$UDR_PASSWORD" scp -o StrictHostKeyChecking=no light-bot-monitor.service ${UDR_USER}@${UDR_HOST}:/etc/systemd/system/light-bot-monitor.service

# Reload systemd and restart the service
sshpass -p "$UDR_PASSWORD" ssh -o StrictHostKeyChecking=no ${UDR_USER}@${UDR_HOST} "systemctl daemon-reload && systemctl restart light-bot-monitor"

# Check it's running
sshpass -p "$UDR_PASSWORD" ssh -o StrictHostKeyChecking=no ${UDR_USER}@${UDR_HOST} "systemctl status light-bot-monitor"
```

Note: `light-bot-monitor.service` in the repo uses `REPLACE_WITH_TOKEN` / `REPLACE_WITH_UDR_API_KEY` placeholders — fill in the real values from `.udr-credentials` or `.env` before deploying, or edit directly on the router.

## Deploying monitor_keenetic.sh in Vinnytsia (KN-2110)

The script runs on the Keenetic Duo router in Vinnytsia under Entware:
- Script location: `/opt/etc/power-monitor/monitor_keenetic.sh` (source: `scripts/monitor_keenetic.sh`)
- Init script: `/opt/etc/init.d/S99power-monitor`
- Env config: `/opt/etc/power-monitor/.env`
  - Defines `API_URL="https://light.rmn.pp.ua/power-status/vinnytsia"`
  - Defines `HA_WEBHOOK_URL="https://ha.rmn.pp.ua/api/webhook/power_status_update_vinnytsia_3b7e92"`
  - Defines `SMART_SOCKET_IP="192.168.1.187"`
  - Defines `API_TOKEN="..."`
- On state transitions, `monitor_keenetic.sh` sends updates to both the Light-Bot backend AND directly to Home Assistant's Vinnytsia webhook in the background for sub-second reaction.

## Dependencies
- **yasno_hass**: Power outage schedule API client adapted from [kuzin2006/yasno_hass](https://github.com/kuzin2006/yasno_hass) - originally a Home Assistant integration, modified to work as a standalone module for fetching Ukrainian power grid outage schedules from Yasno API
