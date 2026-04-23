"""CLI utilities — profile-aware env loading and owner identity."""

import logging
import os

logger = logging.getLogger(__name__)

ZYLCH_DIR = os.path.expanduser("~/.zylch")


def load_env():
    """Load env from active profile (set by activate_profile).

    Falls back to project-level .env for dev environments.
    """
    from dotenv import load_dotenv

    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR")
    if profile_dir:
        env_path = os.path.join(profile_dir, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
            logger.debug(f"[CLI] Loaded env from {env_path}")
            return

    # Legacy fallback
    legacy_env = os.path.join(ZYLCH_DIR, ".env")
    if os.path.exists(legacy_env):
        load_dotenv(legacy_env, override=True)
        logger.debug(f"[CLI] Loaded env from {legacy_env}")
    else:
        load_dotenv()
        logger.debug("[CLI] Loaded project .env")


def get_owner_id() -> str:
    """Get owner ID (EMAIL_ADDRESS from active profile)."""
    owner_id = os.environ.get("EMAIL_ADDRESS", "local-user")
    logger.debug(f"[CLI] owner_id={owner_id}")
    return owner_id


def ensure_zylch_dir():
    """Create ~/.zylch/ directory if it doesn't exist."""
    os.makedirs(ZYLCH_DIR, exist_ok=True)


# Keep ENV_PATH for backward compat (used nowhere critical now)
ENV_PATH = os.path.join(ZYLCH_DIR, ".env")
