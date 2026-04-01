"""Interactive setup wizard for Zylch standalone."""

import logging
import os

import click

from zylch.cli.utils import ENV_PATH, ensure_zylch_dir

logger = logging.getLogger(__name__)


def run_init():
    """Interactive setup: creates ~/.zylch/.env with credentials.

    Prompts for LLM provider/key, email IMAP credentials, and
    optional MrCall integration URL.
    """
    click.echo("Welcome to Zylch! Let's set up your account.\n")

    # 1. LLM Provider
    click.echo("1. LLM Provider")
    provider = click.prompt(
        "Provider",
        type=click.Choice(["anthropic", "openai"]),
        default="anthropic",
    )
    api_key = click.prompt(
        f"{provider.title()} API key", hide_input=True
    )
    logger.debug(
        f"[init] provider={provider}, "
        f"api_key={'present' if api_key else 'absent'}"
    )

    # 2. Email (IMAP)
    click.echo("\n2. Email (IMAP)")
    email = click.prompt("Email address")
    password = click.prompt("App password", hide_input=True)
    logger.debug(
        f"[init] email={email}, "
        f"password={'present' if password else 'absent'}"
    )

    # 3. Database
    click.echo("\n3. Database")
    db_url = click.prompt(
        "PostgreSQL URL",
        default=(
            "postgresql://zylch:zylch_dev@localhost:5432/zylch"
        ),
    )
    logger.debug(f"[init] db_url={db_url}")

    # 4. Optional: MrCall
    mrcall_url = ""
    if click.confirm("\n4. Connect MrCall?", default=False):
        mrcall_url = click.prompt(
            "StarChat URL",
            default="https://test-env-0.scw.hbsrv.net",
        )
        logger.debug(f"[init] mrcall_url={mrcall_url}")

    # Write .env
    ensure_zylch_dir()
    lines = [
        "# Zylch Configuration",
        f"SYSTEM_LLM_PROVIDER={provider}",
    ]
    if provider == "anthropic":
        lines.append(f"ANTHROPIC_API_KEY={api_key}")
    else:
        lines.append(f"OPENAI_API_KEY={api_key}")

    lines.append("")
    lines.append("# Email (IMAP)")
    lines.append(f"EMAIL_ADDRESS={email}")
    lines.append(f"EMAIL_PASSWORD={password}")

    lines.append("")
    lines.append("# Database")
    lines.append(f"DATABASE_URL={db_url}")

    if mrcall_url:
        lines.append("")
        lines.append("# MrCall")
        lines.append(f"MRCALL_BASE_URL={mrcall_url}")

    with open(ENV_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")

    logger.info(f"[init] Config saved to {ENV_PATH}")
    click.echo(f"\nConfig saved to {ENV_PATH}")
    click.echo("Run 'zylch sync' to fetch your emails.")
