# Zylch Avatar Integration Analysis - Swarm Agent Prompt

## CRITICAL CONTEXT

An avatar-based relational memory system was implemented on the `avatar` branch, but it was built **WITHOUT understanding how the actual Zylch CLI and services work**. The implementation is technically complete but **completely disconnected from the real code flow**.

**The problem**: Avatar triggers were added to `EmailSyncManager.sync_emails()`, but the CLI's `/sync` command uses a DIFFERENT code path (`SyncService` via `command_handlers.py`). The avatar code is orphaned.

## MISSION

Analyze the Zylch codebase across TWO branches to:
1. Understand the **main branch** (working Zylch product)
2. Understand the **avatar branch** (disconnected avatar implementation)
3. Create an integration plan that properly connects them
4. Document how to set up a virgin database from scratch

## BRANCH LOCATIONS

```
/Users/mal/hb/zylch-main    # MAIN BRANCH - Working product
/Users/mal/hb/zylch         # AVATAR BRANCH - Disconnected implementation
```

---

# PHASE 1: UNDERSTAND THE WORKING PRODUCT (main branch)

## Task 1.1: Map the CLI Architecture

**Goal**: Trace exactly how `/sync` works in the CLI

**Files to examine** (in `/Users/mal/hb/zylch-main/`):
- `zylch/cli/main.py` - CLI entry point
- `zylch/cli/app.py` - Textual app (if exists)
- `zylch/services/command_handlers.py` - Command handling (CRITICAL)
- `zylch/services/sync_service.py` - Sync service (if exists)

**Questions to answer**:
1. What happens when user types `/sync` in the CLI?
2. What service/function is actually called?
3. How is `owner_id` (Firebase UID) passed through the flow?
4. Where does email data actually get processed and stored?
5. What is `SyncService` vs `EmailSyncManager`? Which one is used?

## Task 1.2: Map the Email Flow

**Goal**: Understand how emails are fetched, analyzed, and stored

**Files to examine**:
- `zylch/tools/email_sync.py` - EmailSyncManager class
- `zylch/services/email_archive_manager.py` - Email archive (if exists)
- `zylch/tools/gmail_client.py` - Gmail API client (if exists)
- `zylch/storage/supabase_client.py` - Database layer

**Questions to answer**:
1. How does Gmail authentication work?
2. Where are emails stored after sync?
3. What tables are used? (`email_archive`, `threads`, etc.)
4. How are threads analyzed with Claude?
5. Where is the "analyzed threads" data stored?

## Task 1.3: Map the Task/Relationship System

**Goal**: Understand how relationships and tasks are currently computed

**Files to examine**:
- `zylch/tools/task_manager.py` - TaskManager class
- `zylch/services/context_builder.py` - Context building (if exists)
- Any files related to "tasks", "priorities", "relationships"

**Questions to answer**:
1. How are "tasks" currently generated?
2. What LLM calls are made per-request?
3. Where is the performance bottleneck (100s per page)?
4. How does `build_tasks_from_threads()` work?

## Task 1.4: Map Database Schema

**Goal**: Document the existing Supabase schema

**Files to examine**:
- Any SQL migration files in `docs/migration/`
- `zylch/storage/supabase_client.py` - All table references
- Supabase Dashboard (if access available)

**Tables to document**:
- `email_archive` - Raw emails
- `threads` - Analyzed threads
- `users` - User accounts
- Any other tables

---

# PHASE 2: UNDERSTAND THE AVATAR IMPLEMENTATION (avatar branch)

## Task 2.1: Inventory Avatar Files

**Goal**: List all files created/modified for avatar system

**New files** (in `/Users/mal/hb/zylch/`):
- `zylch/services/avatar_aggregator.py` - Context builder (NO LLM)
- `zylch/workers/__init__.py` - Workers package
- `zylch/workers/avatar_compute_worker.py` - Background worker
- `zylch/api/routes/avatars.py` - REST API endpoints
- `scripts/backfill_avatars.py` - Backfill tool
- `scripts/benchmark_avatar_performance.py` - Benchmarks
- `tests/integration/test_avatar_system.py` - Tests
- `railway.json` - Railway deployment
- `docs/migration/001_add_avatar_fields_v3.sql` - SQL migration
- `docs/RAILWAY_SETUP.md` - Deployment guide
- `docs/AVATAR_IMPLEMENTATION_SUMMARY.md` - Summary

**Modified files**:
- `zylch/storage/supabase_client.py` - +12 avatar methods
- `zylch/tools/task_manager.py` - +2 fast query methods
- `zylch/tools/email_sync.py` - +avatar triggers (WRONG PLACE!)
- `zylch/api/main.py` - +avatars router
- `Procfile` - +worker process

## Task 2.2: Understand Avatar Architecture

**Goal**: Document what the avatar system is supposed to do

**Read these files**:
- `docs/AVATAR_IMPLEMENTATION_SUMMARY.md` - Full documentation
- `zylch/services/avatar_aggregator.py` - Core logic

**Key concepts**:
1. **Avatars**: Pre-computed person representations
2. **identifier_map**: One person = multiple emails/phones
3. **avatar_compute_queue**: Background processing queue
4. **contact_id**: MD5 hash (12 chars) of normalized email
5. **Memory reconsolidation**: UPSERT-based updates

## Task 2.3: Identify the Integration Gap

**Goal**: Find where avatar triggers SHOULD go

**The problem**:
- Avatar triggers were added to `EmailSyncManager._trigger_avatar_updates()`
- But CLI `/sync` doesn't use `EmailSyncManager.sync_emails()`
- It uses something else (find out what in Phase 1)

**Questions to answer**:
1. What function in main branch handles `/sync`?
2. Where in THAT function should avatar triggers be added?
3. What data is available at that point (threads, contacts, owner_id)?

---

# PHASE 3: DATABASE SETUP FOR VIRGIN ENVIRONMENT

## Task 3.1: Document Full Schema

**Goal**: Create a complete database setup script

**Required tables** (combine main + avatar branches):

### From main branch:
- `users` - User accounts
- `email_archive` - Raw emails
- `threads` - Analyzed threads
- (document others found)

### From avatar branch:
- `avatars` - Pre-computed relationship intelligence
- `identifier_map` - Multi-identifier person resolution
- `avatar_compute_queue` - Background computation queue

**Output**: Single SQL file that creates ALL tables with:
- RLS policies for multi-tenant isolation
- Proper indices
- Correct column types (`owner_id` is TEXT, not UUID!)

## Task 3.2: Document Environment Variables

**Goal**: List ALL required environment variables

```bash
# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_ANON_KEY=

# Anthropic
ANTHROPIC_API_KEY=

# Firebase
FIREBASE_SERVICE_ACCOUNT_JSON=

# Gmail
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# (add others found)
```

## Task 3.3: Create Setup Instructions

**Goal**: Step-by-step virgin environment setup

1. Create Supabase project
2. Run SQL migrations
3. Configure Firebase project
4. Set up Google OAuth for Gmail
5. Configure environment variables
6. First run / user registration

---

# PHASE 4: INTEGRATION PLAN

## Task 4.1: Map Integration Points

**Goal**: Identify exact code changes needed

**Changes required**:
1. Where to add avatar triggers in the REAL sync flow
2. How to pass `owner_id` to avatar system
3. How to connect TaskManager to use avatars
4. How to connect CLI commands to avatar API

## Task 4.2: Create Integration Checklist

**Goal**: Step-by-step integration tasks

Example structure:
```
[ ] 1. Modify [file] to call avatar trigger after [function]
[ ] 2. Update [file] to pass owner_id to [function]
[ ] 3. Connect TaskManager.list_tasks_fast() to CLI
[ ] 4. Add /avatar CLI command
[ ] 5. Test end-to-end flow
```

## Task 4.3: Test Plan

**Goal**: Verify integration works

1. Fresh database setup
2. User registration
3. Gmail OAuth
4. Email sync (`/sync`)
5. Verify avatar queue populated
6. Run worker
7. Verify avatars created
8. Query avatars via API
9. Query avatars via CLI

---

# PHASE 5: DELIVERABLES

## Required Outputs

1. **Architecture Diagram**: Visual flow of main branch CLI
2. **Integration Gap Analysis**: What's wrong and where
3. **Database Schema**: Complete SQL for virgin setup
4. **Environment Setup Guide**: All variables and configs
5. **Integration Plan**: Specific code changes with file:line
6. **Test Plan**: End-to-end verification steps

## File Locations for Outputs

Save all outputs to `/Users/mal/hb/zylch/docs/integration/`:
- `01_main_branch_architecture.md`
- `02_avatar_branch_inventory.md`
- `03_integration_gap_analysis.md`
- `04_complete_database_schema.sql`
- `05_environment_setup.md`
- `06_integration_plan.md`
- `07_test_plan.md`

---

# AGENT ASSIGNMENTS

## Agent 1: Main Branch Analyst
- Focus: Phase 1 (Tasks 1.1-1.4)
- Branch: `/Users/mal/hb/zylch-main`
- Output: `01_main_branch_architecture.md`

## Agent 2: Avatar Branch Analyst
- Focus: Phase 2 (Tasks 2.1-2.3)
- Branch: `/Users/mal/hb/zylch`
- Output: `02_avatar_branch_inventory.md`

## Agent 3: Integration Architect
- Focus: Phase 4 (Tasks 4.1-4.3)
- Both branches
- Output: `03_integration_gap_analysis.md`, `06_integration_plan.md`

## Agent 4: Database Specialist
- Focus: Phase 3 (Tasks 3.1-3.3)
- Both branches
- Output: `04_complete_database_schema.sql`, `05_environment_setup.md`

## Agent 5: QA/Test Engineer
- Focus: Phase 5 test plan
- Both branches
- Output: `07_test_plan.md`

---

# CRITICAL REMINDERS

1. **DO NOT assume** - trace actual code paths
2. **owner_id is TEXT** (Firebase UID), not UUID
3. **The CLI is the primary interface** - not the API
4. **EmailSyncManager might not be used** - find what IS used
5. **Save outputs to docs/integration/** - not root folder
6. **Cross-reference branches** - understand differences


Now run swarm analysis

