# Tech Debt Cleanup Plan

Pre-split cleanup for mrcall-agent / zylch-standalone separation.
Two independent items that can be executed in parallel.

---

## Item 1: Split `tools/factory.py` (2232 lines -> 5 files, each <500)

### Current Structure

`zylch/tools/factory.py` contains:

| Section | Lines | Content |
|---------|-------|---------|
| `SessionState` class | 1-118 | Runtime context (business_id, owner_id, task mode, mrcall config mode, sandbox) |
| Imports | 120-152 | Service client imports, tool imports |
| `ToolFactory` class | 155-584 | Factory methods: `create_all_tools`, `_create_gmail_tools`, `_create_email_sync_tools`, `_create_contact_tools`, `_create_calendar_tools`, `_create_pipedrive_tools`, `_create_mrcall_tools`, `_create_sharing_tools`, `_create_sms_tools` |
| Gmail tools | 591-888 | `_GmailSearchTool`, `_CreateDraftTool`, `_ListDraftsTool`, `_EditDraftTool`, `_UpdateDraftTool`, `_SendDraftTool`, `_RefreshGoogleAuthTool` |
| Email sync tools | 1268-1503 | `_SyncEmailsTool`, `_SearchEmailsTool`, `_CloseEmailThreadTool`, `_EmailStatsTool` |
| Task tool | 1506-1594 | `_GetTasksTool` |
| Memory/contact tools | 1597-1916 | `_SearchLocalMemoryTool`, `_GetContactTool`, `_GetWhatsAppContactsTool` |
| Pipedrive tools | 1919-2090 | `_SearchPipedrivePersonTool`, `_GetPipedrivePersonDealsTool` |
| Compose email tool | 2093-2232 | `_ComposeEmailTool` |

### Target File Layout

```
zylch/tools/
  session_state.py       ~120 lines   SessionState class
  factory.py             ~450 lines   ToolFactory class + imports (references tool modules)
  gmail_tools.py         ~450 lines   7 Gmail + email tool classes
  email_sync_tools.py    ~240 lines   4 email sync tool classes
  contact_tools.py       ~330 lines   3 memory/contact tool classes + 1 task tool
  crm_tools.py           ~320 lines   2 Pipedrive tools + 1 ComposeEmailTool
  __init__.py            (updated)    Re-exports ToolFactory, SessionState
```

### Detailed Changes

#### 1. Create `zylch/tools/session_state.py` (~120 lines)

Move the `SessionState` class (lines 15-118) here. No dependencies on other tool modules.

```python
# zylch/tools/session_state.py
"""Shared session state for tool runtime context."""
from typing import Dict, Optional

class SessionState:
    ...  # exact same code, lines 15-118
```

#### 2. Create `zylch/tools/gmail_tools.py` (~450 lines)

Move these 7 classes:
- `_GmailSearchTool` (lines 591-795)
- `_CreateDraftTool` (lines 798-887)
- `_ListDraftsTool` (lines 890-955)
- `_EditDraftTool` (lines 958-1053)
- `_UpdateDraftTool` (lines 1056-1123)
- `_SendDraftTool` (lines 1126-1233)
- `_RefreshGoogleAuthTool` (lines 1236-1265)

Imports needed: `logging`, `subprocess`, `tempfile`, `Tool`, `ToolResult`, `ToolStatus` from `.base`.

Make classes public (drop leading underscore): `GmailSearchTool`, `CreateDraftTool`, etc.

#### 3. Create `zylch/tools/email_sync_tools.py` (~240 lines)

Move these 4 classes:
- `_SyncEmailsTool` (lines 1268-1315)
- `_SearchEmailsTool` (lines 1318-1396)
- `_CloseEmailThreadTool` (lines 1399-1462)
- `_EmailStatsTool` (lines 1465-1503)

Imports: `logging`, `Optional` from typing, `Tool`, `ToolResult`, `ToolStatus`.

#### 4. Create `zylch/tools/contact_tools.py` (~330 lines)

Move these 4 classes:
- `_GetTasksTool` (lines 1506-1594)
- `_SearchLocalMemoryTool` (lines 1597-1718)
- `_GetContactTool` (lines 1721-1844)
- `_GetWhatsAppContactsTool` (lines 1847-1916)

Imports: `logging`, `Optional`/`Dict`/`Any`/`List` from typing, `Tool`, `ToolResult`, `ToolStatus`, `SessionState` from `.session_state`.
`_SearchLocalMemoryTool` also needs `HybridSearchEngine` (imported at usage or type-hinted with string).

#### 5. Create `zylch/tools/crm_tools.py` (~320 lines)

Move these 3 classes:
- `_SearchPipedrivePersonTool` (lines 1919-1994)
- `_GetPipedrivePersonDealsTool` (lines 1997-2090)
- `_ComposeEmailTool` (lines 2093-2232)

Imports: `logging`, `Optional` from typing, `Tool`, `ToolResult`, `ToolStatus`, `SessionState`.

#### 6. Rewrite `zylch/tools/factory.py` (~450 lines)

Keep only:
- All imports (including new imports from the split modules)
- `ToolFactory` class with all its static methods

Update internal references: replace `_GmailSearchTool` with `GmailSearchTool` (from `.gmail_tools`), etc.

```python
# New imports at top of factory.py
from .session_state import SessionState
from .gmail_tools import (
    GmailSearchTool, CreateDraftTool, ListDraftsTool,
    EditDraftTool, UpdateDraftTool, SendDraftTool, RefreshGoogleAuthTool,
)
from .email_sync_tools import (
    SyncEmailsTool, SearchEmailsTool, CloseEmailThreadTool, EmailStatsTool,
)
from .contact_tools import (
    GetTasksTool, SearchLocalMemoryTool, GetContactTool, GetWhatsAppContactsTool,
)
from .crm_tools import (
    SearchPipedrivePersonTool, GetPipedrivePersonDealsTool, ComposeEmailTool,
)
```

#### 7. Update `zylch/tools/__init__.py`

```python
from .base import Tool, ToolResult
from .config import ToolConfig
from .session_state import SessionState
from .factory import ToolFactory

__all__ = ["Tool", "ToolResult", "ToolConfig", "ToolFactory", "SessionState"]
```

### Files That Import from `zylch.tools.factory`

These files use `from zylch.tools.factory import ToolFactory` or `SessionState`.
No changes needed because `factory.py` will re-export `SessionState` (imported from `session_state.py`):

| File | Imports |
|------|---------|
| `zylch/tools/__init__.py` | `ToolFactory`, `SessionState` |
| `zylch/services/command_handlers.py` | `ToolFactory` (lazy import) |
| `zylch/services/chat_service.py` | `SessionState` (lazy import) |
| `zylch/services/sync_service.py` | `ToolFactory` |
| `zylch/agents/mrcall_orchestrator_agent.py` | `SessionState` |
| `zylch/agents/task_orchestrator_agent.py` | `SessionState` |
| `tests/test_tool_factory.py` | `ToolFactory` |
| `tests/test_mrcall_integration.py` | `SessionState` |

**Action**: Add `from .session_state import SessionState` re-export in `factory.py` so all existing `from zylch.tools.factory import SessionState` imports continue working.

### Execution Order

1. Create `session_state.py` (no deps)
2. Create `gmail_tools.py`, `email_sync_tools.py`, `contact_tools.py`, `crm_tools.py` (all parallel, depend only on `base.py` and `session_state.py`)
3. Rewrite `factory.py` (imports from new modules, removes inline classes)
4. Update `__init__.py`
5. Run tests: `python -m pytest tests/ -v`
6. Run lint: `ruff check zylch/tools/`

---

## Item 2: Rename `SupabaseStorage` -> `Storage`

### Current State

The rename is **already partially done**:

- `zylch/storage/storage.py` contains `class Storage` (3101 lines) -- the real implementation
- `zylch/storage/__init__.py` exports `Storage` and provides `SupabaseStorage = Storage` alias
- `zylch/storage/supabase_client.py` is a backward-compat shim: `from zylch.storage.storage import Storage as SupabaseStorage`

**168 occurrences** of `SupabaseStorage` across **42 .py files**. The shim keeps everything working, but every consumer still uses the old name.

### Plan

Two-phase approach: first update all imports (mechanical), then remove the shim.

#### Phase A: Update all Python imports (can be done in one pass)

Every file that does:
```python
from zylch.storage.supabase_client import SupabaseStorage
```
should become:
```python
from zylch.storage import Storage
```

Every type annotation `SupabaseStorage` becomes `Storage`.

Every `SupabaseStorage()` or `SupabaseStorage.get_instance()` becomes `Storage()` or `Storage.get_instance()`.

##### Files to update (source code, 31 files):

**Services (3 files):**
| File | Occurrences |
|------|-------------|
| `zylch/services/command_handlers.py` | 12 imports + 11 usages = 23 total |
| `zylch/services/chat_service.py` | 1 import + 2 usages = 3 |
| `zylch/services/sync_service.py` | 1 import + 2 usages = 3 |

**Agents (10 files):**
| File | Occurrences |
|------|-------------|
| `zylch/agents/base_agent.py` | 1 import + 2 type hints = 3 |
| `zylch/agents/emailer_agent.py` | 1 import + 3 type hints = 4 |
| `zylch/agents/mrcall_agent.py` | 1 import + 2 type hints = 3 |
| `zylch/agents/mrcall_orchestrator_agent.py` | 1 import + 2 type hints = 3 |
| `zylch/agents/task_orchestrator_agent.py` | 1 import + 2 usages + 3 type hints = 6 |
| `zylch/agents/trainers/base.py` | 1 import + 2 type hints = 3 |
| `zylch/agents/trainers/emailer.py` | 1 import + 2 type hints = 3 |
| `zylch/agents/trainers/memory_email.py` | 1 import + 2 type hints = 3 |
| `zylch/agents/trainers/memory_mrcall.py` | 1 import + 2 type hints = 3 |
| `zylch/agents/trainers/mrcall.py` | 1 import + 2 type hints = 3 |
| `zylch/agents/trainers/mrcall_configurator.py` | 1 import + 2 type hints = 3 |
| `zylch/agents/trainers/task_email.py` | 1 import + 2 type hints = 3 |

**API routes (7 files):**
| File | Occurrences |
|------|-------------|
| `zylch/api/main.py` | 1 import + 1 usage = 2 |
| `zylch/api/routes/auth.py` | 1 import + 4 usages = 5 |
| `zylch/api/routes/chat.py` | 1 import + 1 usage = 2 |
| `zylch/api/routes/connections.py` | 1 import + 6 usages = 7 |
| `zylch/api/routes/data.py` | 1 import + 4 usages = 5 |
| `zylch/api/routes/jobs.py` | 1 import + 3 usages = 4 |
| `zylch/api/routes/mrcall.py` | 1 import + 4 usages = 5 |
| `zylch/api/routes/settings.py` | 1 import + 1 usage = 2 |

**Tools (6 files):**
| File | Occurrences |
|------|-------------|
| `zylch/tools/factory.py` | 1 import + 2 usages (in `_ComposeEmailTool`) + 3 in comments = 6 |
| `zylch/tools/starchat.py` | 1 import + 3 type hints = 4 |
| `zylch/tools/sms_tools.py` | 2 imports + 2 usages = 4 |
| `zylch/tools/email_archive.py` | 1 import + 3 type hints = 4 |
| `zylch/tools/email_sync.py` | 1 import + 2 type hints = 3 |
| `zylch/tools/calendar_sync.py` | 1 import + 2 type hints = 3 |
| `zylch/tools/config.py` | 3 type hints (no import of SupabaseStorage, uses string annotations) = 3 |

**Workers (2 files):**
| File | Occurrences |
|------|-------------|
| `zylch/workers/task_creation.py` | 1 import + 2 usages = 3 |
| `zylch/workers/memory.py` | 1 import + 2 usages = 3 |

**Other (2 files):**
| File | Occurrences |
|------|-------------|
| `zylch/sharing/authorization.py` | 1 import + 2 usages = 3 |
| `zylch/services/webhook_processor.py` | 2 usages = 2 |
| `zylch/services/job_executor.py` | 1 import + 5 type hints/usages = 6 |

**Tests (3 files):**
| File | Occurrences |
|------|-------------|
| `tests/conftest.py` | 1 import + 2 usages = 3 |
| `tests/test_command_handlers.py` | 10 usages |
| `tests/test_mrcall_oauth.py` | 1 usage |

**Scripts (1 file):**
| File | Occurrences |
|------|-------------|
| `scripts/migrate_to_unified_credentials.py` | 1 import + 2 usages = 3 |

**Note**: `command_handlers.py` has some imports aliased as `SupabaseClient`:
```python
from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient
```
These become: `from zylch.storage import Storage as StorageClient` (or just `Storage`).

#### Phase B: Remove shims

After all imports are updated:

1. Delete `zylch/storage/supabase_client.py`
2. Remove the alias line from `zylch/storage/__init__.py`:
   ```python
   # Remove this line:
   SupabaseStorage = Storage
   ```
3. Update `zylch/storage/storage.py` docstring (remove "Replaces SupabaseStorage" references)

#### Phase C: Update documentation

Files with `SupabaseStorage` in docs/comments (update text, not code):
- `docs/guides/qa_testing.md`
- `docs/agents/memory-agent.md`
- `docs/agents/README.md`
- `tests/README.md`
- `.claude/skills/zylch-creating-commands/REFERENCE.md`
- `.claude/skills/zylch-creating-commands/SKILL.md`
- `docs/system-rules.md`
- `docs/active-context.md`
- `docs/quality-grades.md`
- `docs/harness-backlog.md`
- `CLAUDE.md` (mentions "supabase_client.py")

### Execution Order

1. **Phase A**: Mechanical find-and-replace across all 31+ source files. Can be done with a script:
   ```bash
   # Replace import lines
   sed -i 's/from zylch\.storage\.supabase_client import SupabaseStorage$/from zylch.storage import Storage/g'
   # Replace aliased imports
   sed -i 's/from zylch\.storage\.supabase_client import SupabaseStorage as SupabaseClient/from zylch.storage import Storage/g'
   # Replace class name in type hints and usages
   sed -i 's/SupabaseStorage/Storage/g'
   ```
   **WARNING**: The sed approach is too aggressive for `SupabaseStorage` -> `Storage` globally. Use targeted replacements per file, or a Python script that handles:
   - Import lines (replace whole line)
   - Type annotations (replace identifier)
   - `.get_instance()` calls
   - Constructor calls
   - Aliased imports (`as SupabaseClient` -> remove alias or use `Storage`)
2. Run tests: `python -m pytest tests/ -v`
3. **Phase B**: Delete shim, clean `__init__.py`
4. Run tests again
5. **Phase C**: Update docs (non-blocking, can be done anytime)

---

## Execution Strategy

Items 1 and 2 are independent and can be done in parallel on separate branches.

**Recommended order if sequential:**

1. **Item 2 first** (SupabaseStorage rename) -- mechanical, lower risk, removes confusion before the split
2. **Item 1 second** (factory.py split) -- structural change, benefits from clean storage imports

**Branch strategy:**
- `tech-debt/rename-storage` for Item 2
- `tech-debt/split-factory` for Item 1
- Merge both to `dev` before the project split

**Risk assessment:**
- Item 1: Medium risk (new module boundaries, import chains). Mitigated by keeping `factory.py` re-exports.
- Item 2: Low risk (mechanical rename with shim already in place). Mitigated by existing backward-compat layer.

**Total estimated effort:** ~2-3 hours for both items combined.
