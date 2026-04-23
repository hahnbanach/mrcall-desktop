#!/bin/bash
# Initialize the Zylch database schema.
# Run this after starting PostgreSQL (docker compose up postgres).
#
# Usage:
#   ./scripts/init-db.sh              # uses DATABASE_URL from .env
#   DATABASE_URL=... ./scripts/init-db.sh   # explicit URL

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "Running Alembic migrations..."
alembic upgrade head

echo "Database initialized successfully."
