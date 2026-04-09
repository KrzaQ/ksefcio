# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + bundled frontend
FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

COPY backend/src/ ./src/
COPY backend/certs/ ./certs/

COPY --from=frontend-build /app/frontend/dist/ ./src/ksefcio/static/

ENV KSEFCIO_DB_PATH=/data/ksefcio.db
EXPOSE 8000
VOLUME ["/data"]

CMD ["uv", "run", "uvicorn", "ksefcio.main:app", "--host", "0.0.0.0", "--port", "8000"]
