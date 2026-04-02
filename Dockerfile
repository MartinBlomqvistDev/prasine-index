# Prasine Index — production Docker image.
# Multi-stage build: dependencies in the builder stage, minimal runtime image.
# Designed for deployment on Cloud Run, Fly.io, or any container platform.

# ---------------------------------------------------------------------------
# Stage 1: dependency builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies required for asyncpg and other C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ---------------------------------------------------------------------------
# Stage 2: runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY agents/     ./agents/
COPY api/        ./api/
COPY core/       ./core/
COPY ingest/     ./ingest/
COPY models/     ./models/
COPY eval/       ./eval/

# Non-root user for security
RUN addgroup --system prasine && adduser --system --ingroup prasine prasine
USER prasine

# Uvicorn serves on 8080 to match Cloud Run / Fly.io defaults
ENV PORT=8080
EXPOSE 8080

# Health check — verifies the API is accepting requests
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 2"]
