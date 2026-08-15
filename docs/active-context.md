---
doc_baseline_commit: ba8c0aa
doc_baseline_date: 2026-08-15
description: |
  Cross-cutting state of mrcall-desktop — things that span engine ↔ app
  or the repo as a whole (JSON-RPC contract drift, release pipeline,
  brand/rename rollout, monorepo conventions). Engine-only state lives
  in `../engine/docs/active-context.md`; app-only state in
  `../app/docs/active-context.md`.

  This is a LIVING SNAPSHOT, not a changelog: the only sections are
  `State now`, `Unresolved`, `Next`, and it targets ≤ ~120 lines.
  Chronological narrative moves to `active-context-archive.md`.
---

# Active Context — Cross-cutting

## State now

*Snapshot as of 2026-08-15. Dated landings are in
[`active-context-archive.md`](active-context-archive.md).*

**Cross-machine backend live.** The desktop engine runs as a persistent daemon on a remote machine; the Electron app reaches it over `wss://desktop.mrcall.ai` (Caddy + Let's Encrypt) instead of spawning a local stdio sidecar. Engine: a transport-agnostic dispatch core (`rpc/dispatch.py`) feeds both stdio and the WebSocket server (`rpc/server_ws.py`, `serve --ws`/`--unix`), gated by a Firebase-JWT handshake (`uid == OWNER_ID`, RS256). App: `WebSocketRpcClient` vs `StdioRpcClient` chosen per-installation (`~/.zylch/backend-config.json`), connecting to `<base>/ws/<uid>` with the token in the handshake header. Deployed on the Scaleway VPS (alongside `mrcall-agent`): a `zylch-server@<uid>` systemd template behind Caddy, installed/updated via `git` ([`remote-backend.md`](remote-backend.md)). IPC additions: `auth.refresh`, `account:pushToken`, backend-location IPCs. Multi-profile routing is live on the same URL: a dedicated `mrcalld` service user + per-uid Unix sockets (`serve --unix`) + static Caddy `path_regexp` + idempotent `sudo update-daemons.sh`, no app change. See [`execution-plans/multi-profile-routing.md`](execution-plans/multi-profile-routing.md) + [`remote-backend.md`](remote-backend.md).

**The RPC surface is contract-gated at the dispatch boundary.** A call carrying a parameter the handler does not accept, or missing one it cannot do without, is refused with JSON-RPC `-32602` before the handler runs — previously an unknown param was silently dropped (`tasks.list(status="open")` returned every task and looked filtered). The accepted/required sets are derived from each handler's own docstring signature at import time (`rpc/param_spec.py`, built once over all 65 registered methods), so the contract cannot rot away from the code. `engine/tests/rpc/test_contract_boundaries.py` enforces it: every method must declare a checkable signature, every method must answer its documented minimal payload through the real `dispatch_raw`, required-ness is proven leave-one-out, and every `window.zylch.*` binding in `app/src/preload/index.ts` must resolve to a registered engine method. `tasks.complete` gained additive `actor?` / `why?` — defaulting to the desktop-human close, so pre-existing clients are unaffected — and the new `tasks.snooze` carries the same audit pair, letting an external operator such as `mrcall-cs` sign what it closes or parks. Deployed to the 5 vendor daemons on 2026-08-03. Full surface: [`ipc-contract.md`](ipc-contract.md).

**Phase B — the headless auth path for the `cs` CLI** (spans app + engine + VPS ops; plans live in the meta-repo, `~/hb/docs/execution-plans/2026-08-13-phase-b-execution-plan.md` and `~/hb/docs/execution-plans/2026-08-14-b4-provisioning-status-execution-plan.md`). The app now writes `<profile>/cs-descriptor.json` at sign-in (`app/src/main/csDescriptor.ts`, mode 0600, atomic tmp+rename) — a frozen `version: 1` contract carrying uid, email, `engine_ws_url`, the server-side Firebase web API key and a refresh token, so a headless `cs` process mints its own session without going through the renderer. Vendor-side, the daemon set reconciles itself (`engine/scripts/systemd/zylch-reconcile.{path,timer,service}` wrapping `update-daemons.sh` — inotify on `profiles/` for new-profile creation, daily timer as the catch-all), and `engine/zylch/provisiond/` serves `POST /api/provision` + `GET /api/provision/status` over an `AF_UNIX` socket behind a static Caddy `/api/provision*` matcher, authenticated by Firebase JWT with the uid taken from `sub` only. **Provisiond is merged to main but NOT deployed**, and the app-side call at "use vendor engine" time is not wired yet.

**MrCall credits routing now actually consumes credits.** Five-part fix split across `mrcall-desktop` and `mrcall-agent`. Desktop side: `ANTHROPIC_API_KEY` shell-env leak closed (engine reads ONLY the profile `.env`); defensive gzip-SSE inflate in the proxy client; Firebase JWT redacted in the RPC dispatcher's DEBUG `params=` line (was being shipped to Anthropic via the renderer's narration pipeline); `LOG_LEVEL` default flipped to DEBUG; balance card self-heals via shared `ensureEngineSession`. Server side (`mrcall-agent/production` already deployed): `accept-encoding: identity` upstream + `aiter_bytes()` forward so the proxy stops leaking gzipped bytes downstream; pricing YAML aligned with Anthropic 2026-05 (Opus 4.7 mispriced at $15/$75 = Opus 4.1 pricing; Haiku 4.5 dated ID `claude-haiku-4-5-20251001` was missing from the allowlist).

**Tasks reanalyze sees WhatsApp threads + user aliases.** New `EMAIL_ALIASES` config (engine + UI Settings) lets `_is_user_email` recognise secondary identities; `build_whatsapp_thread_history` feeds the same reanalyze prompt that already handled email; deterministic urgency cap demotes medium/high to low when the last non-auto turn is the user's (proactive nudge policy, reason annotated).

**Solve loop is opt-in + self-closing.** Open from Tasks no longer auto-fires `tasks.solve`; the user clicks the lightbulb on the chat composer to trigger the agent loop with optional typed instructions. After a mutating solve the engine auto-runs `reanalyze_task` and decorates the `done` event with `auto_reanalyzed = {action, reason}`; the renderer flips the conversation to read-only on `closed` and refreshes `tasks.list`. Outbound `send_email`/`send_whatsapp` mirror their row into the local store so reanalyze sees the user's reply without waiting for IMAP-Sent / WA echo.

**Live verification status.** Engine path verified end-to-end via `npm run dev` against the production `mrcall-agent` proxy (real credits consumption, real reanalyze, real Solve). The newest packaged build is **`v0.1.37` (2026-07-07)**; it carries the 2026-05-31 fixes (leak, gzip, redaction, DEBUG default, `whatsapp.threads.changed`, solve auto-reanalyze), all confirmed as ancestors of the tag. Nothing from August is in a packaged build: the contract gates and all of Phase B post-date `v0.1.37`, so a DMG/EXE user still gets the pre-gate dispatcher. Continue-with-Google signin paths, cross-channel `ThreadPanel`, and Mac packaged-bundle bring-up all still pending.

### Where stable state lives

| What | Where |
|---|---|
| JSON-RPC method surface (engine ↔ app contract), parameter contract, `-32602` rules | [`ipc-contract.md`](ipc-contract.md) |
| Phase B headless-auth path (`cs-descriptor.json`, reconciler, provisiond) | meta-repo `~/hb/docs/execution-plans/2026-08-13-phase-b-execution-plan.md` + `~/hb/docs/execution-plans/2026-08-14-b4-provisioning-status-execution-plan.md` |
| Cross-machine transport (WS engine, Caddy/TLS, VPS deploy — Phase 1–3b live) | [`execution-plans/cross-machine-transport.md`](execution-plans/cross-machine-transport.md) |
| Multi-profile routing (`mrcalld` + per-uid Unix sockets + `update-daemons.sh`) — LIVE | [`execution-plans/multi-profile-routing.md`](execution-plans/multi-profile-routing.md) |
| Remote-backend operator guide (mrcalld model, setup + runbook) | [`remote-backend.md`](remote-backend.md) |
| Firebase Auth as desktop identity | [`../CLAUDE.md`](../CLAUDE.md) "Identity (Firebase)" |
| LLM billing modes (BYOK ↔ MrCall credits) | [`../CLAUDE.md`](../CLAUDE.md) "LLM billing modes" |
| Brand / rename rollout (zylch → mrcall) | [`../CLAUDE.md`](../CLAUDE.md) "Naming and identifiers" |
| Release pipeline (electron-builder, signing, sidecar bundling, OAuth-secret CI step) | [`execution-plans/release-and-rename-l2.md`](execution-plans/release-and-rename-l2.md) |
| Continue-with-Google sign-in details | [`execution-plans/google-signin.md`](execution-plans/google-signin.md) |
| Engine architecture, code style, conventions | [`../engine/docs/`](../engine/docs/) |
| App architecture (lives in `app/CLAUDE.md` for now) | [`../app/CLAUDE.md`](../app/CLAUDE.md) |
| Enforcement / tooling gaps | [`harness-backlog.md`](harness-backlog.md) + per-tree backlogs |
| Dated landings, pruned narrative | [`active-context-archive.md`](active-context-archive.md) |

## Unresolved

- **One-time JWT leak in Anthropic + zylch.log historical** — pre-`_redact_params` runs shipped the full Firebase id_token through narration. Tokens expire ~1h → no rotation needed; the redactor closes the channel going forward.
- **No live end-to-end verification of any Firebase signin path** (still).
- **The IPC contract tests exist but nothing runs them in CI** — `engine/tests/rpc/test_contract_boundaries.py` does cover engine↔preload divergence (it parses `app/src/preload/index.ts` and cross-checks every binding against the registry) plus the minimal-payload and required-param gates. The gap is the gate, not the test: `.github/workflows/` holds only `release.yml`, so the suite runs only when someone runs it. Tracked in [`harness-backlog.md`](harness-backlog.md).
- **No contract test for desktop ↔ mrcall-agent transport** — the gzip-SSE-without-Content-Encoding regression slipped through silently. Tracked.
- **No CI for `engine/make lint` and `app/npm run typecheck`** — Tracked.
- **No CI for `pytest` on engine** — Tracked.
- **No E2E test for multi-window Firebase auth flows** — Tracked.
- **Release workflow doesn't fail when one arch's installer is missing** — Tracked.
- **No CI gate prevents committing the OAuth Client secret (`GOCSPX-`)** — Tracked.

## Next

### In flight — pending live validation

- Deploy `provisiond` on the VPS and wire the app-side `POST /api/provision` at "use vendor engine" time — both explicitly out of B4's build scope. `update-daemons.sh` keeps the unit *file* current on every run but deliberately does not enable or start it (it is a singleton, not a per-profile discovery); the one-time `systemctl enable --now` and the `/api/provision*` Caddy route stay operator actions, recipe in `engine/scripts/server/README-provisiond.md`.
- End-to-end live verification of Firebase signin paths in `npm run dev` and packaged DMG/EXE.
- Mac validation of the 3-card Update flow + Calendar self-healing.
- Mac validation of the Solve / auto-reanalyze / outbound-mirror loop on a packaged DMG.

### Queued

1. Cut a `v*` tag past `v0.1.37` so the PyInstaller-bundled sidecar carries the August work — the dispatch contract gates (`-32602` on unknown / missing-required params) and the `actor?`/`why?` close-audit params. Wire-visible change: a packaged client that sends junk params starts getting refusals instead of silent drops.
2. Wire `humanize_error` into the remaining RPC surfaces that still raise raw `httpx`/`imaplib` tracebacks (`rpc/account.py:account.balance`, Settings test-connection, chat tools, solve tools).
3. Add the `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret at *Settings → Secrets and variables → Actions*. Until it exists, packaged builds with Google signin fail at the materialise step.
4. Configure `GOOGLE_CALENDAR_CLIENT_ID` in profile Settings → "Connect Google Calendar" → confirm consent + token persistence + self-healing recovery path.
5. Wire `engine/zylch/tools/calendar_sync.py` to the new `provider='google_calendar'` tokens.
6. Open **MrCall pipeline parity Livello B** workstream — phone-call memory ingestion. Plan: [`execution-plans/mrcall-pipeline-parity.md`](execution-plans/mrcall-pipeline-parity.md).

### Deferred (nice-to-have)

Low-priority roadmap — the brief is written, execution is NOT scheduled.
**If Mario asks for one of these and has forgotten it exists, remind him the
brief is already written and restart from it** — do not re-analyse from
scratch. This subsection is durable: it is not session narrative and must
not be pruned or archived.

- **Thin web/mobile client (PWA) on top of the cross-machine transport** —
  *nice-to-have.* Electron stays the primary client; web/mobile is
  emergency access from a browser or phone. Single-tenant,
  single-active-client with eviction (a new connect closes the old one);
  PWA, not native; resume re-scoped to "continue a daemon-side operation
  remotely". Full brief:
  [`execution-plans/cross-machine-thin-clients.md`](execution-plans/cross-machine-thin-clients.md).
  Builds on [`execution-plans/cross-machine-transport.md`](execution-plans/cross-machine-transport.md)
  (now Phase 1–3b live).
