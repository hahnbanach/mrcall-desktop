# Cross-cutting runtime contracts

<!-- doc-scope:start -->
Scope: identity, company-memory access, hosted tenant isolation and LLM billing
contracts shared by the engine and Desktop. Operating rules belong to AGENTS.md;
rollout state belongs to the living contexts and owning execution plans.
<!-- doc-scope:end -->

## Identity (Firebase) — added 2026-05-02

The Electron renderer now gates the entire UI behind a Firebase Auth
sign-in (same `talkmeapp-e696c` project the dashboard uses, so the
account is shared). The renderer sends the ID token to Electron main through
`account:pushToken`. Main forwards it to local `account.set_firebase_token`;
Remote uses it for the WebSocket handshake and `auth.refresh`. The engine
verifies signed identity and effective expiry. ID tokens stay in memory and
supply the `auth:` header for StarChat. Optional refresh tokens are separate:
they are stored through `utils/encryption.py`, using Fernet with a configured
key and plaintext passthrough only on a local engine without a key. Hosted
startup requires an environment encryption key.

Profiles created post-Firebase are keyed by the immutable Firebase
UID (`~/.zylch/profiles/<firebase_uid>/`), not the email — emails can
change. The user's email is stored as `EMAIL_ADDRESS` in the
profile's `.env`, alongside `OWNER_ID = <firebase_uid>`. Native mail ownership
uses `cli.utils.get_owner_id()`, which resolves `EMAIL_ADDRESS`; the profile
path and verified Firebase session identity remain keyed by immutable UID.

Google Calendar is a *separate* OAuth — PKCE flow on
`127.0.0.1:19275`, scope `calendar.readonly`, tokens stored through the encryption helper in
the existing `OAuthToken` table with `provider='google_calendar'`.
The Calendar OAuth is incremental: Firebase signin doesn't ask for it,
the user clicks "Connect Google Calendar" in Settings to grant it
later. `GOOGLE_CALENDAR_CLIENT_ID` overrides the packaged
`GOOGLE_CALENDAR_CLIENT_ID_DEFAULT`. An optional secret is supported:
`GOOGLE_CALENDAR_CLIENT_SECRET` overrides `GOOGLE_CALENDAR_CLIENT_SECRET_DEFAULT`.
Connection refuses when no client ID is available.

The legacy CLI MrCall PKCE flow on `:19274` (`zylch init`) was **removed
2026-05** — MrCall connection today happens exclusively via the Firebase
sign-in in the desktop UI (`tools/mrcall/starchat_firebase.py`); `zylch init`
no longer runs any OAuth/PKCE code for MrCall (corrected 2026-07-14,
doc-critic pass).

## Shared company memory (since 2026-09)

Memory is per company, not per account. A profile carries `MEMORY_KEY`
(`secrets.token_urlsafe(16)`, 22 chars) in its `.env`, and every profile on
the same engine host holding that key reads and writes one SQLite store
under `~/.zylch/memory/` (`MEMORY_DB_DIR` overrides the directory; `ZYLCH_HOME`
overrides `~/.zylch` everywhere): on a local engine `<MEMORY_KEY>.db`, on a
hosted one `mc-c-<sha256(key)[:12]>/<sha256(key)[:32]>.db` so the file name
never carries the key (legacy-named stores are still opened, never shadowed);
the profile's `zylch.db` keeps mail, tasks, tokens and sync cursors.
Company families (`user:<key>`, `facts:<key>`) are visible to every key
holder; rule families (`template:<owner>`, `prefs:<owner>`) only to their
owner; `owner_id` on a company row is provenance, not a wall — the one
predicate is `engine/zylch/memory/scope.py:blob_visible`. The key is a
capability: `memory.join` is its only write path (`settings.update` refuses
it), a key the host does not know is refused rather than turned into an
empty store, and duplicates left by a join are united by the sweep that
runs after each update. Design:
[`docs/briefs/2026-09-08-shared-company-memory-implementation.md`](briefs/2026-09-08-shared-company-memory-implementation.md);
engine detail in [`engine/docs/features/entity-memory-system.md`](../engine/docs/features/entity-memory-system.md)
("Scope"); host operations in [`docs/remote-backend.md`](remote-backend.md)
("Shared company memory on the host"); app surface in [`app/CLAUDE.md`](../app/CLAUDE.md).

## Hosted engines: one Unix user per profile (since 2026-10)

A hosted engine (`zylch serve`) is multi-tenant on one host, and the
boundary between tenants is the operating system, not the model. All seven
hosted profiles, production voice included, run as their own users, and each
has an enforced outbound allow-list (state in the plan).
Each migrated profile's daemon runs as its own Unix user `mc-<sha256(uid)[:12]>`
inside a systemd sandbox, with the engine checkout read-only and its own
root-only `ENCRYPTION_KEY`; its tools read and write only the profile's
`downloads/` and `scratch/` folders, `run_python` is refused, and
`DOCUMENT_PATHS`/`DOWNLOADS_DIR` are ignored (`settings.get` reports them
under `ignored`). Its outbound connections are limited to the hosts in its
egress policy: a per-tenant nftables table keyed on its Unix user, filled
by a dedicated resolver that refuses every other name
(`engine/scripts/server/egress_policy.py`; refusals are listed by
`egress_refused.py`). On a local engine only the profile root is refused as a
write target and attachment filenames are reduced to a basename. Threat model and criteria:
[`docs/briefs/2026-09-29-toward-sandbox.md`](briefs/2026-09-29-toward-sandbox.md);
rollout state and runbook:
[`docs/execution-plans/2026-09-29-toward-sandbox.md`](execution-plans/2026-09-29-toward-sandbox.md);
host operations: [`docs/remote-backend.md`](remote-backend.md).

## LLM billing and spending controls

Saved `LLM_PROVIDER` explicitly selects `anthropic`, `mrcall`, or `openrouter`.
Anthropic and OpenRouter use the corresponding personal API key. MrCall credits
use Firebase authentication and the shared StarChat `CALLCREDIT` pool; top-up
opens `https://dashboard.mrcall.ai/plan`. Switching providers preserves keys
and never falls back to another provider. Legacy profiles without a provider
use their saved Anthropic key when present, otherwise MrCall credits.

The engine reserves each request's maximum cost against the saved daily USD
budget before dispatch. Uncertain requests retain their holds across restarts
and UTC midnight. MrCall calls use the versioned bounded quote/execute/status
contract; an older server without that contract refuses paid work. OpenRouter
supports an explicitly priced Claude/GLM/K3 catalog with provider price caps,
through either personal keys or MrCall credits. Payment and model selection
are separate; `llm.models` discovers available models. Economy, balanced and
custom presets expose effective role models; a small synthetic comparison
does not certify production quality. Automatic preparation is off by default and explicit runs have
a saved batch limit (default 25 steps).

Engine contracts: [`engine/docs/features/daily-llm-budget.md`](../engine/docs/features/daily-llm-budget.md)
and [`engine/docs/features/bounded-preparation.md`](../engine/docs/features/bounded-preparation.md).
`MRCALL_PROXY_URL` selects the billing server (default `https://zylch.mrcall.ai`).
App behavior: [`app/docs/bounded-preparation.md`](../app/docs/bounded-preparation.md).

