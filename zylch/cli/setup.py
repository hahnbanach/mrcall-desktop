"""Interactive setup wizard for Zylch standalone.

Multi-channel wizard: LLM → Email → WhatsApp → Telegram → MrCall.
Re-running shows current values and asks for confirmation.
"""

import logging
import os
from pathlib import Path

import click

from zylch.cli.utils import ENV_PATH, ensure_zylch_dir

logger = logging.getLogger(__name__)

# IMAP presets for common providers
IMAP_PRESETS = {
    "gmail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 587),
    "googlemail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 587),
    "outlook.com": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "hotmail.com": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "live.com": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "yahoo.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 587),
    "icloud.com": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587),
}


def _load_existing_env() -> dict:
    """Load existing .env values into a dict."""
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    return env


def _mask(value: str, show: int = 4) -> str:
    """Mask a secret, showing only last N chars."""
    if not value or len(value) <= show:
        return "***"
    return f"***{value[-show:]}"


def _prompt_with_existing(label: str, existing: str, hide: bool = False) -> str:
    """Prompt for a value, showing existing if present."""
    if existing and not hide:
        if click.confirm(f"  {label}: {existing} — keep?", default=True):
            return existing
    elif existing and hide:
        if click.confirm(f"  {label}: {_mask(existing)} — keep?", default=True):
            return existing
    return click.prompt(f"  {label}", hide_input=hide, default=existing or None)


def run_init():
    """Interactive setup: creates ~/.zylch/.env with all channel credentials.

    Channels: LLM (required), Email, WhatsApp, Telegram, MrCall.
    Re-running preserves existing values with confirmation.
    """
    click.echo("=" * 50)
    click.echo("  Zylch — Setup Wizard")
    click.echo("=" * 50)
    click.echo()

    env = _load_existing_env()
    is_rerun = bool(env)
    if is_rerun:
        click.echo(f"Existing config found at {ENV_PATH}")
        click.echo("Press Enter to keep current values.\n")

    # ─── 1. LLM Provider (required) ──────────────────────────

    click.echo("1. LLM Provider (required)")
    click.echo("   Zylch needs an AI API key to work.\n")

    existing_provider = env.get("SYSTEM_LLM_PROVIDER", "anthropic")
    provider = click.prompt(
        "  Provider",
        type=click.Choice(["anthropic", "openai"]),
        default=existing_provider,
    )

    api_key_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    existing_key = env.get(api_key_var, "")
    api_key = _prompt_with_existing(f"{provider.title()} API key", existing_key, hide=True)

    logger.debug(f"[init] provider={provider}, key={'present' if api_key else 'absent'}")

    # ─── 2. Email (IMAP) ─────────────────────────────────────

    click.echo("\n2. Email (IMAP)")
    click.echo("   Connect your email to sync messages and detect tasks.\n")

    existing_email = env.get("EMAIL_ADDRESS", "")
    existing_pw = env.get("EMAIL_PASSWORD", "")

    if existing_email:
        if click.confirm(f"  Email connected: {existing_email} — keep?", default=True):
            email = existing_email
            password = existing_pw
        else:
            email = click.prompt("  Email address")
            password = click.prompt("  App password (not account password)", hide_input=True)
    elif click.confirm("  Connect email?", default=True):
        email = click.prompt("  Email address")
        password = click.prompt("  App password (not account password)", hide_input=True)
    else:
        email = ""
        password = ""

    # Auto-detect IMAP/SMTP
    imap_host = env.get("IMAP_HOST", "")
    smtp_host = env.get("SMTP_HOST", "")
    if email and not imap_host:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        preset = IMAP_PRESETS.get(domain)
        if preset:
            imap_host, _, smtp_host, _ = preset
            click.echo(f"  Auto-detected: {imap_host} / {smtp_host}")

    logger.debug(f"[init] email={email}, password={'present' if password else 'absent'}")

    # ─── 3. WhatsApp (neonize) ────────────────────────────────

    click.echo("\n3. WhatsApp")
    click.echo("   Connect via QR code to sync WhatsApp messages.\n")

    wa_db = Path(os.path.expanduser("~/.zylch/whatsapp.db"))
    wa_connected = wa_db.exists()

    if wa_connected:
        click.echo("  WhatsApp: connected (session exists)")
        if click.confirm("  Reset WhatsApp connection?", default=False):
            _connect_whatsapp_qr()
    elif click.confirm("  Connect WhatsApp now?", default=True):
        _connect_whatsapp_qr()
    else:
        click.echo("  Skipped. Run /connect whatsapp later.")

    # ─── 4. Telegram bot ──────────────────────────────────────

    click.echo("\n4. Telegram Bot")
    click.echo("   Use Zylch from your phone via Telegram.\n")

    existing_tg_token = env.get("TELEGRAM_BOT_TOKEN", "")
    existing_tg_user = env.get("TELEGRAM_ALLOWED_USER_ID", "")

    if existing_tg_token:
        if click.confirm(
            f"  Telegram bot: configured ({_mask(existing_tg_token)}) — keep?", default=True
        ):
            tg_token = existing_tg_token
            tg_user_id = existing_tg_user
        else:
            tg_token, tg_user_id = _prompt_telegram()
    elif click.confirm("  Connect Telegram bot?", default=False):
        tg_token, tg_user_id = _prompt_telegram()
    else:
        tg_token = ""
        tg_user_id = ""
        click.echo("  Skipped. Add TELEGRAM_BOT_TOKEN to .env later.")

    # ─── 5. MrCall / StarChat ─────────────────────────────────

    click.echo("\n5. MrCall (phone/SMS)")

    existing_mrcall = env.get("MRCALL_BASE_URL", "")

    if existing_mrcall:
        if click.confirm(f"  MrCall: {existing_mrcall} — keep?", default=True):
            mrcall_url = existing_mrcall
        else:
            mrcall_url = click.prompt("  StarChat URL", default="https://test-env-0.scw.hbsrv.net")
    elif click.confirm("  Connect MrCall?", default=False):
        mrcall_url = click.prompt("  StarChat URL", default="https://test-env-0.scw.hbsrv.net")
    else:
        mrcall_url = ""
        click.echo("  Skipped.")

    # ─── Write .env ───────────────────────────────────────────

    ensure_zylch_dir()

    lines = ["# Zylch Configuration (generated by zylch init)"]

    # LLM
    lines.append("")
    lines.append("# LLM")
    lines.append(f"SYSTEM_LLM_PROVIDER={provider}")
    if provider == "anthropic":
        lines.append(f"ANTHROPIC_API_KEY={api_key}")
        # Preserve the other key if it existed
        other = env.get("OPENAI_API_KEY", "")
        if other:
            lines.append(f"OPENAI_API_KEY={other}")
    else:
        lines.append(f"OPENAI_API_KEY={api_key}")
        other = env.get("ANTHROPIC_API_KEY", "")
        if other:
            lines.append(f"ANTHROPIC_API_KEY={other}")

    # Email
    if email:
        lines.append("")
        lines.append("# Email (IMAP)")
        lines.append(f"EMAIL_ADDRESS={email}")
        lines.append(f"EMAIL_PASSWORD={password}")
        if imap_host:
            lines.append(f"IMAP_HOST={imap_host}")
        if smtp_host:
            lines.append(f"SMTP_HOST={smtp_host}")

    # Telegram
    if tg_token:
        lines.append("")
        lines.append("# Telegram")
        lines.append(f"TELEGRAM_BOT_TOKEN={tg_token}")
        if tg_user_id:
            lines.append(f"TELEGRAM_ALLOWED_USER_ID={tg_user_id}")

    # MrCall
    if mrcall_url:
        lines.append("")
        lines.append("# MrCall")
        lines.append(f"MRCALL_BASE_URL={mrcall_url}")

    # Preserve any extra vars from existing .env
    known_keys = {
        "SYSTEM_LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "EMAIL_ADDRESS",
        "EMAIL_PASSWORD",
        "IMAP_HOST",
        "IMAP_PORT",
        "SMTP_HOST",
        "SMTP_PORT",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_ID",
        "MRCALL_BASE_URL",
    }
    extra = {k: v for k, v in env.items() if k not in known_keys}
    if extra:
        lines.append("")
        lines.append("# Other")
        for k, v in extra.items():
            lines.append(f"{k}={v}")

    lines.append("")

    with open(ENV_PATH, "w") as f:
        f.write("\n".join(lines))

    logger.info(f"[init] Config saved to {ENV_PATH}")

    # ─── Summary ──────────────────────────────────────────────

    click.echo("\n" + "=" * 50)
    click.echo("  Setup complete!")
    click.echo("=" * 50)
    click.echo(f"\n  Config: {ENV_PATH}")
    click.echo(f"  LLM:    {provider}")
    if email:
        click.echo(f"  Email:  {email}")
    if wa_db.exists():
        click.echo("  WhatsApp: connected")
    if tg_token:
        click.echo("  Telegram: configured")
    if mrcall_url:
        click.echo(f"  MrCall: {mrcall_url}")

    click.echo("\nNext steps:")
    if email:
        click.echo("  zylch sync       Sync emails")
    click.echo("  zylch            Start interactive chat")
    if tg_token:
        click.echo("  zylch telegram   Start Telegram bot")


def _prompt_telegram() -> tuple:
    """Prompt for Telegram bot configuration."""
    click.echo("  Steps:")
    click.echo("    1. Open Telegram, message @BotFather")
    click.echo("    2. Send /newbot, follow instructions")
    click.echo("    3. Copy the bot token")
    click.echo("    4. Message @userinfobot to get your user ID\n")
    token = click.prompt("  Bot token", hide_input=True)
    user_id = click.prompt("  Your Telegram user ID (for security)", default="")
    return token, user_id


def _connect_whatsapp_qr():
    """Run WhatsApp QR code connection flow inline."""
    try:
        from zylch.whatsapp.client import WhatsAppClient
    except ImportError:
        click.echo("  neonize not installed. Run: pip install neonize")
        return

    import io
    import threading

    import segno

    qr_ready = threading.Event()
    connected_ev = threading.Event()
    qr_text = []

    def _on_qr(client, data_qr: bytes):
        buf = io.StringIO()
        segno.make_qr(data_qr).terminal(out=buf, compact=True)
        qr_text.clear()
        qr_text.append(buf.getvalue())
        qr_ready.set()

    def _on_connected():
        connected_ev.set()

    wa_client = WhatsAppClient()
    wa_client.set_qr_callback(_on_qr)
    wa_client.on_connected(_on_connected)
    wa_client.connect(blocking=False)

    try:
        click.echo("  Generating QR code...")
        if not qr_ready.wait(timeout=15):
            click.echo("  QR code not received. Check network.")
            return

        click.echo("\n  Open WhatsApp → Settings → Linked Devices → Link a Device\n")
        click.echo(qr_text[0])
        click.echo("  Waiting for scan (60s)...")

        if connected_ev.wait(timeout=60):
            click.echo("  WhatsApp connected!")
        else:
            click.echo("  Timeout. Run /connect whatsapp later to retry.")
    finally:
        wa_client.disconnect()
