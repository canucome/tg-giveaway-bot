# Build context = repository root (see docker-compose.yml), so paths below are repo-relative.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY bot ./bot
COPY locales ./locales
COPY templates ./templates

RUN mkdir -p /app/data

EXPOSE 8080
CMD ["python", "-m", "bot"]
