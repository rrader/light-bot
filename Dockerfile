FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY bot.py .
COPY server.py .
COPY config.py .
COPY main.py .
COPY schedule_service.py .

# Copy yasno_hass module
COPY yasno_hass/ yasno_hass/

# Create data directory for status files
RUN mkdir -p /data

# Set environment variables for file locations
ENV WATCHDOG_STATUS_FILE=/data/watchdog_status.txt
ENV LAST_SCHEDULE_HASH_FILE=/data/last_schedule_hash.txt
ENV LAST_CHECK_DATE_FILE=/data/last_check_date.txt
ENV TOMORROW_SENT_DATE_FILE=/data/tomorrow_sent_date.txt

# Expose the Flask port
EXPOSE 5000

# Run the application
CMD ["python", "main.py"]
