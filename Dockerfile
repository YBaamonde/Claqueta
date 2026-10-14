# syntax=docker/dockerfile:1.7
# ---------- 1) Compilar la interfaz (React + Vite) ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2) Imagen final: API FastAPI que también sirve la interfaz ----------
FROM python:3.13-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static

RUN groupadd --gid 1000 claqueta \
 && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin claqueta \
 && mkdir -p /data && chown claqueta:claqueta /data

WORKDIR /app
COPY backend/requirements.lock ./requirements.lock
RUN pip install -r requirements.lock

COPY backend/app ./app
COPY --from=web /web/dist ./static

USER claqueta
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Un solo proceso: el planificador (sincronizaciones, aprendizaje) corre como hilo dentro de la app.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
