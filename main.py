import logging
import threading
import asyncio
from server import run_server
from config import FLASK_PORT
from schedule_service import schedule_service

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def run_schedule_monitoring():
    """Run schedule monitoring in asyncio event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(schedule_service.schedule_monitoring_loop())
    except Exception as e:
        logger.error(f"Schedule monitoring error: {e}")
    finally:
        loop.close()


def main():
    """
    Main entry point that starts Flask server and schedule monitoring

    Components:
    - Flask API: Receives power status updates and sends immediate notifications
    - Schedule Service: Sends daily power outage schedules and detects changes
    """
    logger.info("Starting Telegram Channel Bot with Flask Server and Schedule Monitoring")

    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_server, args=(FLASK_PORT,), daemon=True)
    flask_thread.start()
    logger.info(f"Flask server thread started on port {FLASK_PORT}")

    # Start schedule monitoring in a separate thread
    schedule_thread = threading.Thread(target=run_schedule_monitoring, daemon=True)
    schedule_thread.start()
    logger.info("Schedule monitoring thread started")

    # Keep the main thread alive
    try:
        flask_thread.join()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        schedule_service.stop_monitoring()


if __name__ == '__main__':
    main()
