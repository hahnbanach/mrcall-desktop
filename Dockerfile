FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (build tools for hnswlib, libpq for psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (explicit to avoid .dockerignore issues)
COPY zylch/ ./zylch/
COPY data/ ./data/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY pyproject.toml .
COPY entrypoint.sh .

# Create non-root user for security
RUN useradd -m -u 1000 zylch && \
    chown -R zylch:zylch /app

# Create directories for runtime data
RUN mkdir -p /app/cache /app/.swarm /app/credentials && \
    chown -R zylch:zylch /app/cache /app/.swarm /app/credentials

USER zylch

# Expose API port (Railway provides PORT env var)
EXPOSE 8000

# Set default PORT if not provided
ENV PORT=8000

# Health check (uses PORT env var)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Default command: run migrations then start API server
CMD ["bash", "entrypoint.sh"]
