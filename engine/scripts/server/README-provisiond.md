# provisiond — vendor-side profile provisioning + status

The vendor-side counterpart to the manual "rsync a profile in, then run
`update-daemons.sh`" flow (`docs/remote-backend.md`): the desktop app
POSTs the profile's Settings key/values straight to the VPS over HTTPS,
authenticated with the same Firebase ID token it already carries. One
singleton daemon (`zylch-provisiond` — NOT a per-uid `@`-template, unlike
`zylch-server@<uid>`) behind one static Caddy route (`/api/provision*`).
Source: `engine/zylch/provisiond/` (`python -m zylch.provisiond`).

## What it does

Both routes require `Authorization: Bearer <firebase-id-token>`.

- **`POST /api/provision`** — verifies the caller's Firebase ID token,
  uses its `sub` (uid) as the profile directory name (never anything
  from the request body), refuses with `409` if `zylch-server@<uid>` is
  already active, validates the body's keys against the engine's own
  Settings schema (`400` naming any unknown key), writes a
  `PROVISIONING` marker file THEN the profile `.env` — that order is
  load-bearing, see the comment in `zylch/provisiond/handler.py` — and
  replies `{"uid": ..., "state": "preparing"}`. Retrying against a
  uid whose daemon is NOT active overwrites rather than refuses.
- **`GET /api/provision/status`** — same auth, same uid-from-token rule
  (never from the request), answers from local truth only:
  `{"state": "active"}` (and deletes the marker, the first time it is
  observed), `{"state": "problem"}` (`systemctl is-failed`),
  `{"state": "preparing"}` (marker present, with or without `.env` yet),
  or `{"state": "not_provisioned"}` (nothing on file for this uid).

Once `.env` lands, B3's reconcile automation (`zylch-reconcile.path` +
`update-daemons.sh`) discovers the new profile dir and starts its
`zylch-server@<uid>` daemon exactly as it would for a manually-copied
profile — provisiond only ever writes the profile directory; it never
touches systemd itself.

Entitlement/payment is currently a stub —
`zylch.provisiond.handler.entitlement_allows` always returns `True`. See
the `TODO` on that function before this is trusted for paid
multi-tenant use; a refusal, once real, is a `403`.

## Install

Runs as `mrcalld`, same as every other daemon on this box — root-owned
profile dirs would be unwritable by it otherwise.

    sudo install -m 644 engine/scripts/systemd/zylch-provisiond.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now zylch-provisiond

`update-daemons.sh`'s `== 2b ==` step keeps the unit FILE current on
every run; it does not enable/start/restart provisiond itself (it is a
singleton, not something discovered per-profile) — the one-time enable
above, and any later manual restart, stay an operator action.

**One-time Caddy route** (skip if `desktop.mrcall.ai` already has the
`/api/provision*` matcher — check `/etc/caddy/Caddyfile` first; this
file is otherwise identical to what `remote-backend.md` B.1 already
installs, just re-synced from the engine checkout):

    sudo install -m 644 engine/scripts/caddy/desktop.Caddyfile /etc/caddy/Caddyfile
    sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy

Confirm the socket came up group-writable for Caddy:

    sudo ls -l /run/mrcalld/provisiond.sock   # expect srw-rw---- mrcalld caddy

## Verify with curl

Get a real Firebase ID token for a test account first (the desktop app's
own sign-in flow — provisiond verifies the SAME tokens
`zylch serve --ws`/`--unix` does). Then, from the server (or through the
public URL once Caddy is reloaded):

    TOKEN="<a real firebase id token>"

    # Provision — body is Settings key/values (zylch/services/settings_schema.py);
    # an empty body is valid (a minimal profile with just OWNER_ID).
    curl -s -X POST https://desktop.mrcall.ai/api/provision \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"EMAIL_ADDRESS": "owner@example.com"}'
    # -> {"uid": "<the token's uid>", "state": "preparing"}

    # Status
    curl -s https://desktop.mrcall.ai/api/provision/status \
      -H "Authorization: Bearer $TOKEN"
    # -> {"state": "preparing"}        (until B3 reconciles the daemon up)
    # -> {"state": "active"}           (zylch-server@<uid> is running — marker now gone)
    # -> {"state": "problem"}          (unit is-failed — check that daemon's own journal)
    # -> {"state": "not_provisioned"}  (nothing on file for this uid)

Directly against the socket (bypassing Caddy — e.g. debugging on the box
itself; needs `mrcalld`/`caddy` group membership or `sudo`):

    sudo curl -s --unix-socket /run/mrcalld/provisiond.sock \
      http://localhost/api/provision/status \
      -H "Authorization: Bearer $TOKEN"

No/garbage bearer → `401 {"error": "unauthorized"}` (never leaks the
underlying JWT failure reason). An unknown Settings key in the POST body
→ `400 {"error": "unknown key(s): ..."}`. A uid whose
`zylch-server@<uid>` is already active → `409 {"error": "already
provisioned"}`.

**Negative proof worth re-running live:** a token for uid A cannot
touch uid B's state — `GET /api/provision/status` with uid B's own
token, right after provisioning uid A, must answer
`{"state": "not_provisioned"}`, never uid A's state (covered by
`tests/provisiond/test_server.py::test_a_token_for_uid_a_cannot_touch_uid_b`,
worth one live rerun against real tokens before trusting this in
production).

## Watch

    journalctl -u zylch-provisiond -f

Never logs request bodies or `.env` values — only uid + outcome (see the
"Secrets discipline" note in `handler.py`'s docstrings).

## Disable

    sudo systemctl disable --now zylch-provisiond
