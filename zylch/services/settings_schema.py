"""Settings schema for the Zylch profile `.env`.

Single source of truth for the editable fields exposed to the desktop
Settings tab and to anything else that needs to know "what can I edit
in a profile". Mirrors the prompts asked by `zylch init`
(`zylch/cli/setup.py`); secrets are flagged so the RPC layer can mask
them on read.

Reading and writing the actual `.env` lives in
`zylch.services.settings_io` to keep this file pure metadata.
"""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class SettingsField(TypedDict, total=False):
    key: str
    label: str
    type: str  # one of: text, password, number, select, textarea
    group: str
    optional: bool
    options: List[str]
    help: str
    secret: bool  # True for password / api keys — masked in settings_get


# Order = display order. Groups are also rendered in this order.
SETTINGS_SCHEMA: List[SettingsField] = [
    # ─── LLM ─────────────────────────────────────────────────
    {
        "key": "SYSTEM_LLM_PROVIDER",
        "label": "LLM provider",
        "type": "select",
        "group": "LLM",
        "optional": False,
        "options": ["anthropic", "openai"],
        "help": "Which model provider to use.",
    },
    {
        "key": "ANTHROPIC_API_KEY",
        "label": "Anthropic API key",
        "type": "password",
        "group": "LLM",
        "optional": True,
        "secret": True,
        "help": "Required if provider = anthropic.",
    },
    {
        "key": "OPENAI_API_KEY",
        "label": "OpenAI API key",
        "type": "password",
        "group": "LLM",
        "optional": True,
        "secret": True,
        "help": "Required if provider = openai.",
    },
    # ─── Email (IMAP) ────────────────────────────────────────
    {
        "key": "EMAIL_ADDRESS",
        "label": "Email address",
        "type": "text",
        "group": "Email",
        "optional": True,
    },
    {
        "key": "EMAIL_PASSWORD",
        "label": "App password",
        "type": "password",
        "group": "Email",
        "optional": True,
        "secret": True,
        "help": "Email provider app password (not your account password).",
    },
    {
        "key": "IMAP_HOST",
        "label": "IMAP host",
        "type": "text",
        "group": "Email",
        "optional": True,
    },
    {
        "key": "IMAP_PORT",
        "label": "IMAP port",
        "type": "number",
        "group": "Email",
        "optional": True,
    },
    {
        "key": "SMTP_HOST",
        "label": "SMTP host",
        "type": "text",
        "group": "Email",
        "optional": True,
    },
    {
        "key": "SMTP_PORT",
        "label": "SMTP port",
        "type": "number",
        "group": "Email",
        "optional": True,
    },
    # ─── Telegram ────────────────────────────────────────────
    {
        "key": "TELEGRAM_BOT_TOKEN",
        "label": "Bot token",
        "type": "password",
        "group": "Telegram",
        "optional": True,
        "secret": True,
        "help": "From @BotFather.",
    },
    {
        "key": "TELEGRAM_ALLOWED_USER_ID",
        "label": "Allowed user ID",
        "type": "text",
        "group": "Telegram",
        "optional": True,
        "help": "Your Telegram numeric user ID (from @userinfobot).",
    },
    # ─── MrCall ──────────────────────────────────────────────
    {
        "key": "MRCALL_CLIENT_ID",
        "label": "MrCall client ID",
        "type": "text",
        "group": "MrCall",
        "optional": True,
    },
    {
        "key": "MRCALL_CLIENT_SECRET",
        "label": "MrCall client secret",
        "type": "password",
        "group": "MrCall",
        "optional": True,
        "secret": True,
    },
    {
        "key": "MRCALL_BASE_URL",
        "label": "MrCall base URL",
        "type": "text",
        "group": "MrCall",
        "optional": True,
    },
    {
        "key": "MRCALL_REALM",
        "label": "MrCall realm",
        "type": "text",
        "group": "MrCall",
        "optional": True,
    },
    {
        "key": "MRCALL_DASHBOARD_URL",
        "label": "MrCall dashboard URL",
        "type": "text",
        "group": "MrCall",
        "optional": True,
    },
    # ─── Personal data ──────────────────────────────────────
    {
        "key": "USER_FULL_NAME",
        "label": "Full name",
        "type": "text",
        "group": "Personal data",
        "optional": True,
    },
    {
        "key": "USER_PHONE",
        "label": "Phone number",
        "type": "text",
        "group": "Personal data",
        "optional": True,
    },
    {
        "key": "USER_CODICE_FISCALE",
        "label": "Codice fiscale",
        "type": "text",
        "group": "Personal data",
        "optional": True,
    },
    {
        "key": "USER_DATE_OF_BIRTH",
        "label": "Date of birth",
        "type": "text",
        "group": "Personal data",
        "optional": True,
    },
    {
        "key": "USER_ADDRESS",
        "label": "Address",
        "type": "text",
        "group": "Personal data",
        "optional": True,
    },
    {
        "key": "USER_IBAN",
        "label": "IBAN",
        "type": "text",
        "group": "Personal data",
        "optional": True,
    },
    {
        "key": "USER_COMPANY",
        "label": "Company name",
        "type": "text",
        "group": "Personal data",
        "optional": True,
    },
    {
        "key": "USER_VAT_NUMBER",
        "label": "VAT / P.IVA",
        "type": "text",
        "group": "Personal data",
        "optional": True,
    },
    # ─── Documents & notes ──────────────────────────────────
    {
        "key": "DOCUMENT_PATHS",
        "label": "Document folders",
        "type": "text",
        "group": "Documents & notes",
        "optional": True,
        "help": "Comma-separated absolute paths.",
        "picker": "directories",
    },
    {
        "key": "DOWNLOADS_DIR",
        "label": "Downloads folder",
        "type": "text",
        "group": "Documents & notes",
        "optional": True,
        "help": "Where download_attachment saves files. Defaults to ~/Downloads.",
        "picker": "directory",
    },
    {
        "key": "USER_NOTES",
        "label": "Personal notes",
        "type": "textarea",
        "group": "Documents & notes",
        "optional": True,
        "help": "Free-form context Zylch can use.",
    },
    {
        "key": "USER_SECRET_INSTRUCTIONS",
        "label": "Secret instructions",
        "type": "textarea",
        "group": "Documents & notes",
        "optional": True,
        "secret": True,
        "help": "Instructions Zylch follows but never reveals.",
    },
]


# Set of keys whose value is a secret (used by settings_get to mask).
SECRET_KEYS = {f["key"] for f in SETTINGS_SCHEMA if f.get("secret")}

# Set of all known keys (used by settings_update to validate).
KNOWN_KEYS = {f["key"] for f in SETTINGS_SCHEMA}


def get_schema() -> List[Dict[str, Any]]:
    """Return the schema as a plain list of dicts (JSON-serialisable)."""
    return [dict(f) for f in SETTINGS_SCHEMA]
