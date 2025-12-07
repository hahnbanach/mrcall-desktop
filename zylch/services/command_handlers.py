"""Command handlers for slash commands.

All handlers return markdown-formatted strings (no print statements).
No Anthropic API calls in these handlers.
"""
import logging
from typing import List, Dict, Any
from pathlib import Path
import json
import sqlite3
import uuid

from zylch.tools.config import ToolConfig

logger = logging.getLogger(__name__)


async def handle_help() -> str:
    """Return help message."""
    return """**📋 Zylch AI Commands**

**📧 Data Management:**
• `/sync [days]` - Sync email and calendar
• `/gaps` or `/briefing` - Analyze unanswered conversations
• `/archive [--help]` - Email archive management
• `/cache [--help]` - Cache management

**🧠 Memory & Automation:**
• `/memory [--help]` - Behavioral memory management
• `/trigger [--help]` - Event-driven automation

**📞 Integrations:**
• `/mrcall [--help]` - MrCall/StarChat phone integration

**🔗 Sharing:**
• `/share <email>` - Share data with someone
• `/revoke <email>` - Revoke sharing access
• `/sharing` - Show sharing status

**🔧 Configuration:**
• `/model [haiku|sonnet|opus|auto]` - Change AI model

**📚 Utility:**
• `/tutorial [topic]` - Quick guides
• `/clear` - Clear conversation history
• `/help` - Show this message

**💡 Tip:** You can also chat naturally! Ask "who emailed me today?" or "help me with my emails"."""


async def handle_sync(args: List[str], config, memory, owner_id: str) -> str:
    """Handle /sync command without calling Anthropic."""
    from zylch.services.sync_service import SyncService
    from zylch.tools.factory import ToolFactory
    from zylch.api.token_storage import get_provider, get_email, get_graph_token, get_google_tokens_dir
    from zylch.tools.outlook import OutlookClient
    from zylch.tools.gmail import GmailClient
    from zylch.tools.gcalendar import GoogleCalendarClient

    # Parse days parameter
    days_back = 30
    if args:
        try:
            days_back = int(args[0])
        except ValueError:
            return f"❌ **Error:** `{args[0]}` is not a valid number\n\n**Usage:** `/sync [days]`"

    try:
        # Get user's auth provider
        logger.info(f"handle_sync: owner_id={owner_id}, type={type(owner_id)}")
        provider = get_provider(owner_id)
        email = get_email(owner_id)

        if not provider:
            return f"❌ **Error:** Provider not found for owner {owner_id}. Please login first."

        # Create appropriate email client based on provider
        if provider == "microsoft.com":
            # Microsoft Outlook client
            graph_token_data = get_graph_token(owner_id)
            if not graph_token_data:
                return f"❌ **Error:** Microsoft Graph token not found. Please login again."

            email_client = OutlookClient(
                graph_token=graph_token_data["access_token"],
                account=email
            )
            calendar_client = None  # TODO: Microsoft Calendar support
            logger.info(f"Using Microsoft Outlook for owner {owner_id}")

        else:
            # Google Gmail client
            google_tokens_dir = get_google_tokens_dir(owner_id)
            email_client = GmailClient(
                credentials_path=config.google_credentials_path,
                token_dir=str(google_tokens_dir),
                account=email,
                owner_id=owner_id
            )
            calendar_client = GoogleCalendarClient(
                credentials_path=config.google_credentials_path,
                token_dir=str(google_tokens_dir),
                calendar_id="primary",
                account=email,
                owner_id=owner_id
            )
            logger.info(f"Using Gmail for owner {owner_id}")

        sync_service = SyncService(
            email_client=email_client,
            calendar_client=calendar_client
        )

        # Skip gap analysis to avoid Anthropic API calls for slash commands
        results = await sync_service.run_full_sync(days_back=days_back, skip_gap_analysis=True)

        lines = [f"**🌅 Morning Sync** (last {days_back} days)\n"]

        has_failures = False

        if results['email_sync']['success']:
            email_data = results['email_sync']
            lines.append(f"✅ **Email:** {email_data['new_threads']} new, {email_data['updated_threads']} updated")
        else:
            has_failures = True
            lines.append(f"❌ **Email:** {results['email_sync'].get('error')}")

        if results['calendar_sync']['success']:
            cal_data = results['calendar_sync']
            lines.append(f"✅ **Calendar:** {cal_data['new_events']} new, {cal_data['updated_events']} updated")
        else:
            has_failures = True
            lines.append(f"❌ **Calendar:** {results['calendar_sync'].get('error')}")

        if results['gap_analysis']['success']:
            gap_data = results['gap_analysis']
            lines.append(f"\n✅ **Tasks:** {gap_data['total_tasks']} found")
            lines.append(f"   • Email: {gap_data['email_tasks']}")
            lines.append(f"   • Meeting: {gap_data['meeting_tasks']}")
            lines.append(f"   • Silent contacts: {gap_data['silent_contacts']}")
        else:
            has_failures = True
            lines.append(f"❌ **Gap analysis:** {results['gap_analysis'].get('error')}")

        if has_failures:
            lines.append("\n⚠️ **Sync completed with errors.** Check the issues above.")
        else:
            lines.append("\n✅ **Sync complete!** Use `/gaps` for briefing.")
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return f"❌ **Sync failed:** {str(e)}"


async def handle_clear() -> str:
    """Handle /clear command."""
    return """✅ **History Cleared**

**📝 Client Note:** The server doesn't maintain history.
Clear your local `conversation_history` array."""


async def handle_gaps() -> str:
    """Handle /gaps or /briefing command."""
    return """**⚠️ Gap Analysis**

This command analyzes unanswered emails and meeting follow-ups.

**Note:** Gap analysis is currently integrated in `/sync`.
Use `/sync` to run full sync including gap analysis with Anthropic API.

For instant gap overview without Anthropic calls, this feature is coming soon."""


async def handle_archive(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /archive command - email archive management."""
    if '--help' in args:
        return """**📦 Email Archive Management**

**Usage:**
• `/archive` or `/archive --stats` - Show archive statistics
• `/archive --sync` - Run incremental sync
• `/archive --init [months]` - Initialize archive (download history)
• `/archive --search <query> --limit N` - Search emails

**Examples:**
• `/archive --stats`
• `/archive --search "contract" --limit 10`
• `/archive --init 3`

**Note:** Only Gmail is currently supported for email archiving.
Outlook archiving will be added in a future update."""

    from zylch.tools.email_archive import EmailArchiveManager
    from zylch.api.token_storage import get_provider, get_email, get_google_tokens_dir
    from zylch.tools.gmail import GmailClient

    try:
        # Check provider - only Gmail is supported for archiving
        provider = get_provider(owner_id)
        if provider == 'microsoft.com':
            return """**⏭️ Email Archive**

Email archiving is currently only supported for Gmail accounts.
Outlook/Microsoft archiving will be added in a future update.

For now, Microsoft users can use natural language to search emails:
"Show emails from last week about contracts" """

        # Create Gmail client for archive
        email = get_email(owner_id)
        google_tokens_dir = get_google_tokens_dir(owner_id)
        email_client = GmailClient(
            credentials_path=config.google_credentials_path,
            token_dir=str(google_tokens_dir),
            account=email,
            owner_id=owner_id
        )

        # Authenticate
        try:
            email_client.authenticate()
        except Exception as auth_error:
            return f"**❌ Error:** Could not authenticate with Gmail. Please reconnect Google via `/connect google`.\n\nDetails: {auth_error}"

        # Create archive manager
        archive = EmailArchiveManager(gmail_client=email_client)

        # Parse command
        if '--init' in args:
            # Initialize archive with history
            months_idx = args.index('--init') + 1
            months = 6  # default
            if months_idx < len(args) and args[months_idx].isdigit():
                months = int(args[months_idx])

            result = archive.initial_full_sync(months_back=months)

            if not result['success']:
                return f"**❌ Error:** {result.get('error', 'Unknown error')}"

            return f"""**✅ Archive Initialized**

**Downloaded:** {result['total_fetched']} emails ({months} months)
**Stored:** {result['total_stored']} messages
**Time:** {result.get('duration_seconds', 0):.1f}s

Run `/archive --stats` to see archive details."""

        elif '--sync' in args:
            # Incremental sync
            result = archive.incremental_sync()

            if not result['success']:
                return f"**❌ Error:** {result.get('error', 'Unknown error')}"

            return f"""**✅ Archive Sync Complete**

**Added:** {result['messages_added']} new messages
**Deleted:** {result['messages_deleted']} messages
**Duration:** {result.get('duration_seconds', 0):.1f}s"""

        elif '--search' in args:
            # Search emails
            search_idx = args.index('--search') + 1
            if search_idx >= len(args):
                return "**❌ Error:** Missing search query. Usage: `/archive --search <query>`"

            query = args[search_idx]
            limit = 10  # default

            if '--limit' in args:
                limit_idx = args.index('--limit') + 1
                if limit_idx < len(args) and args[limit_idx].isdigit():
                    limit = int(args[limit_idx])

            messages = archive.search_messages(query=query, limit=limit)

            if not messages:
                return f"**📭 No results found for:** `{query}`"

            # Format results
            results_text = f"**📬 Found {len(messages)} emails matching:** `{query}`\n\n"
            for msg in messages[:limit]:
                from_addr = msg.get('from_email', 'Unknown')
                subject = msg.get('subject', '(no subject)')
                date = msg.get('date', '')
                results_text += f"• **{subject}**\n  From: {from_addr} | {date}\n\n"

            return results_text

        else:
            # Default: show stats
            stats = archive.get_stats()

            return f"""**📦 Email Archive Statistics**

**Total Messages:** {stats.get('total_messages', 0):,}
**Total Threads:** {stats.get('total_threads', 0):,}
**Date Range:** {stats.get('oldest_date', 'N/A')} to {stats.get('newest_date', 'N/A')}
**Full Sync:** {'✅ Completed' if stats.get('full_sync_completed') else '❌ Not completed'}
**Last Sync:** {stats.get('last_sync', 'Never')}

**Storage:** {stats.get('database_path', 'N/A')}

Use `/archive --help` for more commands."""

    except Exception as e:
        logger.error(f"Error in /archive command: {e}", exc_info=True)
        return f"**❌ Error:** {str(e)}\n\nUse `/archive --help` for usage information."


async def handle_cache(args: List[str]) -> str:
    """Handle /cache command - cache management."""
    from pathlib import Path
    import json
    from datetime import datetime
    from zylch.config import settings

    cache_dir = Path(settings.cache_dir)

    if '--help' in args:
        return """**💾 Cache Management**

**Usage:**
• `/cache` - Show cache overview
• `/cache emails` - Email cache details
• `/cache calendar` - Calendar cache details
• `/cache gaps` - Gaps cache details
• `/cache --clear all|emails|calendar|gaps` - Clear caches

**Examples:**
• `/cache emails`
• `/cache --clear all`"""

    if '--clear' in args:
        target_idx = args.index('--clear') + 1
        target = args[target_idx] if len(args) > target_idx else None

        if target == 'all':
            count = 0
            for cache_file in cache_dir.rglob('*.json'):
                try:
                    cache_file.unlink()
                    count += 1
                except Exception:
                    pass
            return f"✅ Cleared {count} cache files"

        elif target == 'emails':
            email_cache = cache_dir / 'emails' / 'email_threads.json'
            if email_cache.exists():
                email_cache.unlink()
                return "✅ Email cache cleared"
            return "📭 Email cache already empty"

        elif target == 'calendar':
            cal_cache = cache_dir / 'calendar_events.json'
            if cal_cache.exists():
                cal_cache.unlink()
                return "✅ Calendar cache cleared"
            return "📭 Calendar cache already empty"

        elif target == 'gaps':
            gaps_cache = cache_dir / 'relationship_gaps.json'
            if gaps_cache.exists():
                gaps_cache.unlink()
                return "✅ Gaps cache cleared"
            return "📭 Gaps cache already empty"

        else:
            return f"❌ Unknown cache target: {target}\n\nUse: all, emails, calendar, gaps"

    elif 'emails' in args:
        threads_file = cache_dir / 'emails' / 'email_threads.json'
        if not threads_file.exists():
            return "📭 **Email cache empty**\n\nRun `/sync` to populate cache."

        try:
            with open(threads_file) as f:
                threads = json.load(f)

            output = f"**📧 Email Cache** ({len(threads)} threads)\n\n"
            for thread_id, data in list(threads.items())[:10]:
                subject = data.get('subject', 'N/A')
                from_addr = data.get('from', 'N/A')
                date = data.get('date', 'N/A')
                output += f"**{subject}**\n"
                output += f"From: {from_addr} | {date}\n\n"

            if len(threads) > 10:
                output += f"_... and {len(threads) - 10} more threads_"

            return output
        except Exception as e:
            return f"❌ Error reading cache: {str(e)}"

    elif 'calendar' in args:
        calendar_file = cache_dir / 'calendar_events.json'
        if not calendar_file.exists():
            return "📭 **Calendar cache empty**\n\nRun `/sync` to populate cache."

        try:
            with open(calendar_file) as f:
                events = json.load(f)

            output = f"**📅 Calendar Cache** ({len(events)} events)\n\n"

            # Show upcoming events
            now = datetime.now()
            upcoming = []
            for e in events:
                try:
                    start = datetime.fromisoformat(e.get('start', ''))
                    if start > now:
                        upcoming.append((start, e))
                except:
                    pass

            upcoming.sort(key=lambda x: x[0])

            for start, event in upcoming[:5]:
                summary = event.get('summary', 'N/A')
                output += f"**{summary}**\n"
                output += f"When: {start.strftime('%Y-%m-%d %H:%M')}\n\n"

            if len(upcoming) > 5:
                output += f"_... and {len(upcoming) - 5} more upcoming events_"

            return output
        except Exception as e:
            return f"❌ Error reading cache: {str(e)}"

    elif 'gaps' in args:
        gaps_file = cache_dir / 'relationship_gaps.json'
        if not gaps_file.exists():
            return "📭 **Gaps cache empty**\n\nRun `/sync` to analyze gaps."

        try:
            with open(gaps_file) as f:
                gaps = json.load(f)

            email_tasks = gaps.get('email_tasks', [])
            meeting_tasks = gaps.get('meeting_followup_tasks', [])
            silent = gaps.get('silent_contacts', [])

            output = f"**⚠️ Relationship Gaps**\n\n"
            output += f"Email tasks: {len(email_tasks)}\n"
            output += f"Meeting follow-ups: {len(meeting_tasks)}\n"
            output += f"Silent contacts: {len(silent)}\n\n"

            if email_tasks:
                output += "**Top Email Tasks:**\n"
                for task in email_tasks[:5]:
                    contact = task.get('contact_name', 'Unknown')
                    subject = task.get('subject', 'N/A')
                    output += f"• {contact}: {subject}\n"

            return output
        except Exception as e:
            return f"❌ Error reading cache: {str(e)}"

    else:
        # Overview
        email_count = 0
        calendar_count = 0
        gaps_count = 0

        threads_file = cache_dir / 'emails' / 'email_threads.json'
        if threads_file.exists():
            try:
                with open(threads_file) as f:
                    email_count = len(json.load(f))
            except:
                pass

        calendar_file = cache_dir / 'calendar_events.json'
        if calendar_file.exists():
            try:
                with open(calendar_file) as f:
                    calendar_count = len(json.load(f))
            except:
                pass

        gaps_file = cache_dir / 'relationship_gaps.json'
        if gaps_file.exists():
            try:
                with open(gaps_file) as f:
                    data = json.load(f)
                    gaps_count = (
                        len(data.get('email_tasks', [])) +
                        len(data.get('meeting_followup_tasks', [])) +
                        len(data.get('silent_contacts', []))
                    )
            except:
                pass

        return f"""**💾 Cache Overview**

📧 Email threads: {email_count}
📅 Calendar events: {calendar_count}
⚠️ Relationship gaps: {gaps_count}

**Commands:**
• `/cache emails` - View email cache
• `/cache calendar` - View calendar cache
• `/cache gaps` - View gaps cache
• `/cache --clear all` - Clear all caches"""


async def handle_model(args: List[str]) -> str:
    """Handle /model command - AI model selection."""
    model_map = {
        'haiku': 'claude-3-5-haiku-20241022',
        'sonnet': 'claude-3-5-sonnet-20241022',
        'opus': 'claude-3-opus-20240229',
        'auto': None
    }

    if not args or '--help' in args:
        return f"""**🤖 AI Model Selection**

**Available models:**
• `haiku` - Claude 3.5 Haiku (fast, economical)
• `sonnet` - Claude 3.5 Sonnet (balanced) ⭐ default
• `opus` - Claude 3 Opus (powerful, expensive)
• `auto` - Automatic selection

**Usage:** `/model sonnet`

**Note for API clients:** Model selection is per-session.
Pass `forced_model` in context for subsequent requests:
```json
{{
  "context": {{
    "forced_model": "claude-3-5-haiku-20241022"
  }}
}}
```"""

    model_choice = args[0].lower()
    if model_choice not in model_map:
        return f"❌ Unknown model: `{model_choice}`\n\nUse: haiku, sonnet, opus, auto"

    model_id = model_map[model_choice]

    if model_id:
        return f"""✅ **Model selected: {model_choice}**

Model ID: `{model_id}`

**For this to take effect:**
API clients should include in context for future requests:
```json
{{
  "context": {{
    "forced_model": "{model_id}"
  }}
}}
```"""
    else:
        return "✅ **Automatic model selection enabled**\n\nZylch will choose the best model for each task."


async def handle_memory(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /memory command - behavioral memory management."""
    if '--help' in args or not args:
        return """**🧠 Behavioral Memory Management**

**Usage:**
• `/memory --add <issue> <correct> <channel>` - Add memory
• `/memory --list [scope]` - List memories (personal/global/all)
• `/memory --stats [scope]` - Memory statistics

**Examples:**
• `/memory --add "Used tu" "Use lei" email`
• `/memory --list personal`
• `/memory --stats global`

**Scope:**
• `personal` - Your personal memories
• `global` - Global system memories
• `all` - Both personal and global"""

    from zylch.tools.factory import ToolFactory

    try:
        # Initialize memory system
        memory = await ToolFactory.create_memory_system(config)

        if '--list' in args:
            # List memories
            scope_idx = args.index('--list') + 1
            scope = args[scope_idx] if len(args) > scope_idx else 'all'

            if scope not in ['personal', 'global', 'all']:
                return f"❌ Invalid scope: `{scope}`\n\nUse: personal, global, all"

            # Determine namespaces to query
            namespaces = []
            if scope in ['personal', 'all']:
                namespaces.append(f"user:{owner_id}")
            if scope in ['global', 'all']:
                namespaces.append("global")

            # Collect memories from all namespaces
            all_memories = []
            for namespace in namespaces:
                memories = memory.storage.get_memories_by_namespace(namespace, limit=50)
                for mem in memories:
                    mem['_namespace'] = namespace  # Tag with namespace
                    all_memories.append(mem)

            if not all_memories:
                return f"**📭 No memories found** (scope: {scope})\n\nMemories are automatically created when Zylch learns from corrections."

            # Format output
            output = f"**🧠 Behavioral Memories** ({len(all_memories)} total, scope: {scope})\n\n"

            for mem in all_memories[:20]:  # Show max 20
                issue = mem.get('issue', 'N/A')
                correct = mem.get('correct', 'N/A')
                category = mem.get('category', 'N/A')
                confidence = mem.get('confidence', 0.0)
                scope_label = '🌍' if mem['_namespace'] == 'global' else '👤'

                output += f"{scope_label} **{issue}** → **{correct}**\n"
                output += f"   Category: {category} | Confidence: {confidence:.2f}\n\n"

            if len(all_memories) > 20:
                output += f"_... and {len(all_memories) - 20} more memories_"

            return output

        elif '--stats' in args:
            # Memory statistics
            scope_idx = args.index('--stats') + 1
            scope = args[scope_idx] if len(args) > scope_idx else 'all'

            if scope not in ['personal', 'global', 'all']:
                return f"❌ Invalid scope: `{scope}`\n\nUse: personal, global, all"

            # Determine namespaces to query
            namespaces = []
            if scope in ['personal', 'all']:
                namespaces.append(f"user:{owner_id}")
            if scope in ['global', 'all']:
                namespaces.append("global")

            # Collect stats
            total_memories = 0
            total_patterns = 0
            by_category = {}

            for namespace in namespaces:
                memories = memory.storage.get_memories_by_namespace(namespace, limit=1000)
                patterns = memory.storage.get_patterns_by_namespace(namespace, limit=1000)

                total_memories += len(memories)
                total_patterns += len(patterns)

                # Count by category
                for mem in memories:
                    cat = mem.get('category', 'unknown')
                    by_category[cat] = by_category.get(cat, 0) + 1

            output = f"**🧠 Memory Statistics** (scope: {scope})\n\n"
            output += f"**Total Memories:** {total_memories}\n"
            output += f"**Total Patterns:** {total_patterns}\n\n"

            if by_category:
                output += "**By Category:**\n"
                for cat, count in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
                    output += f"• {cat}: {count}\n"

            output += f"\n**Storage:** {config.memory_db_path}"

            return output

        elif '--add' in args:
            # Add memory (manual)
            add_idx = args.index('--add') + 1

            if len(args) < add_idx + 3:
                return "❌ Missing arguments\n\nUsage: `/memory --add <issue> <correct> <channel>`"

            issue = args[add_idx]
            correct = args[add_idx + 1]
            channel = args[add_idx + 2]

            # Store memory in personal namespace
            memory_id = memory.store_behavioral_memory(
                namespace=f"user:{owner_id}",
                issue=issue,
                correct=correct,
                category=channel,
                confidence=1.0,  # Manual additions get high confidence
                user_id=owner_id
            )

            return f"""✅ **Memory added** (ID: {memory_id})

**Issue:** {issue}
**Correct:** {correct}
**Category:** {channel}

Zylch will now remember this correction."""

        else:
            # Default: show help
            return """**🧠 Behavioral Memory**

Use `/memory --help` to see available commands.

**Quick start:**
• `/memory --list` - View all memories
• `/memory --stats` - View statistics"""

    except Exception as e:
        logger.error(f"Error in /memory command: {e}", exc_info=True)
        return f"**❌ Error:** {str(e)}\n\nUse `/memory --help` for usage information."


async def handle_trigger(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /trigger command - triggered instructions."""
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient

    TRIGGER_TYPES = ['session_start', 'email_received', 'sms_received', 'call_received']

    if '--help' in args or not args:
        return """**⚡ Triggered Instructions**

**Usage:**
• `/trigger` or `/trigger --list` - List all triggers
• `/trigger --types` - Show trigger types
• `/trigger --add <type> <instruction>` - Add trigger
• `/trigger --remove <id>` - Remove trigger
• `/trigger --toggle <id>` - Enable/disable trigger

**Trigger types:**
• `session_start` - When starting conversation
• `email_received` - When email arrives
• `sms_received` - When SMS arrives
• `call_received` - When call comes in

**Examples:**
```
/trigger --add session_start "Say good morning and list my meetings for today"
/trigger --add email_received "Summarize important emails from unknown senders"
/trigger --remove abc123
```"""

    try:
        client = SupabaseClient()

        if '--types' in args:
            return """**⚡ Available Trigger Types**

• `session_start` - Fires when you start a new conversation
• `email_received` - Fires when new email arrives (via /sync)
• `sms_received` - Fires when SMS arrives (via MrCall)
• `call_received` - Fires when phone call comes in (via MrCall)

**Usage:** `/trigger --add <type> <instruction>`"""

        elif '--list' in args or len(args) == 0:
            # List triggers
            triggers = client.list_triggers(owner_id)

            if not triggers:
                return """**⚡ No Triggers**

You haven't created any triggers yet.

**Get started:**
`/trigger --add session_start "Summarize my unread emails"`

Use `/trigger --help` for more options."""

            output = f"**⚡ Your Triggers** ({len(triggers)} total)\n\n"
            for t in triggers:
                status = "✅" if t.get('active', True) else "❌"
                trigger_type = t.get('trigger_type', 'unknown')
                instruction = t.get('instruction', '')[:50]
                if len(t.get('instruction', '')) > 50:
                    instruction += "..."
                trigger_id = t.get('id', '')[:8]

                output += f"{status} **{trigger_type}** (ID: `{trigger_id}`)\n"
                output += f"   {instruction}\n\n"

            output += "**Commands:** `/trigger --remove <id>` | `/trigger --toggle <id>`"
            return output

        elif '--add' in args:
            # Add trigger
            add_idx = args.index('--add') + 1

            if len(args) < add_idx + 2:
                return "❌ **Error:** Missing arguments\n\n**Usage:** `/trigger --add <type> <instruction>`\n\nExample: `/trigger --add session_start \"Say good morning\"`"

            trigger_type = args[add_idx]
            # Join remaining args as instruction
            instruction = ' '.join(args[add_idx + 1:])

            if trigger_type not in TRIGGER_TYPES:
                return f"❌ **Error:** Invalid trigger type: `{trigger_type}`\n\n**Valid types:** {', '.join(TRIGGER_TYPES)}"

            result = client.add_trigger(owner_id, trigger_type, instruction)

            if result:
                return f"""✅ **Trigger Created**

**Type:** {trigger_type}
**Instruction:** {instruction}
**ID:** `{result.get('id', 'N/A')[:8]}`

This trigger will fire automatically when the event occurs."""
            else:
                return "❌ **Error:** Failed to create trigger. Please try again."

        elif '--remove' in args:
            # Remove trigger
            remove_idx = args.index('--remove') + 1

            if len(args) <= remove_idx:
                return "❌ **Error:** Missing trigger ID\n\n**Usage:** `/trigger --remove <id>`"

            trigger_id = args[remove_idx]
            success = client.remove_trigger(owner_id, trigger_id)

            if success:
                return f"✅ **Trigger Removed** (ID: `{trigger_id[:8]}`)"
            else:
                return f"❌ **Error:** Could not find trigger with ID `{trigger_id[:8]}`"

        elif '--toggle' in args:
            # Toggle trigger active status
            toggle_idx = args.index('--toggle') + 1

            if len(args) <= toggle_idx:
                return "❌ **Error:** Missing trigger ID\n\n**Usage:** `/trigger --toggle <id>`"

            trigger_id = args[toggle_idx]

            # Get current status
            triggers = client.list_triggers(owner_id)
            current_trigger = next((t for t in triggers if t['id'].startswith(trigger_id)), None)

            if not current_trigger:
                return f"❌ **Error:** Could not find trigger with ID `{trigger_id[:8]}`"

            new_status = not current_trigger.get('active', True)
            success = client.update_trigger_active(owner_id, current_trigger['id'], new_status)

            if success:
                status_text = "enabled" if new_status else "disabled"
                return f"✅ **Trigger {status_text}** (ID: `{trigger_id[:8]}`)"
            else:
                return f"❌ **Error:** Could not update trigger"

        else:
            # Default: list triggers
            return await handle_trigger(['--list'], owner_id, user_email)

    except Exception as e:
        logger.error(f"Error in /trigger command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\nUse `/trigger --help` for usage information."


async def handle_assistant(args: List[str]) -> str:
    """Handle /assistant command - assistant management."""
    if '--help' in args or not args:
        return """**🎯 Assistant Management**

**Usage:**
• `/assistant` - Show current assistant
• `/assistant --list` - List all assistants
• `/assistant --create <name>` - Create new assistant
• `/assistant --id <id>` - Switch to assistant

**Examples:**
• `/assistant --list`
• `/assistant --create "Work Assistant"`
• `/assistant --id asst_abc123`

**Note:** Assistants maintain separate memory contexts."""

    # Placeholder
    return """**🎯 Assistants**

**Status:** Multi-assistant system coming soon.

**Current:** Single assistant per user.
Your current assistant maintains all memories and context.

**Future features:**
• Multiple assistants per user
• Separate contexts (work/personal)
• Assistant switching
• Shared memories"""


async def handle_mrcall(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /mrcall command - MrCall integration."""
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient

    if '--help' in args:
        return """**📞 MrCall Integration**

**Usage:**
• `/mrcall` - Show current MrCall link
• `/mrcall <business_id>` - Link to MrCall business
• `/mrcall --unlink` - Remove MrCall link

**Example:**
• `/mrcall 3002475397`

**What it does:**
Links your Zylch assistant to a MrCall/StarChat business for:
• Phone call handling with AI
• SMS automation
• Call transcript sync
• Trigger automation (sms_received, call_received)"""

    try:
        client = SupabaseClient()

        if '--unlink' in args:
            # Remove link
            success = client.remove_mrcall_link(owner_id)
            if success:
                return "✅ **MrCall Unlinked**\n\nYour Zylch is no longer connected to a MrCall business."
            else:
                return "❌ **Error:** No MrCall link found to remove."

        elif len(args) == 0:
            # Show current link
            link = client.get_mrcall_link(owner_id)

            if link:
                return f"""**📞 MrCall Status**

**Linked Business:** `{link.get('mrcall_business_id', 'N/A')}`
**Connected Since:** {link.get('created_at', 'N/A')[:10] if link.get('created_at') else 'N/A'}

**Features enabled:**
• Phone call handling
• SMS automation
• `call_received` triggers
• `sms_received` triggers

**Commands:**
• `/mrcall --unlink` - Disconnect
• `/trigger --add call_received "..."` - Add call automation"""
            else:
                return """**📞 MrCall Status**

**Status:** Not linked

Connect your Zylch to a MrCall business to enable:
• AI-powered phone call handling
• SMS automation
• Call/SMS triggers

**Usage:** `/mrcall <business_id>`

**Example:** `/mrcall 3002475397`

Contact support@zylchai.com to get your MrCall business ID."""

        else:
            # Link to business
            business_id = args[0]

            # Validate business_id (should be numeric or alphanumeric)
            if not business_id.replace('-', '').replace('_', '').isalnum():
                return f"❌ **Error:** Invalid business ID format: `{business_id}`"

            result = client.set_mrcall_link(owner_id, business_id)

            if result:
                return f"""✅ **MrCall Linked**

**Business ID:** `{business_id}`

Your Zylch is now connected to MrCall!

**Next steps:**
1. Configure your MrCall assistant to forward to Zylch
2. Add triggers: `/trigger --add call_received "Summarize the call"`
3. Test with a phone call

**Need help?** Contact support@zylchai.com"""
            else:
                return "❌ **Error:** Failed to link MrCall business. Please try again."

    except Exception as e:
        logger.error(f"Error in /mrcall command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\nUse `/mrcall --help` for usage information."


async def handle_share(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /share command - data sharing."""
    import re
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient

    if '--help' in args or not args:
        return """**🔗 Data Sharing**

**Usage:** `/share <email>`

Registers a recipient to receive shared data from you.

**Example:** `/share colleague@example.com`

**What gets shared:**
• Contact information (avatars)
• Email intelligence
• Relationship context

**How it works:**
1. You send a share request with `/share <email>`
2. Recipient sees the request in their `/sharing`
3. They authorize with their Zylch
4. Your relational data flows to them

**Commands:**
• `/share <email>` - Send share request
• `/revoke <email>` - Cancel sharing
• `/sharing` - View all sharing status"""

    try:
        client = SupabaseClient()

        recipient_email = args[0].lower()

        # Validate email
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, recipient_email):
            return f"❌ **Error:** Invalid email format: `{recipient_email}`"

        # Can't share with yourself
        if user_email and recipient_email == user_email.lower():
            return "❌ **Error:** You can't share with yourself."

        # Check if sender_email is available
        if not user_email:
            return "❌ **Error:** Your email is not available. Please re-authenticate."

        result = client.register_share_recipient(owner_id, user_email, recipient_email)

        if result:
            status = result.get('status', 'pending')
            if status == 'pending':
                return f"""✅ **Share Request Sent**

**Recipient:** {recipient_email}
**Status:** Pending authorization

The recipient needs to authorize this sharing from their Zylch account.

Once authorized, they will receive:
• Your contact intelligence
• Relationship context
• Avatar data

**Manage:** `/sharing` | `/revoke {recipient_email}`"""
            else:
                return f"""ℹ️ **Sharing Already Exists**

**Recipient:** {recipient_email}
**Status:** {status}

Use `/revoke {recipient_email}` to cancel this sharing."""
        else:
            return "❌ **Error:** Failed to create share request. Please try again."

    except Exception as e:
        logger.error(f"Error in /share command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\nUse `/share --help` for usage information."


async def handle_revoke(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /revoke command - revoke sharing access."""
    import re
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient

    if '--help' in args or not args:
        return """**❌ Revoke Sharing**

**Usage:** `/revoke <email>`

Revokes data sharing access for a recipient.

**Example:** `/revoke colleague@example.com`

This stops sharing your data with the specified user.
They will no longer receive updates from you."""

    try:
        client = SupabaseClient()

        recipient_email = args[0].lower()

        # Validate email
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, recipient_email):
            return f"❌ **Error:** Invalid email format: `{recipient_email}`"

        success = client.revoke_sharing(owner_id, recipient_email)

        if success:
            return f"""✅ **Sharing Revoked**

**Recipient:** {recipient_email}

They will no longer receive your data updates.

**Note:** Any data already shared remains with them, but no new updates will be sent.

**Restore:** Use `/share {recipient_email}` to share again."""
        else:
            return f"""❌ **Error:** No active sharing found

Could not find sharing with `{recipient_email}`.

Use `/sharing` to see your current sharing connections."""

    except Exception as e:
        logger.error(f"Error in /revoke command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\nUse `/revoke --help` for usage information."


async def handle_sharing(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /sharing command - show sharing status."""
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient

    if '--help' in args:
        return """**📊 Sharing Status**

**Usage:** `/sharing`

Shows your current sharing connections:
• **Pending requests** - Awaiting authorization
• **Authorized recipients** - Who receives your data
• **Incoming shares** - Whose data you receive

**Related commands:**
• `/share <email>` - Share with someone
• `/revoke <email>` - Stop sharing
• `/sharing --authorize <email>` - Accept incoming share"""

    try:
        client = SupabaseClient()

        # Handle authorize action
        if '--authorize' in args:
            auth_idx = args.index('--authorize') + 1
            if len(args) <= auth_idx:
                return "❌ **Error:** Missing email\n\n**Usage:** `/sharing --authorize <sender_email>`"

            sender_email = args[auth_idx].lower()

            if not user_email:
                return "❌ **Error:** Your email is not available. Please re-authenticate."

            success = client.authorize_sender(user_email, sender_email)

            if success:
                return f"""✅ **Sharing Authorized**

**From:** {sender_email}

You will now receive their shared data:
• Contact intelligence
• Relationship context
• Avatar data"""
            else:
                return f"""❌ **Error:** Could not authorize

No pending share request found from `{sender_email}`.

Use `/sharing` to see pending requests."""

        # Get sharing status
        status = client.get_sharing_status(owner_id, user_email)

        if not status:
            return """**📊 Sharing Status**

**No sharing connections**

Share your relational intelligence with colleagues:
`/share colleague@example.com`

**Benefits of sharing:**
• Contacts know about relationships across your team
• Better meeting prep with shared context
• Seamless handoffs when colleagues leave"""

        outgoing = status.get('outgoing', [])
        incoming = status.get('incoming', [])

        output = "**📊 Sharing Status**\n\n"

        # Outgoing shares (you → others)
        if outgoing:
            output += "**📤 Your Recipients** (you share with them)\n"
            for share in outgoing:
                recipient = share.get('recipient_email', 'Unknown')
                status_text = share.get('status', 'unknown')
                status_icon = {'pending': '⏳', 'authorized': '✅', 'revoked': '❌'}.get(status_text, '❓')
                output += f"{status_icon} {recipient} ({status_text})\n"
            output += "\n"
        else:
            output += "**📤 Your Recipients:** None\n\n"

        # Incoming shares (others → you)
        if incoming:
            output += "**📥 Sharing With You** (you receive their data)\n"
            for share in incoming:
                sender = share.get('sender_email', 'Unknown')
                status_text = share.get('status', 'unknown')
                status_icon = {'pending': '⏳', 'authorized': '✅', 'revoked': '❌'}.get(status_text, '❓')

                if status_text == 'pending':
                    output += f"{status_icon} {sender} - **Pending your authorization**\n"
                    output += f"   → `/sharing --authorize {sender}`\n"
                else:
                    output += f"{status_icon} {sender} ({status_text})\n"
            output += "\n"
        else:
            output += "**📥 Sharing With You:** None\n\n"

        output += "**Commands:** `/share <email>` | `/revoke <email>`"

        return output

    except Exception as e:
        logger.error(f"Error in /sharing command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\nUse `/sharing --help` for usage information."


async def handle_tutorial(args: List[str]) -> str:
    """Handle /tutorial command - quick guides."""
    if '--help' in args or not args:
        return """**📚 Quick Guides**

**Available topics:**
• `/tutorial contact` - Contact management
• `/tutorial email` - Email operations
• `/tutorial calendar` - Calendar management
• `/tutorial sync` - Morning sync workflow
• `/tutorial memory` - Memory system

**Example:** `/tutorial sync`"""

    topic = args[0].lower()

    guides = {
        'contact': """**👤 Contact Management Guide**

**Search contacts:**
"Who is mario@example.com?"
"Find contact for Acme Corp"

**Create contacts:**
"Create contact for luisa@example.com"

**Update contacts:**
"Add phone +39 123456789 to Mario Rossi"

**View relationships:**
"Show my relationship with Mario"

**Pro tip:** Zylch auto-creates contacts from emails.""",

        'email': """**📧 Email Operations Guide**

**Read emails:**
"Show emails from today"
"Unread emails from Mario"

**Draft emails:**
"Draft email to mario@example.com about meeting"

**Search archive:**
"/cache emails" to view cache

**Sync:**
"/sync" - Fetch latest emails

**Pro tip:** Use natural language for complex queries.""",

        'calendar': """**📅 Calendar Management Guide**

**View events:**
"Show calendar for today"
"Meetings this week"

**Create events:**
"Schedule meeting with Mario tomorrow 3pm"

**Find time:**
"When am I free this week?"

**Pro tip:** Zylch auto-analyzes calendar conflicts.""",

        'sync': """**🔄 Morning Sync Workflow**

**Daily routine:**
1. Run `/sync` - Fetch emails + calendar
2. Check `/gaps` - See unanswered emails
3. Review: "Summarize today's emails"
4. Respond: "Draft reply to Mario's email"

**Quick workflow:** `/sync` → `/gaps` → respond

**Pro tip:** Use `/cache` to inspect cached data.""",

        'memory': """**🧠 Memory System Guide**

**How it works:**
Zylch learns from your corrections during conversation.

**Examples:**
"Use 'lei' instead of 'tu' with this contact"
"Always CC marco@example.com on contracts"

**Future:**
• `/memory --add` - Explicit memory creation
• `/memory --list` - View all memories
• `/memory --stats` - Memory statistics

**Pro tip:** Memory learns automatically from feedback."""
    }

    if topic in guides:
        return guides[topic]
    else:
        return f"""❌ **Unknown topic:** {topic}

**Available topics:**
contact, email, calendar, sync, memory

Use `/tutorial --help` to see all topics."""


# Export all handlers
COMMAND_HANDLERS = {
    '/help': handle_help,
    '/sync': handle_sync,
    '/clear': handle_clear,
    '/gaps': handle_gaps,
    '/briefing': handle_gaps,  # Alias
    '/archive': handle_archive,
    '/cache': handle_cache,
    '/model': handle_model,
    '/memory': handle_memory,
    '/trigger': handle_trigger,
    '/assistant': handle_assistant,
    '/mrcall': handle_mrcall,
    '/share': handle_share,
    '/revoke': handle_revoke,
    '/sharing': handle_sharing,
    '/tutorial': handle_tutorial,
}
