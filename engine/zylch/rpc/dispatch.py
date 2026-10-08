"""Transport-agnostic JSON-RPC 2.0 dispatch core.

Both the stdio server (``zylch.rpc.server``) and the WebSocket server
(``zylch.rpc.server_ws``) parse one inbound JSON-RPC frame and route it
here. This module owns parsing, validation, method lookup, handler
invocation, and JSON-RPC error mapping — everything EXCEPT the actual
read/write of bytes, which is the transport adapter's job.

``dispatch_raw(raw, notify)`` returns the response object to send back,
or ``None`` when nothing should be written (a notification with no
``id``, or a blank line). Keeping it pure (no I/O) is what lets a single
dispatch code-path serve two transports — see the plan's decision D2.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from zylch.rpc.methods import METHODS
from zylch.rpc.param_spec import build_registry, missing_required_params, unknown_params

logger = logging.getLogger(__name__)

# Accepted-parameter registry, derived from the handler docstrings at
# import time. Built here (not in param_spec) so it happens exactly once,
# after every sub-module has merged its methods into METHODS.
build_registry(METHODS)

# JSON-RPC 2.0 standard error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _error(req_id: Optional[Any], code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# Secrets MUST never reach the DEBUG "method=X params=Y" line below —
# stderr is captured by the renderer's narration pipeline and forwarded to
# the LLM proxy for summarisation, so anything here ends up in Anthropic's
# request logs. Keep synced with any RPC method that takes a JWT, API key,
# password, OTP, OAuth code, etc. (Origin: the Firebase id_token leak Mario
# caught flowing to Anthropic via narration after the engine defaulted to
# DEBUG logging — ported here when the dispatcher moved out of server.py.)
_SECRET_PARAM_KEYS_BY_METHOD: Dict[str, set] = {
    "account.set_firebase_token": {"id_token"},
    "auth.refresh": {"id_token"},
    "qonto.test": {"login", "api_key"},
    "qonto.connect": {"login", "api_key"},
}
#: Exact key names (compared case-insensitively) that always carry a
#: secret. Deliberately includes the bare words a caller reaches for when
#: it has no better name — ``{"session": …}``, ``{"token": …}`` — because
#: those reached this module's DEBUG line verbatim before 2026-08.
_SECRET_PARAM_KEYS_GLOBAL: set = {
    "auth",
    "credential",
    "credentials",
    "key",
    "passwd",
    "password",
    "secret",
    "session",
    "token",
    # Historical explicit entries; all also matched by the suffix rules
    # below, kept so the table still reads as documentation.
    "id_token",
    "access_token",
    "refresh_token",
    "api_key",
    "client_secret",
    "qonto_api_login",
}
#: Compound shapes: ``firebase_id_token``, ``smtp_password``, ``x_api_key``…
#: Suffixes are singular on purpose — ``input_tokens`` / ``output_tokens``
#: are usage counters, not secrets, and must stay readable.
_SECRET_PARAM_KEY_SUFFIXES: tuple = (
    "_auth",
    "_credential",
    "_credentials",
    "_key",
    "_passwd",
    "_password",
    "_secret",
    "_session",
    "_token",
)
#: Per-method carve-out for a param whose name LOOKS secret but is a
#: plain identifier the operator needs to see when reading logs. Applied
#: to TOP-LEVEL params only — a key of the same name nested inside a
#: payload is not the documented parameter and stays redacted.
#: ``agents.get_prompt(key="task_email")`` names a prompt, not a secret.
_NON_SECRET_PARAM_KEYS_BY_METHOD: Dict[str, set] = {
    "agents.get_prompt": {"key"},
}


def _is_secret_key(key: Any, extra: set) -> bool:
    """True when a param name must never have its value logged.

    Matching is case-insensitive and covers exact names plus the
    ``*_token`` / ``*_key`` / ``*_secret`` / ``*_password`` /
    ``*_session`` / ``*_credential`` compounds. Over-redaction in a
    DEBUG line is a cosmetic loss; under-redaction ships a credential to
    the narration pipeline, so the rule errs wide.
    """
    if not isinstance(key, str):
        return False
    name = key.strip().lower()
    if not name:
        return False
    if name.startswith("qonto_") or name in extra or name in _SECRET_PARAM_KEYS_GLOBAL:
        return True
    return name.endswith(_SECRET_PARAM_KEY_SUFFIXES)


def _redact_params(method: Optional[str], params: Dict[str, Any]) -> Dict[str, Any]:
    """Return a recursively redacted copy of ``params``."""
    if not isinstance(params, dict) or not params:
        return params
    if method == "chat.send":
        return {key: "<redacted chat>" for key in params}
    if method in {"narration.predict", "narration.summarize"}:
        return {key: "<redacted narration>" for key in params}
    if (method or "").startswith(("qonto.", "tasks.")):
        return {key: "<redacted>" for key in params}
    extra = _SECRET_PARAM_KEYS_BY_METHOD.get(method or "", set())
    allowed = _NON_SECRET_PARAM_KEYS_BY_METHOD.get(method or "", set())

    if method in {"projects.write", "projects.create", "instructions.store"}:
        params = dict(params)
        for payload in ("content_base64", "files"):
            if payload in params:
                params[payload] = "<redacted project document>"

    if method == "voice.config.update":
        params = {k: "<redacted voice configuration>" for k in params}

    def redact(value: Any, key: Optional[str] = None) -> Any:
        if key is not None and _is_secret_key(key, extra) and value:
            if key.strip().lower().startswith("qonto_"):
                return "<redacted>"
            return f"<redacted len={len(value)}>" if isinstance(value, str) else "<redacted>"
        if isinstance(value, dict):
            return {k: redact(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(redact(item) for item in value)
        return value

    # `redact(v, None)` keeps the value but still walks into containers,
    # so a carve-out never becomes a hole for something nested under it.
    return {k: redact(v, None if k in allowed else k) for k, v in params.items()}


async def dispatch_raw(raw: str, notify: NotifyFn) -> Optional[Dict[str, Any]]:
    """Parse + dispatch one JSON-RPC line. Performs NO I/O.

    Returns the response dict to send, or ``None`` if nothing should be
    written (notification, or blank line). The error codes and the
    notification-suppression rules mirror the original stdio
    ``_handle_request`` exactly, so behaviour is identical across both
    transports.
    """
    line = raw.strip()
    if not line:
        return None

    # Parse
    try:
        req = json.loads(line)
    except json.JSONDecodeError as e:
        logger.debug(f"[rpc] parse error: {e}")
        return _error(None, PARSE_ERROR, f"Parse error: {e}")

    if not isinstance(req, dict):
        return _error(None, INVALID_REQUEST, "Request must be a JSON object")

    req_id: Optional[Any] = req.get("id")
    method: Optional[str] = req.get("method")
    params: Dict[str, Any] = req.get("params") or {}
    is_notification = "id" not in req

    if not isinstance(method, str) or not method:
        if is_notification:
            return None
        return _error(req_id, INVALID_REQUEST, "Missing or invalid 'method'")

    if not isinstance(params, dict):
        if is_notification:
            return None
        return _error(req_id, INVALID_PARAMS, "'params' must be an object")

    handler = METHODS.get(method)
    if handler is None:
        logger.debug(f"[rpc] unknown method={method}")
        if is_notification:
            return None
        return _error(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")

    # A parameter the handler never reads is a caller bug that used to
    # pass silently — `tasks.list(status="open")` returned every task
    # and looked like a filtered list. Refuse it by name instead.
    rejected = unknown_params(method, params)
    if rejected:
        logger.warning(
            f"[rpc] {method} called with unknown param(s) {rejected} — "
            f"rejected (they would have been ignored)"
        )
        if is_notification:
            return None
        return _error(
            req_id,
            INVALID_PARAMS,
            f"Unknown parameter(s) for {method}: {', '.join(rejected)}",
        )

    missing = missing_required_params(method, params)
    if missing:
        logger.warning(f"[rpc] {method} missing required param(s) {missing} — rejected")
        if is_notification:
            return None
        return _error(
            req_id,
            INVALID_PARAMS,
            f"Missing required parameter(s) for {method}: {', '.join(missing)}",
        )

    logger.debug(f"[rpc] method={method} params={_redact_params(method, params)}")
    try:
        if method.startswith("tasks.") or method in {"narration.predict", "narration.summarize"}:
            from zylch.qonto.logging import private_scope

            with private_scope():
                result = await handler(params, notify)
        else:
            result = await handler(params, notify)
    except Exception as e:
        if method.startswith("tasks.assignment."):
            from zylch.services.task_assignment_types import AssignmentError

            code = e.code if isinstance(e, AssignmentError) else INTERNAL_ERROR
            message = str(e) if isinstance(e, AssignmentError) else "Assignment operation unavailable"
            logger.warning("[rpc] assignment operation refused code=%s", code)
            return None if is_notification else _error(req_id, code, message)
        if method.startswith("tasks."):
            from zylch.qonto.errors import QontoError
            from zylch.services.preparation import PreparationStopped

            if isinstance(e, PreparationStopped):
                logger.warning("[rpc] task preparation refused code=%s", e.code)
                return None if is_notification else _error(
                    req_id, e.code, "Preparation is unavailable; review preparation status."
                )
            code = e.code if isinstance(e, QontoError) else INTERNAL_ERROR
            safe_validation = {"actor must be a string when provided", "why must be a string when provided", "note must be a string when provided", "task_id is required", "task_id must be a string", "pinned is required", "contact_email, title and event_id are required", "pass exactly one of due_at (epoch seconds) or days"}
            message = str(e) if isinstance(e, QontoError) or (isinstance(e, ValueError) and str(e) in safe_validation) else "Task operation failed"
            logger.warning("[rpc] task operation failed code=%s", code)
            return None if is_notification else _error(req_id, code, message)
        if method in {"narration.predict", "narration.summarize"}:
            from zylch.qonto.errors import QontoError

            code = e.code if isinstance(e, QontoError) else INTERNAL_ERROR
            message = (
                f"{type(e).__name__}: {e}"
                if isinstance(e, QontoError)
                else "Narration operation failed"
            )
            logger.warning("[rpc] narration operation failed code=%s", code)
            return None if is_notification else _error(req_id, code, message)
        if method == "chat.send":
            from zylch.qonto.errors import QontoError

            code = e.code if isinstance(e, QontoError) else INTERNAL_ERROR
            message = str(e) if isinstance(e, QontoError) else "Chat operation failed"
            logger.warning("[rpc] chat operation failed code=%s", code)
            return None if is_notification else _error(req_id, code, message)
        if method.startswith("qonto."):
            from zylch.qonto.errors import QontoError

            code = e.code if isinstance(e, QontoError) else INTERNAL_ERROR
            message = str(e) if isinstance(e, QontoError) else "Qonto operation failed"
            logger.warning("[rpc] Qonto operation failed code=%s", code)
            return None if is_notification else _error(req_id, code, message)
        if method.startswith("voice."):
            from zylch.services.voice.agent_config import VoiceError

            code = e.code if isinstance(e, VoiceError) else INTERNAL_ERROR
            message = str(e) if isinstance(e, VoiceError) else "Voice operation failed"
            logger.warning("[rpc] voice operation failed code=%s", code)
            return None if is_notification else _error(req_id, code, message)
        # Project storage exceptions may include SQL parameters (document bytes).
        # Only our dedicated safe exception may cross this boundary verbatim.
        from zylch.services.project_store import ProjectError

        if (
            method.startswith("projects.")
            or method.startswith("instructions.")
            or method == "memory.join"
        ):
            code = e.code if isinstance(e, ProjectError) else INTERNAL_ERROR
            message = str(e) if isinstance(e, ProjectError) else "Project storage operation failed"
            logger.warning("[rpc] project operation failed code=%s", code)
            return None if is_notification else _error(req_id, code, message)
        # Handlers may raise errors with a ``.code`` attribute to map
        # cleanly to JSON-RPC application error codes (e.g. -32000 for
        # "solve already in progress", -32010 for "no signed-in
        # session"). Those are intentional protocol-level signals — log a
        # one-liner. Unknown / unhandled exceptions get the full
        # traceback at ERROR.
        err_code = getattr(e, "code", None)
        if isinstance(err_code, int):
            logger.warning(
                f"[rpc] handler {method} failed code={err_code} " f"{type(e).__name__}: {e}"
            )
        else:
            logger.exception(f"[rpc] handler {method} failed")
            err_code = INTERNAL_ERROR
        if is_notification:
            return None
        return _error(req_id, err_code, f"{type(e).__name__}: {e}")

    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": req_id, "result": result}
