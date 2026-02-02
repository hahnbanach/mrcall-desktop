"""FastAPI main application - HTTP API for Zylch services."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
import logging

import colorlog

from zylch.api.routes import sync, chat, admin, webhooks, data, auth, commands, connections, memory, jobs
from zylch.api.firebase_auth import initialize_firebase
from zylch.config import settings

# Configure colored logging
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(levelname)-8s%(reset)s %(name)s: %(message)s',
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
))

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    handlers=[handler]
)

# Silence noisy third-party loggers
for noisy_logger in ["hpack", "httpcore", "httpx", "h2", "h11", "urllib3", "cachecontrol", "sentence_transformers", "LiteLLM"]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Zylch AI API",
    description="HTTP API for Zylch AI services - email intelligence, skills, and pattern learning",
    version="1.0.0"
)

# CORS middleware - read allowed origins from settings
allowed_origins = [
    origin.strip()
    for origin in settings.cors_allowed_origins.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(data.router, prefix="/api/data", tags=["data"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(commands.router, prefix="/api", tags=["commands"])
app.include_router(connections.router, prefix="/api", tags=["connections"])
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])


@app.on_event("startup")
async def startup_event():
    """Initialize services on application startup."""
    logger.info("Starting Zylch API server...")

    # Initialize Firebase Admin SDK for authentication
    firebase_app = initialize_firebase()
    if firebase_app:
        logger.info("Firebase authentication enabled")
    else:
        logger.warning("Firebase not configured - chat authentication will fail")

    # Background jobs cleanup
    try:
        from zylch.storage.supabase_client import SupabaseStorage
        storage = SupabaseStorage.get_instance()

        # Reset jobs stuck in "running" for >2 hours
        reset_count = storage.reset_stale_background_jobs(timeout_hours=2)
        if reset_count:
            logger.warning(f"Reset {reset_count} stale background jobs (>2h)")

        # Cleanup jobs older than 7 days
        deleted_count = storage.cleanup_old_background_jobs(retention_days=7)
        if deleted_count:
            logger.info(f"Cleaned up {deleted_count} old background jobs")

    except Exception as e:
        logger.warning(f"Background jobs cleanup skipped: {e}")

    logger.info("Zylch API server started successfully")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Zylch AI API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "skill_mode_enabled": settings.skill_mode_enabled
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "skill_mode": settings.skill_mode_enabled
    }


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """Robots.txt for search engines and LLM crawlers."""
    return """# Zylch AI API - https://api.zylchai.com
# AI-powered assistant for email, calendar, CRM, and integrations
#
# Zylch helps users manage:
# - Email (Gmail, Outlook) - smart inbox management
# - Calendar - scheduling and availability
# - CRM (Pipedrive) - contact and deal management
# - Phone (MrCall) - AI phone assistant configuration
#
# Main website: https://zylchai.com
# Documentation: https://zylchai.com/docs
# Contact: support@zylchai.com

User-agent: *
# Allow info endpoints
Allow: /
Allow: /health
Allow: /docs
Allow: /robots.txt

# Disallow API endpoints (require authentication, would fail anyway)
Disallow: /api/
Disallow: /webhooks/

# For LLM crawlers (GPTBot, Claude-Web, etc.):
# This is a REST API backend. For integration info, see https://zylchai.com/docs
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
