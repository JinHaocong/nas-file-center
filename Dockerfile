# Stage 1: Build React Frontend
FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Build fclones binary
FROM rust:1-bookworm AS fclones-builder
ARG FCLONES_VERSION=0.35.0
RUN cargo install fclones --version "${FCLONES_VERSION}" --locked

# Stage 3: Python Runtime
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CONFIG_DIR=/config \
    DATA_MOUNT=/data
WORKDIR /app
COPY --from=fclones-builder /usr/local/cargo/bin/fclones /usr/local/bin/fclones
COPY --from=frontend-builder /build/dist /app/frontend/dist
COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
RUN python -m pip install --upgrade pip && python -m pip install .
RUN mkdir -p /config /data
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
