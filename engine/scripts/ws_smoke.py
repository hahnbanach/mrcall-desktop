"""Live smoke client for `zylch serve --ws`.

Usage:
    python scripts/ws_smoke.py ws://127.0.0.1:5174 <firebase-id-token> [method]

Connects with the bearer token, calls a method (default account.who_am_i),
prints the reply. Get a real ID token from the running desktop app's
renderer DevTools console:

    await firebase.auth().currentUser.getIdToken()

(or from wherever the renderer keeps it). The token's uid must equal the
served profile's OWNER_ID.
"""

import asyncio
import json
import sys

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus


async def main(url: str, token: str, method: str) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with connect(url, additional_headers=headers) as ws:
            req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}
            await ws.send(json.dumps(req))
            # Drain any notifications until our response (id == 1) arrives.
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == 1:
                    print(json.dumps(msg, indent=2, ensure_ascii=False))
                    return 0
                print("notification:", raw, file=sys.stderr)
    except InvalidStatus as e:
        # Handshake rejected by the auth gate — print a clean hint instead
        # of a stack trace, since this is the common "wrong token" case.
        status = getattr(getattr(e, "response", None), "status_code", "?")
        if status == 401:
            print(
                "rejected: HTTP 401 Unauthorized — the token is not a valid "
                "Firebase ID token.\n"
                "  An ID token is a JWT: it starts with 'eyJ' and has two dots "
                "(header.payload.signature).\n"
                "  'AIza…' is the Firebase Web API key, NOT a token.",
                file=sys.stderr,
            )
        elif status == 403:
            print(
                "rejected: HTTP 403 Forbidden — token is valid but its uid does "
                "not own the served profile (OWNER_ID mismatch).",
                file=sys.stderr,
            )
        else:
            print(f"rejected: HTTP {status}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "usage: ws_smoke.py <ws-url> <firebase-id-token> [method]",
            file=sys.stderr,
        )
        sys.exit(2)
    _url, _token = sys.argv[1], sys.argv[2]
    _method = sys.argv[3] if len(sys.argv) > 3 else "account.who_am_i"
    sys.exit(asyncio.run(main(_url, _token, _method)))
