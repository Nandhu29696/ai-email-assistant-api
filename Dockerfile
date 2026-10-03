FROM python:3.11-slim

WORKDIR /app

# Install system deps (fonts-dejavu-core: Unicode font for the PDF trailer page)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl libreoffice tesseract-ocr fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/storage /data && chown -R appuser /app/storage /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
