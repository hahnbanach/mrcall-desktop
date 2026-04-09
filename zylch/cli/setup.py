"""Interactive setup wizard for Zylch standalone.

rclone-style profile management (new/edit/delete) wrapping
multi-channel wizard: LLM → Email → WhatsApp → Telegram → MrCall.
Profiles stored in ~/.zylch/profiles/{email}/.
"""

import logging
import os
from pathlib import Path

import click

from zylch.cli.profiles import (
    delete_profile,
    get_profile_dir,
    list_profiles,
    migrate_legacy_profile,
    profile_exists,
)

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


def _load_profile_env(profile_name: str) -> dict:
    """Load existing .env values from a profile into a dict."""
    env_path = os.path.join(get_profile_dir(profile_name), ".env")
    env = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
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


# ─── Profile menu (rclone-style) ─────────────────────────────


def run_init():
    """rclone-style profile manager: new / edit / delete."""
    migrate_legacy_profile()
    profiles = list_profiles()

    if not profiles:
        click.echo("Welcome to Zylch! Let's create your first profile.\n")
        _run_wizard(env={}, profile_name=None)
        return

    click.echo("Zylch — Profile Manager\n")
    click.echo("Current profiles:")
    for i, name in enumerate(profiles, 1):
        click.echo(f"  {i}. {name}")
    click.echo()

    choices = {
        "n": "New profile",
        "e": "Edit profile",
        "d": "Delete profile",
        "q": "Quit",
    }
    for key, desc in choices.items():
        click.echo(f"  {key}) {desc}")
    click.echo()

    choice = click.prompt(
        "Choice",
        type=click.Choice(list(choices.keys())),
    )

    if choice == "n":
        _run_wizard(env={}, profile_name=None)
    elif choice == "e":
        name = _pick_profile(profiles, "Edit")
        env = _load_profile_env(name)
        _run_wizard(env=env, profile_name=name)
    elif choice == "d":
        _delete_profile_interactive(profiles)


def _pick_profile(profiles: list[str], action: str) -> str:
    """Let user pick a profile from the list."""
    if len(profiles) == 1:
        return profiles[0]
    click.echo()
    for i, name in enumerate(profiles, 1):
        click.echo(f"  {i}. {name}")
    idx = click.prompt(
        f"\n{action} which profile",
        type=click.IntRange(1, len(profiles)),
    )
    return profiles[idx - 1]


def _delete_profile_interactive(profiles: list[str]):
    """Delete a profile with confirmation."""
    name = _pick_profile(profiles, "Delete")
    profile_dir = get_profile_dir(name)
    db_path = os.path.join(profile_dir, "zylch.db")
    db_size = ""
    if os.path.isfile(db_path):
        mb = os.path.getsize(db_path) / 1024 / 1024
        db_size = f" ({mb:.1f} MB database)"

    if click.confirm(
        f"\nDelete profile '{name}'{db_size}?"
        f" This cannot be undone",
        default=False,
    ):
        delete_profile(name)
        click.echo(f"Profile '{name}' deleted.")
    else:
        click.echo("Cancelled.")


# ─── Multi-channel wizard ────────────────────────────────────


def _run_wizard(env: dict, profile_name: str | None):
    """Multi-channel setup wizard.

    Args:
        env: Existing .env values (empty for new profile).
        profile_name: Name of existing profile being edited, or None for new.
    """
    is_edit = bool(env)

    click.echo("=" * 50)
    click.echo("  Zylch — Setup Wizard")
    click.echo("=" * 50)
    click.echo()

    if is_edit:
        click.echo(f"Editing profile: {profile_name}")
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

    api_key_var = (
        "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    )
    existing_key = env.get(api_key_var, "")
    api_key = _prompt_with_existing(
        f"{provider.title()} API key", existing_key, hide=True,
    )

    logger.debug(
        f"[init] provider={provider},"
        f" key={'present' if api_key else 'absent'}",
    )

    # ─── 2. Email (IMAP) ─────────────────────────────────────

    click.echo("\n2. Email (IMAP)")
    click.echo(
        "   Connect your email to sync messages"
        " and detect tasks.\n",
    )

    existing_email = env.get("EMAIL_ADDRESS", "")
    existing_pw = env.get("EMAIL_PASSWORD", "")

    if existing_email:
        if click.confirm(
            f"  Email connected: {existing_email} — keep?",
            default=True,
        ):
            email = existing_email
            password = existing_pw
        else:
            email = click.prompt("  Email address")
            password = click.prompt(
                "  App password (not account password)",
                hide_input=True,
            )
    elif click.confirm("  Connect email?", default=True):
        email = click.prompt("  Email address")
        password = click.prompt(
            "  App password (not account password)",
            hide_input=True,
        )
    else:
        email = ""
        password = ""

    # Auto-detect IMAP/SMTP
    imap_host = env.get("IMAP_HOST", "")
    smtp_host = env.get("SMTP_HOST", "")
    if email and not imap_host:
        domain = (
            email.split("@")[-1].lower() if "@" in email else ""
        )
        preset = IMAP_PRESETS.get(domain)
        if preset:
            imap_host, _, smtp_host, _ = preset
            click.echo(
                f"  Auto-detected: {imap_host} / {smtp_host}",
            )
        else:
            click.echo(
                f"\n  Domain '{domain}' — can't auto-detect.",
            )
            provider_choice = click.prompt(
                "  Email provider",
                type=click.Choice([
                    "google", "outlook", "other",
                ]),
                default="google",
            )
            if provider_choice == "google":
                imap_host = "imap.gmail.com"
                smtp_host = "smtp.gmail.com"
                click.echo(
                    f"  Set: {imap_host} / {smtp_host}",
                )
            elif provider_choice == "outlook":
                imap_host = "outlook.office365.com"
                smtp_host = "smtp.office365.com"
                click.echo(
                    f"  Set: {imap_host} / {smtp_host}",
                )
            else:
                imap_host = click.prompt(
                    "  IMAP server",
                    default=f"imap.{domain}",
                )
                smtp_host = click.prompt(
                    "  SMTP server",
                    default=f"smtp.{domain}",
                )

    logger.debug(
        f"[init] email={email},"
        f" password={'present' if password else 'absent'}",
    )

    # ─── 3. WhatsApp (neonize) ────────────────────────────────

    click.echo("\n3. WhatsApp")
    click.echo(
        "   Connect via QR code to sync"
        " WhatsApp messages.\n",
    )

    # Check per-profile WA session (or legacy global)
    _profile_name = email or profile_name or "default"
    _wa_profile_path = Path(
        get_profile_dir(_profile_name),
    ) / "whatsapp.db"
    _wa_global_path = Path(
        os.path.expanduser("~/.zylch/whatsapp.db"),
    )
    wa_db = (
        _wa_profile_path
        if _wa_profile_path.exists()
        else _wa_global_path
    )
    wa_connected = wa_db.exists()

    if wa_connected:
        click.echo("  WhatsApp: connected (session exists)")
        if click.confirm(
            "  Reset WhatsApp connection?", default=False,
        ):
            _connect_whatsapp_qr()
    elif click.confirm(
        "  Connect WhatsApp now?", default=True,
    ):
        _connect_whatsapp_qr()
    else:
        click.echo("  Skipped. Run /connect whatsapp later.")

    # ─── 4. Telegram bot ──────────────────────────────────────

    click.echo("\n4. Telegram Bot")
    click.echo(
        "   Use Zylch from your phone via Telegram.\n",
    )

    existing_tg_token = env.get("TELEGRAM_BOT_TOKEN", "")
    existing_tg_user = env.get("TELEGRAM_ALLOWED_USER_ID", "")

    if existing_tg_token:
        if click.confirm(
            f"  Telegram bot: configured"
            f" ({_mask(existing_tg_token)}) — keep?",
            default=True,
        ):
            tg_token = existing_tg_token
            tg_user_id = existing_tg_user
        else:
            tg_token, tg_user_id = _prompt_telegram()
    elif click.confirm(
        "  Connect Telegram bot?", default=False,
    ):
        tg_token, tg_user_id = _prompt_telegram()
    else:
        tg_token = ""
        tg_user_id = ""
        click.echo(
            "  Skipped. Add TELEGRAM_BOT_TOKEN to .env later.",
        )

    # ─── 5. MrCall (OAuth2) ──────────────────────────────────

    click.echo("\n5. MrCall (phone/SMS)")
    click.echo(
        "   Connect MrCall to sync calls and send SMS.\n",
    )

    existing_client_id = env.get("MRCALL_CLIENT_ID", "")
    existing_client_secret = env.get("MRCALL_CLIENT_SECRET", "")
    mrcall_client_id = ""
    mrcall_client_secret = ""
    mrcall_connected = False

    if existing_client_id:
        from zylch.tools.mrcall.oauth import check_mrcall_connected

        already_authed = check_mrcall_connected(
            email or "local-user",
        )
        if already_authed:
            click.echo(
                f"  MrCall: connected"
                f" (client {_mask(existing_client_id)})",
            )
            if click.confirm(
                "  Reconnect MrCall?", default=False,
            ):
                mrcall_client_id, mrcall_client_secret = (
                    _prompt_mrcall_creds(
                        existing_client_id,
                        existing_client_secret,
                    )
                )
                mrcall_connected = _run_mrcall_oauth(
                    email or "local-user",
                )
            else:
                mrcall_client_id = existing_client_id
                mrcall_client_secret = existing_client_secret
                mrcall_connected = True
        else:
            click.echo(
                "  MrCall: credentials present"
                " but not authorized",
            )
            mrcall_client_id = existing_client_id
            mrcall_client_secret = existing_client_secret
    elif click.confirm("  Connect MrCall?", default=False):
        mrcall_client_id, mrcall_client_secret = (
            _prompt_mrcall_creds("", "")
        )
    else:
        click.echo("  Skipped.")

    run_mrcall_oauth_after = bool(
        mrcall_client_id and not mrcall_connected,
    )

    # ─── 6. Personal data ─────────────────────────────────────

    click.echo("\n6. Personal Data (optional)")
    click.echo(
        "   Zylch uses this to fill forms,"
        " draft emails, etc.\n",
    )

    personal_fields = {
        "USER_FULL_NAME": "Full name",
        "USER_PHONE": "Phone number",
        "USER_CODICE_FISCALE": "Codice fiscale",
        "USER_DATE_OF_BIRTH": "Date of birth",
        "USER_ADDRESS": "Address",
        "USER_IBAN": "IBAN",
        "USER_COMPANY": "Company name",
        "USER_VAT_NUMBER": "VAT / P.IVA",
    }

    personal_data = {}
    for key, label in personal_fields.items():
        existing_val = env.get(key, "")
        if existing_val:
            if click.confirm(
                f"  {label}: {existing_val} — keep?",
                default=True,
            ):
                personal_data[key] = existing_val
            else:
                val = click.prompt(
                    f"  {label}", default="",
                    show_default=False,
                )
                if val:
                    personal_data[key] = val
        else:
            val = click.prompt(
                f"  {label} (Enter to skip)",
                default="", show_default=False,
            )
            if val:
                personal_data[key] = val

    # ─── 7. Document folders ──────────────────────────────────

    click.echo("\n7. Document Folders (optional)")
    click.echo(
        "   Zylch can read your documents"
        " (visure, ID, contracts) to fill forms.\n",
    )

    existing_doc_paths = env.get("DOCUMENT_PATHS", "")
    if existing_doc_paths:
        click.echo(
            f"  Current: {existing_doc_paths}",
        )
        if click.confirm("  Keep these?", default=True):
            doc_paths = existing_doc_paths
        else:
            doc_paths = _prompt_document_paths()
    else:
        doc_paths = _prompt_document_paths()

    # ─── Determine profile name ───────────────────────────────

    # Profile name = email address (or original name if no email)
    new_profile_name = email or profile_name or "default"

    # If editing and email changed, rename profile
    if is_edit and profile_name and new_profile_name != profile_name:
        if profile_exists(new_profile_name):
            if not click.confirm(
                f"\nProfile '{new_profile_name}'"
                f" already exists. Overwrite?",
            ):
                click.echo("Cancelled.")
                return
        delete_profile(profile_name)
    elif not is_edit and profile_exists(new_profile_name):
        if not click.confirm(
            f"\nProfile '{new_profile_name}'"
            f" already exists. Overwrite?",
        ):
            click.echo("Cancelled.")
            return

    # ─── Write profile .env ───────────────────────────────────

    profile_dir = get_profile_dir(new_profile_name)
    os.makedirs(profile_dir, exist_ok=True)
    env_path = os.path.join(profile_dir, ".env")

    lines = ["# Zylch Configuration (generated by zylch init)"]

    # LLM
    lines.append("")
    lines.append("# LLM")
    lines.append(f"SYSTEM_LLM_PROVIDER={provider}")
    if provider == "anthropic":
        lines.append(f"ANTHROPIC_API_KEY={api_key}")
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
    if mrcall_client_id:
        lines.append("")
        lines.append("# MrCall")
        lines.append(f"MRCALL_CLIENT_ID={mrcall_client_id}")
        lines.append(f"MRCALL_CLIENT_SECRET={mrcall_client_secret}")

    # Personal data
    if personal_data:
        lines.append("")
        lines.append("# Personal Data")
        for key, val in personal_data.items():
            lines.append(f"{key}={val}")

    # Document folders
    if doc_paths:
        lines.append("")
        lines.append("# Document Folders")
        lines.append(f"DOCUMENT_PATHS={doc_paths}")

    # Preserve extra vars from existing .env
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
        "MRCALL_CLIENT_ID",
        "MRCALL_CLIENT_SECRET",
        "MRCALL_DASHBOARD_URL",
        "MRCALL_REALM",
        "DOCUMENT_PATHS",
        *personal_data.keys(),
    }
    extra = {k: v for k, v in env.items() if k not in known_keys}
    if extra:
        lines.append("")
        lines.append("# Other")
        for k, v in extra.items():
            lines.append(f"{k}={v}")

    lines.append("")

    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines))

    logger.info(f"[init] Profile saved to {env_path}")

    # ─── MrCall OAuth (after .env written) ────────────────────

    if run_mrcall_oauth_after:
        os.environ["MRCALL_CLIENT_ID"] = mrcall_client_id
        os.environ["MRCALL_CLIENT_SECRET"] = mrcall_client_secret
        from zylch import config as _cfg

        _cfg.settings = _cfg.Settings()
        mrcall_connected = _run_mrcall_oauth(
            email or "local-user",
        )

    # ─── Summary ──────────────────────────────────────────────

    action = "updated" if is_edit else "created"
    click.echo("\n" + "=" * 50)
    click.echo(f"  Profile '{new_profile_name}' {action}!")
    click.echo("=" * 50)
    click.echo(f"\n  Config: {env_path}")
    click.echo(f"  LLM:    {provider}")
    if email:
        click.echo(f"  Email:  {email}")
    if wa_db.exists():
        click.echo("  WhatsApp: connected")
    if tg_token:
        click.echo("  Telegram: configured")
    if mrcall_connected:
        click.echo("  MrCall: connected")
    elif mrcall_client_id:
        click.echo("  MrCall: configured (not yet authorized)")

    if personal_data:
        click.echo(
            f"  Personal: {len(personal_data)} fields saved",
        )
    if doc_paths:
        n = len(doc_paths.split(","))
        click.echo(f"  Documents: {n} folder(s)")

    click.echo("\nNext steps:")
    click.echo(
        f"  zylch -p {new_profile_name} process"
        f"   Sync + analyze everything",
    )
    click.echo(
        f"  zylch -p {new_profile_name}"
        f"           Start interactive chat",
    )
    if tg_token:
        click.echo(
            f"  zylch telegram"
            f"                Start Telegram bot",
        )


# ─── Channel-specific helpers ─────────────────────────────────


def _prompt_document_paths() -> str:
    """Prompt for document folder paths.

    Returns comma-separated paths, or empty string.
    """
    paths = []
    click.echo(
        "  Add folder paths (Enter empty to finish):",
    )
    while True:
        path = click.prompt(
            "  Path", default="", show_default=False,
        )
        if not path:
            break
        # Expand ~ but keep in stored format
        expanded = os.path.expanduser(path.strip())
        if os.path.isdir(expanded):
            paths.append(path.strip())
            click.echo(f"    Added: {path.strip()}")
        else:
            click.echo(
                f"    [Warning] '{path}' not found,"
                f" added anyway",
            )
            paths.append(path.strip())

    if paths:
        click.echo(f"  {len(paths)} folder(s) registered.")
    else:
        click.echo("  Skipped.")
    return ",".join(paths)


def _prompt_telegram() -> tuple:
    """Prompt for Telegram bot configuration."""
    click.echo("  Steps:")
    click.echo("    1. Open Telegram, message @BotFather")
    click.echo("    2. Send /newbot, follow instructions")
    click.echo("    3. Copy the bot token")
    click.echo(
        "    4. Message @userinfobot to get your user ID\n",
    )
    token = click.prompt("  Bot token", hide_input=True)
    user_id = click.prompt(
        "  Your Telegram user ID (for security)", default="",
    )
    return token, user_id


def _connect_whatsapp_qr():
    """Run WhatsApp QR code connection flow inline."""
    try:
        from zylch.whatsapp.client import WhatsAppClient
    except ImportError:
        click.echo(
            "  neonize not installed. Run: pip install neonize",
        )
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
            # Session already exists — no QR needed
            if connected_ev.wait(timeout=10):
                click.echo("  WhatsApp connected (existing session)!")
                return
            click.echo("  QR code not received. Check network.")
            return

        click.echo(
            "\n  Open WhatsApp → Settings"
            " → Linked Devices → Link a Device\n",
        )
        click.echo(qr_text[0])
        click.echo("  Waiting for scan (60s)...")

        if connected_ev.wait(timeout=60):
            click.echo("  WhatsApp connected!")
        else:
            click.echo(
                "  Timeout. Run /connect whatsapp later"
                " to retry.",
            )
    finally:
        # Don't call disconnect() — the daemon thread will die
        # with the process. Calling disconnect() triggers Go's
        # websocket close which logs noisy warnings to stderr.
        pass


def _prompt_mrcall_creds(
    existing_id: str, existing_secret: str,
) -> tuple:
    """Prompt for MrCall OAuth2 client credentials."""
    click.echo(
        "  You need a client_id and client_secret"
        " from your MrCall admin.\n",
    )
    client_id = _prompt_with_existing(
        "Client ID", existing_id, hide=False,
    )
    client_secret = _prompt_with_existing(
        "Client secret", existing_secret, hide=True,
    )
    return client_id, client_secret


def _run_mrcall_oauth(owner_id: str) -> bool:
    """Run MrCall OAuth2 browser flow."""
    from zylch.tools.mrcall.oauth import run_oauth_flow

    click.echo("\n  Opening browser for MrCall authorization...")
    click.echo("  Log in and approve Zylch access.\n")

    tokens = run_oauth_flow(owner_id)
    if tokens:
        target = tokens.get("target_owner", "")
        if target:
            click.echo(
                f"  MrCall connected! (user: {target[:12]}...)",
            )
        else:
            click.echo("  MrCall connected!")
        return True
    else:
        click.echo(
            "  MrCall authorization failed."
            " Try /connect mrcall later.",
        )
        return False
