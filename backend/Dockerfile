# ---- frontend builder ----
# node:20-slim is multi-arch (ARM64 + x86_64) — runs natively on Pi 5.
FROM node:20-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ---- python deps builder ----
FROM python:3.12-slim-bookworm AS builder
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ---- runtime ----
FROM python:3.12-slim-bookworm AS runtime
RUN useradd -m -u 1000 app
WORKDIR /app
COPY --from=builder /root/.local /home/app/.local
COPY --from=frontend-builder /frontend/dist /app/static
ENV PATH=/home/app/.local/bin:$PATH
COPY --chown=app:app backend/ .
USER app
HEALTHCHECK --interval=30s --timeout=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
