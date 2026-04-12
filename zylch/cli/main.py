"""Zylch CLI — local sales intelligence assistant.

Entry point for the `zylch` command. Uses click for subcommand
dispatch, defaults to interactive chat when invoked bare.
"""

import atexit
import logging
import os

import click

logger = logging.getLogger(__name__)


_update_data = None  # (version, notes), False (no update), or None (pending)


def _check_update():
    """Check GitHub for newer release (non-blocking)."""
    import threading

    def _check():
        global _update_data
        try:
            import httpx

            from zylch import __version__

            resp = httpx.get(
                "https://api.github.com/repos/malemi/zylch"
                "/releases/latest",
                timeout=3,
            )
            if resp.status_code != 200:
                _update_data = False
                return
            data = resp.json()
            latest = data.get("tag_name", "").lstrip("v")
            if not latest or latest == __version__:
                _update_data = False
                return
            # Proper semver compare
            def _ver(v):
                return tuple(
                    int(x) for x in v.split(".")
                )
            if _ver(latest) > _ver(__version__):
                body = (data.get("body") or "").strip()
                _update_data = (latest, body)
            else:
                _update_data = False
        except Exception:
            _update_data = False

    threading.Thread(
        target=_check, daemon=True, name="update-check",
    ).start()


def _show_update():
    """Show update info and offer to upgrade."""
    import subprocess
    import sys
    import time

    from zylch import __version__

    # Wait for background thread (up to 3s)
    for _ in range(6):
        if _update_data is not None:
            break
        time.sleep(0.5)
    if not _update_data or _update_data is False:
        return

    latest, notes = _update_data

    click.echo(
        f"\n  New version available:"
        f" v{__version__} → v{latest}",
    )
    if notes:
        # Show release notes (non-tech summary)
        for line in notes.splitlines()[:5]:
            if line.strip():
                click.echo(f"    {line.strip()}")
    click.echo()

    if click.confirm("  Upgrade now?", default=True):
        # Detect install method and upgrade
        is_binary = getattr(sys, "frozen", False)
        if is_binary:
            click.echo("  Downloading update...")
            try:
                subprocess.run(
                    [
                        "bash", "-c",
                        "curl -sfL https://raw.githubusercontent.com"
                        "/malemi/zylch/main/scripts/install.sh | bash",
                    ],
                    check=True,
                )
                click.echo(
                    "  Updated! Restart zylch to use"
                    f" v{latest}.",
                )
                raise SystemExit(0)
            except subprocess.CalledProcessError:
                click.echo(
                    "  Update failed. Run manually:\n"
                    "  curl -sL https://raw.githubusercontent"
                    ".com/malemi/zylch/main/scripts"
                    "/install.sh | bash",
                )
        else:
            click.echo("  Upgrading via pip...")
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip",
                     "install", "--upgrade", "zylch"],
                    check=True,
                )
                click.echo(
                    f"  Updated to v{latest}!"
                    f" Restart zylch.",
                )
                raise SystemExit(0)
            except subprocess.CalledProcessError:
                click.echo(
                    "  Update failed. Run manually:\n"
                    "  pip install --upgrade zylch",
                )
    click.echo()


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

    # Suppress noisy third-party loggers on console
    for noisy in (
        "httpx", "httpcore", "huggingface_hub",
        "fastembed", "onnxruntime", "urllib3",
    ):
        logging.getLogger(noisy).setLevel(logging.ERROR)


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
    _show_update()
    return profile


@click.group(invoke_without_command=True)
@click.version_option(
    version=__import__("zylch").__version__,
    prog_name="zylch",
)
@click.option(
    "-p", "--profile",
    default=None,
    help="Profile name (email). Auto-selects if only one exists.",
)
@click.pass_context
def cli(ctx, profile):
    """Zylch — Sales Intelligence."""
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
def update(ctx):
    """Sync + analyze + detect tasks. Cron-friendly."""
    _configure_logging()
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    profile = _setup_profile(profile_name)
    logger.info(f"[CLI] Running update, profile={profile}")
    from zylch.cli.commands import run_update

    run_update()


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
@click.pass_context
def rpc(ctx):
    """JSON-RPC 2.0 sidecar over stdin/stdout (for Electron desktop app).

    Reads line-delimited JSON-RPC requests from stdin and writes
    responses/notifications to stdout. Logs go to the profile log file
    and stderr only — stdout is the RPC wire.
    """
    import asyncio
    import logging as _logging
    import sys

    # Configure logging BEFORE profile setup, with stderr as console
    # so we never pollute stdout (which is the RPC wire).
    _configure_logging()
    root = _logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, _logging.StreamHandler) and getattr(
            h, "stream", None
        ) is sys.stdout:
            root.removeHandler(h)
    has_stderr = any(
        isinstance(h, _logging.StreamHandler)
        and getattr(h, "stream", None) is sys.stderr
        for h in root.handlers
    )
    if not has_stderr:
        stderr_h = _logging.StreamHandler(sys.stderr)
        stderr_h.setLevel(_logging.WARNING)
        stderr_h.setFormatter(_logging.Formatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        ))
        root.addHandler(stderr_h)

    # Activate profile manually (not _setup_profile — it calls
    # _show_update which writes to stdout and would corrupt the wire).
    from zylch.cli.profiles import (
        activate_profile,
        acquire_lock,
        migrate_legacy_profile,
        release_lock,
        select_profile,
    )
    from zylch.cli.utils import load_env

    profile_name = ctx.obj.get("profile") if ctx.obj else None
    migrate_legacy_profile()
    profile = select_profile(profile_name)
    if not acquire_lock(profile):
        sys.stderr.write(
            f"Profile '{profile}' is already in use by another session.\n"
        )
        raise SystemExit(1)
    atexit.register(release_lock)
    activate_profile(profile)
    _setup_log_file()
    load_env()
    logger.info(f"[CLI] rpc server starting, profile={profile}")

    from zylch.rpc.server import serve

    asyncio.run(serve())


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
    # Suppress multiprocessing resource_tracker warnings
    # (fastembed/onnxruntime spawn processes that die on exit)
    import warnings

    warnings.filterwarnings(
        "ignore", "resource_tracker",
    )
    cli()


if __name__ == "__main__":
    main()
