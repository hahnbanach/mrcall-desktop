"""Zylch CLI — local sales intelligence assistant.

Entry point for the `zylch` command. Uses click for subcommand
dispatch, defaults to interactive chat when invoked bare.
"""

import atexit
import logging
import os

import click

logger = logging.getLogger(__name__)


def _check_update():
    """Check GitHub for newer release (non-blocking)."""
    import threading

    def _check():
        try:
            import httpx

            from zylch import __version__

            resp = httpx.get(
                "https://api.github.com/repos/malemi/zylch"
                "/releases/latest",
                timeout=3,
            )
            if resp.status_code != 200:
                return
            data = resp.json()
            latest = data.get("tag_name", "").lstrip("v")
            if not latest or latest == __version__:
                return
            # Simple version compare (works for semver)
            if latest > __version__:
                body = data.get("body", "").strip()
                notes = ""
                if body:
                    # First 3 lines of release notes
                    lines = body.splitlines()[:3]
                    notes = "\n    ".join(lines)

                click.echo(
                    f"\n  Update available: v{__version__}"
                    f" → v{latest}",
                )
                if notes:
                    click.echo(f"    {notes}")
                click.echo(
                    "  Run: curl -sL https://raw.githubusercontent.com"
                    "/malemi/zylch/main/scripts/install.sh | bash\n",
                )
        except Exception:
            pass  # Never block on update check

    threading.Thread(
        target=_check, daemon=True, name="update-check",
    ).start()


def _configure_logging():
    """Set up logging: console (WARNING only), file (DEBUG).

    Console shows only warnings/errors — no noise.
    File gets everything (DEBUG) for troubleshooting.
    Override console with LOG_LEVEL env var if needed.
    """
    console_level = os.environ.get(
        "LOG_LEVEL", "WARNING",
    ).upper()
    # Root logger at DEBUG so file handler catches all
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[],  # No default handler
    )
    # Console handler: WARNING+ (quiet)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(
        getattr(logging, console_level, logging.WARNING),
    )
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    ))
    logging.getLogger().addHandler(console_handler)


def _setup_log_file():
    """Add file handler after profile is activated."""
    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR")
    if not profile_dir:
        return

    log_path = os.path.join(profile_dir, "zylch.log")
    handler = logging.FileHandler(
        log_path, encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(handler)
    logger.debug(f"[CLI] Log file: {log_path}")


def _setup_profile(profile_name: str | None = None, lock: bool = True):
    """Select and activate a profile for subcommands.

    Args:
        profile_name: Explicit profile name. If None, interactive selection.
        lock: If True, acquire exclusive lock (for write ops).
              If False, just activate without locking (read-only).
    """
    from zylch.cli.profiles import (
        activate_profile,
        acquire_lock,
        migrate_legacy_profile,
        release_lock,
        select_profile,
    )

    migrate_legacy_profile()
    profile = select_profile(profile_name)

    if lock:
        if not acquire_lock(profile):
            click.echo(
                f"Profile '{profile}' is already in use"
                f" by another session."
            )
            raise SystemExit(1)
        atexit.register(release_lock)

    activate_profile(profile)
    _setup_log_file()
    return profile


@click.group(invoke_without_command=True)
@click.option(
    "-p", "--profile",
    default=None,
    help="Profile name (email). Auto-selects if only one exists.",
)
@click.pass_context
def cli(ctx, profile):
    """Zylch — AI-powered sales intelligence."""
    _configure_logging()
    _check_update()
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    if ctx.invoked_subcommand is None:
        logger.info("[CLI] No subcommand, entering chat")
        from zylch.cli.chat import interactive_chat

        _setup_profile(profile)
        interactive_chat()


@cli.command()
def init():
    """Manage profiles: create, edit, delete."""
    logger.info("[CLI] Running init wizard")
    from zylch.cli.setup import run_init

    run_init()


@cli.command(name="profiles")
def list_profiles_cmd():
    """List available profiles."""
    from zylch.cli.profiles import list_profiles, migrate_legacy_profile

    migrate_legacy_profile()
    profiles = list_profiles()
    if not profiles:
        click.echo("No profiles. Run 'zylch init' to create one.")
        return
    for name in profiles:
        click.echo(f"  {name}")


@cli.command()
@click.pass_context
def process(ctx):
    """Sync all channels + extract memory + detect tasks."""
    _configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _setup_profile(profile_name)
    logger.info(f"[CLI] Running process, profile={profile}")
    from zylch.cli.commands import run_process

    run_process()


@cli.command()
@click.pass_context
def dream(ctx):
    """Run background memory consolidation (can be cron'd)."""
    _configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _setup_profile(profile_name)
    logger.info(f"[CLI] Running dream, profile={profile}")
    from zylch.cli.commands import run_dream

    run_dream()


@cli.command()
@click.pass_context
def sync(ctx):
    """Sync emails and WhatsApp (fetch only, no AI)."""
    _configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _setup_profile(profile_name)
    logger.info(f"[CLI] Running sync, profile={profile}")
    from zylch.cli.commands import run_sync

    run_sync()


@cli.command()
@click.pass_context
def tasks(ctx):
    """Show actionable tasks."""
    _configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _setup_profile(profile_name)
    logger.info(f"[CLI] Running tasks, profile={profile}")
    from zylch.cli.commands import run_tasks

    run_tasks()


@cli.command()
@click.pass_context
def status(ctx):
    """Show sync status and stats."""
    _configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _setup_profile(profile_name, lock=False)
    logger.info(f"[CLI] Running status, profile={profile}")
    from zylch.cli.commands import run_status

    run_status()


@cli.command()
def telegram():
    """Start Telegram bot interface."""
    logger.info("[CLI] Starting Telegram bot")
    from zylch.cli.utils import load_env

    load_env()
    from zylch.telegram.bot import run_telegram_bot

    run_telegram_bot()


def main():
    """Entry point for pipx / setuptools console_scripts."""
    cli()


if __name__ == "__main__":
    main()
