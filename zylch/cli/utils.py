"""CLI utilities — env loading and owner identity."""

import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

ZYLCH_DIR = os.path.expanduser("~/.zylch")
ENV_PATH = os.path.join(ZYLCH_DIR, ".env")


def load_env():
    """Load .env from ~/.zylch/ if it exists.

    Falls back to project-level .env for dev environments.
    """
    if os.path.exists(ENV_PATH):
        load_dotenv(ENV_PATH, override=True)
        logger.debug(f"[CLI] Loaded env from {ENV_PATH}")
    else:
        logger.debug(
            f"[CLI] No env at {ENV_PATH}, using project .env"
        )
        load_dotenv()


def get_owner_id() -> str:
    """Get owner ID for standalone mode (single-user).

    Uses EMAIL_ADDRESS as the identity key. Falls back to
    'local-user' when no email is configured.
    """
    owner_id = os.environ.get("EMAIL_ADDRESS", "local-user")
    logger.debug(f"[CLI] owner_id={owner_id}")
    return owner_id


def ensure_zylch_dir():
    """Create ~/.zylch/ directory if it doesn't exist."""
    os.makedirs(ZYLCH_DIR, exist_ok=True)
    logger.debug(f"[CLI] Ensured dir {ZYLCH_DIR}")
