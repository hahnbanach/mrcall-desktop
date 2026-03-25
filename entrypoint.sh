#!/bin/sh

# Run database migrations if DB is configured
if [ -n "$DATABASE_URL" ]; then
    echo "Running database migrations..."
    alembic upgrade head 2>&1 || echo "WARNING: migrations failed"
fi

# Start the API server
exec uvicorn zylch.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
