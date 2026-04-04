"""Zylch CLI — local sales intelligence assistant.

Entry point for the `zylch` command. Uses click for subcommand
dispatch, defaults to interactive chat when invoked bare.
"""

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


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Zylch — AI-powered sales intelligence."""
    _configure_logging()
    if ctx.invoked_subcommand is None:
        logger.info("[CLI] No subcommand, entering chat")
        from zylch.cli.chat import interactive_chat

        interactive_chat()


@cli.command()
def init():
    """Set up Zylch: API key, email, app password."""
    logger.info("[CLI] Running init wizard")
    from zylch.cli.setup import run_init

    run_init()


@cli.command()
def sync():
    """Sync emails from IMAP."""
    logger.info("[CLI] Running sync")
    from zylch.cli.commands import run_sync

    run_sync()


@cli.command()
def tasks():
    """Show actionable tasks."""
    logger.info("[CLI] Running tasks")
    from zylch.cli.commands import run_tasks

    run_tasks()


@cli.command()
def status():
    """Show sync status and stats."""
    logger.info("[CLI] Running status")
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
