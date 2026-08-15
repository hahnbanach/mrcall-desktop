"""provisiond — vendor-side profile provisioning + status service.

Runs on the desktop VPS, behind one static Caddy route, as its own
systemd unit (`zylch-provisiond.service`, singleton — one process for
the whole box, unlike the per-uid `zylch-server@<uid>` daemons). Stdlib
only: a `BaseHTTPRequestHandler` server bound to an `AF_UNIX` socket, no
websockets, no pydantic-settings import.

Two routes, both requiring `Authorization: Bearer <firebase-id-token>`:

    POST /api/provision            create/prepare a profile for the
                                    caller's uid (`claims["sub"]`)
    GET  /api/provision/status      report `{"state": ...}` for the
                                    caller's uid

See `zylch.provisiond.handler` for the route logic and
`zylch.provisiond.__main__` for the process entrypoint
(`python -m zylch.provisiond`). `engine/scripts/server/README-provisiond.md`
has the install + curl-verify runbook.
"""
