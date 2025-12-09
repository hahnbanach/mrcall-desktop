# CLI Archive Commands - Integration Complete

✅ **Status**: Archive commands added to interactive CLI
📅 **Completed**: November 23, 2025

## Overview

The `/archive` commands have been added to Zylch's interactive CLI, providing easy access to the email archive system without leaving the conversation interface.

## Usage

### Start Interactive CLI

```bash
python -m zylch.cli.main
```

You'll see:
```
🏗️  Initializing Zylch AI...
✅ Google services authenticated (Gmail, Calendar)
✅ Email archive initialized
✅ Ready!

You:
```

## `/archive` Commands

### Show Statistics (Default)
```
You: /archive
```
or
```
You: /archive --stats
```

Output:
```
📊 ARCHIVE STATISTICS
============================================================
Backend: SQLITE
Location: cache/emails/archive.db

Messages: 477
Threads: 260

Date Range:
  Earliest: 2025-10-24T10:00:41
  Latest: 2025-11-23T10:52:37

Last Sync: 2025-11-23T11:39:28.975955+00:00
Database Size: 5.21 MB
============================================================
```

### Run Incremental Sync
```
You: /archive --sync
```

Output:
```
🔄 Running incremental archive sync...
✅ Sync complete!
   Messages added: 3
   Messages deleted: 0
```

### Search Emails
```
You: /archive --search project --limit 10
```

Output:
```
🔍 Searching for: 'project' (limit: 10)

Found 5 results:

1. Project Update - Q4 Review
   From: manager@company.com
   Date: Mon, 20 Nov 2025 14:30:00 +0000

2. Re: Project Timeline
   From: client@example.com
   Date: Fri, 17 Nov 2025 09:15:00 +0000
...
```

### Initialize Archive (First Time)
```
You: /archive --init
```
or specify months:
```
You: /archive --init 3
```

Output:
```
📦 Initializing email archive (3 months)...
This may take a few minutes...

✅ Archive initialized!
   Messages: 1,234
   Date range: 2025/08/23 to 2025/11/23
```

### Show Help
```
You: /archive --help
```

Output:
```
📦 EMAIL ARCHIVE MANAGEMENT
============================================================

Commands:
  /archive                    Show archive statistics
  /archive --help             Show this help
  /archive --stats            Show archive statistics
  /archive --sync             Run incremental sync
  /archive --init [months]    Initialize archive (one-time)
  /archive --search <query> [--limit N]
                              Search archived emails

Examples:
  /archive
  /archive --sync
  /archive --search project --limit 10
  /archive --init 3
============================================================
```

## Integration with Other Commands

### `/sync` - Morning Sync

The `/sync` command now uses the archive system:

```
You: /sync
```

Workflow:
1. **Archive incremental sync** - Fetch new emails (<1 second)
2. **Build intelligence cache** - Read from archive (fast)
3. **Calendar sync** - Sync calendar events
4. **Gap analysis** - Analyze relationship gaps

Output:
```
🌅 Running morning sync...

📧 Step 1: Syncing archive...
✅ Archive: +5 -0

🧠 Step 2: Building intelligence cache...
✅ Cache: 260 threads analyzed

📅 Step 3: Syncing calendar...
✅ Calendar: 12 events

🔍 Step 4: Analyzing gaps...
✅ Gap analysis complete

✅ Morning sync complete! Use /gaps to see your briefing.
```

## All CLI Commands Reference

### Core
- `/help` - Show all commands
- `/business <id>` - Select MrCall assistant
- `/clear` - Clear conversation
- `/history` - Show history
- `/quit` - Exit

### Data & Sync
- `/sync [days]` - Full morning sync
- `/gaps` - Show relationship gaps
- `/archive` - Email archive (see above)
- `/cache` - Cache management

### Memory
- `/memory --list` - List memories
- `/memory --add "wrong" "correct" channel` - Add memory
- `/memory --remove <id>` - Remove memory
- `/memory --stats` - Show statistics

### Cache
- `/cache` - Show overview
- `/cache emails` - Email cache details
- `/cache calendar` - Calendar cache details
- `/cache --clear all` - Clear all caches

## Architecture

### Initialization Flow

When you start the interactive CLI:

1. **Gmail authenticated** - Uses existing tokens
2. **EmailArchiveManager created** - `self.email_archive = EmailArchiveManager(gmail)`
3. **EmailSyncManager refactored** - Now uses archive instead of Gmail
4. **All tools initialized** - Archive available to `/archive` commands

### Command Handler

```python
async def _handle_archive_command(self, command: str):
    """Handle /archive command - email archive management."""

    if not self.email_archive:
        print("❌ Email archive not initialized")
        return

    # Parse subcommand (--stats, --sync, --search, etc.)
    # Execute corresponding archive operation
    # Display formatted results
```

### Integration Points

1. **Initialization** (`__init__`):
   ```python
   self.email_archive = None  # Email archive manager
   ```

2. **Setup** (`initialize`):
   ```python
   # Email archive manager (NEW - permanent storage)
   self.email_archive = EmailArchiveManager(gmail_client=gmail)

   # Email sync manager (REFACTORED - reads from archive)
   email_sync = EmailSyncManager(
       email_archive=self.email_archive,
       cache_dir=settings.cache_dir + "/emails",
       anthropic_api_key=settings.anthropic_api_key,
       days_back=30,
   )
   ```

3. **Command Routing** (`handle_command`):
   ```python
   elif cmd.startswith("/archive"):
       await self._handle_archive_command(command)
   ```

4. **Help Display** (`print_welcome`):
   ```python
   print("  /archive       - Email archive management (use /archive --help for details)")
   ```

## Examples

### Daily Workflow

**Morning:**
```
You: /sync
```
- Syncs new emails
- Updates intelligence cache
- Analyzes relationships

**During Day:**
```
You: /archive --search contract
```
- Find specific emails quickly

**Check Status:**
```
You: /archive
```
- See archive statistics

### First Time Setup

**Day 1:**
```
You: /archive --init
```
- Initializes with 1 month of emails
- Takes ~2-5 minutes

**Day 2+:**
```
You: /archive --sync
```
- Incremental sync (<1 second)
- Only fetches new emails

## Benefits

### User Experience
- ✅ **No context switching** - Archive commands in conversation
- ✅ **Instant access** - Type `/archive` anytime
- ✅ **Consistent interface** - Same as `/cache`, `/memory`, `/sync`

### Performance
- ✅ **Fast queries** - Archive already initialized
- ✅ **No overhead** - Shares Gmail client with other tools
- ✅ **Background ready** - Archive always available

### Integration
- ✅ **Works with `/sync`** - Seamless integration
- ✅ **Complements `/cache`** - Archive is permanent, cache is temporary
- ✅ **Search from CLI** - No need for separate scripts

## Technical Details

### File Changes

**Modified**: `zylch/cli/main.py`

1. **Import**:
   ```python
   from ..tools.email_archive import EmailArchiveManager
   ```

2. **Initialization**:
   ```python
   self.email_archive = None  # Email archive manager
   ```

3. **Setup**:
   ```python
   self.email_archive = EmailArchiveManager(gmail_client=gmail)
   ```

4. **Handler** (138 lines):
   ```python
   async def _handle_archive_command(self, command: str):
       # Handles --help, --stats, --sync, --init, --search
   ```

5. **Routing**:
   ```python
   elif cmd.startswith("/archive"):
       await self._handle_archive_command(command)
   ```

6. **Help text**:
   ```python
   print("  /archive       - Email archive management")
   ```

### Error Handling

All commands have error handling:

```python
try:
    result = self.email_archive.incremental_sync()
    if result['success']:
        print("✅ Sync complete!")
    else:
        print(f"❌ Sync failed: {result.get('error')}")
except Exception as e:
    print(f"❌ Sync error: {e}")
```

### Async Support

Archive commands are async-compatible:

```python
async def _handle_archive_command(self, command: str):
    # Can await other async operations if needed
```

## Comparison: Two CLI Systems

### 1. Interactive CLI (Full-Featured)
**Command**: `python -m zylch.cli.main`

**Features**:
- Full agent with AI
- Conversational interface
- All tools available
- Memory system
- `/archive` commands ✅ **NEW**

**Use Case**: Daily interactive work

### 2. Standalone Archive CLI (Focused)
**Command**: `python zylch_cli.py archive sync`

**Features**:
- Archive operations only
- Standard CLI syntax
- No agent overhead
- Fast startup

**Use Case**: Automation, cron jobs, scripts

Both are useful for different scenarios!

## Summary

✅ **Archive commands integrated into interactive CLI**
✅ **All operations available: stats, sync, search, init**
✅ **Consistent with existing `/` command patterns**
✅ **Error handling and help text included**
✅ **Works seamlessly with `/sync` workflow**
✅ **Documented in memory system**

The interactive CLI now provides complete access to the email archive system without leaving the conversation!
