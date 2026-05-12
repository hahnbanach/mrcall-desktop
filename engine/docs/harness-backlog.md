# Harness Backlog

Enforcement gaps, missing tooling, and documentation debt.

## Open

- [ ] **`tests/storage/test_data_backfills.py::test_init_db_invokes_channel_backfill_when_thread_id_backfill_is_noop` broken at HEAD (2026-05-12).**
  - Setup fails with `sqlite3.IntegrityError: NOT NULL constraint failed: task_items.pinned` when the fixture inserts a synthetic task row that omits the `pinned` column. The schema gained a `NOT NULL` on `pinned` (probably with a column-add migration that lacked a default) some time after this test was written; the test fixture never got updated.
  - Pre-existing on `c5c1922d` (HEAD before the whatsapp-pipeline-parity Phase 2 landing). Confirmed via `git stash; pytest …`.
  - The sibling test in the same file (`test_apply_data_backfills_calls_every_step`) is green, so the dispatcher-orchestration regression check still runs — only the integrity check via a real init_db is broken.
  - Fix: add `pinned=0` to the test INSERT, OR change the model to have `default=False`. Latter is the cleaner fix because production callers that insert via the ORM rely on the default being false; bare-SQL callers in tests are the exception.

- [ ] **`_normalise_phone` doesn't split on `/`-separated phones (Phase 1a era, surfaced during Phase 2 live verification).**
  - Real Mario data: a blob `#IDENTIFIERS` block containing `Phone: 02 316562 / 338 594946` is parsed as a single value. `_normalise_phone` strips spaces/dots/dashes/parens/slashes BUT does not treat ` / ` as a value separator, so the two phones get concatenated into one 18-digit "phone" `023165623385949462`, indexed in `person_identifiers` as `kind='phone'`. False-match risk if any unrelated entity has this concatenation as a substring.
  - `_parse_identifiers_block` splits multi-value lines on `,` only. Add ` / ` (slash with whitespace) as an additional split delimiter; bare `/` mid-number must stay valid (e.g. `+39/02-…` formatting). 14 such rows visible on the gmail profile before the Phase 2 cleanup; after the cleanup the count reverts to whatever the cosine-fallback / future re-extractions produce.

- [ ] **`LID:` kind never indexed on profiles that haven't retrained the memory agent.**
  - Phase 2b added the `memory_message` storage key + channel-aware META_PROMPT that explicitly instructs the LLM to emit `LID:` lines for WhatsApp messages. The worker reads `memory_message` first and falls back to legacy `memory_email` (`engine/zylch/workers/memory.py:_get_extraction_prompt`), so an existing profile keeps booting fine — but the legacy prompt has no `LID:` instruction, so `person_identifiers.kind='lid'` rows never get written.
  - Cross-channel match works anyway via `Phone:` (resolved from `whatsapp_contacts`), so this is a *future-proofing* gap, not a current functional break. The gap closes either when the user retrains (`/agent memory train email` or the Settings → Maintenance button if one ever exists) or when a future schema-change migration force-invalidates the legacy key.
  - Recommendation: add a one-shot auto-retrain prompt on startup if `get_agent_prompt('memory_message')` is None but `get_agent_prompt('memory_email')` is not None, OR document the "retrain after upgrade" step in a release-notes file users can read.

- [ ] **`tests/workers/test_task_worker_bugs.py` further out of sync (2026-05-06).**
  - Already broken by the 2026-05-04 transport refactor (mocks removed
    `LLMClient` attribute on `task_creation`).
  - Fase 1.1 (`3473348`) widened the gap further — `_collect` now calls
    `get_tasks_by_contact` (plural) instead of `get_task_by_contact`
    (singular). 8 mock setups in this test file still stub the singular.
    Even if the LLMClient mock is restored, contact-task assertions
    will not match the new shape until they're rewritten against the
    plural API and the new dedup'd `existing_tasks_all`.
  - Fase 1.5 (`89c9398`) and Fase 1.3 (`d2aca2a`) further changed the
    shape of `existing_task_context` (notification-class threshold,
    calendar create→update conversion). Any mock relying on the
    old skip-or-include rule will mis-assert.
  - Recommended: rewrite this file as a harness pass, against a real
    Storage backend (in-memory SQLite is fine) instead of MagicMock —
    the LLMClient is the only piece worth mocking.

## Resolved

- [x] `tools/factory.py` exceeds 500-line limit → split into 6 modules (2026-04-01)
- [x] `SupabaseStorage` misleading name → renamed to `Storage` (2026-04-01)
- [x] `ScheduledJob` and `ThreadAnalysis` unused models → removed in SQLite migration (2026-04-01)
- [x] `integration_providers` SQL migrations redundant → removed with Alembic (2026-04-01)
- [x] ONNX_WEIGHTS_NAME import error → resolved by switching to fastembed (2026-04-01)

## Open

- [ ] **Two functions claim to resolve `owner_id` and disagree.**
  Discovered: 2026-05-06 (during the WhatsApp-empty-list bug investigation)
  - ``cli/utils.get_owner_id()`` returns ``EMAIL_ADDRESS`` (fallback
    ``"local-user"``). Used by all RPC handlers, ``process_pipeline``,
    ``WhatsAppSyncService``.
  - ``config.settings.owner_id`` is a Pydantic field that reads the
    ``OWNER_ID`` env var (fallback ``"owner_default"``). Used to live
    in three call-sites: ``telegram/bot.py:_get_owner_id`` (fixed),
    ``api/token_storage.py:_owner`` (fixed), and
    ``tools/config.py:ToolConfig.from_settings`` (still divergent).
  Impact: rows written under the EMAIL_ADDRESS key are invisible to
  any caller that resolves owner_id via ``settings.owner_id`` — and
  vice versa. The WhatsApp tab showed zero conversations on Firebase
  profiles because of exactly this; same shape would silently hit
  the Telegram bot and any tool constructed via
  ``ToolConfig.from_settings`` (no per-owner wiring).
  Recommendation: collapse to one canonical function. The cleanest
  is to delete ``settings.owner_id`` entirely (and the
  ``"owner_default"`` fallback string with it) so there is only ONE
  way to resolve owner_id. Alternative: keep the field but make
  ``get_owner_id()`` consult it as a fallback when EMAIL_ADDRESS is
  unset, then audit every call-site once. Tracked here because the
  ``ToolConfig`` rewrite touches many tool factories and warrants
  its own PR.

- [ ] No linter or CI check enforcing the 500-line file limit
  Discovered: 2026-03-17
  Impact: Large files accumulate silently (command_handlers.py now 5137 lines, gmail_tools.py 988)
  Update: black + ruff installed in venv/ (2026-04-03) but no CI pipeline yet

- [ ] `oauth_tokens.last_sync` field is never written by any code path
  Discovered: 2026-04-03
  Impact: Dashboard works around it using newest email date; `chat_service.py` auto-sync check may be broken

- [x] `/process` pipeline was fire-and-forget (used background jobs) → rewritten to run synchronously (2026-04-04)

- [x] `blob_storage.py` passed `uuid.UUID()` objects to SQLite (only accepts strings) → fixed (2026-04-04)

- [x] Auth errors (401) swallowed at 3 levels (worker, job_executor, handler) → re-raise at all levels (2026-04-04)

- [ ] Memory extraction is slow (~2 emails/min) due to sequential LLM calls
  Discovered: 2026-04-04 QA
  Impact: `/process` on 190 emails takes ~90 minutes; consider parallel LLM calls or batching

- [ ] `tests/` directory entirely stale — references old SaaS architecture
  Discovered: 2026-04-01 standalone transformation
  Impact: No test coverage at all; regressions undetectable

- [ ] No end-to-end test for `zylch init` → `zylch sync` → `zylch tasks`
  Discovered: 2026-04-01 standalone transformation
  Impact: Full flow untested with real IMAP + LLM

- [ ] No test for incremental task prompt generation
  Discovered: 2026-04-01 QA session
  Impact: Prompt reconsolidation logic untested

- [ ] No test for notification dedup in storage.create_notification()
  Discovered: 2026-04-01 QA session
  Impact: Duplicate banners could return if dedup logic regresses

- [ ] No test for auto-sync trigger in chat_service.py
  Discovered: 2026-04-01 QA session
  Impact: Auto-sync could fail silently or trigger every message

- [ ] Stale modules: `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/`
  Discovered: 2026-04-01 standalone transformation
  Impact: Dead code, confusing for new contributors

- [ ] `command_handlers.py` still has SaaS-era `/connect` stubs
  Discovered: 2026-04-01 standalone transformation
  Impact: User sees broken UI for provider connections

- [ ] `chat_service.py` still references MrCall routing paths
  Discovered: 2026-04-01 standalone transformation
  Impact: Dead code paths, potential runtime errors

- [x] `docs/` has many stale files referencing old SaaS architecture → cleaned up (2026-04-01)

- [ ] neonize Go runtime prints "Press Ctrl+C to exit" to stdout — not suppressible from Python
  Discovered: 2026-04-04
  Impact: Cosmetic noise in CLI output during WhatsApp connect

- [ ] neonize `get_all_contacts()` API does not exist — contacts derived from messages instead
  Discovered: 2026-04-04
  Impact: Contact sync depends on having messages first; no standalone contact fetch

- [ ] WhatsApp session DB (`~/.zylch/whatsapp.db`) is global, not per-profile
  Discovered: 2026-04-04
  Impact: Multi-profile with different WA accounts not supported
  19 SaaS-only files deleted, 8 files rewritten for standalone, README index rebuilt
