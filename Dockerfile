# Copernicus Berlin AI Assistant — production image
#
# Use Playwright's official image so we don't have to manage Chromium
# system deps ourselves. The image already ships with Python 3.12 +
# Chromium + every shared library Chromium needs. Saves ~15 minutes of
# apt-get juggling and avoids breakage on Alpine/Debian variants.

FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Default to 2 workers — keeps memory under 600 MB on Railway's free
    # trial. Override via Railway env vars (WORKERS) for production.
    WORKERS=2 \
    PORT=8000

WORKDIR /app

# Install Python deps first so Docker layer-caches them across rebuilds.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application source.
COPY app ./app
COPY scripts ./scripts

# Pre-built knowledge base + seed config travel with the image so the
# container is immediately useful. Runtime state (SQLite DB, analytics)
# is written to /app/data at runtime — mount a volume to persist it.
COPY data ./data

# Railway sends SIGTERM on redeploys; uvicorn handles it gracefully.
EXPOSE 8000

# Use sh -c so we can interpolate $PORT and $WORKERS at runtime — Railway
# injects $PORT dynamically.
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS:-2} --proxy-headers --forwarded-allow-ips='*'"
