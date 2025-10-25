import logging
import threading
from server import run_server
from config import FLASK_PORT

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """
    Main entry point that starts Flask server

    Note: File monitoring is disabled because the API endpoint directly sends
    Telegram notifications when called. The monitoring would create duplicate
    notifications since both the API and monitoring would send messages.
    """
    logger.info("Starting Telegram Channel Bot with Flask Server")

    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_server, args=(FLASK_PORT,), daemon=True)
    flask_thread.start()
    logger.info(f"Flask server thread started on port {FLASK_PORT}")

    # Keep the main thread alive
    try:
        flask_thread.join()
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == '__main__':
    main()
