#!/bin/sh
echo "Starting uvicorn on port ${PORT:-8000}..."
export LITELLM_LOCAL_MODEL_COST_MAP=True
exec uvicorn zylch.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
