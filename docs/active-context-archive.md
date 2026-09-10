# Active Context — Archive (cross-cutting)

Historical narrative pruned out of [`active-context.md`](active-context.md).
That file is a living snapshot and carries only `State now` / `Unresolved` /
`Next`; anything chronological lands here instead. Newest section first.
Nothing is discarded — only relocated, verbatim.

## 2026-09-09 — Prior cross-cutting snapshot (historical, deployment claims not reverified)



*Snapshot as of 2026-09-09. Dated landings are in
[`active-context-archive.md`](active-context-archive.md).*

**Shared company memory — shipped 2026-09-09: pushed, released as `v0.1.46`, deployed to all daemons; Café 124 converged on one store (four accounts analysing their mailboxes into it; the post-update sweep united its first 12 duplicates at 14:03 UTC), MrCall's two identities still separate.** One
memory per company, addressed by a 128-bit capability key (`MEMORY_KEY`).
Four commits: M0 `efac9e7` (single-owner migration runner), M1 `cb3bef8` (key,
per-family scope — company families by key, rules by key AND owner — keyed
namespaces, family filters on all nine family-blind paths), M2 `0131627` (the
six memory tables move to `~/.zylch/memory/<key>.db`; creation gated by
provenance; `memory.join` as the only key write path; compare-and-swap writes;
one sweep per company; provisiond fails closed on an unmapped uid), M3 `638e721`
(onboarding key field + mint-or-join step, Settings memory card with copy and
join-with-echo, right-click edit menu); follow-up `e3b0e4b` (deployed):
the sweep runs after every update when the store changed, identifiers
unique per company, `join-company.sh` asks before merging, `zylch
memory-sweep`. Brief and plan:
[`briefs/2026-09-08-shared-company-memory-implementation.md`](briefs/2026-09-08-shared-company-memory-implementation.md),
[`execution-plans/2026-09-08-shared-company-memory-implementation.md`](execution-plans/2026-09-08-shared-company-memory-implementation.md)
(open: the host company map file `/etc/mrcalld/company-map.json`, a dev-app
run of the UI). The product-facing text is the root `README.md` ("One memory
for the whole company").

**Cross-machine backend live.** The desktop engine runs as a persistent daemon on a remote machine; the Electron app reaches it over `wss://desktop.mrcall.ai` (Caddy + Let's Encrypt) instead of spawning a local stdio sidecar. Engine: a transport-agnostic dispatch core (`rpc/dispatch.py`) feeds both stdio and the WebSocket server (`rpc/server_ws.py`, `serve --ws`/`--unix`), gated by a Firebase-JWT handshake (`uid == OWNER_ID`, RS256). App: `WebSocketRpcClient` vs `StdioRpcClient` chosen per-installation (`~/.zylch/backend-config.json`), connecting to `<base>/ws/<uid>` with the token in the handshake header. Deployed on the Scaleway VPS (alongside `mrcall-agent`): a `zylch-server@<uid>` systemd template behind Caddy, installed/updated via `git` ([`remote-backend.md`](remote-backend.md)). IPC additions: `auth.refresh`, `account:pushToken`, backend-location IPCs. Multi-profile routing is live on the same URL: a dedicated `mrcalld` service user + per-uid Unix sockets (`serve --unix`) + static Caddy `path_regexp` + idempotent `sudo update-daemons.sh`, no app change. See [`execution-plans/multi-profile-routing.md`](execution-plans/multi-profile-routing.md) + [`remote-backend.md`](remote-backend.md).

**The RPC surface is contract-gated at the dispatch boundary.** A call carrying a parameter the handler does not accept, or missing one it cannot do without, is refused with JSON-RPC `-32602` before the handler runs — previously an unknown param was silently dropped (`tasks.list(status="open")` returned every task and looked filtered). The accepted/required sets are derived from each handler's own docstring signature at import time (`rpc/param_spec.py`, built once over all 65 registered methods), so the contract cannot rot away from the code. `engine/tests/rpc/test_contract_boundaries.py` enforces it: every method must declare a checkable signature, every method must answer its documented minimal payload through the real `dispatch_raw`, required-ness is proven leave-one-out, and every `window.zylch.*` binding in `app/src/preload/index.ts` must resolve to a registered engine method. `tasks.complete` gained additive `actor?` / `why?` — defaulting to the desktop-human close, so pre-existing clients are unaffected — and the new `tasks.snooze` carries the same audit pair, letting an external operator such as `mrcall-cs` sign what it closes or parks. Deployed to the 5 vendor daemons on 2026-08-03. Full surface: [`ipc-contract.md`](ipc-contract.md).

**One approval gate on four dispatchers, and no draft sent twice** (`c341963` + `343540a`, deployed to all five `zylch-server@` units). A wrong-recipient send happened without `send_draft` ever being called: the semantic matcher rewrote the message into a bare `/email send` and dropped the draft id, and the handler picked the most recent draft. Four fail-open paths are closed — `tools/gmail_tools.py::_resolve_draft`, the `/email send` handler, `command_matcher._format_email`, `agents/task_orchestrator_agent._handle_send_email` — and `draft_id` is now `required` in the `send_draft` tool schema, so an absent or unknown id sends nothing. Separately, four dispatchers that previously bypassed `chat.pending_approval` entirely are now gated, and they share one module, `services/approval_gate.py`, so a single allow-list decision covers every route. Three of them call it directly: slash commands (`services/chat_service.py:436`) and the CLI REPL (`cli/chat.py:724`) through `gate_slash_command`, task mode through `request_approval` — and `_process_task_mode_message` now actually receives an `approval_callback`, re-pointed every turn because the orchestrator outlives the turn that built it. The fourth, the Telegram bot, is closed by the gate itself becoming **fail-closed**: `assistant/core.py:379` keys on `tool_name in APPROVAL_TOOLS` alone, and a `None` callback returns a refusal `tool_result` without calling the tool. The bot was the only caller relying on the old fail-open behaviour. The Telegram bot keeps its capability through an inline-button approval card (`_make_approval_callback` + `CallbackQueryHandler`); that card is **approve/refuse only** and cannot edit recipient or body the way the desktop card can. `send_draft` also refuses a draft already `sent`/`sending`; `failed` stays sendable on purpose, because nothing reads that status while three listers filter on `draft`, so parking a draft there would hide it from every retry path.

**The engine answers "does this message need a reply?"** (`1139da2`, merged `810d7a4`, deployed). `zylch/utils/reply_need.py` is the judgement, `zylch/rpc/reply_queries.py` exposes it as `emails.needs_reply(thread_ids)`, registered through `rpc/methods.py`. Hybrid by design: `screen()` is deterministic, structural, and **can return only *needs a reply*** — it answers `None` ("ask the adjudicator") when it has nothing to say, so no arrangement of its rules can silence a customer. It defers anything carrying a question mark, an attachment, a link, an unreadable body, over 600 visible characters, or no prior human answer of ours; the residue goes to one batched LLM call at temperature 0. Every failure path — no transport, spend cap, a 400 handed back as a response, a missing or non-boolean verdict — degrades to `needs_reply=True` and says so in `decided_by="degraded"`. Live-verified on the deployed support@ daemon (`emails.needs_reply` answers; the 200-id cap refuses with `-32603`). Contract: [`ipc-contract.md`](ipc-contract.md).

**Phase B — the headless auth path for the `cs` CLI** (spans app + engine + VPS ops; plans live in the meta-repo, `~/hb/docs/execution-plans/2026-08-13-phase-b-execution-plan.md` and `~/hb/docs/execution-plans/2026-08-14-b4-provisioning-status-execution-plan.md`). The app now writes `<profile>/cs-descriptor.json` at sign-in (`app/src/main/csDescriptor.ts`, mode 0600, atomic tmp+rename) — a frozen `version: 1` contract carrying uid, email, `engine_ws_url`, the server-side Firebase web API key and a refresh token, so a headless `cs` process mints its own session without going through the renderer. Vendor-side, the daemon set reconciles itself (`engine/scripts/systemd/zylch-reconcile.{path,timer,service}` wrapping `update-daemons.sh` — inotify on `profiles/` for new-profile creation, daily timer as the catch-all), and `engine/zylch/provisiond/` serves `POST /api/provision` + `GET /api/provision/status` over an `AF_UNIX` socket behind a static Caddy `/api/provision*` matcher, authenticated by Firebase JWT with the uid taken from `sub` only. **Provisiond is deployed** — `zylch-provisiond.service` is `enabled` + `active` on the VPS since 2026-08-17 and `/etc/caddy/Caddyfile` reverse-proxies `path /api/provision*` to `unix//run/mrcalld/provisiond.sock`. The app side is wired too: `app/src/main/provisionClient.ts` calls `POST /api/provision` and `GET /api/provision/status`, and `app/src/renderer/src/components/ProvisionStatus.tsx` renders the sidebar row. Not verified here: an end-to-end provisioning of a fresh profile through the packaged app.

**MrCall credits routing now actually consumes credits.** Five-part fix split across `mrcall-desktop` and `mrcall-agent`. Desktop side: `ANTHROPIC_API_KEY` shell-env leak closed (engine reads ONLY the profile `.env`); defensive gzip-SSE inflate in the proxy client; Firebase JWT redacted in the RPC dispatcher's DEBUG `params=` line (was being shipped to Anthropic via the renderer's narration pipeline); `LOG_LEVEL` default flipped to DEBUG; balance card self-heals via shared `ensureEngineSession`. Server side (`mrcall-agent/production` already deployed): `accept-encoding: identity` upstream + `aiter_bytes()` forward so the proxy stops leaking gzipped bytes downstream; pricing YAML aligned with Anthropic 2026-05 (Opus 4.7 mispriced at $15/$75 = Opus 4.1 pricing; Haiku 4.5 dated ID `claude-haiku-4-5-20251001` was missing from the allowlist).

**Tasks reanalyze sees WhatsApp threads + user aliases.** New `EMAIL_ALIASES` config (engine + UI Settings) lets `_is_user_email` recognise secondary identities; `build_whatsapp_thread_history` feeds the same reanalyze prompt that already handled email; deterministic urgency cap demotes medium/high to low when the last non-auto turn is the user's (proactive nudge policy, reason annotated).

**Solve loop is opt-in + self-closing.** Open from Tasks no longer auto-fires `tasks.solve`; the user clicks the lightbulb on the chat composer to trigger the agent loop with optional typed instructions. After a mutating solve the engine auto-runs `reanalyze_task` and decorates the `done` event with `auto_reanalyzed = {action, reason}`; the renderer flips the conversation to read-only on `closed` and refreshes `tasks.list`. Outbound `send_email`/`send_whatsapp` mirror their row into the local store so reanalyze sees the user's reply without waiting for IMAP-Sent / WA echo.

**A draft can be retired, and only one pipeline runs at a time — coded and unit-tested, NOT live-verified** (`11e8db5` + `9c72683`, on `main`, unpushed). Two additions to the RPC surface that an external operator needs and could not fake. `drafts.discard(draft_id)` (`engine/zylch/rpc/draft_actions.py`) retires ONE engine draft for the calling owner: it DELETES the row, because every listing filters `status == 'draft'` and a new terminal status would need a full table rebuild on every existing profile database. `sending` and `sent` are refused with `{ok: false, reason}` — an answer about the mailbox, not a transport error — matching what `send_draft` refuses; `failed` stays discardable for the same reason it stays sendable. Separately, `handle_process` admits one pipeline run at a time, so an on-demand catch-up landing on a scheduled tick can no longer analyse the same mail twice; a refused `update.run` answers `busy: true`, `success: false` and an empty diff, which a caller cannot confuse with a pass that found nothing. Contract: [`ipc-contract.md`](ipc-contract.md). Consumer: cs-kernel `v0.31.0` (tagged locally, unpushed) drives both surfaces through `cs catchup` and its draft-retire path, and degrades until this engine is deployed.

**Live verification status.** Engine path verified end-to-end via `npm run dev` against the production `mrcall-agent` proxy (real credits consumption, real reanalyze, real Solve). **The vendor daemons are behind `main`**: `/home/mrcalld/mrcall-desktop` is at `810d7a4`, which predates both `11e8db5` and `9c72683`, so neither `drafts.discard` nor the single-flight guard is reachable over the wire yet; all five `zylch-server@` units are active on that older revision. Deploying is step 1 of the cross-repo rollout plan, meta-repo `~/hb/docs/execution-plans/2026-08-27-cs-review-fresh-state.md`, and waits on Mario's go. The newest packaged build is **`v0.1.44` (2026-08-18)**, a GitHub Release carrying one asset, `MrCall.Desktop-0.1.44-arm64.dmg` — no Windows installer, which is the intended behaviour since Windows became opt-in (`3ec5d36`). The tag resolves to `f2fcfd7`, so it carries the August dispatch contract gates and Phase B, but **not** the send-approval work or `emails.needs_reply` — both post-date it (`c341963` is not an ancestor of `v0.1.44`). A DMG user therefore still gets the ungated slash-command dispatchers. Continue-with-Google signin paths, cross-channel `ThreadPanel`, and Mac packaged-bundle bring-up all still pending.

### Where stable state lives

| What | Where |
|---|---|
| JSON-RPC method surface (engine ↔ app contract), parameter contract, `-32602` rules | [`ipc-contract.md`](ipc-contract.md) |
| Phase B headless-auth path (`cs-descriptor.json`, reconciler, provisiond) | meta-repo `~/hb/docs/execution-plans/2026-08-13-phase-b-execution-plan.md` + `~/hb/docs/execution-plans/2026-08-14-b4-provisioning-status-execution-plan.md` |
| Cross-machine transport (WS engine, Caddy/TLS, VPS deploy — Phase 1–3b live) | [`execution-plans/cross-machine-transport.md`](execution-plans/cross-machine-transport.md) |
| Multi-profile routing (`mrcalld` + per-uid Unix sockets + `update-daemons.sh`) — LIVE | [`execution-plans/multi-profile-routing.md`](execution-plans/multi-profile-routing.md) |
| Remote-backend operator guide (mrcalld model, setup + runbook) | [`remote-backend.md`](remote-backend.md) |
| Firebase Auth as desktop identity | [`../AGENTS.md`](../AGENTS.md) "Identity (Firebase)" |
| LLM billing modes (BYOK ↔ MrCall credits) | [`../AGENTS.md`](../AGENTS.md) "LLM billing modes" |
| Brand / rename rollout (zylch → mrcall) | [`../AGENTS.md`](../AGENTS.md) "Naming and identifiers" |
| Release pipeline (electron-builder, signing, sidecar bundling, OAuth-secret CI step) | [`execution-plans/release-and-rename-l2.md`](execution-plans/release-and-rename-l2.md) |
| Continue-with-Google sign-in details | [`execution-plans/google-signin.md`](execution-plans/google-signin.md) |
| Engine architecture, code style, conventions | [`../engine/docs/`](../engine/docs/) |
| App architecture (lives in `app/CLAUDE.md` for now) | [`../app/CLAUDE.md`](../app/CLAUDE.md) |
| Enforcement / tooling gaps | [`harness-backlog.md`](harness-backlog.md) + per-tree backlogs |
| Dated landings, pruned narrative | [`active-context-archive.md`](active-context-archive.md) |

## Unresolved

- **One-time JWT leak in Anthropic + zylch.log historical** — pre-`_redact_params` runs shipped the full Firebase id_token through narration. Tokens expire ~1h → no rotation needed; the redactor closes the channel going forward.
- **No live end-to-end verification of any Firebase signin path** (still). The key itself is fixed: `ba81727` moved the app off a referrer-restricted Firebase web API key (an Electron renderer sends no `Referer`, so every request looked like an empty referer and was blocked) onto the API-restricted key the `cs` clones already use. That was proved by probing `accounts:signInWithPassword` — old key `Requests from referer <empty> are blocked`, new key `INVALID_LOGIN_CREDENTIALS` — which is not the same thing as a real sign-in. Follow-up worth doing: give the desktop app its **own** api-restricted key, so one restriction change cannot break the app and the clones at once.
- **Task mode is dead code that still holds a send path.** `zylch/agents/task_orchestrator_agent.py` imports `zylch.agents.mrcall_agent`, deleted in `da38647`; the module raises `ModuleNotFoundError` on import (verified), and its two transports `zylch/tools/gmail.py` / `outlook.py` do not exist either. `343540a` fixed and gated `_handle_send_email` anyway — no DB fallback, refusals decided before the `sending` write, the caller's `approval_callback` re-pointed every turn — so restoring the module does not re-arm the old defect. But nothing here is exercised, and the tests are the only thing holding it.
- **The IPC contract tests exist but nothing runs them in CI** — `engine/tests/rpc/test_contract_boundaries.py` does cover engine↔preload divergence (it parses `app/src/preload/index.ts` and cross-checks every binding against the registry) plus the minimal-payload and required-param gates. The gap is the gate, not the test: `.github/workflows/` holds only `release.yml`, so the suite runs only when someone runs it. Tracked in [`harness-backlog.md`](harness-backlog.md).
- **No contract test for desktop ↔ mrcall-agent transport** — the gzip-SSE-without-Content-Encoding regression slipped through silently. Tracked.
- **No CI for `engine/make lint` and `app/npm run typecheck`** — Tracked.
- **No CI for `pytest` on engine** — Tracked.
- **No E2E test for multi-window Firebase auth flows** — Tracked.
- **Release workflow doesn't fail when one arch's installer is missing** — Tracked.
- **No CI gate prevents committing the OAuth Client secret (`GOCSPX-`)** — Tracked.

## Next

### In flight — pending live validation

- Provision a fresh profile end-to-end through the packaged app against the live `provisiond` — the service and the Caddy route are up, but no full round trip has been observed from a DMG.
- End-to-end live verification of Firebase signin paths in `npm run dev` and packaged DMG/EXE.
- Mac validation of the 3-card Update flow + Calendar self-healing.
- Mac validation of the Solve / auto-reanalyze / outbound-mirror loop on a packaged DMG.

### Queued

1. Deploy the five `zylch-server@` daemons past `810d7a4` (`scripts/server/update-daemons.sh`) so `drafts.discard` and the single-flight guard exist over the wire, then live-verify both against the support@ daemon. Step 1 of meta-repo `~/hb/docs/execution-plans/2026-08-27-cs-review-fresh-state.md`; cs-kernel `v0.31.0` degrades until it happens. Timing is Mario's.
2. Cut a `v*` tag past `v0.1.44` so the PyInstaller-bundled sidecar carries the send-approval work (`c341963`, `343540a`), `emails.needs_reply` (`1139da2`), and the draft-retire + single-flight pair (`11e8db5`, `9c72683`). Until then a packaged client's slash-command dispatchers are still ungated, and `send_draft` there still accepts a missing `draft_id`.
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


## 2026-08-28 — Claims pruned from the living snapshot

*Relocated from `active-context.md` on 2026-08-28.*

- **"The vendor daemons run the newest code: `/home/mrcalld/mrcall-desktop` is
  at `810d7a4` and all five `zylch-server@` units are active."** Written
  2026-08-26. Superseded the moment `11e8db5` and `9c72683` landed on `main`:
  the sha and the five active units are still accurate, but they are no longer
  the newest code, and the gap is now what the entry in `Next` is about.

## 2026-08-26 — Claims pruned from the living snapshot

*Relocated from `active-context.md` on 2026-08-26. Each of these was true when
written and is false now; they are kept because a reader who remembers them
should be able to see when and why they stopped being true.*

- **"Provisiond is merged to main but NOT deployed, and the app-side call at
  'use vendor engine' time is not wired yet."** Written 2026-08-15. Superseded:
  `zylch-provisiond.service` has been `enabled` + `active` on the VPS since
  2026-08-17 with the `/api/provision*` Caddy route live, and the app side
  landed the same week (`6c06657`, `f26011c`, `81e93ad`).
- **"The newest packaged build is `v0.1.37` (2026-07-07) … Nothing from August
  is in a packaged build."** Superseded by the `v0.1.38 … v0.1.44` release run
  of 2026-08-16→18. The shape of the claim survives with new numbers: `v0.1.44`
  predates the send-approval work and `emails.needs_reply`, so a packaged
  client is still behind the daemons.
- **"Cut a `v*` tag past `v0.1.37` so the PyInstaller-bundled sidecar carries
  the August work — the dispatch contract gates and the `actor?`/`why?`
  close-audit params."** Done by `v0.1.44`.
- **"Deploy `provisiond` on the VPS and wire the app-side `POST /api/provision`
  at 'use vendor engine' time — both explicitly out of B4's build scope."**
  Done; what remains is a live round trip from a packaged build, which is now
  the entry in `Next`.

## 2026-06-15 → 2026-05-20 — Recent landings

*Relocated verbatim from `active-context.md` on 2026-08-04, during the
harness v3 bootstrap. It was the "Recent landings (last ~2 weeks)" table.*

| Date | What | Spans | Refs |
|---|---|---|---|
| 2026-06-15 | **support@ auto-responder incident + `send_sms` on MrCall credits.** Two coupled engine bugs (Italian `Ciao MrCaller!` auto-reply mis-classified + multi-thread urgency-cap judging the wrong turn) starved the task list; both fixed, 138 rows backfilled, `pmscasevacanze` recovery verified live. Separately `send_sms` now bills the unified CALLCREDIT pool via `mrcall-agent`'s `/api/desktop/sms/send` (was a deleted-`sms_tools` broken import that crash-looped all 6 daemons). Engine detail in [`../engine/docs/active-context.md`](../engine/docs/active-context.md); incident in `~/hb/docs/known-issues-and-solutions.md`. | engine + ops + server | `b889eb8` `170cae7` `70172c9..d01a04f` |
| 2026-06-05 | **Multi-profile routing — LIVE.** `mrcalld` service user + per-uid Unix sockets (`serve --unix`) + static Caddy `path_regexp` + idempotent `update-daemons.sh` (discover / enable / restart / `--prune`). `<prod-uid>` migrated `mal`→`mrcalld` (data intact), multi-profile proven on one URL; `server_ws.py` socket `chmod 0o660` + stale-`unlink`; unit `ExecStopPost`. App unchanged. `remote-backend.md` rewritten. | engine + ops + docs | [multi-profile-routing.md](execution-plans/multi-profile-routing.md) |
| 2026-06-04 | **Remote-backend deploy via git + docs.** Engine deploys/updates by `git clone`/`git pull` → `~/mrcall-desktop/engine` (profile stays rsync — private); operator guide + agent runbook in `docs/remote-backend.md`; README local-first quickstart. Also: 6 stale engine tests removed (suite green). | ops + docs + engine | [`remote-backend.md`](remote-backend.md) |
| 2026-06-02 | **Cross-machine transport — Phase 1–3b live** (`wss://desktop.mrcall.ai`, no tunnel). Engine `serve --ws`/`--unix` + shared `rpc/dispatch.py` + Firebase-JWT gate (`rpc/server_ws.py`, `rpc/firebase_auth.py`, `auth.refresh`/4401); app `WebSocketRpcClient` (base URL + `/ws/<uid>`, `account:pushToken` token flow, `BackendLocationCard`); VPS deploy = `zylch-server@<uid>` systemd + Caddy/LE. (Multi-profile per-uid sockets → landed 2026-06-05.) | engine + app + IPC + ops | [cross-machine-transport.md](execution-plans/cross-machine-transport.md) |
| 2026-05-31 | **MrCall credits — leak fix, gzip SSE, secret redaction, balance self-heal, DEBUG default** + companion server-side fixes in `mrcall-agent/production` (allowlist + identity encoding + aiter_bytes). End-to-end verified: 10 230 in / 264 out / 3 303 cache_creation on a Sonnet 4.5 reanalyze actually billed. | engine + app + server | `ed6eeef8` |
| 2026-05-31 | **Solve lightbulb + auto-reanalyze + outbound mirror.** Open from Tasks idle; Lightbulb button → `tasks.solve(task_id, instructions)`. Engine emits `tasks.solve.event.done.result.auto_reanalyzed`; renderer closes conversation + refreshes Tasks. `_send_email` / `_send_whatsapp` mirror outbound into local store. | engine + app + IPC | `9be36c9b` · [`ipc-contract.md`](ipc-contract.md) §`tasks.solve.event` |
| 2026-05-31 | **Tasks reanalyze with WhatsApp history + urgency cap + EMAIL_ALIASES.** `build_whatsapp_thread_history` parity with email side; cap medium/high → low when user replied last (proactive nudge); `EMAIL_ALIASES` config recognised by `_is_user_email` + thread renderer. | engine | `109bfd99` |
| 2026-05-31 | **WhatsApp end-to-end live refresh.** `whatsapp.threads.changed` notification (renderer subscribes + 600 ms trailing debounce); `SourceWebMsg.messageTimestamp` fallback for offline catch-up; `HistorySync.Data` field name fix; `_run_whatsapp_sync` reuses persistent client (kills the per-Update `<conflict type="replaced"/>`); `_resolve_wa_sender` prefers rubric `name` over Pushname. | engine + app + IPC | `0e576197` · [`ipc-contract.md`](ipc-contract.md) §`whatsapp.threads.changed` |
| 2026-05-28 | Onboarding hub on the Update view (3 cards Sync → Train → Update with `setup.state` gating; default view `'update'`). New RPCs `sync.run` + `setup.state`. Engine trainers async to keep loop responsive during `agents.train_all`. | engine + app + IPC | `d3de37ac` · [`ipc-contract.md`](ipc-contract.md) §`sync.run` §`setup.state` |
| 2026-05-26 | WhatsApp tab gains send + search; solve attachment fix (RFC822 Message-ID + multi-folder IMAP search); Onboarding `_resolve_host` defaults to Google for unknown domains; memory `template:<owner>` namespace + `entry_type` guard; Update view surfaces structured errors via `humanize_error`. | engine + app + IPC | `ca784d0d..4e243bdb` merged via `436bb291` |
| 2026-05-26 | "Train assistant" button (`agents.train_all` RPC + `agents.train.progress` notifications); `MessageMemoryAgentTrainer` ingests WhatsApp 1-on-1 chats alongside email samples. | engine + app + IPC | `3c152cc7` |
| 2026-05-22 | Current datetime injected into EVERY LLM request (single LLMClient chokepoint + chat_compaction bypass). | engine | `5f5c73e8` |
| 2026-05-20 | MrCall channel: delegated/PKCE OAuth + `/mrcall` removed (Firebase-JWT only); MrCall tab lists + searches businesses; onboarding unblocked for MrCall-only users; in-wizard Calendar session fix. | engine + app + IPC | `770522e8..2b0a54ce` |
| 2026-05-20 | WhatsApp voice-note transcription — event-time download + deferred faster-whisper `small`/int8 pass; archived chats excluded from memory/task analysis. Live download + packaged bundling still pending. | engine + app + IPC | [`../engine/docs/execution-plans/whatsapp-voice-transcription.md`](../engine/docs/execution-plans/whatsapp-voice-transcription.md) |
