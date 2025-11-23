import logging
import threading
import asyncio
from light_bot.core.server import run_server
from light_bot.config import FLASK_PORT, DB_PATH
from light_bot.services.stats_service import StatsService
from light_bot.services.schedule_service import get_schedule_service

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def run_schedule_monitoring():
    """Run schedule monitoring and outage warnings in dedicated event loop"""
    stats_service = StatsService(db_path=DB_PATH)
    schedule_service = get_schedule_service(stats_service)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Run both monitoring loops in parallel
        loop.run_until_complete(asyncio.gather(
            schedule_service.schedule_monitoring_loop(),
            schedule_service.outage_warning_loop()
        ))
    except Exception as e:
        logger.error(f"Schedule monitoring error: {e}")
    finally:
        loop.close()


def main():
    """Main entry point - starts Flask API server and schedule monitoring service"""
    logger.info("Starting Light Bot: Flask API + Schedule Monitoring")

    flask_thread = threading.Thread(target=run_server, args=(FLASK_PORT,), daemon=True)
    flask_thread.start()
    logger.info(f"Flask server started on port {FLASK_PORT}")

    schedule_thread = threading.Thread(target=run_schedule_monitoring, daemon=True)
    schedule_thread.start()
    logger.info("Schedule monitoring started")

    try:
        flask_thread.join()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        # This is a bit of a hack, but it's the easiest way to stop the monitoring
        # without a major refactor.
        stats_service = StatsService(db_path=DB_PATH)
        schedule_service = get_schedule_service(stats_service)
        schedule_service.stop_monitoring()


if __name__ == '__main__':
    main()
