# syntax=docker/dockerfile:1

# ---- build the web app ------------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- runtime: one process serves the API and the built SPA -------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCAUTH_ENV=production \
    DOCAUTH_DATA_DIR=/data \
    DOCAUTH_FRONTEND_DIST=/app/frontend/dist
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/ backend/
RUN pip install --no-cache-dir ./backend
COPY --from=web /web/dist frontend/dist
RUN useradd --create-home --uid 10001 docauth && mkdir -p /data && chown docauth /data
USER docauth
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "docauth.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
