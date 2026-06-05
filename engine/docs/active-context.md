---
description: |
  Engine-side state of mrcall-desktop. Current focus + recent landings +
  known issues. Older context lives in git history, `execution-plans/`,
  and `features/`. This file is a working list, not a changelog — keep
  it ≤ ~150 lines. /doc-endsession prunes anything older than ~2 weeks.
---

# Active Context — Engine

## Current focus (as of 2026-06-04)

**Correction-learning landed (merged from `origin/main`).** When the user edits an approval-gated send (`send_email`/`send_whatsapp`/`send_sms`) before approving it, `task_executor` captures the `{tool_name, proposed, edited}` diff; after the send, `services/correction_learning.learn_from_corrections` (fire-and-forget bg task in `rpc/methods`) judges each diff TWICE with a cheap Haiku pass — as a durable **rule** (tone/policy → `prefs:<owner>` blob, injected always-on into generation via `solve_constants.get_operating_rules_block`) and as a corrected **business fact** (price/term → `services/facts_store`, `facts:<owner>` namespace, category-tagged, deduped by exact (Category, Key), retrieved all-and-only by category through the new `list_fact_categories`/`get_facts_by_category` solve tools). `APPROVAL_TOOLS` gained `send_email`/`send_whatsapp` so their edits are captured. NOT yet live-verified by us (background path; never blocks the send).

**Cross-machine backend live on the Scaleway VPS.** The engine runs as a persistent daemon reachable from the Mac over `wss://desktop.mrcall.ai` (Caddy + Let's Encrypt), not just the local stdio sidecar. New: `rpc/dispatch.py` — the transport-agnostic dispatch core BOTH stdio (`rpc/server.py`) and the WS server route through (and where `_redact_params` now lives); `rpc/server_ws.py` (`zylch serve --ws HOST:PORT | --unix <socket>`); `rpc/firebase_auth.py` (RS256 verify of the Firebase ID token; handshake gate `uid == OWNER_ID`); `auth.refresh` + close-code 4401 on expiry; `config.firebase_project_id`; deps `websockets` + `pyjwt[crypto]`. Deployed via the `zylch-server@<uid>` systemd template behind Caddy. **Multi-profile routing now LIVE (2026-06-05):** a dedicated `mrcalld` service user + one daemon per profile on a per-uid Unix socket + static Caddy `path_regexp` + idempotent `sudo update-daemons.sh`; `server_ws.py` `chmod(0o660)`+stale-`unlink` on the socket; `<prod-uid>` migrated `mal`→`mrcalld`. See [`multi-profile-routing.md`](../../docs/execution-plans/multi-profile-routing.md) + [`remote-backend.md`](../../docs/remote-backend.md).

**MrCall credits routing finally end-to-end live.** The leak that kept `<prod-profile>`'s balance frozen for days was `ANTHROPIC_API_KEY` exported in `~/.bash_profile` bleeding into the sidecar via Pydantic Settings' env-var merge — every "I'm on credits" UI claim was actually a BYOK direct call. `llm/client._read_profile_anthropic_key` now reads ONLY the active profile's `.env`, ignoring shell env. Companion fixes: `llm/proxy_client._wrap_gzip_iter` defensively inflates a gzipped SSE body that arrived without `Content-Encoding` (the prod `mrcall-agent` flushed raw `aiter_raw()` bytes downstream — the server-side commit on `mrcall-agent/production` now pins `accept-encoding: identity` upstream + uses `aiter_bytes()`, but client side stays defensive). The shared dispatcher (`rpc/dispatch.py` since the cross-machine refactor) masks `id_token` / `access_token` / `api_key` / `password` / `client_secret` in its DEBUG `params=` line — the renderer's narration pipeline was scooping the Firebase JWT off stderr and shipping it to Anthropic. `cli/main.py` default `LOG_LEVEL` is now `DEBUG` (Mario's standing policy: mrcall-desktop boots loud).

**Tasks reanalyze now sees WhatsApp threads.** `workers/thread_presenter.build_whatsapp_thread_history` mirrors the email-side renderer (USER REPLY ✓ / CONTACT / AUTO-REPLY, voice-note transcriptions). `workers/task_reanalyze` detects WA tasks via `channel=='whatsapp'` or `sources.whatsapp_chat_jid` and routes. Two adjacent landings: (a) urgency cap — when the last non-auto turn is the user, medium/high gets capped to low ("proactive nudge" policy, reason annotated); (b) `EMAIL_ALIASES` config — `_is_user_email` and the thread renderer recognise secondary identities (Ivan from `carol@example.com` on a profile keyed under `<prod-profile>`) as the user.

**Solve loop becomes opt-in + self-closing.** `tasks.solve.event.done.result` now carries `auto_reanalyzed = {action, reason}` when the executor ran any mutating tool (send_email / send_whatsapp / send_sms / update_memory / run_python); `_send_email` and `_send_whatsapp` mirror their outbound row into the local store keyed on Message-ID / SendResponse.ID so reanalyze sees the user's reply without a full IMAP sync.

## Recent landings (last ~2 weeks)

| Date | What | Refs |
|---|---|---|
| 2026-06-05 | **Multi-profile routing LIVE.** `mrcalld` user + per-uid Unix sockets (`serve --unix`) + static Caddy `path_regexp` + `update-daemons.sh`. `rpc/server_ws.py`: socket `chmod 0o660` after bind + `unlink` stale socket before bind (caddy-connectable + clean respawn on py3.12). Unit reworked (mrcalld / `--unix` / `UMask=0007` / StartLimit / `ExecStopPost`) + new `scripts/tmpfiles.d/mrcalld.conf` + `scripts/server/update-daemons.sh`. `<prod-uid>` migrated `mal`→`mrcalld`, data intact (54 email / 18 task). | [multi-profile-routing.md](../../docs/execution-plans/multi-profile-routing.md) |
| 2026-06-04 | **Deploy via git + 6 stale tests removed.** Engine deploys/updates by `git clone`/`git pull` → `~/mrcall-desktop/engine` (was rsync → `~/zylch-engine`; profile stays rsync — private, not in git); systemd `ExecStart` follows. Operator + agent runbook: [`../../docs/remote-backend.md`](../../docs/remote-backend.md). Removed 6 stale red tests (intentional-change drift); suite green (303 passed). | `fa2598d2..ccfa0143` |
| 2026-06-03 | **Correction-learning merged** (`origin/main`): `services/correction_learning` + `services/facts_store`; rules → `prefs:`, facts → `facts:` (category all-and-only); solve tools `list_fact_categories`/`get_facts_by_category`; `APPROVAL_TOOLS` += `send_email`/`send_whatsapp`. | `a63b33d3..f83b9d14` |
| 2026-06-02 | **Cross-machine transport — Phase 1–3b** (live: `wss://desktop.mrcall.ai`). `rpc/dispatch.py` (transport-agnostic core + `_redact_params`), `rpc/server_ws.py` (`serve --ws`/`--unix`, Firebase-JWT handshake gate), `rpc/firebase_auth.py` (RS256), `auth.refresh`/4401, `config.firebase_project_id`, deps `websockets`+`pyjwt`. VPS: `~/zylch-engine` venv, `zylch-server@<uid>` systemd template, Caddy/LE. (Multi-profile per-uid sockets → landed 2026-06-05.) | [cross-machine-transport.md](../../docs/execution-plans/cross-machine-transport.md) |
| 2026-05-31 | **MrCall credits — five fixes**: shell-env leak (`llm/client._read_profile_anthropic_key`); defensive gzip-SSE inflate (`llm/proxy_client._wrap_gzip_iter`); secret redaction in dispatcher `params=` log (`rpc/dispatch._redact_params`); `LOG_LEVEL` default DEBUG (`cli/main.py`); `config.email_aliases` field. Tests: autouse `_isolate_profile_dir` provisions a per-test profile so `MemoryWorker`/`LLMMergeService`/`TaskWorker` constructors work without the dev machine's shell env. Companion deploy on `mrcall-agent/production`: `accept-encoding: identity` upstream + `aiter_bytes()` forward + pricing YAML aligned with Anthropic 2026-05 (Opus 4.7 was wrongly priced at $15/$75; new Opus 4.8 + Haiku 4.5 dated IDs added). | `ed6eeef8` |
| 2026-05-31 | **Solve lightbulb + auto-reanalyze + outbound mirror**: `task_executor` tracks `mutating_actions_taken`; `rpc/methods._maybe_reanalyze_after_solve` runs `reanalyze_task` after a mutating solve and decorates the done event; `solve_tools._send_email` upserts into `emails` keyed on Message-ID, `_send_whatsapp` reuses the persistent `_active_client` + calls `WhatsAppSyncService.store_outgoing` (resolves canonical `chat_jid` from `whatsapp_contacts.phone_number` to avoid LID/phone split). Removes the throwaway-neonize-client kick that previously fired `<conflict type="replaced"/>` on every Solve. | `9be36c9b` |
| 2026-05-31 | **Tasks reanalyze with WA history + urgency cap + EMAIL_ALIASES**: new `build_whatsapp_thread_history` + `is_last_turn_user_reply` + `cap_urgency_for_silent_followup` in `workers/thread_presenter`; `reanalyze_task` branches on channel and passes aliases through primary + sibling threads; cap applied (medium/high → low when last non-auto turn is user); `TaskWorker._is_user_email` consults `EMAIL_ALIASES`; `_analyze_event` cap applied + previously-dropped `target_task_id`/`title` now propagate; settings_schema gains `EMAIL_ALIASES`. | `109bfd99` |
| 2026-05-31 | **WhatsApp end-to-end**: `whatsapp.threads.changed` notification from `_on_message`/`_on_history` (renderer debounces + re-fetches); `_extract_timestamp` falls back to `event.SourceWebMsg.messageTimestamp` for offline catch-up (fixes 717-message timestamp collapse); `handle_history_sync` reads `event.Data` (capital D — proto field name) so the path stops always logging "0 conversations"; `process_pipeline._run_whatsapp_sync` reuses the persistent `_active_client` (no more `<conflict type="replaced"/>` + EOF per Update); `task_creation_whatsapp._resolve_wa_sender` prefers rubric `name` over Pushname (Roberto Scoppa no longer becomes "Imperatore"). | `0e576197` |
| 2026-05-28 | Onboarding hub (`sync.run`, `setup.state`) + async trainers (`_generate_prompt` awaits `create_message` — fixes `whatsapp.status` timeout during `agents.train_all`). | `d3de37ac` |
| 2026-05-26 | `humanize_error` classifier (`services/error_messages`); memory `template:<owner>` namespace + `entry_type` guard; `_resolve_host` defaults unknown domains to Google; multi-folder IMAP search; `whatsapp_search` shared helper backs `whatsapp.send_message` + `whatsapp.search_messages`. | `ca784d0d..4e243bdb` |
| 2026-05-26 | `agents.train_all` RPC (memory_message → task_email → emailer serial + `agents.train.progress`); WhatsApp 1-on-1 samples folded into `MessageMemoryAgentTrainer`. | `3c152cc7` |
| 2026-05-22 | Current datetime injected into EVERY LLM request (single LLMClient chokepoint + chat_compaction bypass). | `5f5c73e8` |
| 2026-05-20 | MrCall delegated/PKCE OAuth + `/mrcall` command surface + `mrcall_link` removed (−~3000 LOC); StarChat via Firebase JWT only; `mrcall.search_businesses` RPC. | `770522e8..2b0a54ce` |

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
- **Urgency cap is deterministic regex on thread role lines** — disagrees with LLM judgment in edge cases (auto-template "thanks for your inquiry" replies mark user as last replier, cap fires even when the contact is the one waiting). Mario's option B was explicit; refine to "ignore senders in a known-automated set" if false-low rate gets high.
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
