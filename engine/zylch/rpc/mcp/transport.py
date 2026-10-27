import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable

from aiohttp import web

from zylch.auth import set_session
from zylch.qonto.logging import private_scope
from zylch.rpc.firebase_auth import verify_firebase_id_token
from zylch.workflows.errors import MESSAGES, WorkflowError

from . import tools
from .elicitation import start_legal
from .sessions import Session, request_key
from .http_privacy import LOGGER, PrivateRunner

PROTOCOL = "2025-11-25"
STATE = web.AppKey("mcp_state", dict)


def error(
    request_id: str | int | None = None, code: int = -32600, message: str = "Invalid MCP request"
) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def reply(request_id: str | int, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def authenticate(request: web.Request) -> str:
    raw = request.headers.get("Authorization", "")
    parts = raw.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) > 16384:
        raise PermissionError
    token = parts[1]
    claims = await asyncio.to_thread(verify_firebase_id_token, token)
    owner = os.environ.get("OWNER_ID")
    if not owner or claims["sub"] != owner:
        raise PermissionError
    set_session(owner, claims.get("email"), token, int(claims["exp"] * 1000))
    return owner


def boundary(request: web.Request, state: dict[str, Any]) -> None:
    host = request.headers.get("Host", "")
    if host not in state["allowed_hosts"]:
        raise PermissionError
    origin = request.headers.get("Origin")
    if origin is not None and origin not in state["allowed_origins"]:
        raise PermissionError
    if request.query_string:
        raise ValueError


def get_session(request: web.Request, state: dict[str, Any], uid: str) -> Session | None:
    session_id = request.headers.get("Mcp-Session-Id", "")
    session = state["sessions"].get(session_id)
    if session is None or session.uid != uid or session.expires_at <= time.time():
        if session is not None and session.expires_at <= time.time():
            session.close()
            state["sessions"].pop(session_id, None)
        return None
    return session


@web.middleware
async def protected(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    with private_scope():
        try:
            uid = await authenticate(request)
        except Exception:
            return web.json_response(
                error(code=-32011, message="Authentication refused"), status=401
            )
        request["uid"] = uid
        try:
            boundary(request, request.app[STATE])
        except PermissionError:
            return web.json_response(error(message="HTTP origin or host refused"), status=403)
        except ValueError:
            return web.json_response(error(), status=400)
        try:
            return await handler(request)
        except web.HTTPRequestEntityTooLarge:
            return web.json_response(error(message="Request limit exceeded"), status=413)
        except asyncio.CancelledError:
            raise
        except Exception:
            return web.json_response(
                error(code=-32603, message="Private MCP operation failed"), status=400
            )


async def execute_call(
    message: dict[str, Any], session: Session, queue: asyncio.Queue, state: dict[str, Any]
) -> dict[str, Any]:
    request_id = message["id"]
    try:
        params = message.get("params", {})
        if not isinstance(params, dict) or set(params) - {"name", "arguments", "_meta"}:
            raise WorkflowError("invalid_input")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str):
            raise WorkflowError("invalid_input")

        async def legal(args: dict[str, Any]) -> dict[str, Any]:
            return await start_legal(args, session, queue, state)

        value = await tools.call(name, arguments, session, legal, state)
        return reply(request_id, value)
    except WorkflowError as exc:
        return reply(
            request_id,
            tools.result(
                {"schema_version": 1, "outcome": exc.outcome, "message": MESSAGES[exc.outcome]},
                failed=True,
            ),
        )
    except asyncio.CancelledError:
        return error(request_id, -32800, "Request cancelled")
    except Exception:
        return error(request_id, -32603, "Private MCP operation failed")


async def document_response(request: web.Request, task: asyncio.Task) -> web.Response:
    async def disconnected() -> None:
        while not task.done():
            transport = request.transport
            if transport is None or transport.is_closing():
                task.cancel()
                return
            await asyncio.sleep(0.05)

    watcher = asyncio.create_task(disconnected())
    try:
        return web.json_response(await asyncio.shield(task))
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def document_task(
    request: web.Request,
    message: dict[str, Any],
    session: Session,
    queue: asyncio.Queue,
    state: dict[str, Any],
) -> asyncio.Task:
    from zylch.workflows.document_async import REQUEST_ALIVE

    def connected() -> bool:
        transport = request.transport
        return transport is not None and not transport.is_closing()

    token = REQUEST_ALIVE.set(connected)
    try:
        return asyncio.create_task(execute_call(message, session, queue, state))
    finally:
        REQUEST_ALIVE.reset(token)


async def stream_call(
    request: web.Request, message: dict[str, Any], session: Session, state: dict[str, Any]
) -> web.StreamResponse:
    key = request_key(message["id"])
    if not isinstance(message.get("params"), dict) or len(session.requests) >= 32:
        return web.json_response(error(message["id"]), status=400)
    if key in session.requests:
        return web.json_response(
            error(message["id"], message="Request is already active"), status=400
        )
    queue = asyncio.Queue(maxsize=4)
    document = message.get("params", {}).get("name") in {
        "documents_upload_chunk",
        "documents_finish_upload",
    }
    task = (
        document_task(request, message, session, queue, state)
        if document
        else asyncio.create_task(execute_call(message, session, queue, state))
    )
    session.requests[key] = task

    def completed(done: asyncio.Task) -> None:
        session.requests.pop(key, None)
        queue.put_nowait(
            error(message["id"], -32800, "Request cancelled") if done.cancelled() else done.result()
        )

    task.add_done_callback(completed)
    if document:
        return await document_response(request, task)
    if message.get("params", {}).get("name") != "cs_legal_research":
        return web.json_response(await asyncio.shield(task))
    response = web.StreamResponse(
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
    )
    await response.prepare(request)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), 15)
            except asyncio.TimeoutError:
                await response.write(b": keepalive\n\n")
                continue
            await response.write(
                (
                    "event: message\ndata: "
                    + json.dumps(event, ensure_ascii=False, allow_nan=False)
                    + "\n\n"
                ).encode()
            )
            if "method" not in event:
                break
        await response.write_eof()
    except (ConnectionError, asyncio.CancelledError):
        pass
    return response


async def post(request: web.Request) -> web.StreamResponse:
    state = request.app[STATE]
    accept = {
        part.split(";", 1)[0].strip() for part in request.headers.get("Accept", "").split(",")
    }
    if not {"application/json", "text/event-stream"}.issubset(accept):
        return web.json_response(error(message="MCP response media types required"), status=406)
    if request.content_type != "application/json":
        return web.json_response(error(), status=415)
    try:
        message = json.loads(
            await request.read(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
        )
    except (ValueError, UnicodeError):
        return web.json_response(error(code=-32700, message="Invalid JSON"), status=400)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return web.json_response(error(), status=400)
    uid = request["uid"]
    if message.get("method") == "initialize":
        return initialize(request, message, state, uid)
    if request.headers.get("MCP-Protocol-Version") != PROTOCOL:
        return web.json_response(error(message="Unsupported protocol version"), status=400)
    session = get_session(request, state, uid)
    if session is None:
        return web.json_response(error(message="MCP session unavailable"), status=404)
    if "method" not in message:
        return elicitation_response(message, session)
    method = message["method"]
    if "id" not in message:
        return await notification(message, session)
    request_key(message["id"])
    if set(message) - {"jsonrpc", "id", "method", "params"}:
        return web.json_response(error(message["id"]), status=400)
    if not session.initialized:
        return web.json_response(
            error(message["id"], message="Initialization required"), status=400
        )
    if method == "ping":
        return web.json_response(reply(message["id"], {}))
    if method == "tools/list":
        params = message.get("params", {})
        if (
            not isinstance(params, dict)
            or set(params) - {"cursor", "_meta"}
            or params.get("cursor") is not None
            or ("_meta" in params and not isinstance(params["_meta"], dict))
        ):
            return web.json_response(error(message["id"]), status=400)
        return web.json_response(reply(message["id"], {"tools": tools.listing()}))
    if method == "tools/call":
        return await stream_call(request, message, session, state)
    return web.json_response(error(message["id"], -32601, "MCP method unavailable"), status=400)


def initialize(
    request: web.Request, message: dict[str, Any], state: dict[str, Any], uid: str
) -> web.Response:
    request_key(message.get("id"))
    params = message.get("params")
    if (
        request.headers.get("Mcp-Session-Id")
        or set(message) - {"jsonrpc", "id", "method", "params"}
        or not isinstance(params, dict)
        or set(params) - {"protocolVersion", "capabilities", "clientInfo", "_meta"}
        or not isinstance(params.get("protocolVersion"), str)
        or not isinstance(params.get("capabilities"), dict)
        or not isinstance(params.get("clientInfo"), dict)
        or not isinstance(params["clientInfo"].get("name"), str)
        or not 1 <= len(params["clientInfo"]["name"]) <= 128
        or not isinstance(params["clientInfo"].get("version"), str)
        or not 1 <= len(params["clientInfo"]["version"]) <= 128
        or not 1 <= len(params["protocolVersion"]) <= 32
    ):
        return web.json_response(error(message["id"]), status=400)
    for key, session in list(state["sessions"].items()):
        if session.expires_at <= time.time():
            session.close()
            state["sessions"].pop(key)
    if len(state["sessions"]) >= 128:
        return web.json_response(
            error(message["id"], message="MCP session limit reached"), status=429
        )
    capability = params["capabilities"].get("elicitation")
    elicitation = isinstance(capability, dict) and (
        not capability or isinstance(capability.get("form"), dict)
    )
    session = Session(uid, elicitation)
    state["sessions"][session.id] = session
    result = {
        "protocolVersion": PROTOCOL,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "mrcall-engine-workflows", "version": "1"},
    }
    return web.json_response(reply(message["id"], result), headers={"Mcp-Session-Id": session.id})


def elicitation_response(message: dict[str, Any], session: Session) -> web.Response:
    request_key(message.get("id"))
    if set(message) - {"jsonrpc", "id", "result", "error"} or ("result" in message) == (
        "error" in message
    ):
        return web.json_response(error(), status=400)
    future = session.pending.get(message.get("id"))
    if future is None or future.done():
        return web.json_response(error(message="Unexpected elicitation response"), status=400)
    future.set_result(message.get("result", {"action": "cancel"}))
    return web.Response(status=202)


async def notification(message: dict[str, Any], session: Session) -> web.Response:
    if set(message) - {"jsonrpc", "method", "params"}:
        return web.json_response(error(), status=400)
    if message["method"] == "notifications/initialized":
        if session.initialized or message.get("params", {}) != {}:
            return web.json_response(error(), status=400)
        session.initialized = True
    elif message["method"] == "notifications/cancelled":
        params = message.get("params", {})
        if not isinstance(params, dict) or set(params) - {"requestId", "reason"}:
            return web.json_response(error(), status=400)
        key = request_key(params.get("requestId"))
        task = session.requests.get(key)
        if task is not None:
            task.cancel()
    else:
        return web.json_response(error(message="MCP notification unavailable"), status=400)
    return web.Response(status=202)


async def other(request: web.Request) -> web.Response:
    state = request.app[STATE]
    if request.headers.get("MCP-Protocol-Version") != PROTOCOL:
        return web.json_response(error(message="Unsupported protocol version"), status=400)
    session = get_session(request, state, request["uid"])
    if session is None:
        return web.json_response(error(message="MCP session unavailable"), status=404)
    if request.method == "DELETE":
        session.close()
        state["sessions"].pop(session.id, None)
        return web.Response(status=200)
    return web.json_response(
        error(message="Standalone event stream unavailable"),
        status=405,
        headers={"Allow": "POST, DELETE"},
    )


def create_app(
    *,
    allowed_hosts: Iterable[str] | None = None,
    allowed_origins: Iterable[str] = (),
    trust_file: str | Path | None = None,
    hosted: bool = False,
) -> web.Application:
    app = web.Application(client_max_size=1048576, middlewares=[protected])
    app[STATE] = {
        "sessions": {},
        "allowed_hosts": set(allowed_hosts or ("localhost", "127.0.0.1", "[::1]")),
        "allowed_origins": set(allowed_origins),
        "trust_file": trust_file,
        "hosted": hosted,
    }
    app.router.add_post("/mcp", post)
    app.router.add_route("GET", "/mcp", other)
    app.router.add_route("DELETE", "/mcp", other)

    async def cleanup(application: web.Application) -> None:
        sessions = list(application[STATE]["sessions"].values())
        tasks = [task for session in sessions for task in session.requests.values()]
        for session in sessions:
            session.close()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app.on_cleanup.append(cleanup)
    return app


@asynccontextmanager
async def listener(
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    unix_path: str | None = None,
    allowed_hosts: Iterable[str] | None = None,
    allowed_origins: Iterable[str] = (),
    trust_file: str | Path | None = None,
    hosted: bool = False,
) -> AsyncIterator[web.AppRunner]:
    if allowed_hosts is None and not unix_path:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Explicit MCP allowed hosts required")
        allowed_hosts = {
            f"{host}:{port}",
            f"localhost:{port}",
            f"127.0.0.1:{port}",
            f"[::1]:{port}",
        }
    app = create_app(
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        trust_file=trust_file,
        hosted=hosted,
    )
    runner = PrivateRunner(app, access_log=None, logger=LOGGER)
    await runner.setup()
    try:
        if unix_path:
            path = Path(unix_path)
            if path.exists() or path.is_symlink():
                raise ValueError("MCP socket path already exists")
            site = web.UnixSite(runner, str(path))
        else:
            site = web.TCPSite(runner, host, port)
        await site.start()
        if not unix_path and port == 0:
            assigned = site._server.sockets[0].getsockname()[1]
            app[STATE]["allowed_hosts"] = (
                {f"localhost:{assigned}", f"127.0.0.1:{assigned}", f"[::1]:{assigned}"}
                if allowed_hosts is None
                else {item.replace(":0", f":{assigned}") for item in app[STATE]["allowed_hosts"]}
            )
        if unix_path:
            os.chmod(unix_path, 0o660)
        yield runner
    finally:
        await runner.cleanup()
