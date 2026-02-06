"""
Sandbox enforcement for restricted access modes.

Server-side restriction of available commands and features.
Supports multiple sandbox modes (e.g., "mrcall" for MrCall Dashboard users).
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


# Sandbox mode constants
SANDBOX_MODE_MRCALL = "mrcall"


def is_command_allowed_in_sandbox(cmd: str, args: List[str], sandbox_mode: Optional[str] = None) -> bool:
    """
    Check if command+args is allowed in the given sandbox mode.

    Whitelist approach: only explicitly allowed commands can execute.

    Args:
        cmd: The command (e.g., "/mrcall", "/email")
        args: Command arguments (e.g., ["open", "abc123"])
        sandbox_mode: The sandbox mode (e.g., "mrcall") or None for no sandbox

    Returns:
        True if command is allowed, False otherwise
    """
    # No sandbox = everything allowed
    if sandbox_mode is None:
        return True

    cmd_lower = cmd.lower()

    # MrCall sandbox mode
    if sandbox_mode == SANDBOX_MODE_MRCALL:
        return _is_command_allowed_mrcall_sandbox(cmd_lower, args)

    # Unknown sandbox mode = block everything for safety
    logger.warning(f"[Sandbox] Unknown sandbox mode: {sandbox_mode}")
    return False


def _is_command_allowed_mrcall_sandbox(cmd: str, args: List[str]) -> bool:
    """Check if command is allowed in MrCall sandbox mode."""
    # /help is always allowed
    if cmd == "/help":
        return True

    # /mrcall is allowed, but NOT exit/close subcommands (user must stay in config mode)
    if cmd == "/mrcall":
        if len(args) > 0 and args[0].lower() in ("exit", "close"):
            return False
        return True

    # /agent is allowed ONLY with "mrcall" subcommand
    if cmd == "/agent":
        if len(args) > 0 and args[0].lower() == "mrcall":
            return True
        return False

    # Everything else is blocked
    return False


def get_sandbox_blocked_response(sandbox_mode: Optional[str] = SANDBOX_MODE_MRCALL) -> str:
    """Error message for blocked commands."""
    if sandbox_mode == SANDBOX_MODE_MRCALL:
        return """❌ Questo comando non è disponibile nella dashboard MrCall.

**Comandi disponibili:**
- `/mrcall variables` - Mostra variabili configurabili
- `/mrcall show` - Mostra configurazione attuale
- `/mrcall config <var> <val>` - Imposta un valore
- `/agent mrcall train` - Genera prompt personalizzato
- `/agent mrcall run` - Applica configurazione
- `/help` - Mostra tutti i comandi disponibili

Per funzionalità complete (email, calendar, tasks), usa l'app Zylch."""

    # Generic fallback
    return "❌ Questo comando non è disponibile in questa modalità."


def get_sandbox_freeform_blocked_response(sandbox_mode: Optional[str] = SANDBOX_MODE_MRCALL) -> str:
    """Error message when free-form chat is not allowed (not in config mode)."""
    if sandbox_mode == SANDBOX_MODE_MRCALL:
        return """⚠️ Per favore apri prima un assistente con `/mrcall open <id>`

Usa `/mrcall list` per vedere gli assistenti disponibili."""

    # Generic fallback
    return "⚠️ Azione non disponibile in questa modalità."


def get_sandbox_help(sandbox_mode: Optional[str] = SANDBOX_MODE_MRCALL) -> str:
    """Help text for sandbox users."""
    if sandbox_mode == SANDBOX_MODE_MRCALL:
        return """**MrCall Dashboard - Comandi Disponibili**

**Configurazione Assistente:**
- `/mrcall open <id>` - Apri configurazione assistente
- `/mrcall variables` - Mostra variabili configurabili
- `/mrcall show` - Mostra configurazione attuale
- `/mrcall config <variabile> <valore>` - Imposta un valore
- `/mrcall close` - Esci dalla modalità configurazione

**Training Agente:**
- `/agent mrcall train` - Genera prompt personalizzato dai tuoi dati
- `/agent mrcall run` - Applica la configurazione
- `/agent mrcall show` - Mostra configurazione agente
- `/agent mrcall reset` - Reset ai valori default

**Suggerimenti:**
Una volta in modalità configurazione, puoi usare linguaggio naturale:
- "Il mio studio è aperto dal lunedì al venerdì dalle 9 alle 18"
- "Rispondi in modo più formale"
- "Aggiungi che accettiamo prenotazioni online"

Per funzionalità complete (email, calendar, tasks), usa l'app Zylch."""

    # Generic fallback
    return "Usa `/help` per vedere i comandi disponibili."
