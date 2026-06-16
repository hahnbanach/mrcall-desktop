---
description: |
  Engine-side state of mrcall-desktop. Current focus + recent landings +
  known issues. Older context lives in git history, `execution-plans/`,
  and `features/`. This file is a working list, not a changelog — keep
  it ≤ ~150 lines. /doc-endsession prunes anything older than ~2 weeks.
---

# Active Context — Engine

## Current focus (as of 2026-06-16)

**Auto-responder no longer eats customer tasks (support@).** Two coupled bugs starved the task list. (1) The legacy Italian product auto-reply (`Ciao MrCaller!`, sent FROM `support@` with no RFC-3834 headers) was classified `is_auto_reply=0`, so `task_creation_email` dedup read it as a genuine user reply and closed/skipped the customer's task. `tools/email_archive._convert_message` now also flags a first body line opening with `Ciao MrCaller` (joins the `17d30bd` English `auto-replay` stopgap); human replies open with "Buongiorno"/"Ciao <customer>", so it is safe (138/138 template, 167/167 human, zero false positives through the real codepath). 138 historical rows backfilled on the live `support@` DB. (2) `workers/thread_presenter.is_last_turn_user_reply` walked the rendered text backwards, so on `reanalyze_task`'s primary + `--- RELATED THREAD ---` concatenation it judged whichever sibling was rendered last, not the chronologically newest turn — the urgency cap then demoted high→low every sweep. It now parses the bracketed timestamp on each role line and judges the newest non-`AUTO-REPLY` turn (single-thread callers like `task_creation` unchanged: newest == last line). **Verified live:** `pmscasevacanze` "Modifiche non recepite" recreated as a high task. Full incident write-up in the meta-repo `~/hb/docs/known-issues-and-solutions.md`.

**`send_sms` now bills MrCall credits; live channel availability injected into the prompt.** The old `SendSMSTool` imported a Vonage `tools/sms_tools.py` that had been deleted — a latent broken import on `main` that crash-looped all 6 daemons once a deploy `git clean`'d the stray untracked copy (fixed `70172c9`). SMS was then rebuilt on the credits proxy: `tools/sms_send.py` (proxy client) + re-added `tools/sms_tools.SendSMSTool` (chat path) + `solve_tools._send_sms`, all POSTing `{MRCALL_PROXY_URL}/api/desktop/sms/send` with the Firebase `auth:` header (matches `mrcall-agent/api/routes/desktop_sms.py`; 402 → top-up, graceful message when `SMS_FROM` isn't configured). `services/channel_status.py` injects per-channel availability into the assistant prompt via `assistant/core.py`. **Daemon import chain verified clean; the actual SMS send is NOT yet live-verified** (needs a real send + confirmation the prod `mrcall-agent` has the route deployed).

**Headless auto-update — the engine now syncs with the GUI off.** The 5-minute auto-update was renderer-only (`app/src/renderer/.../hooks/useAutoUpdate.ts`), so the cross-machine `mrcalld` daemons never synced mail or built memory unattended — a headless backend that did nothing headless. Fix: `rpc/server_ws.py` spawns `_auto_update_loop` inside `serve_ws` — a single sequential loop running the `update.run` pipeline (sync → memory → tasks) every `AUTO_UPDATE_INTERVAL_MINUTES` (default 30, clamp 5–360), gated by `AUTO_UPDATE_ENABLED`; per-tick failures are logged (not swallowed) and the loop continues. Verified live on the `support@` daemon: **0 → 662 emails synced headless**; memory blobs build once the profile has an LLM credential (BYOK key OR a live Firebase session) — proxy-mode profiles with neither do **sync-only**, the memory/task stages logging a clean `no_llm` skip. Rolled out to all 6 profile daemons (BYOK today: `support@`, `cafe124`).

**Correction-learning landed (merged from `origin/main`).** When the user edits an approval-gated send (`send_email`/`send_whatsapp`/`send_sms`) before approving it, `task_executor` captures the `{tool_name, proposed, edited}` diff; after the send, `services/correction_learning.learn_from_corrections` (fire-and-forget bg task in `rpc/methods`) judges each diff TWICE with a cheap Haiku pass — as a durable **rule** (tone/policy → `prefs:<owner>` blob, injected always-on into generation via `solve_constants.get_operating_rules_block`) and as a corrected **business fact** (price/term → `services/facts_store`, `facts:<owner>` namespace, category-tagged, deduped by exact (Category, Key), retrieved all-and-only by category through the new `list_fact_categories`/`get_facts_by_category` solve tools). `APPROVAL_TOOLS` gained `send_email`/`send_whatsapp` so their edits are captured. NOT yet live-verified by us (background path; never blocks the send).

**Cross-machine backend live on the Scaleway VPS.** The engine runs as a persistent daemon reachable from the Mac over `wss://desktop.mrcall.ai` (Caddy + Let's Encrypt), not just the local stdio sidecar. New: `rpc/dispatch.py` — the transport-agnostic dispatch core BOTH stdio (`rpc/server.py`) and the WS server route through (and where `_redact_params` now lives); `rpc/server_ws.py` (`zylch serve --ws HOST:PORT | --unix <socket>`); `rpc/firebase_auth.py` (RS256 verify of the Firebase ID token; handshake gate `uid == OWNER_ID`); `auth.refresh` + close-code 4401 on expiry; `config.firebase_project_id`; deps `websockets` + `pyjwt[crypto]`. Deployed via the `zylch-server@<uid>` systemd template behind Caddy. **Multi-profile routing now LIVE (2026-06-05):** a dedicated `mrcalld` service user + one daemon per profile on a per-uid Unix socket + static Caddy `path_regexp` + idempotent `sudo update-daemons.sh`; `server_ws.py` `chmod(0o660)`+stale-`unlink` on the socket; `<prod-uid>` migrated `mal`→`mrcalld`. See [`multi-profile-routing.md`](../../docs/execution-plans/multi-profile-routing.md) + [`remote-backend.md`](../../docs/remote-backend.md).

**MrCall credits routing finally end-to-end live.** The leak that kept `<prod-profile>`'s balance frozen for days was `ANTHROPIC_API_KEY` exported in `~/.bash_profile` bleeding into the sidecar via Pydantic Settings' env-var merge — every "I'm on credits" UI claim was actually a BYOK direct call. `llm/client._read_profile_anthropic_key` now reads ONLY the active profile's `.env`, ignoring shell env. Companion fixes: `llm/proxy_client._wrap_gzip_iter` defensively inflates a gzipped SSE body that arrived without `Content-Encoding` (the prod `mrcall-agent` flushed raw `aiter_raw()` bytes downstream — the server-side commit on `mrcall-agent/production` now pins `accept-encoding: identity` upstream + uses `aiter_bytes()`, but client side stays defensive). The shared dispatcher (`rpc/dispatch.py` since the cross-machine refactor) masks `id_token` / `access_token` / `api_key` / `password` / `client_secret` in its DEBUG `params=` line — the renderer's narration pipeline was scooping the Firebase JWT off stderr and shipping it to Anthropic. `cli/main.py` default `LOG_LEVEL` is now `DEBUG` (Mario's standing policy: mrcall-desktop boots loud).

**Tasks reanalyze now sees WhatsApp threads.** `workers/thread_presenter.build_whatsapp_thread_history` mirrors the email-side renderer (USER REPLY ✓ / CONTACT / AUTO-REPLY, voice-note transcriptions). `workers/task_reanalyze` detects WA tasks via `channel=='whatsapp'` or `sources.whatsapp_chat_jid` and routes. Two adjacent landings: (a) urgency cap — when the last non-auto turn is the user, medium/high gets capped to low ("proactive nudge" policy, reason annotated); (b) `EMAIL_ALIASES` config — `_is_user_email` and the thread renderer recognise secondary identities (Jane from `carol@example.com` on a profile keyed under `<prod-profile>`) as the user.

**Solve loop becomes opt-in + self-closing.** `tasks.solve.event.done.result` now carries `auto_reanalyzed = {action, reason}` when the executor ran any mutating tool (send_email / send_whatsapp / send_sms / update_memory / run_python); `_send_email` and `_send_whatsapp` mirror their outbound row into the local store keyed on Message-ID / SendResponse.ID so reanalyze sees the user's reply without a full IMAP sync.

## Recent landings (last ~2 weeks)

| Date | What | Refs |
|---|---|---|
| 2026-06-16 | **`send_sms` via MrCall credits proxy + channel availability in prompt.** `tools/sms_send.py` + `tools/sms_tools.SendSMSTool` (chat) + `solve_tools._send_sms` → `POST /api/desktop/sms/send` (Firebase `auth:`, 402 top-up, clean no-`SMS_FROM` message); `services/channel_status.py` feeds live channel availability to `assistant/core.py`. Import chain verified clean; SMS send NOT yet live-verified. (`70172c9` first fixed a crash-looping broken `sms_tools` import on `main`.) | `70172c9..d01a04f` |
| 2026-06-15 | **Auto-responder no longer eats tasks (support@).** `email_archive._convert_message` flags a `Ciao MrCaller` opener as auto-reply (138 rows backfilled live); `thread_presenter.is_last_turn_user_reply` judges the newest-by-timestamp turn across primary+sibling histories (was last-rendered-line → spurious urgency caps). Verified live: `pmscasevacanze` task recreated. Incident: meta-repo `known-issues`. | `b889eb8` `170cae7` |
| 2026-06-08 | **Headless auto-update in `serve`.** `rpc/server_ws.py:_auto_update_loop` runs the `update.run` pipeline every `AUTO_UPDATE_INTERVAL_MINUTES` with no GUI (was renderer-only `useAutoUpdate.ts`). Single sequential loop, failures logged not swallowed, honours `AUTO_UPDATE_ENABLED`. Live: support@ 0→662 emails headless; memory needs a BYOK key or Firebase session (proxy-no-session → sync-only, clean `no_llm`). Rolled out to all 6 daemons. | `server_ws.py` |
| 2026-06-05 | **Multi-profile routing LIVE.** `mrcalld` user + per-uid Unix sockets (`serve --unix`) + static Caddy `path_regexp` + `update-daemons.sh`. `rpc/server_ws.py`: socket `chmod 0o660` after bind + `unlink` stale socket before bind (caddy-connectable + clean respawn on py3.12). Unit reworked (mrcalld / `--unix` / `UMask=0007` / StartLimit / `ExecStopPost`) + new `scripts/tmpfiles.d/mrcalld.conf` + `scripts/server/update-daemons.sh`. `<prod-uid>` migrated `mal`→`mrcalld`, data intact (54 email / 18 task). | [multi-profile-routing.md](../../docs/execution-plans/multi-profile-routing.md) |
| 2026-06-04 | **Deploy via git + 6 stale tests removed.** Engine deploys/updates by `git clone`/`git pull` → `~/mrcall-desktop/engine` (was rsync → `~/zylch-engine`; profile stays rsync — private, not in git); systemd `ExecStart` follows. Operator + agent runbook: [`../../docs/remote-backend.md`](../../docs/remote-backend.md). Removed 6 stale red tests (intentional-change drift); suite green (303 passed). | `fa2598d2..ccfa0143` |
| 2026-06-03 | **Correction-learning merged** (`origin/main`): `services/correction_learning` + `services/facts_store`; rules → `prefs:`, facts → `facts:` (category all-and-only); solve tools `list_fact_categories`/`get_facts_by_category`; `APPROVAL_TOOLS` += `send_email`/`send_whatsapp`. | `a63b33d3..f83b9d14` |
| 2026-06-02 | **Cross-machine transport — Phase 1–3b** (live: `wss://desktop.mrcall.ai`). `rpc/dispatch.py` (transport-agnostic core + `_redact_params`), `rpc/server_ws.py` (`serve --ws`/`--unix`, Firebase-JWT handshake gate), `rpc/firebase_auth.py` (RS256), `auth.refresh`/4401, `config.firebase_project_id`, deps `websockets`+`pyjwt`. VPS: `~/zylch-engine` venv, `zylch-server@<uid>` systemd template, Caddy/LE. (Multi-profile per-uid sockets → landed 2026-06-05.) | [cross-machine-transport.md](../../docs/execution-plans/cross-machine-transport.md) |

## In progress

- **Live verification of today's stack on packaged DMG** — engine-side flows worked in `npm run dev`, but the PyInstaller-bundled sidecar hasn't seen the gzip path / redaction yet.
- **MrCall pipeline parity Livello B** — phone-call memory ingestion via StarChat (Firebase-JWT auth, defence-in-depth UID scope). Plan: [`../../docs/execution-plans/mrcall-pipeline-parity.md`](../../docs/execution-plans/mrcall-pipeline-parity.md).
- **Mac validation backlog** — IMAP archive against real Gmail/Outlook/iCloud/Fastmail; Open → Tasks filter (0/N tasks, Clear filter); close-note composer; end-to-end memory tool round-trip in chat.

## Next steps

1. Wire `humanize_error` into the other RPC surfaces that still surface raw `httpx`/`imaplib` tracebacks (`rpc/account.py:account.balance`, Settings test-connection, chat tools, solve tools). Classifier exists; only `update.run` + `sync.run` consume it today.
2. Settings → "Connect Google Calendar" recovery path (no raw `_NotSignedInError`).
3. Wire `tools/calendar_sync.py` to read tokens from `provider='google_calendar'` (current 469-line module is partial scaffolding).
4. Split oversized files: `services/command_handlers.py` (5427), `workers/task_creation.py` (well over 1100), `tools/gmail_tools.py` (1002), `workers/memory.py` (916).
5. Audit other `create_message_sync` callers (`memory/llm_merge.py:76`, `services/solve_tools.py:481` etc.) for asyncio-blocking — today's trainer fix was surgical, not exhaustive.

## Known issues

- **Stale Firebase id_token still in zylch.log + Anthropic request logs (one-time)** — pre-`_redact_params` runs leaked the JWT through narration; tokens expire ~1h so no rotation needed. Going-forward: redaction handles new RPCs only if `_SECRET_PARAM_KEYS_*` tables are kept in sync.
- **`humanize_error` wired only to `update.run` + `sync.run`** — `account.balance` and other httpx callers still log full tracebacks. Tracked in [`harness-backlog.md`](harness-backlog.md).
- **Urgency cap is deterministic regex on thread role lines** — disagrees with LLM judgment in edge cases (auto-template "thanks for your inquiry" replies mark user as last replier, cap fires even when the contact is the one waiting). Mario's option B was explicit; refine to "ignore senders in a known-automated set" if false-low rate gets high. (The multi-thread mis-judgment — judging the last-rendered sibling instead of the newest turn — is FIXED as of `b889eb8`; this caveat is now only about the auto-template edge case.)
- **`send_sms` (credits proxy) not live-verified** — `tools/sms_send.py` / `tools/sms_tools.SendSMSTool` / `solve_tools._send_sms` import clean and match `mrcall-agent/api/routes/desktop_sms.py`, but no real SMS has been sent end-to-end and the prod `mrcall-agent` route's deployment isn't confirmed. A stale `sms_tools` comment lingers in `tools/config.py:54`.
- **Behavioral_rule guard depends on the model declaring `entry_type`** — if the model omits it, `update_memory` on a contact blob is NOT blocked. Approval card is the human backstop.
- **WA voice transcription dev-verified only** — live neonize `download_any` + packaged bundling of ctranslate2/av (+~50–100 MB) not verified. Tracked.
- **`tools/calendar_sync.py` partial scaffolding** — wiring to `provider='google_calendar'` OAuth tokens pending.
- WhatsApp session DB (`~/.zylch/whatsapp.db`) is global, not per-profile — multi-profile with different WA accounts not supported. **Now LIVE-relevant**: the `mrcalld` cross-machine deploy runs N profiles under one Linux user sharing one whatsapp.db → run ≤1 WhatsApp profile until it's per-profile (see `remote-backend.md` Caveats, `multi-profile-routing.md` R2).
- Slash-separated phones (`02 316562 / 338 594946`) parsed as one value. Tracked.
- `LID:` kind not indexed on profiles that haven't retrained memory agent (cross-channel match still works via `Phone:` resolved from `whatsapp_contacts`).
- **`sandbox_service` dangling import** — `command_handlers.py:171` + `chat_service.py:399` import a missing module. Lazy branch; harmless until reached.

## Where stable state lives

| What | Where |
|---|---|
| Module map, dependency direction, data flow | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Code style, patterns, logging, security | [`CONVENTIONS.md`](CONVENTIONS.md) |
| Tech stack, dependency rules, imperatives | [`system-rules.md`](system-rules.md) |
| Module quality assessment + live test ledger | [`quality-grades.md`](quality-grades.md) |
| Enforcement / tooling gaps | [`harness-backlog.md`](harness-backlog.md) |
| Per-feature reference docs | [`features/`](features/) |
| Active execution plans | [`execution-plans/`](execution-plans/) |
| JSON-RPC method surface | [`../../docs/ipc-contract.md`](../../docs/ipc-contract.md) |
| Cross-cutting recent state | [`../../docs/active-context.md`](../../docs/active-context.md) |
| App-side recent state | [`../../app/docs/active-context.md`](../../app/docs/active-context.md) |
| Firebase auth, BYOK vs MrCall credits, transport model | [`../CLAUDE.md`](../CLAUDE.md) |
