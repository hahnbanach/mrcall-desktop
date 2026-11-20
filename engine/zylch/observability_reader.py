"""Independent owner-scoped log reader for a loopback TLS proxy upstream."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from zylch.observability import EventStore


class ReaderServer(HTTPServer):
    """Serve fixed selected-owner metadata without starting the engine."""

    def __init__(self, address: tuple[str, int], store: EventStore, token: str):
        if address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Reader requires a loopback TLS proxy")
        if not isinstance(token, str) or len(token) < 32 or len(token) > 256:
            raise ValueError("Reader credential unavailable")
        self.store = store
        self.token = token
        self.last_maintenance = 0.0
        self.maintenance_ok = False
        super().__init__(address, ReaderHandler)

    def service_actions(self) -> None:
        """Run explicit service maintenance independently of read requests."""
        from .observability_retention import maintain_profile

        if time.monotonic() - self.last_maintenance < 60:
            return
        self.last_maintenance = time.monotonic()
        try:
            self.maintenance_ok = (
                maintain_profile(self.store.root.parent, self.store.owner_uid)["status"]
                == "observed"
            )
        except Exception:
            self.maintenance_ok = False

    def coverage(self, result: dict) -> dict:
        """Expose maintenance failure without treating a quiet process as healthy."""
        if not self.maintenance_ok:
            result["status"] = "degraded"
            result.setdefault("gaps", []).append({"reason": "unreadable", "count": 1})
        return result


class ReaderHandler(BaseHTTPRequestHandler):
    """Handle bounded, authenticated read-only requests."""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _reply(self, code: int, value: dict) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        if len(body) > 256 * 1024:
            code, body = 503, b'{"error":"diagnostic_response_limit"}'
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self) -> None:
        if len(self.path) > 1024:
            self._reply(400, {"error": "invalid_query"})
            return
        supplied = self.headers.get("Authorization", "")
        if len(supplied) > 300 or not hmac.compare_digest(
            supplied.encode(), ("Bearer " + self.server.token).encode()
        ):
            self._reply(401, {"error": "authentication_required"})
            return
        route = urlsplit(self.path)
        try:
            query = parse_qs(route.query, keep_blank_values=True, max_num_fields=4)
        except ValueError:
            self._reply(400, {"error": "invalid_query"})
            return
        if route.path not in {"/locations", "/health", "/events"}:
            self._reply(404, {"error": "unknown_route"})
            return
        if (
            set(query) - {"cursor", "trace_id", "limit", "recent"}
            or any(len(values) != 1 for values in query.values())
            or (query and route.path != "/events")
        ):
            self._reply(400, {"error": "invalid_query"})
            return
        try:
            if route.path == "/locations":
                result = self.server.store.locations()
                result["coverage"] = self.server.coverage(result["coverage"])
            elif route.path == "/health":
                result = self.server.coverage(self.server.store.health())
            elif "recent" in query:
                if query["recent"][0] not in {"true", "false"} or (
                    query["recent"][0] == "true" and ("cursor" in query or "trace_id" in query)
                ):
                    raise ValueError("Invalid recent query")
                if query["recent"][0] == "true":
                    result = self.server.store.recent(limit=int(query.get("limit", ["100"])[0]))
                else:
                    result = self.server.store.events(
                        limit=int(query.get("limit", ["100"])[0]),
                        cursor=query.get("cursor", [None])[0],
                        trace_id=query.get("trace_id", [None])[0],
                    )
            else:
                result = self.server.store.events(
                    cursor=query.get("cursor", [None])[0],
                    trace_id=query.get("trace_id", [None])[0],
                    limit=int(query.get("limit", ["100"])[0]),
                )
            if route.path == "/events":
                result["coverage"] = self.server.coverage(result["coverage"])
            self._reply(200, result)
        except (TypeError, ValueError):
            self._reply(400, {"error": "invalid_query"})
        except OSError:
            self._reply(503, {"error": "diagnostic_store_unavailable"})

    def do_POST(self) -> None:
        self._reply(405, {"error": "read_only"})


def main() -> int:
    """Run the reader with deployment-owned fixed profile and credential."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--owner-uid", required=True)
    parser.add_argument("--token-env", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", args.token_env):
        parser.error("Invalid credential reference")
    directory = args.profile_dir.absolute()
    if directory.name != args.owner_uid:
        parser.error("Profile identity mismatch")
    token = os.environ.get(args.token_env, "")
    try:
        server = ReaderServer(
            ("127.0.0.1", args.port),
            EventStore(directory / "observability", args.owner_uid, component="engine"),
            token,
        )
    except (OSError, ValueError):
        parser.error("Reader configuration unavailable")
    print(json.dumps({"port": server.server_port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
