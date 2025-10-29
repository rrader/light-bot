FROM python:3.11-slim

WORKDIR /app

# Copy dependency files first for better layer caching
COPY requirements.txt pyproject.toml ./

# Install dependencies in a separate layer
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code after dependencies are installed
COPY src/ src/

# Install the package in editable mode
RUN pip install --no-cache-dir -e .

# Create data directory for runtime files
RUN mkdir -p /data

# Set environment variables for file locations
ENV WATCHDOG_STATUS_FILE=/data/watchdog_status.txt
ENV LAST_SCHEDULE_HASH_FILE=/data/last_schedule_hash.txt
ENV LAST_CHECK_DATE_FILE=/data/last_check_date.txt
ENV TOMORROW_SENT_DATE_FILE=/data/tomorrow_sent_date.txt

EXPOSE 5000

CMD ["python", "-m", "light_bot"]
