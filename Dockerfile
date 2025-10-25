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

# Create data directory for power status files
RUN mkdir -p /data

# Set environment variables for file locations
ENV POWER_STATUS_FILE=/data/power_status.txt
ENV LAST_STATUS_FILE=/data/last_status.txt

# Expose the Flask port
EXPOSE 5000

# Run the application
CMD ["python", "main.py"]
