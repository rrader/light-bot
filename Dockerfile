FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir -r requirements.txt && \
    pip install -e .

RUN mkdir -p /data

ENV WATCHDOG_STATUS_FILE=/data/watchdog_status.txt
ENV LAST_SCHEDULE_HASH_FILE=/data/last_schedule_hash.txt
ENV LAST_CHECK_DATE_FILE=/data/last_check_date.txt
ENV TOMORROW_SENT_DATE_FILE=/data/tomorrow_sent_date.txt

EXPOSE 5000

CMD ["python", "-m", "light_bot"]
