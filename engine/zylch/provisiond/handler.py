"""Route logic + HTTP wiring for provisiond.

Business logic (`handle_provision` / `handle_status`) is a pure function
of `(claims, body)` plus the filesystem/`systemctl` world — no HTTP
objects touch it — so tests call it directly with a hand-built claims
dict, no server required. `ProvisiondRequestHandler` is the thin
`BaseHTTPRequestHandler` glue: read the request, authenticate, call the
pure function, write the JSON response.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any

from zylch.rpc.firebase_auth import FirebaseAuthError, verify_firebase_id_token
from zylch.services.settings_io import _quote
from zylch.services.settings_schema import KNOWN_KEYS

logger = logging.getLogger(__name__)

# ─── Configuration — all resolved at CALL time, never import-time
# constants, so a systemd `EnvironmentFile=` change or a test's
# `monkeypatch.setenv` takes effect without reimporting this module. ───

DEFAULT_PROFILES_ROOT = "/home/mrcalld/.zylch/profiles"
DEFAULT_FIREBASE_PROJECT_ID = "talkmeapp-e696c"
DEFAULT_SOCKET_PATH = "/run/mrcalld/provisiond.sock"


def config_profiles_root() -> str:
    return os.environ.get("MRCALL_PROFILES_ROOT", DEFAULT_PROFILES_ROOT)


def config_firebase_project_id() -> str:
    return os.environ.get("FIREBASE_PROJECT_ID", DEFAULT_FIREBASE_PROJECT_ID)


def config_socket_path() -> str:
    return os.environ.get("PROVISIOND_SOCKET", DEFAULT_SOCKET_PATH)


# ─── Constants ──────────────────────────────────────────────────────

# Marker file name: written BEFORE `.env` on provision, deleted the first
# time the status route observes the unit active (D3). Its presence,
# independent of whether `.env` exists yet, is the whole "preparing"
# signal.
MARKER_NAME = "PROVISIONING"

# uid becomes a filesystem path component (`<profiles_root>/<uid>/`) —
# this regex plus the explicit `.`/`..` refusal below is the entire
# traversal boundary. `/` is already outside the allowed charset, so a
# match here can never escape a single path component. Firebase uids are
# always safe alphanumeric strings in practice, but validate explicitly
# rather than trust it — a path-component guard the kernel review taught
# us to make explicit.
_UID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# A profile `.env` is a few KB at most; this bounds the request body we
# are willing to buffer in memory before even attempting to parse it.
MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB


class ProvisionError(Exception):
    """An expected, client-facing error.

    `status_code` + `public_message` are safe to put on the wire
    verbatim — never wrap an internal exception's message/traceback in
    one of these; that belongs behind the generic 500 branch instead.
    """

    def __init__(self, status_code: int, public_message: str) -> None:
        super().__init__(public_message)
        self.status_code = status_code
        self.public_message = public_message


def _validate_uid(uid: str) -> str:
    """Return `uid` unchanged if safe as a single path component.

    Raises `ProvisionError(400, ...)` otherwise. Refuses anything outside
    `[A-Za-z0-9_.-]` (already excluding `/`, which rules out traversal
    via a path separator) and the two filesystem-special values `.` /
    `..`, which that charset alone does not exclude.
    """
    if not uid or not _UID_RE.match(uid) or uid in (".", ".."):
        raise ProvisionError(400, "invalid uid")
    return uid


def entitlement_allows(uid: str, claims: dict[str, Any]) -> bool:
    """Entitlement/payment gate (D5) — STUBBED PERMISSIVE.

    TODO: replace with a real check against StarChat (the account's
    entitlement/payment status for provisioning a vendor engine) before
    this is trusted for paid multi-tenant use. Always True today; a
    refusal, once this is real, is a 403.
    """
    return True


def _profile_dir(uid: str) -> str:
    return os.path.join(config_profiles_root(), uid)


def _marker_path(uid: str) -> str:
    return os.path.join(_profile_dir(uid), MARKER_NAME)


def _env_path(uid: str) -> str:
    return os.path.join(_profile_dir(uid), ".env")


def _unit_name(uid: str) -> str:
    return f"zylch-server@{uid}"


def _systemctl_is_active(uid: str) -> bool:
    """True iff `systemctl is-active zylch-server@<uid>` reports active."""
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", _unit_name(uid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"[provisiond] systemctl is-active failed uid={uid}: {e}")
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "active"


def _systemctl_is_failed(uid: str) -> bool:
    """True iff `systemctl is-failed zylch-server@<uid>` reports failed."""
    try:
        proc = subprocess.run(
            ["systemctl", "is-failed", _unit_name(uid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"[provisiond] systemctl is-failed failed uid={uid}: {e}")
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "failed"


def authenticate(headers: Any) -> dict[str, Any]:
    """Verify the bearer token from an HTTP headers mapping; return claims.

    Raises `FirebaseAuthError` (missing/malformed/invalid token) — the
    HTTP layer maps that to 401. `project_id` is resolved from our own
    env config (`config_firebase_project_id`), never the pydantic
    settings graph — provisiond has no active profile (it is not a
    per-profile daemon), so nothing in `zylch.config` describes it.
    """
    auth = headers.get("Authorization") or headers.get("authorization")
    if not auth:
        raise FirebaseAuthError("missing 'Authorization: Bearer <firebase-id-token>' header")
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise FirebaseAuthError("malformed Authorization header")
    token = parts[1].strip()
    if not token:
        raise FirebaseAuthError("empty bearer token")
    return verify_firebase_id_token(token, project_id=config_firebase_project_id())


def _write_env_atomic(path: str, values: dict[str, str]) -> None:
    """Write `path` atomically: tmp file in the same dir, fsync, rename.

    0600 from creation via `os.open` — mirrors
    `zylch.services.settings_io.update_env`'s own tmp+fsync+rename
    pattern, and quotes values with that module's `_quote` so the file is
    byte-compatible with what the app itself would write.
    """
    tmp_path = path + ".tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for key, value in values.items():
                f.write(f"{key}={_quote(value)}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def handle_provision(claims: dict[str, Any], body: Any) -> tuple[int, dict[str, Any]]:
    """Core logic for `POST /api/provision`. See module docstring."""
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise ProvisionError(401, "token missing sub")
    uid = _validate_uid(sub)

    if not isinstance(body, dict):
        raise ProvisionError(400, "body must be a JSON object")

    # D4: a live profile is not re-provisionable through this route (that
    # is a support action); a dir left by a failed or partial attempt is,
    # and gets overwritten below. The check is inherently racy — a unit
    # that goes active in the window between here and the write would get
    # its `.env` overwritten — but the race is only reachable by the
    # profile's own owner (the uid comes from their verified token), and
    # closing it would need a lock the profile tree does not have.
    if _systemctl_is_active(uid):
        raise ProvisionError(409, "already provisioned")

    # Python is the authority on which keys are valid Settings fields —
    # 400 naming every offender in one response rather than the first.
    unknown = sorted(str(k) for k in body if str(k) not in KNOWN_KEYS)
    if unknown:
        raise ProvisionError(400, f"unknown key(s): {', '.join(unknown)}")

    values: dict[str, str] = {str(k): ("" if v is None else str(v)) for k, v in body.items()}
    # OWNER_ID is injected OUTSIDE the KNOWN_KEYS validation above — it is
    # deliberately not a user-editable Settings field (mirror of the
    # app-side profileFS.ts:259-279 exclusion) and it must always be the
    # verified uid, never anything the client could put in the body.
    values["OWNER_ID"] = uid

    if not entitlement_allows(uid, claims):
        raise ProvisionError(403, "not entitled")

    profile_dir = _profile_dir(uid)
    os.makedirs(profile_dir, exist_ok=True)
    os.chmod(profile_dir, 0o700)

    # Write order is load-bearing: the marker MUST exist before `.env`.
    # The instant `.env` carries `OWNER_ID=`, B3's watcher + reconciler
    # will discover and start the profile, so a marker written after
    # `.env` would make the "preparing" state a lie for whatever window
    # separates the two writes.
    with open(_marker_path(uid), "w", encoding="utf-8"):
        pass

    _write_env_atomic(_env_path(uid), values)

    logger.info(f"[provisiond] provisioned uid={uid} keys={sorted(values.keys())}")
    return 200, {"uid": uid, "state": "preparing"}


def handle_status(claims: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Core logic for `GET /api/provision/status`. uid comes ONLY from
    `claims["sub"]` — never from the request — see module docstring."""
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise ProvisionError(401, "token missing sub")
    uid = _validate_uid(sub)

    if _systemctl_is_active(uid):
        try:
            os.unlink(_marker_path(uid))
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"[provisiond] could not remove marker uid={uid}: {e}")
        return 200, {"state": "active"}

    if _systemctl_is_failed(uid):
        return 200, {"state": "problem"}

    if os.path.exists(_marker_path(uid)):
        return 200, {"state": "preparing"}

    # Neither active nor failed and no marker: either nothing was ever
    # provisioned, or a provisioned profile is between runs — every B3
    # reconcile restarts the daemon, and the marker is long gone by then
    # (deleted the first time this route saw it active). Only a `.env`
    # on disk tells those two apart, and answering "not_provisioned" for
    # a live customer mid-restart would send them back to the app to
    # re-do setup they already did.
    if os.path.exists(_env_path(uid)):
        return 200, {"state": "preparing"}

    return 200, {"state": "not_provisioned"}


class ProvisiondRequestHandler(BaseHTTPRequestHandler):
    """Stdlib `BaseHTTPRequestHandler` glue around the two routes.

    Deliberately left at the class default `protocol_version = "HTTP/1.0"`
    (no keep-alive): every request gets its own connection, so replying
    early (e.g. a 401 before the body is read) can never leave unread
    body bytes to be misparsed as the start of a following request on a
    reused connection. Concurrency instead comes from the server being
    `ThreadingMixIn` (see `__main__.py`) — one thread per connection, so
    one slow client never blocks another. `timeout` bounds how long any
    single connection (its own thread) may sit on a slow client.
    """

    server_version = "provisiond/1"
    timeout = 30  # seconds; socketserver.StreamRequestHandler applies this

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("[provisiond] " + (format % args))

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError as e:
            # Client gone / connection timed out mid-response — nothing
            # left to do; do not let this take the worker thread down.
            logger.debug(f"[provisiond] send failed (client gone?): {e}")

    def _authenticate_or_fail(self) -> dict[str, Any] | None:
        try:
            return authenticate(self.headers)
        except FirebaseAuthError as e:
            logger.warning(f"[provisiond] 401: {e}")
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return None
        except Exception:
            # Anything NOT raised as FirebaseAuthError (e.g. a bug, or a
            # future change to the auth path that adds a new failure
            # mode) must still land on the same 500-no-internals taxonomy
            # as the route handlers below — never let it escape uncaught
            # to the raw socketserver error handler.
            logger.exception("[provisiond] unhandled error during authentication")
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})
            return None

    def _read_json_body(self) -> Any:
        # No Content-Length -> refuse rather than guess a framing (we do
        # not implement chunked transfer-decoding — stdlib http.server
        # does not provide it, and guessing risks blocking forever).
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            raise ProvisionError(400, "missing Content-Length")
        try:
            length = int(length_header)
        except ValueError:
            raise ProvisionError(400, "invalid Content-Length")
        if length < 0:
            raise ProvisionError(400, "invalid Content-Length")
        if length > MAX_BODY_BYTES:
            raise ProvisionError(400, "body too large")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ProvisionError(400, "malformed JSON body") from e

    def do_POST(self) -> None:
        if self.path != "/api/provision":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        claims = self._authenticate_or_fail()
        if claims is None:
            return
        try:
            body = self._read_json_body()
            status_code, payload = handle_provision(claims, body)
            self._send_json(status_code, payload)
        except ProvisionError as e:
            self._send_json(e.status_code, {"error": e.public_message})
        except Exception:
            logger.exception("[provisiond] unhandled error in POST /api/provision")
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

    def do_GET(self) -> None:
        if self.path != "/api/provision/status":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        claims = self._authenticate_or_fail()
        if claims is None:
            return
        try:
            status_code, payload = handle_status(claims)
            self._send_json(status_code, payload)
        except ProvisionError as e:
            self._send_json(e.status_code, {"error": e.public_message})
        except Exception:
            logger.exception("[provisiond] unhandled error in GET /api/provision/status")
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})
