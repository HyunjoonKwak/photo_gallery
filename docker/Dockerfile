# syntax=docker/dockerfile:1

# --- Stage 1: build the frontend (Vite) ---
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
# npm ci for reproducible installs from the lockfile.
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: backend runtime serving the built frontend ---
FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FRONTEND_DIST=/app/static \
    SQLITE_PATH=/data/app.db

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /frontend/dist ./static

# Run as a non-root user; give it ownership of the SQLite volume mount point.
RUN useradd --system --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 9800
VOLUME ["/data"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9800"]
