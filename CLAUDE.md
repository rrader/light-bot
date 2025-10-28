# Light Bot - Power Status Monitoring System

## Project Overview
Light Bot is a distributed power status monitoring system that tracks host availability and sends Telegram notifications when status changes. It consists of a remote Flask API server and a local bash monitoring script.

## Purpose
1. **Power Status Monitoring**: Track remote host(s) availability and notify a Telegram channel of power status changes (on/off)
2. **Daily Schedule Notifications**: Automatically send daily power outage schedules from Yasno API
3. **Schedule Change Detection**: Monitor and notify about changes to power outage schedules during the day

## Tech Stack
- **Backend**: Python 3.11, Flask, python-telegram-bot
- **Infrastructure**: Docker, Docker Compose
- **Monitoring**: Bash script (monitor.sh) with ping-based detection
- **Testing**: pytest with async support

## Architecture
- **Remote Server**:
  - Flask API + Telegram bot (receives status updates, sends power status notifications)
  - Schedule Service (fetches Yasno schedules, sends daily notifications, detects changes)
- **Local Router**: Bash script monitoring 2 hosts with 3-check threshold
- **Communication**: HTTP POST with Bearer token authentication
- **Storage**: File-based persistence with timestamp in Kyiv timezone
- **Schedule Notifications**:
  - Evening (20:00): Tomorrow's power outage schedule
  - Hourly checks: Detect and notify about schedule changes during the day

## Key Files
- `main.py` - Entry point, starts Flask server and schedule monitoring
- `bot.py` - TelegramChannelBot class for channel messaging
- `server.py` - Flask API endpoints with token auth
- `schedule_service.py` - Schedule monitoring and notification service
  - `ScheduleFormatter` - Formats Yasno schedule data for Telegram
  - `ScheduleService` - Monitors schedules and sends notifications
- `monitor.sh` - Local monitoring script (pings + API calls)
- `config.py` - Environment variable management
- `yasno_hass/` - Yasno Power Outage API client (adapted from kuzin2006/yasno_hass)
  - `api.py` - API client for fetching power outage schedules
  - `models.py` - Pydantic models for API data
- `tests/` - Comprehensive unit tests

## Running the Project
- **Remote Server**: `docker-compose up -d` or `python main.py`
- **Local Monitor**: `./monitor.sh` (with API_TOKEN env var set)

## Testing
- `pytest tests/ -v` - Run all tests
- `pytest tests/test_bot.py -v` - Test Telegram integration
- `pytest tests/test_server.py -v` - Test API endpoints

## Configuration
Key environment variables in `.env`:
- `TELEGRAM_SCHEDULE_CHANNEL_ID` - Channel for schedule notifications (can be same as status channel)
- `YASNO_CITY` - City for schedules (default: kiev)
- `YASNO_GROUP` - Power group to monitor (default: 2.1)
- `SCHEDULE_CHECK_INTERVAL` - How often to check for changes in seconds (default: 3600)
- `SCHEDULE_EVENING_HOUR` - Hour to send tomorrow's schedule (default: 20)

## Dependencies
- **yasno_hass**: Power outage schedule API client adapted from [kuzin2006/yasno_hass](https://github.com/kuzin2006/yasno_hass) - originally a Home Assistant integration, modified to work as a standalone module for fetching Ukrainian power grid outage schedules from Yasno API
