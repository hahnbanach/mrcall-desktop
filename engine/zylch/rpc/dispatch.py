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

logger = logging.getLogger(__name__)

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
}
_SECRET_PARAM_KEYS_GLOBAL: set = {
    # Defence-in-depth: redact regardless of method, in case a new RPC
    # ships before this table is updated. Broad, but not so broad we hit
    # innocent fields like "passenger" or usage "*_tokens".
    "id_token",
    "access_token",
    "refresh_token",
    "api_key",
    "password",
    "client_secret",
    "secret",
}


def _redact_params(method: Optional[str], params: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``params`` with known-sensitive fields masked."""
    if not isinstance(params, dict) or not params:
        return params
    secret_keys = _SECRET_PARAM_KEYS_BY_METHOD.get(method or "", set()) | _SECRET_PARAM_KEYS_GLOBAL
    redacted = dict(params)
    for k in list(redacted.keys()):
        if k in secret_keys and redacted[k]:
            v = redacted[k]
            redacted[k] = f"<redacted len={len(v)}>" if isinstance(v, str) else "<redacted>"
    return redacted


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

    logger.debug(f"[rpc] method={method} params={_redact_params(method, params)}")
    try:
        result = await handler(params, notify)
    except Exception as e:
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
