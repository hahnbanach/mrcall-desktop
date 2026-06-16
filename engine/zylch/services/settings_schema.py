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
    default: str  # placeholder / first-option hint shown when the value is unset


# Order = display order. Groups are also rendered in this order.
SETTINGS_SCHEMA: List[SettingsField] = [
    # ─── LLM ─────────────────────────────────────────────────
    #
    # Single field: the user's Anthropic key. Presence of the key flips
    # the engine into BYOK ("direct" transport); absence means MrCall
    # credits (Firebase JWT routed through mrcall-agent's proxy).
    {
        "key": "ANTHROPIC_API_KEY",
        "label": "Anthropic API key (BYOK)",
        "type": "password",
        "group": "LLM",
        "optional": True,
        "secret": True,
        "help": (
            "Set this to use your own Anthropic billing. Leave blank to "
            "use MrCall credits — requires Firebase signin in the desktop "
            "app."
        ),
    },
    {
        "key": "SMS_BUSINESS_ID",
        "label": "SMS billing business",
        "type": "text",
        "group": "LLM",
        "optional": True,
        "help": (
            "Which business's credits to bill for SMS you send. Required if "
            "your account can see more than one business (e.g. an admin "
            "account, or you manage several assistants) — otherwise the "
            "server refuses to guess. Leave blank if you have a single "
            "business."
        ),
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
    {
        "key": "EMAIL_ALIASES",
        "label": "Email aliases",
        "type": "text",
        "group": "Email",
        "optional": True,
        "help": (
            "Other email addresses you also write from, comma-separated "
            "(e.g. 'carol@example.com, info@example.com'). "
            "Replies from any of these count as YOUR reply for task "
            "tracking — without them, threads where you wrote from a "
            "secondary address look like the contact had the last word "
            "and the task stays open."
        ),
    },
    # ─── Sync ────────────────────────────────────────────────
    #
    # While the desktop app is open, the renderer schedules an
    # automatic Update at this interval (the same RPC that the manual
    # "Update" button calls — IMAP sync + WhatsApp + memory + task
    # detection). Toggle off if the auto-loop gets in the way; the
    # manual button stays available either way.
    #
    # No effect when the app is closed: real cron / launchd scheduling
    # is a separate, future workstream (see docs/active-context.md).
    {
        "key": "AUTO_UPDATE_ENABLED",
        "label": "Auto-Update while app is open",
        "type": "select",
        "group": "Sync",
        "optional": True,
        "options": ["Yes", "No"],
        "default": "Yes",
        "help": (
            "When enabled, the app re-runs Update every "
            "AUTO_UPDATE_INTERVAL_MINUTES while it is open. The "
            "manual Update button is always available."
        ),
    },
    {
        "key": "AUTO_UPDATE_INTERVAL_MINUTES",
        "label": "Auto-Update interval (minutes)",
        "type": "number",
        "group": "Sync",
        "optional": True,
        "default": "30",
        "help": "Minutes between automatic Updates. Allowed range 5–360.",
    },
    # ─── Google ─────────────────────────────────────────────
    # Calendar is connected via the "Connect Google Calendar" button in
    # the Settings → Integrations section (PKCE OAuth on :19275, using the
    # Desktop OAuth client injected as GOOGLE_CALENDAR_CLIENT_ID_DEFAULT
    # by the Electron main process). No editable field is exposed — the
    # button is the whole flow. A power-user who needs a different OAuth
    # client can still set GOOGLE_CALENDAR_CLIENT_ID / _SECRET by hand in
    # the profile `.env` (config.py reads them via Pydantic); they're just
    # not surfaced in the Settings UI because the override confused users.
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
    {
        "key": "USER_LANGUAGE",
        "label": "Preferred language",
        "type": "text",
        "group": "Personal data",
        "optional": True,
        "help": (
            "Two-letter code the assistant uses when talking to you: "
            "it / en / es / fr / de. Leave empty to match the language "
            "of the latest incoming message."
        ),
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
        # NOT marked secret: "secret" here means "never leak to contacts /
        # emails / drafts", not "hide from the account owner editing their
        # own Settings". Masking this field in the UI led the user to
        # believe it wasn't being saved.
        "help": "Instructions Zylch follows but never reveals to contacts.",
    },
]


# Set of keys whose value is a secret (used by settings_get to mask).
SECRET_KEYS = {f["key"] for f in SETTINGS_SCHEMA if f.get("secret")}

# Set of all known keys (used by settings_update to validate).
KNOWN_KEYS = {f["key"] for f in SETTINGS_SCHEMA}


def get_schema() -> List[Dict[str, Any]]:
    """Return the schema as a plain list of dicts (JSON-serialisable)."""
    return [dict(f) for f in SETTINGS_SCHEMA]
