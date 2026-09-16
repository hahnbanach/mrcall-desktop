"""Reserved service-only read transport; never enters owner JSON-RPC/session.

The endpoint is injected at trusted server startup and absent by default. Existing
Firebase verification authenticates a dedicated service UID; binding/contact grants
then constrain its reads. A successful login never grants general engine access.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
import json
import logging
import threading
import time

from zylch.services.capability_contract import CapabilityRequest
from zylch.services.scoped_capabilities import ScopedCapabilities

PATH = "/assistant-capabilities/v1"
PREFIX = "/assistant-capabilities"
logger = logging.getLogger(__name__)


class BoundedReads:
    """No pending executor queue: timed-out work retains its admission slot."""

    def __init__(self, workers: int = 2):
        if not 1 <= workers <= 2:
            raise ValueError("invalid read concurrency")
        self._slots = threading.BoundedSemaphore(workers)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="capability-read")

    async def run(self, function, timeout: float):
        if timeout <= 0 or not self._slots.acquire(blocking=False):
            raise TimeoutError("read capacity unavailable")
        try:
            future = self._pool.submit(function)
        except Exception:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        wrapped = asyncio.wrap_future(future)
        # A timed-out caller may never observe the worker's later exception.
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.wait_for(asyncio.shield(wrapped), timeout)

    def close(self):
        # Running IO cannot be killed by cancelling its Python Future. The pool
        # stays bounded; this does not promise cancellation of a provider request.
        self._pool.shutdown(wait=False, cancel_futures=True)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


class CapabilityEndpoint:
    def __init__(
        self,
        service: ScopedCapabilities,
        verify_token=None,
        now_ms=lambda: time.time_ns() // 1_000_000,
    ):
        if verify_token is None:
            from zylch.rpc.firebase_auth import verify_firebase_id_token

            verify_token = verify_firebase_id_token
        self.service = service
        self._verify_token = verify_token
        self._now_ms = now_ms
        self._reads = BoundedReads()
        self._replays = {}
        self._connections = 0
        self._connection_watchers = set()

    def _authenticate(self, request):
        authorization = request.headers.get("Authorization", "")
        if len(authorization) > 8192 or not authorization.startswith("Bearer "):
            raise PermissionError("capability authentication failed")
        claims = self._verify_token(authorization[7:])
        if claims.get("sub") != self.service.binding.service_uid:
            raise PermissionError("capability authentication failed")
        self._check_authority(claims)
        return {"sub": claims["sub"], "exp": claims["exp"]}

    def _check_authority(self, claims):
        if (
            claims.get("sub") != self.service.binding.service_uid
            or type(claims.get("exp")) is not int
            or claims["exp"] * 1000 <= self._now_ms()
        ):
            raise PermissionError("capability authentication expired")
        self.service.check_scope()

    async def handshake(self, connection, request):
        # Reserve before authentication can yield and before HTTP becomes a
        # WebSocket. A busy refusal must not create another upgraded socket.
        if self._connections >= 2:
            return connection.respond(HTTPStatus.TOO_MANY_REQUESTS, "capability busy\n")
        self._connections += 1
        watcher = asyncio.create_task(self._release_on_close(connection))
        self._connection_watchers.add(watcher)
        watcher.add_done_callback(self._connection_watchers.discard)
        try:
            claims = await self._reads.run(lambda: self._authenticate(request), 2.0)
            self._check_authority(claims)
        except asyncio.CancelledError:
            connection.transport.abort()
            raise
        except Exception:
            logger.debug("capability handshake denied")
            return connection.respond(HTTPStatus.UNAUTHORIZED, "capability denied\n")
        connection._capability_claims = claims
        # Set the scoped limit before any data frame; owner connections keep the
        # original 16 MiB limit. Tested on the actual websockets server protocol.
        connection.protocol.max_size = 4096
        return None

    async def _release_on_close(self, connection):
        # wait_closed tracks TCP termination, including failed upgrades whose
        # application handler never starts. Keep this bounded watcher independent
        # of handler cancellation and the peer's delayed CLOSE acknowledgement.
        await connection.wait_closed()
        self._connections -= 1

    async def handle(self, connection):
        try:
            async with asyncio.timeout(10):
                claims = getattr(connection, "_capability_claims", {})
                for _ in range(4):
                    raw = await connection.recv()
                    self._check_authority(claims)
                    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 4096:
                        raise ValueError("invalid capability frame")
                    payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
                    request = CapabilityRequest.parse(payload, self.service.binding, self._now_ms())
                    self._admit(request)
                    try:
                        outcome = await self._reads.run(
                            lambda: self.service.execute_authorized(request),
                            (request.expires_at_ms - self._now_ms()) / 1000,
                        )
                    except Exception:
                        outcome = {"status": "unavailable"}
                    # Reads can finish after a token expires or a profile joins
                    # another company. Do not rely on handshake-time authority.
                    self._check_authority(claims)
                    if self._now_ms() >= request.expires_at_ms:
                        raise TimeoutError("capability expired")
                    response = json.dumps(
                        {"request": request.public_dict(), "outcome": outcome},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    if len(response.encode("utf-8")) > 16384:
                        raise ValueError("capability output too large")
                    await connection.send(response)
        except Exception:
            # No raw error, identifier, bearer or provider object reaches logs/wire.
            logger.debug("capability connection ended or denied")
        finally:
            try:
                await connection.close(4403, "capability ended")
            except BaseException:
                # Cancellation while closing must not strand the admitted TCP
                # transport. Only its termination watcher releases admission.
                connection.transport.abort()
                raise

    def _admit(self, request):
        now = self._now_ms()
        self._replays = {key: expiry for key, expiry in self._replays.items() if expiry > now}
        key = (request.session_id, request.request_id)
        if key in self._replays or len(self._replays) >= 256:
            raise PermissionError("capability replay or capacity exceeded")
        self._replays[key] = request.expires_at_ms

    def close(self):
        self._reads.close()


def scoped_routes(endpoint, owner_handshake, owner_handler):
    """Used by BOTH existing TCP/Unix listeners; reserved paths never fall through."""

    async def handshake(connection, request):
        if request.path.startswith(PREFIX):
            if endpoint is None or request.path != PATH:
                return connection.respond(HTTPStatus.NOT_FOUND, "capability unavailable\n")
            return await endpoint.handshake(connection, request)
        result = await owner_handshake(connection, request)
        # A service UID must not inherit owner RPC if this process is rebound to
        # that UID while its old capability endpoint still exists.
        if (
            endpoint is not None
            and result is None
            and getattr(connection, "_fb_claims", {}).get("sub")
            == endpoint.service.binding.service_uid
        ):
            return connection.respond(HTTPStatus.FORBIDDEN, "capability identity is not an owner\n")
        return result

    async def handle(connection):
        if connection.request.path.startswith(PREFIX):
            if endpoint is not None and connection.request.path == PATH:
                await endpoint.handle(connection)
            else:
                await connection.close(4403, "capability unavailable")
        else:
            await owner_handler(connection)

    return handshake, handle
