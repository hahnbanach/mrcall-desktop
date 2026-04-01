"""MrCall Error Handler — Retry, humanize, and log API errors.

Handles transient Anthropic API errors (529 Overloaded, 500, timeouts)
with retry + exponential backoff. On persistent failure, uses Haiku
to generate a user-friendly error message, logs to error_logs table,
and returns a graceful fallback.

Design principle: an LLM call that prevents user abandonment costs $0.001.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Errors worth retrying (transient)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds: 2, 4, 8


def is_retryable(error: Exception) -> bool:
    """Check if an Anthropic API error is transient and worth retrying."""
    error_str = str(error)
    # Anthropic SDK includes status code in the error message
    for code in RETRYABLE_STATUS_CODES:
        if f"Error code: {code}" in error_str:
            return True
    # Also catch generic connection errors
    if any(term in error_str.lower() for term in ["timeout", "connection", "temporarily"]):
        return True
    return False


def parse_error_details(error: Exception) -> Dict[str, Any]:
    """Extract structured details from an Anthropic API error."""
    error_str = str(error)
    details = {
        "error_type": "unknown",
        "error_code": None,
        "error_message": error_str,
        "request_id": None,
    }

    # Parse "Error code: 529 - {'type': 'error', 'error': {'type': 'overloaded_error', ...}}"
    if "Error code:" in error_str:
        try:
            code_part = error_str.split("Error code: ")[1].split(" -")[0]
            details["error_code"] = int(code_part)
        except (IndexError, ValueError):
            pass

    if "'type': '" in error_str:
        try:
            type_part = error_str.split("'type': '")[2].split("'")[0]
            details["error_type"] = type_part
        except (IndexError, ValueError):
            pass

    if "'request_id': '" in error_str:
        try:
            req_id = error_str.split("'request_id': '")[1].split("'")[0]
            details["request_id"] = req_id
        except (IndexError, ValueError):
            pass

    return details


async def humanize_error(error: Exception, api_key: str) -> str:
    """Use Haiku to generate a user-friendly error message.

    Returns a short (2 lines max) message explaining the error
    in non-technical terms. Falls back to a generic message
    if Haiku itself fails.
    """
    import anthropic

    details = parse_error_details(error)
    generic_fallback = (
        "Mi scuso, c'è un problema temporaneo con il servizio. "
        "Riprovo automaticamente tra qualche secondo..."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.messages.create(
                model="claude-haiku-3-5-20241022",
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": (
                        "Sei l'assistente di un configuratore telefonico AI (MrCall). "
                        "L'utente stava configurando il suo assistente e c'è stato un errore tecnico. "
                        f"Errore: {details['error_type']} (codice {details['error_code']}). "
                        "Scrivi UN messaggio di massimo 2 righe per spiegare all'utente "
                        "cosa è successo in modo semplice e rassicurante. "
                        "Non usare termini tecnici. Usa il tu. "
                        "Se è un errore temporaneo, dì che riproverai automaticamente."
                    ),
                }],
            )
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"[error_handler] Haiku humanize failed: {e}")
        return generic_fallback


async def log_error(
    error: Exception,
    owner_id: str,
    business_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_message: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Log error to the error_logs database table."""
    try:
        from zylch.storage.database import get_engine
        from zylch.storage.models import ErrorLog
        from sqlalchemy.orm import Session

        details = parse_error_details(error)
        engine = get_engine()

        with Session(engine) as session:
            log_entry = ErrorLog(
                owner_id=owner_id,
                business_id=business_id,
                session_id=session_id,
                error_type=details["error_type"],
                error_code=details["error_code"],
                error_message=details["error_message"],
                user_message=user_message,
                request_id=details["request_id"],
                context=context or {},
            )
            session.add(log_entry)
            session.commit()
            logger.info(
                f"[error_handler] Logged error: type={details['error_type']}, "
                f"code={details['error_code']}, request_id={details['request_id']}"
            )
    except Exception as e:
        # Don't let logging failure break the flow
        logger.error(f"[error_handler] Failed to log error to DB: {e}")


FINAL_FALLBACK_MESSAGE = (
    "Mi dispiace, purtroppo ci sono dei problemi tecnici temporanei "
    "e non riesco a elaborare la tua richiesta in questo momento. 😔\n\n"
    "Puoi riprovare tra qualche minuto, oppure scrivere a "
    "**support@mrcall.ai** indicando il valore della conversazione "
    "che trovi in basso nella chat. Ti aiuteremo il prima possibile!"
)
