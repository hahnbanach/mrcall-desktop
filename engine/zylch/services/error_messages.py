"""Turn an exception into a clear, actionable user-facing message.

The pipeline and RPC layers used to surface raw tracebacks (or, worse,
swallow them and report success). This module classifies KNOWN failures
by exception TYPE / errno / status — structured signals, NOT prose
parsing — into a small dict the UI can render:

    {stage, kind, severity, title, detail, action}

`severity` is "error" (the run failed / the user's goal is blocked) or
"warning" (an optional stage failed but the run still did something).

An LLM fallback for *unrecognised* errors is a deliberate later phase —
this module is the deterministic, offline, always-available first tier.
:func:`humanize_error` never raises.
"""

from __future__ import annotations

import errno as _errno
import os
import socket
import ssl
from typing import Any, Dict, Optional

# Stage → human label (for the title of an otherwise-unclassified error).
_STAGE_LABEL = {
    "email_sync": "Email sync",
    "whatsapp": "WhatsApp sync",
    "memory": "Memory extraction",
    "tasks": "Task detection",
    "llm": "AI",
}


def _imap_host_hint() -> str:
    return (os.environ.get("IMAP_HOST") or "").strip() or "the mail server"


def _mk(
    stage: Optional[str],
    kind: str,
    severity: str,
    title: str,
    detail: str,
    action: str = "",
) -> Dict[str, Any]:
    return {
        "stage": stage or "",
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "action": action,
    }


def humanize_error(error: BaseException, stage: Optional[str] = None) -> Dict[str, Any]:
    """Classify ``error`` into a user-facing ``{stage,kind,severity,title,
    detail,action}`` dict. Defensive: any failure inside classification
    degrades to a generic 'unknown' entry rather than raising."""
    try:
        return _classify(error, stage)
    except Exception:
        return _mk(
            stage,
            "unknown",
            "error",
            "Something went wrong",
            str(error)[:500] or type(error).__name__,
            "See the logs for details, or retry.",
        )


def _walk_chain(error: BaseException):
    """Yield ``error`` and each link of its ``__cause__`` chain (capped to
    avoid pathological loops). Transport wrappers like
    ``httpx.ConnectError`` / ``httpcore.ConnectError`` carry the real
    cause (e.g. ``socket.gaierror``) under ``__cause__``; walking lets us
    classify wrapped and direct errors uniformly. We deliberately do NOT
    follow ``__context__`` — that's the implicit "during handling of X"
    link and would risk matching unrelated handlers."""
    seen: set = set()
    cur: Optional[BaseException] = error
    for _ in range(8):
        if cur is None or id(cur) in seen:
            return
        seen.add(id(cur))
        yield cur
        cur = getattr(cur, "__cause__", None)


def _is_host_stage(stage: Optional[str]) -> bool:
    return stage in ("email_sync", "whatsapp")


def _classify(error: BaseException, stage: Optional[str]) -> Dict[str, Any]:
    # WhatsApp is the only optional stage — a failure there is a warning,
    # everything else blocks the run.
    sev = "warning" if stage == "whatsapp" else "error"
    label = _STAGE_LABEL.get(stage or "", "")

    # ── MrCall credits / auth (raised directly by proxy_client; only
    #    meaningful at the top of the error, not inside a generic wrap) ──
    try:
        from zylch.llm.proxy_client import MrCallAuthError, MrCallInsufficientCredits
    except Exception:
        MrCallInsufficientCredits = MrCallAuthError = None  # type: ignore

    if MrCallInsufficientCredits is not None and isinstance(error, MrCallInsufficientCredits):
        topup = getattr(error, "topup_url", "") or "https://dashboard.mrcall.ai/plan"
        return _mk(
            stage,
            "credits",
            "error",
            "Out of MrCall credits",
            "The AI steps (memory + task detection) need credits and the balance is empty.",
            f"Top up at {topup}, then run Update again.",
        )
    if MrCallAuthError is not None and isinstance(error, MrCallAuthError):
        return _mk(
            stage,
            "auth",
            "error",
            "MrCall sign-in expired",
            "The server rejected your session token.",
            "Sign out and back in, then retry.",
        )

    # ── Walk the __cause__ chain for transport-layer signals. This is what
    #    catches `httpx.ConnectError` (which the proxy / mrcall RPCs raise)
    #    by finding the underlying `socket.gaierror` it wraps. ────────────
    import imaplib
    import smtplib

    for cur in _walk_chain(error):
        # DNS — gaierror subclasses OSError, so check it BEFORE the generic
        # OSError errno branch below.
        if isinstance(cur, socket.gaierror):
            if _is_host_stage(stage):
                host = _imap_host_hint()
                return _mk(
                    stage,
                    "dns",
                    sev,
                    f"Can't reach the mail server ({host})",
                    f"The address “{host}” didn’t resolve — it may be wrong, " "or you’re offline.",
                    "Check the IMAP/SMTP host in Settings and your internet connection.",
                )
            return _mk(
                stage,
                "dns",
                sev,
                "Can’t reach the server",
                "A network address didn’t resolve — you may be offline, or your " "DNS is flaky.",
                "Check your internet connection and retry.",
            )

        # IMAP login / protocol
        if isinstance(cur, (imaplib.IMAP4.error, imaplib.IMAP4.abort)):
            msg = str(cur)
            up = msg.upper()
            if "AUTHENTICATIONFAILED" in up or "INVALID CREDENTIALS" in up or "LOGIN" in up:
                return _mk(
                    stage,
                    "auth",
                    sev,
                    "Email login rejected",
                    "The mail server refused the username or password.",
                    "For Gmail/Workspace use a Google App Password and make sure "
                    "IMAP is enabled; check EMAIL_PASSWORD in Settings.",
                )
            return _mk(
                stage,
                "imap",
                sev,
                "Email server error",
                f"The mail server returned an error: {msg[:200]}",
                "Check the account settings, then retry.",
            )

        # SMTP auth
        if isinstance(cur, smtplib.SMTPAuthenticationError):
            return _mk(
                stage,
                "auth",
                sev,
                "Email send login rejected",
                "SMTP refused the username or password.",
                "Use a Google App Password for Gmail/Workspace; check the SMTP settings.",
            )

        # TLS (subclass of OSError; before the OSError errno branch below)
        if isinstance(cur, ssl.SSLError):
            return _mk(
                stage,
                "tls",
                sev,
                "Secure connection failed",
                "The TLS handshake failed.",
                "Check the host and port in Settings.",
            )

        # Timeouts
        if isinstance(cur, (TimeoutError, socket.timeout)):
            return _mk(
                stage,
                "timeout",
                sev,
                "The server didn’t respond in time",
                "The connection timed out.",
                "Check your connection and retry.",
            )

        # Connection-level OSError (refused / unreachable)
        if isinstance(cur, OSError):
            en = getattr(cur, "errno", None)
            if en in (
                _errno.ECONNREFUSED,
                _errno.EHOSTUNREACH,
                _errno.ENETUNREACH,
                _errno.ENETDOWN,
                _errno.ECONNRESET,
            ):
                if _is_host_stage(stage):
                    host = _imap_host_hint()
                    return _mk(
                        stage,
                        "network",
                        sev,
                        f"Can’t connect to the mail server ({host})",
                        "The server refused the connection or is unreachable.",
                        "Check the host/port and your internet connection.",
                    )
                return _mk(
                    stage,
                    "network",
                    sev,
                    "Can’t connect to the server",
                    "The server refused the connection or is unreachable.",
                    "Check your internet connection and retry.",
                )

        # No LLM configured — our own RuntimeError message
        if isinstance(cur, RuntimeError) and "no llm" in str(cur).lower():
            return _mk(
                stage,
                "no_llm",
                "error",
                "No AI model configured",
                "Memory and task detection need an LLM, but none is set for this profile.",
                "Add an Anthropic API key in Settings, or switch to “Use MrCall credits” "
                "and sign in.",
            )

    # ── Fallback ────────────────────────────────────────────────────────
    return _mk(
        stage,
        "unknown",
        sev,
        f"{label} failed" if label else "Something went wrong",
        str(error)[:500] or type(error).__name__,
        "See the logs for details, or retry.",
    )
