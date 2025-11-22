# Changelog

All notable changes to the MrPark project will be documented in this file.

## [Unreleased]

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
