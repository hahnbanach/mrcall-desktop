# Railway Procfile for Zylch services
# This defines the different process types Railway can run

# Main API server (default web process)
web: uvicorn zylch.api.main:app --host 0.0.0.0 --port $PORT

# Avatar compute worker (cron job - runs every 5 minutes)
# Schedule: */5 * * * * (every 5 minutes)
# Configure in Railway dashboard or railway.json
worker: python -m zylch.workers.avatar_compute_worker

# Alternative: Run as scheduler if Railway doesn't support cron
# scheduler: while true; do python -m zylch.workers.avatar_compute_worker; sleep 300; done
