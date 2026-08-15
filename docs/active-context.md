---
doc_baseline_commit: ebb1c7f82b30f2cecb3bacf2a437903953fcde40
doc_baseline_date: 2026-07-31
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

**Task ledger hardened, contract gates at the RPC boundary — deployed to the 5 live daemons.** The 2026-08-01 fifteen-defect wave (`da38647`) landed ledger integrity (notifier-keyed contact identities, a per-pair identity precondition on dedup, `reopen_if_closed`, `close_actor`), policy (an urgency floor beside the cap, `due_at` + `tasks.snooze`, a single write door for prefs) and per-folder IMAP UID cursors replacing the date watermark whose 3-day hole had hidden a customer mail. On top of it (`677e319`, `1367e71`, `d239e5f`) the dispatcher stopped accepting what the handler would silently drop: unknown params and genuinely-missing required params are refused at `engine/zylch/rpc/dispatch.py` with `-32602`, the accepted and required sets being derived from each handler's own docstring signature (`rpc/param_spec.py`) and enforced leave-one-out across all 65 registered methods. `tasks.complete` gained additive `actor?`/`why?` so an external operator can sign its own closures. Deployed and live-probed 2026-08-03; suite 545 passed / 2 skipped. Engine detail: [`../engine/docs/active-context.md`](../engine/docs/active-context.md).

**Vendor-side provisioning + daemon-set reconcile — merged to `main`, NOT deployed.** Two Phase-B branches merged 2026-08-15 (`8172008`, `be542c2`). `engine/zylch/provisiond/` is a stdlib `http.server` on an `AF_UNIX` socket (`python -m zylch.provisiond`): `POST /api/provision` creates a profile from a Firebase-JWT-authenticated request (uid taken from `sub` only, never the body; 409 when the profile's `zylch-server@<uid>` is already active) and `GET /api/provision/status` answers `active` / `problem` / `preparing` / `not_provisioned`. Beside it, `engine/scripts/systemd/zylch-reconcile.{path,service,timer}` + `reconcile-notify.sh` wrap the unmodified `update-daemons.sh`, so a new profile directory brings its own daemon up, with a daily timer covering inotify's non-recursive limit. Both carry install instructions (`engine/scripts/server/README-provisiond.md`, `README-reconcile.md`); neither is installed on the VPS yet, and the app-side "use vendor engine" POST is still unwritten. Plan: meta-repo `docs/execution-plans/2026-08-14-b4-provisioning-status-execution-plan.md`.

**The desktop hands the `cs` CLI a descriptor at sign-in.** `app/src/main/csDescriptor.ts` (`45c9455`) writes `~/.zylch/profiles/<uid>/cs-descriptor.json` (0600, atomic) on every token push that carries a refresh token, and only for the window's own bound profile (`OWNER_ID` must match the pushed uid): email, uid, engine WS URL (remote-derived or the vendor default), the Identity-Toolkit-restricted server API key, refresh token. That is how a headless `<company>-cs` operator obtains a session with no browser in the loop. `deleteCsDescriptor` exists but is deliberately not yet wired to sign-out.

**Cross-machine backend live.** The desktop engine can now run as a persistent daemon on a remote machine; the Electron app reaches it over `wss://desktop.mrcall.ai` (Caddy + Let's Encrypt) instead of spawning a local stdio sidecar. Engine: a transport-agnostic dispatch core (`rpc/dispatch.py`) feeds both stdio and a new WebSocket server (`rpc/server_ws.py`, `serve --ws`/`--unix`), gated by a Firebase-JWT handshake (`uid == OWNER_ID`, RS256). App: `WebSocketRpcClient` vs `StdioRpcClient` chosen per-installation (`~/.zylch/backend-config.json`), connecting to `<base>/ws/<uid>` with the token in the handshake header. Deployed on the Scaleway VPS (alongside `mrcall-agent`): a `zylch-server@<uid>` systemd template behind Caddy, installed/updated via `git` ([`remote-backend.md`](remote-backend.md)). IPC additions: `auth.refresh`, `account:pushToken`, backend-location IPCs. **Multi-profile routing now LIVE too (2026-06-05):** a dedicated `mrcalld` service user + per-uid Unix sockets (`serve --unix`) + static Caddy `path_regexp` + idempotent `sudo update-daemons.sh` — same URL for every profile, no app change; `<prod-uid>` migrated `mal`→`mrcalld`, multi-profile proven on one URL. See [`execution-plans/multi-profile-routing.md`](execution-plans/multi-profile-routing.md) + [`remote-backend.md`](remote-backend.md).

**MrCall credits routing now actually consumes credits.** Five-part fix split across `mrcall-desktop` and `mrcall-agent`. Desktop side: `ANTHROPIC_API_KEY` shell-env leak closed (engine reads ONLY the profile `.env`); defensive gzip-SSE inflate in the proxy client; Firebase JWT redacted in the RPC dispatcher's DEBUG `params=` line (was being shipped to Anthropic via the renderer's narration pipeline); `LOG_LEVEL` default flipped to DEBUG; balance card self-heals via shared `ensureEngineSession`. Server side (`mrcall-agent/production` already deployed): `accept-encoding: identity` upstream + `aiter_bytes()` forward so the proxy stops leaking gzipped bytes downstream; pricing YAML aligned with Anthropic 2026-05 (Opus 4.7 mispriced at $15/$75 = Opus 4.1 pricing; Haiku 4.5 dated ID `claude-haiku-4-5-20251001` was missing from the allowlist).

**Tasks reanalyze sees WhatsApp threads + user aliases.** New `EMAIL_ALIASES` config (engine + UI Settings) lets `_is_user_email` recognise secondary identities; `build_whatsapp_thread_history` feeds the same reanalyze prompt that already handled email; deterministic urgency cap demotes medium/high to low when the last non-auto turn is the user's (proactive nudge policy, reason annotated).

**Solve loop is opt-in + self-closing.** Open from Tasks no longer auto-fires `tasks.solve`; the user clicks the lightbulb on the chat composer to trigger the agent loop with optional typed instructions. After a mutating solve the engine auto-runs `reanalyze_task` and decorates the `done` event with `auto_reanalyzed = {action, reason}`; the renderer flips the conversation to read-only on `closed` and refreshes `tasks.list`. Outbound `send_email`/`send_whatsapp` mirror their row into the local store so reanalyze sees the user's reply without waiting for IMAP-Sent / WA echo.

**Live verification status.** Engine path verified end-to-end via `npm run dev` against the production `mrcall-agent` proxy (real credits consumption, real reanalyze, real Solve), and the 2026-08-03 hardening was live-probed on the support@ daemon. The last release is `v0.1.37` (2026-07-07), so the PyInstaller-bundled sidecar inside the shipped DMG/EXE does carry the 2026-05-31 fixes but none of the August ledger / contract-gate work — a fresh `v*` tag is the release gate for that. Continue-with-Google signin paths, cross-channel `ThreadPanel`, and Mac packaged-bundle bring-up all still pending.

### Where stable state lives

| What | Where |
|---|---|
| JSON-RPC method surface — prose for the non-obvious methods; the *enforced* contract is each handler's docstring signature, parsed by `engine/zylch/rpc/param_spec.py` | [`ipc-contract.md`](ipc-contract.md) |
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
- **Nothing runs the IPC contract test automatically** — `engine/tests/rpc/test_contract_boundaries.py` does cross-check every `app/src/preload/index.ts` binding against the engine registry and drives all 65 methods through the real `dispatch_raw`, so engine↔preload divergence is caught *when the suite is run by hand*. `.github/workflows/` holds only `release.yml`, so no CI runs it. Tracked in [`harness-backlog.md`](harness-backlog.md).
- **No contract test for desktop ↔ mrcall-agent transport** — the gzip-SSE-without-Content-Encoding regression slipped through silently. Tracked.
- **No CI for `engine/make lint` and `app/npm run typecheck`** — Tracked.
- **No CI for `pytest` on engine** — Tracked.
- **No E2E test for multi-window Firebase auth flows** — Tracked.
- **Release workflow doesn't fail when one arch's installer is missing** — Tracked.
- **No CI gate prevents committing the OAuth Client secret (`GOCSPX-`)** — Tracked.

## Next

### In flight — pending live validation

- End-to-end live verification of Firebase signin paths in `npm run dev` and packaged DMG/EXE.
- Mac validation of the 3-card Update flow + Calendar self-healing.
- Mac validation of the Solve / auto-reanalyze / outbound-mirror loop on a packaged DMG.

### Queued

1. Install the Phase-B units on the VPS (`zylch-provisiond.service`, `zylch-reconcile.{path,service,timer}`, the two Caddy path matchers) and wire the app-side "use vendor engine" POST — the code is on `main`, nothing of it runs in production.
2. Cut a fresh `v*` tag so the PyInstaller-bundled sidecar carries the August ledger + contract-gate work (`v0.1.37`, 2026-07-07, predates all of it).
3. Wire `humanize_error` into the remaining RPC surfaces that still raise raw `httpx`/`imaplib` tracebacks (`rpc/account.py:account.balance`, Settings test-connection, chat tools, solve tools).
4. Add the `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret at *Settings → Secrets and variables → Actions*. Until it exists, packaged builds with Google signin fail at the materialise step.
5. Configure `GOOGLE_CALENDAR_CLIENT_ID` in profile Settings → "Connect Google Calendar" → confirm consent + token persistence + self-healing recovery path.
6. Wire `engine/zylch/tools/calendar_sync.py` to the new `provider='google_calendar'` tokens.
7. Open **MrCall pipeline parity Livello B** workstream — phone-call memory ingestion. Plan: [`execution-plans/mrcall-pipeline-parity.md`](execution-plans/mrcall-pipeline-parity.md).

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
