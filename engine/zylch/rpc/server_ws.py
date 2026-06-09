"""WebSocket JSON-RPC transport for the sidecar (cross-machine backend).

``zylch serve --ws HOST:PORT`` runs this. It exposes the SAME JSON-RPC
dispatch table as the stdio server (``zylch.rpc.dispatch.dispatch_raw``),
but over a WebSocket so the Electron client (or a future mobile client)
can reach an engine running on another machine.

Auth: unlike stdio (which trusts its parent process), every connection
must present a verified Firebase ID token. Phase 1 reads it from the
``Authorization: Bearer <jwt>`` request header — every current client
(Node ``ws``, python ``websockets``, smoke scripts) can set headers. A
browser-friendly ``Sec-WebSocket-Protocol: bearer.<jwt>`` fallback is
deferred to the phase that introduces an actual browser/mobile client.
The token's ``sub`` (Firebase uid) must equal this profile's
``OWNER_ID``; the verified token is installed as the in-memory
``FirebaseSession`` so credit / StarChat calls work exactly as they do
over stdio.

Outbound framing: responses AND notifications for one connection are
funnelled through a single per-connection queue drained by one writer
task. WebSocket sends must not overlap, and notifications can be emitted
from worker threads (e.g. ``update.progress``); the queue + a thread-safe
``call_soon_threadsafe`` hand-off makes both safe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from http import HTTPStatus
from typing import Any, Dict, Optional, Tuple

from zylch.auth import get_session, set_session
from zylch.rpc.dispatch import dispatch_raw

logger = logging.getLogger(__name__)

# Custom WS close code: the Firebase token expired / auth was lost
# mid-session. The client should refresh its token and reconnect.
# 4000-4999 is the private-use range per RFC 6455.
WS_CLOSE_AUTH_EXPIRED = 4401


def _expected_owner_uid() -> str:
    """The Firebase uid this profile is bound to (OWNER_ID in its .env)."""
    return os.environ.get("OWNER_ID", "") or ""


def _bearer_from_request(request) -> Optional[str]:
    """Extract the JWT from ``Authorization: Bearer <jwt>``; None if absent."""
    headers = request.headers
    auth = headers.get("Authorization") or headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


def _authenticate_blocking(request) -> Tuple[Dict[str, Any], str]:
    """Verify the bearer token and gate ``uid == OWNER_ID``.

    Returns ``(claims, token)`` on success. Raises ``FirebaseAuthError``
    (bad token) or ``PermissionError`` (valid token, wrong owner / no
    OWNER_ID on this profile). Runs Google cert fetch + RS256 verify, so
    callers invoke it via ``asyncio.to_thread``.
    """
    from zylch.rpc.firebase_auth import FirebaseAuthError, verify_firebase_id_token

    token = _bearer_from_request(request)
    if not token:
        raise FirebaseAuthError("missing 'Authorization: Bearer <firebase-id-token>' header")

    claims = verify_firebase_id_token(token)
    uid = claims.get("sub", "")

    expected = _expected_owner_uid()
    if not expected:
        raise PermissionError(
            "this profile has no OWNER_ID — cross-machine serving requires a "
            "Firebase-keyed profile"
        )
    if uid != expected:
        raise PermissionError("token uid does not own this profile")
    return claims, token


async def _process_request(connection, request):
    """Gate the WebSocket handshake on a valid, owning Firebase token.

    Returns ``None`` to accept (stashing the verified claims/token on the
    connection for the handler), or an HTTP error response to reject so
    the socket never opens.
    """
    from zylch.rpc.firebase_auth import FirebaseAuthError

    try:
        claims, token = await asyncio.to_thread(_authenticate_blocking, request)
    except FirebaseAuthError as e:
        logger.warning(f"[ws] handshake rejected (401): {e}")
        return connection.respond(HTTPStatus.UNAUTHORIZED, f"unauthorized: {e}\n")
    except PermissionError as e:
        logger.warning(f"[ws] handshake forbidden (403): {e}")
        return connection.respond(HTTPStatus.FORBIDDEN, f"forbidden: {e}\n")
    except Exception as e:
        logger.exception("[ws] handshake auth crashed")
        return connection.respond(HTTPStatus.INTERNAL_SERVER_ERROR, f"auth error: {e}\n")

    connection._fb_claims = claims  # type: ignore[attr-defined]
    connection._fb_token = token  # type: ignore[attr-defined]
    return None


async def _handle_connection(connection) -> None:
    """Per-connection loop: install the session, then dispatch frames.

    Each inbound frame is dispatched as its own task (matching the stdio
    server's per-line concurrency) so a long method like ``tasks.solve``
    or ``update.run`` does not block other requests on the same socket.
    All outbound frames go through ``out_q`` + a single writer task.
    """
    claims: Optional[Dict[str, Any]] = getattr(connection, "_fb_claims", None)
    token: Optional[str] = getattr(connection, "_fb_token", None)
    if not claims or not token:
        # _process_request should have gated this; be defensive.
        await connection.close(WS_CLOSE_AUTH_EXPIRED, "unauthenticated")
        return

    uid = claims.get("sub", "")
    email = claims.get("email")
    expires_at_ms = int(claims["exp"]) * 1000
    # Reconstruct the in-memory session from the VERIFIED token — better
    # than stdio, where the renderer's pushed values are trusted as-is.
    set_session(uid=uid, email=email, id_token=token, expires_at_ms=expires_at_ms)
    logger.info(f"[ws] client connected uid={uid} email={email!r}")

    loop = asyncio.get_running_loop()
    out_q: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
    inflight: set[asyncio.Task] = set()

    def notify(method: str, params: Dict[str, Any]) -> None:
        # May be called from a worker thread (e.g. update.progress runs in
        # asyncio.to_thread). Hand the send off to the loop thread.
        msg = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params},
            ensure_ascii=False,
            default=str,
        )
        loop.call_soon_threadsafe(out_q.put_nowait, msg)

    async def _writer() -> None:
        while True:
            msg = await out_q.get()
            if msg is None:
                return
            try:
                await connection.send(msg)
            except Exception as e:
                logger.debug(f"[ws] send failed (client gone?): {e}")
                return

    async def _handle_one(raw: str) -> None:
        try:
            resp = await dispatch_raw(raw, notify)
        except Exception:
            logger.exception("[ws] dispatch crashed")
            return
        if resp is not None:
            out_q.put_nowait(json.dumps(resp, ensure_ascii=False, default=str))

    writer_task = asyncio.create_task(_writer())
    try:
        async for raw in connection:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", "replace")
            # Enforce token expiry lazily on each inbound frame: if the
            # cached session is gone or expired, close 4401 so the client
            # refreshes and reconnects.
            sess = get_session()
            if sess is None or sess.is_expired():
                logger.info(f"[ws] closing uid={uid}: firebase token expired")
                await connection.close(WS_CLOSE_AUTH_EXPIRED, "firebase token expired")
                break
            task = asyncio.create_task(_handle_one(raw))
            inflight.add(task)
            task.add_done_callback(inflight.discard)
    except Exception as e:
        logger.warning(f"[ws] connection error uid={uid}: {type(e).__name__}: {e}")
    finally:
        # Drain in-flight handlers, then stop the writer.
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)
        out_q.put_nowait(None)
        await asyncio.gather(writer_task, return_exceptions=True)
        logger.info(f"[ws] client disconnected uid={uid}")


def _warmup() -> None:
    """Mirror the stdio server's warmup: force Settings + Storage init so
    the first real RPC doesn't pay the lazy cost. Best-effort."""
    try:
        from zylch.config import settings as _settings
        from zylch.storage.storage import Storage

        _ = _settings.email_address
        Storage.get_instance()
        logger.info("[ws] warmup done (Storage + Settings)")
    except Exception as e:
        logger.warning(f"[ws] warmup failed (non-fatal): {e}")


def _auto_update_enabled() -> bool:
    """Headless auto-update on/off (AUTO_UPDATE_ENABLED, default yes)."""
    val = (os.environ.get("AUTO_UPDATE_ENABLED") or "y").strip().lower()
    return val not in ("n", "no", "false", "0", "off", "")


def _auto_update_interval_seconds() -> int:
    """Interval from AUTO_UPDATE_INTERVAL_MINUTES (default 30, clamped 5..360)."""
    raw = (os.environ.get("AUTO_UPDATE_INTERVAL_MINUTES") or "30").strip()
    try:
        minutes = int(raw)
    except ValueError:
        minutes = 30
    minutes = max(5, min(360, minutes))
    return minutes * 60


async def _auto_update_loop() -> None:
    """Headless auto-update — the renderer's ``useAutoUpdate``, server-side.

    A ``serve`` daemon with NO GUI attached still syncs mail, builds
    memory and detects tasks every ``AUTO_UPDATE_INTERVAL_MINUTES``, so
    replies and new leads land without anyone opening the desktop app.
    Runs the same pipeline as ``update.run`` / ``zylch update``.

    Single sequential loop ⇒ its own ticks never overlap. Per-tick
    failures are logged (never swallowed) and the loop keeps running. The
    memory/task stages need an LLM credential (a BYOK key in the profile
    ``.env`` or a live Firebase session for proxy mode); the IMAP sync
    stage runs regardless, so mail still lands headless.
    """
    from zylch.rpc.methods import update_run

    def _notify(method: str, params: Dict[str, Any]) -> None:
        if method == "update.progress":
            logger.debug(f"[auto-update] {params.get('pct')}% {params.get('message')}")

    await asyncio.sleep(60)  # let warmup + any first handshake settle
    while True:
        try:
            if not _auto_update_enabled():
                logger.info("[auto-update] disabled via AUTO_UPDATE_ENABLED — skipping tick")
            else:
                logger.info("[auto-update] tick — running pipeline headless")
                result = await update_run({}, _notify)
                if isinstance(result, dict) and result.get("success"):
                    logger.info("[auto-update] tick OK")
                else:
                    errs = result.get("errors") if isinstance(result, dict) else result
                    logger.warning(f"[auto-update] tick finished with errors: {errs}")
        except asyncio.CancelledError:
            logger.info("[auto-update] cancelled — exiting loop")
            raise
        except Exception:
            logger.exception("[auto-update] tick crashed — will retry next interval")
        await asyncio.sleep(_auto_update_interval_seconds())


def _own_zombie_pids() -> set[int]:
    """PIDs of our own direct children currently in zombie (``Z``) state.

    Reads ``/proc`` rather than calling ``waitpid`` — it OBSERVES, it does
    not reap. The comm field in ``/proc/<pid>/stat`` can contain spaces and
    parentheses (``pid (comm) state ppid ...``), so we parse from the right
    of the last ``)``.
    """
    me = str(os.getpid())
    zombies: set[int] = set()
    try:
        names = os.listdir("/proc")
    except OSError:
        return zombies
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", encoding="ascii", errors="replace") as fh:
                data = fh.read()
        except OSError:
            continue  # process vanished or unreadable — ignore
        rparen = data.rfind(")")
        if rparen == -1:
            continue
        rest = data[rparen + 2 :].split()
        if len(rest) < 2:
            continue
        state, ppid = rest[0], rest[1]
        if state == "Z" and ppid == me:
            try:
                zombies.add(int(name))
            except ValueError:
                continue
    return zombies


async def _reap_orphans_loop(interval: float = 30.0) -> None:
    """Reap leaked zombie children that nothing else will ``wait()`` on.

    The whatsmeow Go runtime — a c-shared library loaded into this Python
    process via ``ctypes`` by ``neonize`` — occasionally ``fork``+``exec``s
    a ``/bin/sh`` helper and, running as a guest library rather than the
    main program, never ``wait()``s it. The child is a DIRECT child of this
    process, and Python's default ``SIGCHLD`` disposition is ``SIG_DFL`` (no
    kernel auto-reap), so it lingers as ``[sh] <defunct>`` indefinitely.
    Observed in production on the per-uid ``serve`` daemons.

    We can't make the Go side ``wait()``, but we are the parent, so we can.
    The hazard is our OWN ``subprocess.run`` children (the ``run_python`` /
    ``tasks.solve`` tool execution): if we ``waitpid()`` one of those before
    the ``subprocess`` module does, it gets ``ECHILD`` and reports
    ``returncode == 0``, masking a real failure. To stay clear of that race
    we ONLY reap a zombie that has survived a FULL ``interval``: the
    ``subprocess`` module reaps its own children within microseconds of
    exit, so anything still defunct a whole interval later is genuinely
    orphaned. Leaked Go shells sit forever and are always caught (within two
    intervals).
    """
    seen: set[int] = set()
    while True:
        try:
            await asyncio.sleep(interval)
            current = _own_zombie_pids()
            # Defunct for >= one full interval ⇒ not a live subprocess child.
            aged = current & seen
            for pid in aged:
                try:
                    reaped, status = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    continue  # already reaped elsewhere
                except OSError as e:
                    logger.debug(f"[reaper] waitpid({pid}) failed: {e}")
                    continue
                if reaped:
                    logger.info(f"[reaper] reaped leaked zombie pid={pid} (status={status})")
            # Carry forward only the young zombies so they age into the next
            # pass; the aged ones we just reaped are gone.
            seen = current - aged
        except asyncio.CancelledError:
            logger.info("[reaper] cancelled — exiting loop")
            raise
        except Exception:
            logger.exception("[reaper] tick crashed — continuing")


async def serve_ws(
    host: Optional[str] = None,
    port: Optional[int] = None,
    warmup: bool = True,
    unix_path: Optional[str] = None,
) -> None:
    """Run the WebSocket JSON-RPC server until cancelled.

    Listens on a TCP ``host:port`` OR a Unix domain socket (``unix_path``).
    The Unix-socket mode is for the multi-tenant VPS deploy: each profile's
    daemon owns a socket (named by uid) and Caddy reverse-proxies
    ``/ws/<uid>`` to it — no TCP port juggling across users. The
    ``Authorization: Bearer`` gate is identical (Caddy forwards the header
    through to the upstream).

    ``warmup=False`` is used by tests that only exercise the transport +
    auth path (no DB needed).
    """
    from websockets.asyncio.server import serve, unix_serve

    if warmup:
        _warmup()

    # Generous frame size — a chat.send with embedded email bodies can be
    # large, same rationale as the stdio reader's 16 MiB limit.
    if unix_path:
        # Remove a stale socket left by a SIGKILLed predecessor: asyncio's
        # create_unix_server (py3.12) does NOT pre-unlink, so a leftover file
        # makes bind() fail with EADDRINUSE and the daemon can't respawn. The
        # profile fcntl lock (cli.profiles.acquire_lock, held before we reach
        # here) guarantees we're the only instance, so a residual socket of
        # this name is ours to remove.
        if os.path.exists(unix_path):
            logger.info(f"[ws] removing stale socket {unix_path}")
            os.unlink(unix_path)
        logger.info(f"[ws] serving JSON-RPC on unix:{unix_path}")
        server_cm = unix_serve(
            _handle_connection,
            unix_path,
            process_request=_process_request,
            max_size=16 * 1024 * 1024,
        )
    else:
        logger.info(f"[ws] serving JSON-RPC on ws://{host}:{port}")
        server_cm = serve(
            _handle_connection,
            host,
            port,
            process_request=_process_request,
            max_size=16 * 1024 * 1024,
        )

    async with server_cm as server:
        if unix_path:
            # Guarantee the socket is group-writable so the reverse-proxy
            # (Caddy, group `caddy`, inherited via the setgid /run/mrcalld dir)
            # can connect — independent of the process umask / library default.
            os.chmod(unix_path, 0o660)
            logger.info(f"[ws] chmod 0o660 {unix_path} (group-writable for the reverse-proxy)")
        # Headless auto-update: keep syncing with no GUI attached.
        auto_task = asyncio.create_task(_auto_update_loop())
        logger.info(
            f"[ws] headless auto-update started "
            f"(every {_auto_update_interval_seconds() // 60} min, "
            f"enabled={_auto_update_enabled()})"
        )
        # Reap zombie children leaked by the whatsmeow Go c-shared lib.
        reaper_task = asyncio.create_task(_reap_orphans_loop())
        logger.info("[ws] zombie reaper started (reaps leaked c-shared children)")
        try:
            await server.serve_forever()
        finally:
            auto_task.cancel()
            reaper_task.cancel()
            await asyncio.gather(auto_task, reaper_task, return_exceptions=True)
