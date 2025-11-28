# Changelog

All notable changes to the Zylch AI project will be documented in this file.

## [Unreleased]

### Fixed - Contact Enrichment Performance & Clarity (2025-11-27)

#### Web Search Opt-In
- **Problem**: Contact enrichment automatically triggered web search, taking 10+ minutes
- **Solution**: Changed to opt-in only - web search executes ONLY when user explicitly asks
- **Examples**: "cerca sul web", "search web for...", "find online info about..."
- **Impact**: Contact enrichment completes in seconds instead of 10+ minutes when web search not needed
- **Files**: `zylch/agent/prompts.py:170`

#### Contact Dual-Save Clarification
- **Problem**: Users confused about where enriched contacts are saved
- **Solution**: Clarified that `save_contact` automatically saves to BOTH locations:
  1. **StarChat** - Structured contact data (name, email, phone, company, variables)
  2. **ZylchMemory** - Semantic person-centric namespace `{owner}:{assistant}:{contact_id}`
- **Changes**:
  - Updated tool description to emphasize dual-save (`factory.py:1516`)
  - Updated prompt instructions to explain dual-save when asking permission (`prompts.py:175-176`)
  - Implementation already present (`factory.py:1624-1663`)
- **Files**: `zylch/agent/prompts.py`, `zylch/tools/factory.py`

#### Documentation
- **NEW**: `docs/implementation-notes.md` - Implementation decisions and recent changes
- Added to `docs/README.md` index under Developer Documentation

### Added - Multi-Tenant Person-Centric Memory Architecture (2025-11-27)

#### 🚨 Single-Assistant Mode (v0.2.0)
- **Constraint**: ONE assistant per owner (temporary limitation)
- **Auto-creation**: Default assistant created automatically on first startup
- **Validation**: `/assistant --create` blocked if assistant already exists
- **Rationale**: Simplifies development without requiring StarChat modifications
- **Future-ready**: Architecture supports multi-assistant expansion

#### Core Multi-Tenant Implementation
- **Two-level isolation**: Owner-level (Firebase UID) + Assistant-level (business separation)
- **Namespace structure**: `{owner}:{zylch_assistant_id}` for business data, `{owner}:{zylch_assistant_id}:{contact_id}` for person data
- **Zero data leakage**: Complete workspace isolation between owners
- **Category-based organization**: business, config, style, person, relationship
- **StarChat contact integration**: Uses StarChat contact IDs in person namespaces

#### New Services
- **AssistantManager**: JSON-based service for managing multiple assistants per owner
  - `create_assistant()` - Create new isolated workspace
  - `list_assistants()` - List all assistants for owner
  - `link_mrcall_assistant()` - Connect to MrCall/StarChat assistant
  - Storage: `cache/zylch_assistants.json`

#### CLI Commands
- **`/assistant`** - Manage Zylch assistants
  - `--list` - List all assistants for current owner
  - `--create <name>` - Create new assistant
  - `--id <assistant_id>` - Switch to different assistant
- **`/mrcall`** - Link to MrCall/StarChat assistant
  - `--id <mrcall_id>` - Link assistant to MrCall contacts
  - `--list` - List available MrCall assistants (placeholder)

#### Updated Components
- **TaskManager**: Multi-tenant person memory namespace `{owner}:{assistant}:{contact}`
- **DraftEmailFromMemoryTool**: Retrieves memories from namespaced storage
- **populate_business_memory.py**: Reads OWNER_ID/ZYLCH_ASSISTANT_ID from env
- **CLI /memory --build**: Uses multi-tenant namespaces for person memories
- **Config**: Added `owner_id` and `zylch_assistant_id` settings

#### Documentation
- **NEW**: `docs/features/multi-tenant-architecture.md` - Complete 650-line guide
  - Architecture overview and namespace structure
  - CLI command reference
  - Use cases (multiple businesses, multi-tenant SaaS, person-centric memory)
  - AssistantManager API documentation
  - Migration guide from single-tenant
  - Best practices
- **UPDATED**: `docs/README.md` - Added multi-tenant as featured capability

#### Configuration
- **NEW env vars**: `OWNER_ID`, `ZYLCH_ASSISTANT_ID`
- **Placeholder mode**: Development support without Firebase
- **Firebase-ready**: Production ready with Firebase UID integration

### Added - Gmail Draft Threading & Google Meet Integration (2025-11-21)

#### Gmail Draft Thread Preservation
- **Fixed thread association bug**: Drafts now stay in conversation threads when edited
- **Delete+create pattern**: `update_draft()` now deletes old draft and creates new one with preserved `threadId`
- **Threading headers preservation**: Automatic In-Reply-To and References header management
- **Read-only metadata**: To/Subject fields shown as comments in nano editor (not editable)
- **Case-insensitive headers**: Fixed header lookup to use lowercase keys matching Gmail API

#### Google Meet Video Conference Integration
- **`add_meet_link` parameter** in `create_event()`: Automatically generates Google Meet links
- **conferenceData API**: Uses Google Calendar's conference creation with `hangoutsMeet` solution
- **Meet link extraction**: `_parse_event()` extracts Meet URLs from conferenceData.entryPoints
- **Automatic invites**: `sendUpdates='all'` sends calendar invitations with Meet link to all attendees
- **Email-to-event workflow**: Create calendar events from emails with all participants and Meet link
- **Agent prompts updated**: Added specific instructions for creating events from emails with Meet links

#### AI-Generated Email Detection
- **Low-priority filtering**: Identifies AI-generated business development emails
- **Detection signals**: Perfect structure, buzzwords, template patterns, zero personalization
- **Business rule**: "Email from BD with AI-generated content = LOW PRIORITY / NO TASK"
- **Integrated into analysis**: Added to both `_analyze_person_for_task()` and `_sonnet_requires_response()` prompts

#### Documentation Updates
- **README.md**: Added draft threading, Google Meet, and AI detection features
- **docs/README.md**: Updated integrations section with new capabilities
- **relationship-intelligence.md**: Added AI-generated email detection section
- **agent/prompts.py**: Added "Creating Events from Emails" workflow guide

#### Testing
- Created `test_calendar_with_meet.py` - Validates Meet link generation
- Created `create_draft_in_thread.py` - Demonstrates thread preservation
- Created `test_delete_create_approach.py` - Validates threadId preservation
- Created `test_ai_generated_detection.py` - Tests AI email filtering

### Added - Global Memory System (2025-11-20)

#### Core Implementation
- **Two-tier memory architecture**: Personal (`memory_{user_id}.json`) + Global (`memory_global.json`)
- **ReasoningBankMemory enhancements**:
  - `add_correction(is_global=False)` - Add corrections to either scope
  - `delete_correction(is_global=False)` - Delete from either scope
  - `record_application(is_global=False)` - Track applications by scope
  - `get_relevant_memories(include_global=True)` - Automatic merging of global + personal
  - `export_memories(scope='all')` - Export by scope ('all', 'personal', 'global')
  - `get_stats(scope='all')` - Statistics with scope breakdown
  - `get_correction_by_id(is_global=None)` - Search both or specific scope

#### CLI Refactoring
- **Unix-style commands** replacing old individual commands:
  - OLD: `/memory`, `/addmemory`, `/memorystats`, `/deletememory`
  - NEW: `/memory --list`, `/memory --add`, `/memory --stats`, `/memory --remove`
- **Flags support**:
  - `--global` - Operate on global memory
  - `--all` - Show both personal and global
  - `--help` - Show command help
- **Examples**:
  ```bash
  /memory --list --all
  /memory --add --global "wrong" "correct" type
  /memory --remove 5 --global
  /memory --stats --all
  ```

#### Visual Enhancements
- **Scope indicators**: 🌍 for global, 👤 for personal in all outputs
- **Enhanced prompt builder**: Distinguishes global vs personal rules in LLM context
- **Statistics breakdown**: Shows personal/global counts when using `--all`

#### Documentation
- **NEW**: `MEMORY_USAGE.md` - Complete CLI usage guide with examples
- **UPDATED**: `REASONING_BANK_DESIGN.md` - Added Section 5: Global Memory & Meta-Rules
- **UPDATED**: `README.md` - Added Behavioral Memory feature section
- **UPDATED**: `QUICK_START.md` - Added memory system quick reference

#### Testing
- Created `test_global_memory.py` - Comprehensive test suite validating:
  - Personal memory addition/deletion
  - Global memory addition/deletion
  - Scope validation (global cannot be contact-specific)
  - Memory merging (global + personal)
  - Prompt building with scope indicators
  - Statistics by scope
  - JSON file creation

#### Migration
- ✅ Backward compatible with existing `memory_mario.json` files
- ✅ No breaking changes to existing API
- ✅ Old personal memories load correctly

### Previous Features

#### Bot Detection (2025-11-20)
- Automatic detection of bot/automated emails using wildcard patterns
- Configurable via `BOT_EMAILS` in .env
- Automatic score capping at 2 for bot emails
- Default patterns: `*@noreply.*`, `*@no-reply.*`, `noreply@*`, `notifications@*`, etc.

#### Behavioral Memory - Phase 1 (2025-11-20)
- ReasoningBank-inspired memory system for behavioral corrections
- User-scoped personal memory (`memory_{user_id}.json`)
- Bayesian confidence updates (success/failure learning)
- Automatic injection into LLM system prompt
- CLI commands: `/memory`, `/addmemory`, `/memorystats`, `/deletememory`
- Correction types: formality, length, tone, content, style, structure, repetition, context

#### Person-Centric Task Management (2025-11)
- Email thread aggregation by person
- Priority scoring (1-10) with emotional context
- Task status tracking (open, waiting, closed)
- Bot email detection and de-prioritization
- StarChat integration for contact storage

#### Email Intelligence (2025-11)
- Thread caching with AI summaries (Haiku)
- Smart search by participant, subject, content
- Draft management (create, edit, list)
- Gmail OAuth multi-account support

## Future

### Planned Features
- [ ] Automatic memory extraction from user feedback
- [ ] Memory confidence visualization
- [ ] Memory export/import for backup
- [ ] Cross-user memory analytics (for global rules)
- [ ] Memory compression (merge similar rules)

### Under Consideration
- [ ] Voice interface for memory addition
- [ ] Memory templates for common scenarios
- [ ] Machine learning for memory prioritization
- [ ] Integration with external knowledge bases
