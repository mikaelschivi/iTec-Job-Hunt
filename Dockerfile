FROM python:3.13.17-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY watcher ./watcher

RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001

CMD ["python", "-m", "watcher.main"]
