"""Zylch CLI — local sales intelligence assistant.

Entry point for the `zylch` command. Uses click for subcommand
dispatch, defaults to interactive chat when invoked bare.
"""

import atexit
import logging
import os

import click

logger = logging.getLogger(__name__)


def _configure_logging():
    """Set up logging from LOG_LEVEL env var."""
    level = os.environ.get("LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.debug(f"[CLI] Logging configured, level={level}")


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
def sync(ctx):
    """Sync emails from IMAP."""
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
