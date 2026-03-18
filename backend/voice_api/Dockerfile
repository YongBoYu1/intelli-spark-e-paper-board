FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY backend/voice_api/requirements.txt ./backend/voice_api/requirements.txt
RUN pip install --no-cache-dir -r backend/voice_api/requirements.txt

COPY app ./app
COPY backend ./backend
COPY docs/prompt ./docs/prompt

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.voice_api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
