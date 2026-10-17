"""Opt-in Unix-socket MCP lifecycle inside the Linux profile daemon."""

import asyncio
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn


class RuntimeRefused(ValueError):
    """Safe runtime refusal without configuration or credentials."""


class _ProfileServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # The existing profile daemon owns process signals.
        yield


class UnixMCPListener:
    def __init__(self, app, socket_path, *, startup_timeout=10, shutdown_timeout=5):
        self.app = app
        self.path = Path(socket_path)
        self.startup_timeout = startup_timeout
        self.shutdown_timeout = shutdown_timeout
        self.server = None
        self.task = None
        self.socket_identity = None

    async def __aenter__(self):
        if sys.platform != "linux" or not self.path.is_absolute():
            raise RuntimeRefused("Linux Unix listener required")
        try:
            parent = self.path.parent.lstat()
            if (
                self.path.parent.resolve() != self.path.parent
                or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != os.getuid()
                or parent.st_mode & 0o007
                or os.path.lexists(self.path)
            ):
                raise RuntimeRefused("Private unused operator socket required")
            self.server = _ProfileServer(
                uvicorn.Config(
                    self.app,
                    uds=str(self.path),
                    lifespan="on",
                    access_log=False,
                    log_config=None,
                    log_level="critical",
                    timeout_graceful_shutdown=self.shutdown_timeout,
                )
            )

            async def serve_owned():
                try:
                    await self.server.serve()
                except SystemExit:
                    raise RuntimeRefused("Operator listener startup refused") from None

            self.task = asyncio.create_task(serve_owned(), name="operator-mcp-listener")
            deadline = asyncio.get_running_loop().time() + self.startup_timeout
            while not self.server.started:
                if self.task.done() or asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeRefused("Operator listener startup refused")
                await asyncio.sleep(0.01)
            metadata = self.path.lstat()
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise RuntimeRefused("Operator socket owner refused")
            self.socket_identity = (metadata.st_dev, metadata.st_ino)
            os.chmod(self.path, 0o660)
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def serve_with(self, foreground):
        """A failed MCP listener retires the shared daemon lifecycle."""
        task = asyncio.create_task(foreground)
        try:
            done, _ = await asyncio.wait({task, self.task}, return_when=asyncio.FIRST_COMPLETED)
            if self.task in done:
                raise RuntimeRefused("Operator listener stopped")
            return await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def __aexit__(self, exc_type, exc, traceback):
        if self.server is not None:
            self.server.should_exit = True
        if self.task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self.task), self.shutdown_timeout + 1)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            except Exception:
                pass
        if self.socket_identity:
            try:
                value = self.path.lstat()
                if (
                    stat.S_ISSOCK(value.st_mode)
                    and (value.st_dev, value.st_ino) == self.socket_identity
                ):
                    self.path.unlink()
            except FileNotFoundError:
                pass


def profile_listener(config_path):
    from .auth import GrantVerifier
    from .policy import load_profile_config, profile_binding
    from .read_port import NativeReadPort
    from .server import create_server

    if sys.platform != "linux":
        raise RuntimeRefused("Operator daemon requires Linux")
    config = load_profile_config(config_path)
    if os.environ.get("OWNER_ID") != config["profile_uid"]:
        raise RuntimeRefused("Operator profile owner refused")

    def snapshot():
        current = load_profile_config(config_path)
        if current != config:
            raise RuntimeRefused("Operator configuration changed; restart required")
        return profile_binding(current)

    verifier = GrantVerifier(
        issuer=config["issuer"],
        introspection_url=config["issuer"] + "/introspect",
        client_registry_url=config["issuer"] + "/clients/approved",
        service_client_id=config["service_client_id"],
        service_client_secret=config["service_secret"],
        resource=config["resource"],
        profile_uid=config["profile_uid"],
        company_ref=config["company_ref"],
    )
    server = create_server(
        verifier,
        NativeReadPort(snapshot),
        path=urlsplit(config["resource"]).path,
        allowed_hosts=[urlsplit(config["resource"]).netloc],
    )

    class BoundListener(UnixMCPListener):
        async def __aenter__(self):
            snapshot()
            return await super().__aenter__()

    return BoundListener(server.streamable_http_app(), config["socket_path"])
