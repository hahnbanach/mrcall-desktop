# Implementation Plan -- QA Fixes for Zylch Standalone

**Date**: 2026-03-31
**Source**: `docs/qa/standalone-qa-report.md`
**Status**: Ready for implementation

---

## Work Streams

Items are grouped into three parallel work streams. Within each stream, items
are ordered by dependency. Streams A, B, and C can proceed in parallel.

```
Stream A (Data/Infra)     Stream B (Commands/Docs)     Stream C (AI Quality)
  1. Seed providers         2. Remove /gaps               3. Fix task priorities
  7. Fix duplicate migration  5. Auto-sync on login       4. Memory person facts
  6. Fix OAuth redirect_uri
```

---

## Priority 1 -- Blockers

### Item 1: Seed `integration_providers` in Alembic

**Problem**: Fresh deploys have an empty `integration_providers` table. The seed
SQL exists in `zylch/integrations/migrations/001_create_providers_table.sql`
(and follow-up files 003-006) but is not wired into Alembic.

**Files to modify**:
- `alembic/versions/0004_seed_integration_providers.py` (NEW)

**What to change**:
1. Create new Alembic migration `0004` with `down_revision = "0003"`.
2. In `upgrade()`, execute the seed INSERT from
   `zylch/integrations/migrations/001_create_providers_table.sql` lines 28-52
   (the INSERT with ON CONFLICT DO NOTHING).
3. Then execute the UPDATE statements from lines 77-80 (config_fields for
   pipedrive, vonage, anthropic, mrcall).
4. Then execute the INSERTs from `005_add_openai_mistral_providers.sql`
   (openai + mistral providers, anthropic description update).
5. Then execute the UPDATEs from `006_add_env_vars_to_config_fields.sql`
   (env_var fields for all API-key providers).
6. All statements use ON CONFLICT DO NOTHING or UPDATE with WHERE, so they
   are safe to run on databases that already have the data.
7. In `downgrade()`, delete from `integration_providers` where `provider_key`
   is in the seeded list.

**Do NOT include**: The ALTER TABLE statements from 001 (lines 55-67) or
the CREATE TABLE -- those are already handled by `0001_initial_schema.py`.
Verify by checking the initial schema migration.

**Complexity**: S
**Dependencies**: None (0003 already exists).

---

### Item 2: Remove `/gaps` command

**Problem**: `/gaps` is documented but was never implemented. It returns
"Command not found". Gap detection is handled by `/tasks`.

**Files to modify**:
- `docs/guides/cli-commands.md` -- bulk of the changes
- `zylch/services/sync_service.py` -- line 103, comment reference
- `zylch/api/routes/chat.py` -- line 112, docstring reference
- `zylch/api/routes/commands.py` -- line 29, docstring reference
- `docs/features/relationship-intelligence.md` -- description header mentions
  "gap detection" but no `/gaps` command references (leave as-is, the concept
  is valid, just the command does not exist)

**What to change in `docs/guides/cli-commands.md`**:
1. Remove the description header reference to `/gaps` (line 3):
   change `"/gaps (relationships)"` to just remove it from the list.
2. Remove `/gaps` from the features list (line 17).
3. Remove the entire `/gaps [days]` section (lines 366-386).
4. In the COMMAND REFERENCE box (line 1433): remove `/gaps` from the
   Data line.
5. In the daily workflow example (lines 1521-1525): replace `/gaps` step
   with `/tasks` and update surrounding text.
6. In the "Instead of" section (line 1590): remove `/gaps 1`.
7. In the sequential workflow example (lines 1608-1613): replace `/gaps`
   with `/tasks`.
8. In the performance table (line 1740): remove the `/gaps` row.
9. Remove the "Gaps Not Showing" troubleshooting section (lines 1786-1805).
10. Wherever `/gaps` was the next step after `/sync`, replace with `/tasks`
    and add a note: "Gap detection is integrated into task analysis."

**What to change in code files**:
- `zylch/services/sync_service.py` line 103: change comment from
  "AI analysis is done separately via /gaps command" to
  "AI analysis is done separately via /tasks command".
- `zylch/api/routes/chat.py` line 112: change docstring example from
  `"/sync", "/gaps", "help"` to `"/sync", "/tasks", "help"`.
- `zylch/api/routes/commands.py` line 29: change docstring example from
  `'/gaps'` to `'/tasks'`.

**Complexity**: S
**Dependencies**: None.

---

### Item 3: Fix task priorities (all MEDIUM)

**Problem**: The task detection LLM generates `urgency: "high" | "medium" | "low"`
but in practice almost everything comes back as MEDIUM. The meta-prompt in
`task_email.py` says "emails older than 2 weeks cannot be high urgency" but
gives no positive guidance on when to use HIGH.

The tool schema in `task_creation.py` (TASK_DECISION_TOOL) defines
`"enum": ["high", "medium", "low"]` -- there is no CRITICAL level.

**Root cause**: Two places need changes:
1. The meta-prompt (`TASK_AGENT_META_PROMPT` in `task_email.py`) that
   generates the per-user task detection prompt.
2. The tool schema (`TASK_DECISION_TOOL` in `task_creation.py`) that
   constrains LLM output.

**Files to modify**:
- `zylch/agents/trainers/task_email.py` -- TASK_AGENT_META_PROMPT
- `zylch/workers/task_creation.py` -- TASK_DECISION_TOOL schema
- `zylch/storage/storage.py` -- urgency_order dicts (add "critical")

**What to change**:

**(a) `task_creation.py` -- TASK_DECISION_TOOL**:

Change the urgency enum from:
```python
"enum": ["high", "medium", "low"],
"description": "high=urgent/blocking, medium=needs attention this week, low=when time permits"
```
to:
```python
"enum": ["critical", "high", "medium", "low"],
"description": (
    "critical=angry customer, payment dispute, churn risk, explicit deadline today; "
    "high=unanswered direct question >48h, broken commitment, escalation; "
    "medium=needs attention this week, routine follow-up; "
    "low=when time permits, informational"
)
```

**(b) `task_email.py` -- TASK_AGENT_META_PROMPT**:

In section `2. URGENCY WITH TIME DECAY`, replace the current text (lines 67-71)
with explicit urgency criteria:

```
2. **URGENCY LEVELS (USE ALL FOUR)**
   - CRITICAL: angry/frustrated customer, payment dispute, risk of churn,
     explicit deadline today or past-due. These are rare but must stand out.
   - HIGH: direct question unanswered >48h, broken promise/commitment,
     escalation from previous lower-urgency item, VIP contact waiting.
   - MEDIUM: routine follow-up needed this week, new inquiry, standard
     support question.
   - LOW: informational, nice-to-have follow-up, when time permits.

   Time decay: emails older than 2 weeks cannot be CRITICAL.
   But a 5-day-old unanswered customer question is still HIGH.

   IMPORTANT: Do NOT default to MEDIUM. Actively evaluate sentiment,
   time elapsed, and business impact. If the customer uses angry language
   ("furious", "unacceptable", "cancel", "disappointed"), that is at
   minimum HIGH, possibly CRITICAL.
```

Also update the output examples (lines 97-104) to include a CRITICAL example:
```
- `ACTION: critical | Call customer immediately | Customer explicitly angry about config change, risk of cancellation`
```

**(c) `zylch/storage/storage.py`** -- two urgency_order dicts:

Line 2353: add `'critical': 4` to the dict.
Line 2458: add `'critical': -1` (so critical sorts before high in display).

**Complexity**: M
**Dependencies**: After this change, users must re-train their task prompt
via `/agent train tasks` for the new urgency levels to take effect. Add a
log message in `task_creation.py` if the returned urgency is not in the
updated enum.

---

## Priority 2 -- Significant UX

### Item 4: Memory processing should extract person facts

**Problem**: `/memory search "Antonietta Lonati"` returns generic TEMPLATE
entities instead of PERSON facts. The memory processing in
`zylch/agents/trainers/memory_email.py` correctly defines PERSON, COMPANY,
and TEMPLATE entity types, but the trained prompt apparently over-indexes
on TEMPLATEs.

**Root cause**: The `EMAIL_AGENT_META_PROMPT` in `memory_email.py` has
section 5 "IMPORTANCE ASSESSMENT" (line 158) that says:
`"PRIORITIZE TEMPLATE extraction"`. This biases the LLM toward templates
over person/company entities.

**Files to modify**:
- `zylch/agents/trainers/memory_email.py` -- EMAIL_AGENT_META_PROMPT

**What to change**:

1. In section 5 "IMPORTANCE ASSESSMENT" (around line 158-163), change:
   ```
   - PRIORITIZE TEMPLATE extraction -- templates that appear multiple times
     are the highest-value entities because they directly save user time
   ```
   to:
   ```
   - PRIORITIZE PERSON and COMPANY extraction -- every non-trivial contact
     should have a PERSON entity with their role, company, and relationship
     history. TEMPLATEs are also valuable but secondary to relationship data.
   - For PERSON entities: always include what you can infer about who they are,
     what company they represent, and the nature of their relationship with
     the user (customer, prospect, partner, vendor, colleague).
   - For TEMPLATE entities: only extract when the user has sent substantially
     similar responses to 3+ different contacts on the same topic.
   ```

2. In the entity format suffix (`_get_entity_format_suffix`, line 206+),
   reorder the example to show PERSON first (it already does, so just
   verify the example emphasizes person extraction).

3. Add to the generated prompt instructions (section 3, EXTRACTION RULES,
   around line 79-85):
   ```
   - For EVERY external sender in the email, create or update a PERSON entity.
     Even if the email is routine, record what you learn about the person.
   ```

**Complexity**: M
**Dependencies**: After this change, users must re-train their memory prompt
via `/agent train memory`. Existing blobs are not affected -- only new
processing will produce more person entities. Consider adding a note in
the `/agent train memory` output suggesting to run `/memory --reset` and
re-process to rebuild with the new prompt.

---

### Item 5: Auto-sync on login (if last sync > 24h)

**Problem**: Users must manually run `/sync` every time. If last sync was
more than 24 hours ago, the system should trigger a background sync when
the user sends their first message.

**Files to modify**:
- `zylch/services/chat_service.py` -- `process_message()` method

**What to change**:

1. At the top of `process_message()` (around line 170, after the notification
   check), add an auto-sync check:

```python
# Auto-sync check: if last sync > 24h, trigger background sync
try:
    from zylch.storage.models import OAuthToken
    from datetime import datetime, timedelta, timezone
    from zylch.storage.database import get_session

    with get_session() as session:
        token = session.query(OAuthToken).filter(
            OAuthToken.owner_id == user_id,
            OAuthToken.provider.in_(["google", "microsoft"]),
        ).first()

        if token and token.last_sync:
            hours_since_sync = (
                datetime.now(timezone.utc) - token.last_sync
            ).total_seconds() / 3600
            if hours_since_sync > 24:
                logger.info(
                    f"[AUTO-SYNC] Last sync {hours_since_sync:.0f}h ago "
                    f"for {user_id}, triggering background sync"
                )
                # Import and trigger sync as background job
                from zylch.services.job_executor import submit_sync_job
                submit_sync_job(user_id)
                notification_banner = (
                    (notification_banner or "")
                    + "\n--- Auto-sync started (last sync was "
                    + f"{hours_since_sync:.0f}h ago) ---\n"
                )
        elif token and not token.last_sync:
            logger.debug(
                f"[AUTO-SYNC] Provider connected but never synced for {user_id}"
            )
except Exception as e:
    logger.warning(f"[AUTO-SYNC] Check failed: {e}")
```

2. Verify that `submit_sync_job` (or equivalent) exists in `job_executor.py`.
   If not, create a helper that enqueues a sync background job the same way
   `/sync` does. The sync command handler in `command_handlers.py` is the
   reference implementation.

3. Add a flag to prevent re-triggering on every message in the same session.
   Use `SessionState` (from `zylch/tools/factory.py`) to store
   `auto_sync_triggered: bool`. Check it before triggering.

**Complexity**: M
**Dependencies**: Requires a connected provider (Google/Microsoft) with
`last_sync` populated. The `OAuthToken.last_sync` column already exists
(model line 724).

---

## Priority 3 -- Polish

### Item 6: Fix OAuth redirect_uri

**Problem**: The OAuth redirect_uri falls back to `api_server_url` which
defaults to `http://localhost:8000`. If the server runs on a different port,
OAuth breaks.

**Files to modify**:
- `zylch/api/routes/auth.py` -- lines 1099-1102 and 1170-1172
- `zylch/config.py` -- verify `api_server_url` default

**What to change**:

The current code (auth.py lines 1099-1102):
```python
redirect_uri = settings.google_oauth_redirect_uri
if not redirect_uri:
    redirect_uri = f"{settings.api_server_url}/api/auth/google/callback"
```

This is actually correct -- it uses `settings.api_server_url` as fallback.
The real issue is that `api_server_url` defaults to `http://localhost:8000`
in `config.py` (line 93) and users do not override it when running on a
different port.

Two options:

**(a) Derive from request (preferred)**:
In the OAuth initiation endpoint, detect the actual server URL from the
incoming request object:

```python
redirect_uri = settings.google_oauth_redirect_uri
if not redirect_uri:
    # Derive from incoming request
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}api/auth/google/callback"
```

This requires adding `request: Request` as a parameter to the endpoint
function (FastAPI injects it automatically).

Apply the same fix at both locations (lines 1099-1102 and 1170-1172).

**(b) Also fix line 1467**: The hardcoded `http://localhost:8766/callback`
for CLI callback is intentional (the CLI runs its own local server on 8766),
so leave it as-is.

**Complexity**: S
**Dependencies**: None.

---

### Item 7: Fix duplicate Alembic migration

**Problem**: The error_logs migration was originally `0002` but renamed to
`0003`. The file `alembic/versions/0003_add_error_logs.py` has
`revision = "0003"` and `down_revision = "0002"` which is correct. However,
the docstring still says `Revision ID: 0002` (line 9 of the file).

**Current git status shows**:
- `D alembic/versions/0002_add_error_logs.py` (deleted)
- `?? alembic/versions/0003_add_error_logs.py` (untracked, new)

**Files to modify**:
- `alembic/versions/0003_add_error_logs.py` -- fix docstring

**What to change**:
1. Line 9: change `Revision ID: 0002` to `Revision ID: 0003`.
2. Stage the deletion of `0002_add_error_logs.py` and addition of
   `0003_add_error_logs.py` in git.

**Complexity**: S
**Dependencies**: Must be committed before Item 1 (the new 0004 migration
depends on 0003).

---

## Implementation Order

Given the dependency graph and parallel streams:

```
Phase 1 (can all run in parallel):
  - Item 7: Fix duplicate migration docstring (S, 5 min)
  - Item 2: Remove /gaps references (S, 30 min)
  - Item 6: Fix OAuth redirect_uri (S, 15 min)

Phase 2 (depends on Item 7):
  - Item 1: Seed integration_providers (S, 30 min)

Phase 3 (can all run in parallel):
  - Item 3: Fix task priorities (M, 1h)
  - Item 4: Memory person facts (M, 1h)
  - Item 5: Auto-sync on login (M, 1-2h)
```

Total estimated effort: ~4-5 hours.

---

## Verification Checklist

After implementation, verify each fix:

- [ ] `alembic upgrade head` runs cleanly on a fresh database
- [ ] `/connect status` shows all providers without manual SQL
- [ ] No references to `/gaps` in docs/ or zylch/ (grep for "gaps")
- [ ] `/tasks` output includes CRITICAL and HIGH urgency items after
      re-training (`/agent train tasks`)
- [ ] `/memory search "Antonietta Lonati"` returns PERSON entity after
      re-training (`/agent train memory`) and re-processing
- [ ] First message after 24h+ triggers background sync automatically
- [ ] `/connect google` generates correct redirect_uri on any port
- [ ] `alembic heads` shows single head (no "Multiple head revisions")
