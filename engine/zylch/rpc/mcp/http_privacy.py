import logging
from typing import Any

from aiohttp import web
from aiohttp.web_protocol import RequestHandler
from aiohttp.web_server import Server


class _SafeLogger(logging.Logger):
    def _log(
        self,
        level: int,
        msg: Any,
        args: Any,
        exc_info: Any = None,
        extra: Any = None,
        stack_info: bool = False,
        stacklevel: int = 1,
    ) -> None:
        super()._log(level, "MCP HTTP protocol event", (), stacklevel=stacklevel)


LOGGER = _SafeLogger("mrcall.mcp.http")
LOGGER.parent = logging.getLogger()


class _PrivateHandler(RequestHandler):
    def handle_error(
        self,
        request: web.BaseRequest,
        status: int = 500,
        exc: BaseException | None = None,
        message: str | None = None,
    ) -> web.StreamResponse:
        if request.writer.output_size > 0:
            raise ConnectionError("MCP HTTP response unavailable")
        response = web.json_response(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid MCP HTTP request"},
            },
            status=status,
        )
        response.force_close()
        return response


class _PrivateServer(Server):
    def __call__(self) -> RequestHandler:
        return _PrivateHandler(self, loop=self._loop, **self._kwargs)


class PrivateRunner(web.AppRunner):
    async def _make_server(self) -> Server:
        server = await super()._make_server()
        return _PrivateServer(
            server.request_handler,
            request_factory=server.request_factory,
            loop=server._loop,
            handler_cancellation=server.handler_cancellation,
            **server._kwargs,
        )
