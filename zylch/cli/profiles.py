"""Multi-profile management for Zylch standalone.

Each profile lives in ~/.zylch/profiles/{email}/ with its own
.env, zylch.db, and profile.lock. Inspired by rclone config.
"""

import fcntl
import logging
import os
import shutil

import click

logger = logging.getLogger(__name__)

ZYLCH_DIR = os.path.expanduser("~/.zylch")
PROFILES_DIR = os.path.join(ZYLCH_DIR, "profiles")

# Module-level state: set by activate_profile()
_active_profile: str | None = None
_active_profile_dir: str | None = None
_lock_fd = None


def list_profiles() -> list[str]:
    """Return sorted list of profile names (email addresses)."""
    if not os.path.isdir(PROFILES_DIR):
        return []
    profiles = []
    for name in sorted(os.listdir(PROFILES_DIR)):
        profile_dir = os.path.join(PROFILES_DIR, name)
        env_path = os.path.join(profile_dir, ".env")
        if os.path.isdir(profile_dir) and os.path.isfile(env_path):
            profiles.append(name)
    return profiles


def get_profile_dir(profile_name: str) -> str:
    """Return the directory path for a profile."""
    return os.path.join(PROFILES_DIR, profile_name)


def profile_exists(profile_name: str) -> bool:
    """Check if a profile exists."""
    env_path = os.path.join(get_profile_dir(profile_name), ".env")
    return os.path.isfile(env_path)


def acquire_lock(profile_name: str) -> bool:
    """Acquire exclusive lock on a profile. Returns False if locked.

    Uses flock which auto-releases when the process dies, even on crash.
    Also writes PID for informational purposes.
    """
    global _lock_fd
    lock_path = os.path.join(get_profile_dir(profile_name), "profile.lock")

    # Clean stale lock: if file exists, check if PID is alive
    if os.path.isfile(lock_path):
        try:
            with open(lock_path, "r") as f:
                content = f.read().strip()
            if not content:
                raise ValueError("empty lock file")
            old_pid = int(content)
            # Check if process is still running
            os.kill(old_pid, 0)
            # Process alive — lock is legitimate, don't remove
        except (ValueError, ProcessLookupError):
            # PID invalid, empty, or dead — remove stale lock
            try:
                os.remove(lock_path)
                logger.debug(f"[profile] Removed stale lock: {lock_path}")
            except OSError:
                pass
        except PermissionError:
            pass  # Process exists but different user

    try:
        _lock_fd = open(lock_path, "w")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        logger.debug(f"[profile] Lock acquired: {lock_path}")
        return True
    except (OSError, IOError):
        logger.warning(f"[profile] Lock failed: {lock_path}")
        if _lock_fd:
            _lock_fd.close()
            _lock_fd = None
        return False


def release_lock():
    """Release profile lock."""
    global _lock_fd
    if _lock_fd:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
        except Exception:
            pass
        _lock_fd = None


def activate_profile(profile_name: str):
    """Set a profile as active: load its .env, point DB to its dir.

    Must be called before any storage/config access.
    Sets environment variables so Settings() and database.py
    pick up the right paths.
    """
    global _active_profile, _active_profile_dir

    profile_dir = get_profile_dir(profile_name)
    env_path = os.path.join(profile_dir, ".env")

    if not os.path.isfile(env_path):
        raise FileNotFoundError(f"Profile '{profile_name}' not found at {env_path}")

    # Load profile .env into os.environ
    from dotenv import load_dotenv

    load_dotenv(env_path, override=True)

    # Point database to profile directory
    db_path = os.path.join(profile_dir, "zylch.db")
    os.environ["ZYLCH_DB_PATH"] = db_path
    os.environ["ZYLCH_PROFILE_DIR"] = profile_dir

    _active_profile = profile_name
    _active_profile_dir = profile_dir

    # Reload settings singleton so it picks up new env vars
    import zylch.config as _cfg

    _cfg.settings = _cfg.Settings()

    logger.info(f"[profile] Activated: {profile_name} ({profile_dir})")


def get_active_profile() -> str | None:
    """Return the currently active profile name."""
    return _active_profile


def get_active_profile_dir() -> str | None:
    """Return the currently active profile directory."""
    return _active_profile_dir


def select_profile(name: str | None = None) -> str:
    """Select a profile by name, or interactively.

    Args:
        name: Explicit profile name. If None, auto-select or prompt.

    Returns:
        Profile name (email address).

    Raises:
        SystemExit: If no profiles exist or name not found.
    """
    profiles = list_profiles()

    if not profiles:
        click.echo("No profiles found. Run 'zylch init' to create one.")
        raise SystemExit(1)

    if name:
        if name in profiles:
            return name
        click.echo(f"Profile '{name}' not found. Available:")
        for p in profiles:
            click.echo(f"  {p}")
        raise SystemExit(1)

    if len(profiles) == 1:
        return profiles[0]

    click.echo("Available profiles:\n")
    for i, name in enumerate(profiles, 1):
        click.echo(f"  {i}. {name}")
    click.echo()

    while True:
        choice = click.prompt(
            "Select profile",
            type=click.IntRange(1, len(profiles)),
        )
        return profiles[choice - 1]


def delete_profile(profile_name: str) -> bool:
    """Delete a profile directory entirely."""
    profile_dir = get_profile_dir(profile_name)
    if not os.path.isdir(profile_dir):
        return False
    shutil.rmtree(profile_dir)
    logger.info(f"[profile] Deleted: {profile_name}")
    return True


def migrate_legacy_profile():
    """Migrate ~/.zylch/.env + zylch.db to profiles/ structure.

    Only runs once: if ~/.zylch/.env exists but profiles/ doesn't.
    """
    legacy_env = os.path.join(ZYLCH_DIR, ".env")
    legacy_db = os.path.join(ZYLCH_DIR, "zylch.db")

    if not os.path.isfile(legacy_env):
        return
    if os.path.isdir(PROFILES_DIR) and list_profiles():
        return  # Already migrated

    # Read email from legacy .env to name the profile
    from dotenv import dotenv_values

    values = dotenv_values(legacy_env)
    email = values.get("EMAIL_ADDRESS", "default")

    profile_dir = get_profile_dir(email)
    os.makedirs(profile_dir, exist_ok=True)

    # Move .env
    dest_env = os.path.join(profile_dir, ".env")
    if not os.path.isfile(dest_env):
        shutil.copy2(legacy_env, dest_env)
        logger.info(f"[migrate] Copied .env to {dest_env}")

    # Move DB
    dest_db = os.path.join(profile_dir, "zylch.db")
    if os.path.isfile(legacy_db) and not os.path.isfile(dest_db):
        shutil.move(legacy_db, dest_db)
        logger.info(f"[migrate] Moved zylch.db to {dest_db}")

    # Also move WAL/SHM if present
    for ext in (".db-wal", ".db-shm"):
        src = legacy_db + ext.replace(".db", "")
        if os.path.isfile(src):
            shutil.move(src, dest_db + ext.replace(".db", ""))

    # Remove legacy .env (DB already moved)
    os.remove(legacy_env)
    logger.info(f"[migrate] Legacy profile migrated to" f" profiles/{email}/")
    click.echo(f"Migrated existing config to profile: {email}")
