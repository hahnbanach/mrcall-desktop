"""FastAPI main application - HTTP API for Zylch services."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from zylch.api.routes import sync, chat, admin, webhooks, data, auth, commands, connections, memory
from zylch.api.firebase_auth import initialize_firebase
from zylch.config import settings

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

# Silence noisy third-party loggers
for noisy_logger in ["hpack", "httpcore", "httpx", "h2", "h11", "urllib3", "cachecontrol"]:
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
