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
from zylch.config import settings

logger = logging.getLogger(__name__)


async def handle_echo(args: List[str] = None) -> str:
    """Echo back the provided text."""
    if not args:
        return ""
    return " ".join(args)


async def handle_help() -> str:
    """Return help message."""
    return """**📋 Zylch AI Commands**

💡 **Remember:** All commands accept `--help` for detailed usage

**📧 Data & Email:**
• `/sync --days <n>` - Sync email and calendar
• `/stats` - Email statistics (count, unread, threads)
• `/email list|create|send|delete|search` - Manage drafts and search

**📅 Calendar & Tasks:**
• `/calendar [days]` - Show upcoming events
• `/tasks` - List open tasks (needs response)
• `/briefing [days]` - Daily briefing with context
• `/jobs` - Scheduled reminders and jobs

**🧠 Memory & Automation:**
• `/memory [search|store|stats|list]` - Entity memory with hybrid search
• `/trigger` - Event-driven automation

**📡 Integrations:**
• `/connect` - View and manage external connections
• `/mrcall` - MrCall/StarChat phone integration

**🔗 Sharing:**
• `/share <email>` - Share data with someone
• `/revoke <email>` - Revoke sharing access

**🔧 Configuration:**
• `/model [haiku|sonnet|opus|auto]` - Change AI model

**📚 Utility:**
• `/tutorial [topic]` - Quick guides
• `/clear` - Clear conversation history
• `/help` - Show this message

**💡 Tip:** Chat naturally! "show my tasks", "email stats", "what's on my calendar"."""


async def handle_sync(args: List[str], config, memory, owner_id: str) -> str:
    """Handle /sync command without calling Anthropic."""
    from zylch.services.sync_service import SyncService
    from zylch.tools.factory import ToolFactory
    from zylch.api.token_storage import get_provider, get_email, get_graph_token
    from zylch.tools.outlook import OutlookClient
    from zylch.tools.gmail import GmailClient
    from zylch.tools.gcalendar import GoogleCalendarClient
    from zylch.storage.supabase_client import SupabaseStorage

    # Check for --status flag
    status_check = '--status' in args
    if status_check:
        logger.info(f"[/sync] Status check for owner_id={owner_id}")
        try:
            supabase = SupabaseStorage()
            result = supabase.client.table('sync_state').select('*').eq('owner_id', owner_id).execute()

            if not result.data:
                return "📊 **Sync Status**\n\n❌ No sync state found - never synced.\n\nRun `/sync` or `/sync --days <n>` to start."

            sync_state = result.data[0]
            last_sync = sync_state.get('last_sync')

            # Format last sync time or show "Never" if missing
            if last_sync:
                # Parse and format the timestamp nicely
                from datetime import datetime
                try:
                    if isinstance(last_sync, str):
                        dt = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))
                        last_sync_display = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                    else:
                        last_sync_display = str(last_sync)
                except:
                    last_sync_display = str(last_sync)
            else:
                last_sync_display = "Never"

            # Count emails
            email_count_result = supabase.client.table('emails').select('id', count='exact').eq('owner_id', owner_id).execute()
            email_count = email_count_result.count if hasattr(email_count_result, 'count') else 0

            # Count calendar events
            event_count_result = supabase.client.table('calendar_events').select('id', count='exact').eq('owner_id', owner_id).execute()
            event_count = event_count_result.count if hasattr(event_count_result, 'count') else 0

            return f"""📊 **Sync Status**

✅ **Last synced:** {last_sync_display}
📧 **Emails archived:** {email_count:,}
📅 **Calendar events:** {event_count:,}

Run `/sync` or `/sync --days <n>` to sync more data."""
        except Exception as e:
            logger.error(f"[/sync] Failed to get sync status: {e}")
            return f"❌ **Error getting sync status:** {str(e)}"

    # Check for --reset flag
    reset_sync = '--reset' in args
    if reset_sync:
        logger.info(f"[/sync] Reset flag detected, clearing all sync data for owner_id={owner_id}")
        try:
            supabase = SupabaseStorage()
            cleared_tables = []

            # Clear sync state
            supabase.client.table('sync_state').delete().eq('owner_id', owner_id).execute()
            logger.info(f"[/sync] Cleared sync_state")

            # Clear emails
            email_result = supabase.client.table('emails').delete().eq('owner_id', owner_id).execute()
            logger.info(f"[/sync] Cleared emails")

            # Clear calendar events
            cal_result = supabase.client.table('calendar_events').delete().eq('owner_id', owner_id).execute()
            logger.info(f"[/sync] Cleared calendar_events")

            return """✅ **Sync state reset!**

All emails and calendar events cleared.
Next `/sync` will perform a full re-sync from scratch.

⚠️ **Memory note:** Your memory blobs still exist. If you want fresh memory:
```
/memory --reset
```
Then run `/sync --days <n>` to rebuild memory from re-synced emails."""
        except Exception as e:
            logger.error(f"[/sync] Failed to reset sync state: {e}")
            return f"❌ **Error resetting sync state:** {str(e)}"

    # Parse --days parameter
    days_back = 30
    for i, arg in enumerate(args):
        if arg == '--days' and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                return f"❌ **Error:** `{args[i + 1]}` is not a valid number\n\n**Usage:** `/sync --days <number> [--reset]`"
            break

    try:
        # Get user's auth provider
        logger.info(f"[/sync] Starting sync for owner_id={owner_id}, days_back={days_back}")
        provider = get_provider(owner_id)
        email = get_email(owner_id)
        logger.debug(f"[/sync] provider={provider}, email={email}")

        if not provider:
            logger.warning(f"[/sync] No provider found for owner_id={owner_id}")
            return """❌ **Error:** Zylch has no access to any channel!
  Run /connect to see available connections
  Run /connect {provider} to connect"""

        # Create appropriate email client based on provider
        if provider == "microsoft":
            # Microsoft Outlook client
            graph_token_data = get_graph_token(owner_id)
            if not graph_token_data:
                return f"❌ **Error:** Microsoft Graph token not found. Please login again."

            email_client = OutlookClient(
                graph_token=graph_token_data["access_token"],
                account=email
            )
            calendar_client = None  # TODO: Microsoft Calendar support
            logger.info(f"[/sync] Using Microsoft Outlook for {email}")

        else:
            # Google Gmail client (tokens stored in Supabase)
            # Note: credentials_path is not used when owner_id is provided (uses Supabase)
            email_client = GmailClient(
                credentials_path="credentials/gmail_oauth.json",  # Not used with owner_id
                account=email,
                owner_id=owner_id
            )
            calendar_client = GoogleCalendarClient(
                credentials_path="credentials/gmail_oauth.json",  # Not used with owner_id
                calendar_id="primary",
                account=email,
                owner_id=owner_id
            )
            logger.info(f"[/sync] Using Gmail for {email}")

        from zylch.storage.supabase_client import SupabaseStorage
        supabase_storage = SupabaseStorage()

        sync_service = SyncService(
            email_client=email_client,
            calendar_client=calendar_client,
            owner_id=owner_id,
            supabase_storage=supabase_storage
        )

        # Run sync (archive only, no AI analysis)
        logger.info(f"[/sync] Running archive sync...")
        results = await sync_service.run_full_sync(days_back=days_back)
        logger.info(f"[/sync] Sync complete: email={results['email_sync']['success']}, calendar={results['calendar_sync']['success']}, pipedrive={results.get('pipedrive_sync', {}).get('success', 'N/A')}")

        lines = ["**🔄 Sync Complete**\n"]

        has_failures = False

        if results['email_sync']['success']:
            email_data = results['email_sync']
            new_msgs = email_data.get('new_messages', 0)
            del_msgs = email_data.get('deleted_messages', 0)

            lines.append(f"✅ **Email:** +{new_msgs} new, -{del_msgs} deleted")

            # Show warning if incremental sync
            if email_data.get('incremental'):
                first_sync = email_data.get('first_sync_date', 'previous sync')
                lines.append(f"ℹ️  **Incremental sync** - fetching changes since {first_sync}")
                lines.append(f"   If you want to go further in the past, run `/sync --reset` first, then `/sync --days <n>`")
        else:
            has_failures = True
            lines.append(f"❌ **Email:** {results['email_sync'].get('error')}")

        if results['calendar_sync']['success']:
            cal_data = results['calendar_sync']
            lines.append(f"✅ **Calendar:** {cal_data['new_events']} new, {cal_data['updated_events']} updated")
        else:
            has_failures = True
            lines.append(f"❌ **Calendar:** {results['calendar_sync'].get('error')}")

        # Pipedrive sync (only show if connected)
        pipedrive_data = results.get('pipedrive_sync', {})
        if pipedrive_data.get('success'):
            if not pipedrive_data.get('skipped'):
                deals_synced = pipedrive_data.get('deals_synced', 0)
                lines.append(f"✅ **Pipedrive:** {deals_synced} deals synced")
        elif pipedrive_data.get('error'):
            has_failures = True
            lines.append(f"❌ **Pipedrive:** {pipedrive_data.get('error')}")

        if has_failures:
            lines.append("\n⚠️ **Sync completed with errors.** Check the issues above.")
        else:
            # Check if user has trained a custom prompt
            storage = SupabaseStorage.get_instance()
            has_custom_prompt = storage.get_user_prompt(owner_id, 'memory_email') is not None
            if has_custom_prompt:
                lines.append("\n✅ **Done!** Run `/memory process` to extract memories.")
            else:
                lines.append("\n✅ **Done!** Run `/train build memory-email` then `/memory process`.")
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return f"❌ **Sync failed:** {str(e)}"


async def handle_clear() -> str:
    """Handle /clear command."""
    return """✅ **History Cleared**

**📝 Client Note:** The server doesn't maintain history.
Clear your local `conversation_history` array."""


async def handle_briefing(args: List[str], owner_id: str) -> str:
    """Handle /briefing command - Show daily briefing of tasks and unanswered conversations.

    Usage: /briefing [days]

    This queries pre-computed avatars (NOT real-time LLM calls).
    Avatars are updated in background after each /sync.

    Note: config and memory parameters removed - not needed for avatar query.
    """
    from zylch.storage.supabase_client import SupabaseStorage
    from datetime import datetime, timedelta, timezone

    # Parse days argument
    days_back = 7  # default
    if args:
        try:
            days_back = int(args[0])
        except ValueError:
            return f"❌ **Error:** `{args[0]}` is not a valid number\n\n**Usage:** `/briefing [days]`"

    logger.info(f"[/briefing] Querying avatars for owner_id={owner_id}, days_back={days_back}")

    try:
        supabase = SupabaseStorage()
        from .task_formatter import filter_own_emails, format_task_list

        # Query avatars with open status or waiting action (score >= 3 for all priorities)
        result = supabase.client.table('avatars')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .or_('relationship_status.eq.open,relationship_status.eq.waiting')\
            .gte('relationship_score', 3)\
            .order('relationship_score', desc=True)\
            .execute()

        avatars = result.data if result.data else []
        avatars = filter_own_emails(avatars)

        return format_task_list(avatars, include_stale_warning=True)

    except Exception as e:
        logger.error(f"Briefing failed: {e}", exc_info=True)
        return f"❌ **Briefing failed:** {str(e)}"


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
    """Handle /memory command - entity-centric memory management."""
    if '--help' in args or not args:
        return """**🧠 Entity Memory System**

**Usage:**
• `/memory process` - Process all unprocessed data into memory blobs
• `/memory process email` - Process only emails
• `/memory process calendar` - Process only calendar events
• `/memory process pipedrive` - Process only Pipedrive deals
• `/memory search <query>` - Search memories (hybrid FTS + semantic)
• `/memory store <content>` - Store new memory (with auto-reconsolidation)
• `/memory stats` - Show memory statistics
• `/memory list [limit]` - List recent memories
• `/memory --reset` - Delete ALL memories AND reset processing timestamps

**Before processing emails:**
First, create a personalized extraction prompt:
```
/train build memory-email
```
This learns YOUR patterns for better cold outreach detection and VIP prioritization.

**Examples:**
• `/train build memory-email` - Create personalized prompt first
• `/memory process email` - Process emails with your custom prompt
• `/memory search John Smith`
• `/memory store "Mario prefers formal Italian in emails"`

**How it works:**
1. `/sync` fetches emails, calendar, and Pipedrive
2. `/train build memory-email` learns your patterns (recommended)
3. `/memory process` extracts facts using personalized prompt
4. `/memory search` finds information using hybrid FTS + semantic search"""

    from zylch.storage.supabase_client import SupabaseStorage
    from zylch_memory import BlobStorage, HybridSearchEngine, EmbeddingEngine, ZylchMemoryConfig

    try:
        # Initialize services
        storage = SupabaseStorage.get_instance()
        supabase = storage.client
        mem_config = ZylchMemoryConfig()
        embedding_engine = EmbeddingEngine(mem_config)
        blob_storage = BlobStorage(supabase, embedding_engine)
        search_engine = HybridSearchEngine(supabase, embedding_engine)

        namespace = f"user:{owner_id}"

        # Normalize args - accept both 'search' and '--search'
        cmd = args[0].lstrip('-') if args else ''

        if cmd == 'process':
            # Process synced data into memory blobs
            from zylch.workers.memory_worker import MemoryWorker

            service = args[1].lower() if len(args) > 1 else 'all'
            valid_services = ['all', 'email', 'calendar', 'pipedrive']

            if service not in valid_services:
                return f"❌ Unknown service: `{service}`\n\nValid options: `email`, `calendar`, `pipedrive`, or omit for all."

            # Get Anthropic API key from user's stored key or system settings
            anthropic_key = storage.get_anthropic_key(owner_id) or settings.anthropic_api_key

            if not anthropic_key:
                return """❌ **Anthropic API key required**

Connect your Anthropic account:
`/connect anthropic`"""

            worker = MemoryWorker(storage=storage, owner_id=owner_id, anthropic_api_key=anthropic_key)

            # Gate: Check if processing emails without a custom prompt
            if service in ['all', 'email'] and not worker.has_custom_prompt():
                # Show recommendation to build custom prompt first
                unprocessed_count = len(storage.get_unprocessed_emails(owner_id, limit=1))
                if unprocessed_count > 0:
                    return """⚠️ **No personalized extraction prompt found**

For better memory extraction, create a personalized prompt first:

```
/train build memory-email
```

This analyzes your email patterns to understand:
- **Who matters to you** (VIP contacts get detailed extraction)
- **What to ignore** (cold outreach specific to you)
- **Your role/context** (founder vs investor vs engineer)

The personalized prompt significantly improves:
- Cold outreach detection
- Relevant fact extraction
- VIP contact prioritization"""

            results = []

            # Process emails
            if service in ['all', 'email']:
                unprocessed_emails = storage.get_unprocessed_emails(owner_id, limit=100)
                if unprocessed_emails:
                    processed = await worker.process_batch(unprocessed_emails)
                    prompt_note = " (using custom prompt)" if worker.has_custom_prompt() else " (using default prompt)"
                    results.append(f"📧 **Emails:** {processed}/{len(unprocessed_emails)} processed{prompt_note}")
                else:
                    results.append("📧 **Emails:** No unprocessed emails")

            # Process calendar events
            if service in ['all', 'calendar']:
                unprocessed_events = storage.get_unprocessed_calendar_events(owner_id, limit=100)
                if unprocessed_events:
                    processed = await worker.process_calendar_batch(unprocessed_events)
                    results.append(f"📅 **Calendar:** {processed}/{len(unprocessed_events)} processed")
                else:
                    results.append("📅 **Calendar:** No unprocessed events")

            # Process pipedrive deals
            if service in ['all', 'pipedrive']:
                unprocessed_deals = storage.get_unprocessed_pipedrive_deals(owner_id, limit=100)
                if unprocessed_deals:
                    processed = await worker.process_pipedrive_batch(unprocessed_deals)
                    results.append(f"💼 **Pipedrive:** {processed}/{len(unprocessed_deals)} processed")
                else:
                    results.append("💼 **Pipedrive:** No unprocessed deals")

            output = "**🧠 Memory Processing Complete**\n\n"
            output += "\n".join(results)
            output += "\n\nUse `/memory search <query>` to find stored information."
            return output

        elif cmd == 'search':
            # Search memories
            if len(args) < 2:
                return "❌ Missing query\n\nUsage: `/memory search <query>`"

            query = ' '.join(args[1:])
            results = search_engine.search(
                owner_id=owner_id,
                query=query,
                namespace=namespace,
                limit=5
            )

            if not results:
                return f"**📭 No memories found** for: `{query}`"

            output = f"**🔍 Search Results** ({len(results)} found)\n\n"
            for i, r in enumerate(results, 1):
                score_info = f"hybrid: {r.hybrid_score:.2f} (FTS: {r.fts_score:.2f}, semantic: {r.semantic_score:.2f})"
                content_preview = r.content[:200] + "..." if len(r.content) > 200 else r.content
                output += f"**{i}.** {content_preview}\n"
                output += f"   _Score: {score_info}_\n\n"

            return output

        elif cmd == 'store':
            # Store new memory (with auto-reconsolidation)
            if len(args) < 2:
                return "❌ Missing content\n\nUsage: `/memory store <content>`"

            content = ' '.join(args[1:])

            # Check for reconsolidation candidate
            existing = search_engine.find_for_reconsolidation(
                owner_id=owner_id,
                content=content,
                namespace=namespace
            )

            if existing:
                # Reconsolidate: append to existing
                merged_content = f"{existing.content}\n\n{content}"
                result = blob_storage.update_blob(
                    blob_id=existing.blob_id,
                    owner_id=owner_id,
                    content=merged_content,
                    event_description="Reconsolidated via /memory store"
                )
                return f"""✅ **Memory reconsolidated** (ID: {result['id'][:8]}...)

**Merged with existing memory** (score: {existing.hybrid_score:.2f})

New content added to existing entity blob."""

            else:
                # Create new blob
                result = blob_storage.store_blob(
                    owner_id=owner_id,
                    namespace=namespace,
                    content=content,
                    event_description="Created via /memory store"
                )
                return f"""✅ **Memory stored** (ID: {result['id'][:8]}...)

**Content:** {content[:100]}{'...' if len(content) > 100 else ''}

Memory will be searchable via hybrid search."""

        elif cmd == 'stats':
            # Memory statistics
            stats = blob_storage.get_stats(owner_id)

            output = f"**🧠 Memory Statistics**\n\n"
            output += f"**Total Blobs:** {stats['total_blobs']}\n"
            output += f"**Total Sentences:** {stats['total_sentences']}\n"
            output += f"**Avg Sentences/Blob:** {stats['avg_blob_size']}\n"
            output += f"**Namespaces:** {len(stats['namespaces'])}\n"

            if stats['namespaces']:
                output += "\n**Namespaces:**\n"
                for ns in stats['namespaces'][:10]:
                    output += f"• `{ns}`\n"

            return output

        elif cmd == 'list':
            # List recent memories
            limit = 10
            if len(args) > 1:
                try:
                    limit = int(args[1])
                    limit = min(limit, 50)  # Cap at 50
                except ValueError:
                    pass

            # Get recent blobs
            result = supabase.table("blobs")\
                .select("id, namespace, content, created_at, updated_at")\
                .eq("owner_id", owner_id)\
                .order("updated_at", desc=True)\
                .limit(limit)\
                .execute()

            if not result.data:
                return "**📭 No memories found**\n\nUse `/memory store <content>` to add memories."

            output = f"**🧠 Recent Memories** ({len(result.data)} shown)\n\n"
            for blob in result.data:
                content_preview = blob['content'][:100] + "..." if len(blob['content']) > 100 else blob['content']
                blob_id_short = blob['id'][:8]
                output += f"**{blob_id_short}...** {content_preview}\n"
                output += f"   _Updated: {blob['updated_at'][:10]}_\n\n"

            return output

        elif cmd == 'reset':
            # Delete ALL user memories AND reset processing timestamps
            # First delete sentences (they reference blobs)
            supabase.table("blob_sentences")\
                .delete()\
                .eq("owner_id", owner_id)\
                .execute()

            # Then delete blobs
            result = supabase.table("blobs")\
                .delete()\
                .eq("owner_id", owner_id)\
                .execute()

            deleted_count = len(result.data) if result.data else 0

            # Reset processing timestamps so data can be reprocessed
            reset_counts = storage.reset_memory_processing_timestamps(owner_id)

            return f"""🗑️ **Memory reset complete**

**Deleted:**
• {deleted_count} memory blobs and all associated sentences

**Reset timestamps:**
• {reset_counts.get('emails', 0)} emails marked as unprocessed
• {reset_counts.get('calendar_events', 0)} calendar events marked as unprocessed
• {reset_counts.get('pipedrive_deals', 0)} Pipedrive deals marked as unprocessed

Run `/memory process` to rebuild memory from your synced data."""

        else:
            # Unknown subcommand
            return f"""❌ Unknown subcommand: `{args[0]}`

Use `/memory --help` to see available commands."""

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
"/archive --search query" to search emails

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

**Quick workflow:** `/sync` → `/briefing` → respond

**Pro tip:** Use `/sync --status` to check sync status.""",

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


async def handle_connect(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /connect command - list available connections and initiate connection flow.

    Usage:
    - /connect - List all available providers
    - /connect <provider> - Initiate connection for specific provider
    """
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.integrations.registry import get_available_providers, get_category_emoji

    try:
        supabase = SupabaseStorage()

        # If no args, show all available providers
        if not args:
            providers = get_available_providers(supabase, include_unavailable=False)

            if not providers:
                return "❌ **Error:** No providers available"

            output = "**📡 Available Connections**\n\n"
            output += "Select a provider to connect:\n\n"

            for i, provider in enumerate(providers, 1):
                emoji = get_category_emoji(provider['category'])
                output += f"{i}. {emoji} **{provider['display_name']}** - `/connect {provider['provider_key']}`\n"

            return output

        # Connect to specific provider
        provider_key = args[0].lower()

        # Get provider info
        result = supabase.client.table('integration_providers')\
            .select('*')\
            .eq('provider_key', provider_key)\
            .execute()

        # Debug logging
        logger.info(f"🔍 Query for provider_key='{provider_key}'")
        logger.info(f"🔍 Result.data: {result.data}")
        logger.info(f"🔍 Result.count: {result.count if hasattr(result, 'count') else 'N/A'}")

        if not result.data:
            return f"❌ **Error:** Provider '{provider_key}' not found\n\nRun `/connect` to see available providers"

        provider = result.data[0]

        if not provider['is_available']:
            return f"⏳ **{provider['display_name']}** is coming soon!\n\nRun `/connect` to see available providers"

        # OAuth provider - return authorization URL
        # Note: The CLI handles the local OAuth server and browser opening.
        # The backend just returns the OAuth URL for the CLI to use.
        if provider['requires_oauth']:
            oauth_url = provider.get('oauth_url', f'/api/auth/{provider_key}/authorize')

            return f"""**🔗 Connect {provider['display_name']}**

**OAuth Authorization Required**

For API clients, redirect user to:
```
{oauth_url}?owner_id={owner_id}
```

After authorization, tokens will be stored automatically.

Run `/connections` to verify connection."""

        # API key provider - show configuration instructions
        else:
            config_fields = provider.get('config_fields', {})
            fields_list = '\n'.join([f"• `{field}`: {info.get('label', field)}" for field, info in config_fields.items()])

            return f"""**🔧 Configure {provider['display_name']}**

This integration requires manual configuration.

**Required fields:**
{fields_list}

**Setup:**
1. Get your credentials from {provider['display_name']}
2. Store them securely in environment variables or database
3. Run `/connections` to verify connection

**Documentation:** {provider.get('documentation_url', 'Contact support for setup help')}"""

    except Exception as e:
        logger.error(f"Error in /connect command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


async def handle_email(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /email command - email listing, drafts, and search.

    Drafts are stored in Supabase (Superhuman-style).
    Sending routes through Gmail or Outlook API based on user's provider.

    Usage:
        /email list [--limit N]                  - List recent emails
        /email list --draft [--limit N]          - List drafts
        /email create [--to X] [--subject Y]     - Create draft
        /email send <draft_id>                   - Send draft
        /email delete <draft_id>                 - Delete draft
        /email search <query> [--from X] [--days N] [--limit N]  - Search emails
    """
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.api.token_storage import get_provider, get_email
    from datetime import datetime, timezone, timedelta
    import uuid
    import shlex

    if '--help' in args or not args:
        return """**📧 Email Command**

**List:**
• `/email list [--limit N]` - List recent emails
• `/email list --draft [--limit N]` - List drafts

**Drafts:**
• `/email create --to <email> --subject <text>` - Create draft
• `/email send <draft_id>` - Send draft via Gmail/Outlook
• `/email delete <draft_id>` - Delete draft

**Search:**
• `/email search <query>` - Search emails
• `/email search <query> --from <sender>` - Filter by sender
• `/email search <query> --days N` - Search last N days
• `/email search <query> --limit N` - Limit results

**Examples:**
• `/email list`
• `/email list --draft`
• `/email create --to mario@example.com --subject "Meeting tomorrow"`
• `/email search "contract" --days 30 --limit 10`
• `/email send abc123`

**Note:** Drafts are stored in Zylch. When you send, it routes through your connected Gmail or Outlook."""

    try:
        supabase = SupabaseStorage.get_instance().client

        # Get the subcommand (first positional arg)
        subcommand = args[0].lower() if args else ''
        sub_args = args[1:] if len(args) > 1 else []

        # Parse arguments
        def parse_flag(flag: str, default=None):
            """Extract value after a flag like --to or --subject."""
            for i, arg in enumerate(sub_args):
                if arg == flag and i + 1 < len(sub_args):
                    return sub_args[i + 1]
            return default

        def has_flag(flag: str) -> bool:
            """Check if a flag is present."""
            return flag in sub_args

        # --- LIST EMAILS or DRAFTS ---
        if subcommand == 'list':
            limit = int(parse_flag('--limit', '20'))
            limit = min(limit, 50)

            # If --draft flag, list drafts
            if has_flag('--draft'):
                result = supabase.table('drafts')\
                    .select('*')\
                    .eq('owner_id', owner_id)\
                    .eq('status', 'draft')\
                    .order('updated_at', desc=True)\
                    .limit(limit)\
                    .execute()

                if not result.data:
                    return "**📭 No drafts**\n\nCreate one with `/email create --to <email> --subject <text>`"

                output = f"**📝 Drafts** ({len(result.data)} found)\n\n"
                for i, draft in enumerate(result.data, 1):
                    to_str = ', '.join(draft.get('to_addresses', [])[:2])
                    if len(draft.get('to_addresses', [])) > 2:
                        to_str += f" (+{len(draft['to_addresses']) - 2})"
                    subject = draft.get('subject', '(no subject)')[:50]
                    draft_id = draft['id'][:8]
                    updated = draft['updated_at'][:10] if draft.get('updated_at') else ''

                    output += f"**{i}. {subject}**\n"
                    output += f"   To: {to_str}\n"
                    output += f"   ID: `{draft_id}` | {updated}\n\n"

                output += "_Use `/email send <id>` to send a draft._"
                return output

            # Default: list recent emails
            days = int(parse_flag('--days', '7'))
            since_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            result = supabase.table('emails')\
                .select('gmail_id, thread_id, subject, from_email, from_name, snippet, date')\
                .eq('owner_id', owner_id)\
                .gte('date', since_date)\
                .order('date', desc=True)\
                .limit(limit)\
                .execute()

            if not result.data:
                return f"**📭 No emails** in the last {days} days\n\nTry `/sync` to fetch recent emails."

            output = f"**📧 Recent Emails** ({len(result.data)} found)\n\n"
            for email in result.data:
                subject = email.get('subject', '(no subject)')[:45]
                from_name = email.get('from_name') or email.get('from_email', '?')
                date = email.get('date', '')[:10]

                output += f"**{subject}**\n"
                output += f"   From: {from_name} | {date}\n\n"

            output += f"_Showing last {days} days. Use `--days N` or `--limit N` to adjust._"
            return output

        # --- CREATE DRAFT ---
        if subcommand == 'create':
            to_addr = parse_flag('--to', '')
            subject = parse_flag('--subject', '')

            # Parse body from remaining args (everything after known flags)
            body = ''
            skip_next = False
            for i, arg in enumerate(sub_args):
                if skip_next:
                    skip_next = False
                    continue
                if arg in ('--to', '--subject'):
                    skip_next = True
                    continue
                body += arg + ' '
            body = body.strip()

            if not to_addr:
                return "❌ Missing recipient\n\nUsage: `/email create --to <email> [--subject <text>]`"

            # Parse multiple recipients
            to_addresses = [addr.strip() for addr in to_addr.split(',')]

            # Insert into Supabase
            draft_data = {
                'owner_id': owner_id,
                'to_addresses': to_addresses,
                'subject': subject or None,
                'body': body or None,
                'status': 'draft',
            }

            result = supabase.table('drafts').insert(draft_data).execute()

            if not result.data:
                return "❌ Failed to create draft"

            draft = result.data[0]
            return f"""✅ **Draft created** (ID: `{draft['id'][:8]}`)

**To:** {', '.join(to_addresses)}
**Subject:** {subject or '(none)'}

Use `/email send {draft['id'][:8]}` to send it.
Or `/email list` to see all drafts."""

        # --- SEND DRAFT ---
        if subcommand == 'send':
            # Get draft_id from first positional arg after 'send'
            draft_id = sub_args[0] if sub_args and not sub_args[0].startswith('--') else None

            if not draft_id:
                return "❌ Missing draft ID\n\nUsage: `/email send <draft_id>`"

            # Find the draft (support partial ID)
            result = supabase.table('drafts')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .eq('status', 'draft')\
                .like('id', f'{draft_id}%')\
                .execute()

            if not result.data:
                return f"❌ Draft not found: `{draft_id}`\n\nUse `/email list` to see your drafts."

            draft = result.data[0]

            # Get user's email provider
            provider = get_provider(owner_id)
            user_email = get_email(owner_id)

            if not provider:
                return "❌ No email provider connected\n\nUse `/connect google` or `/connect microsoft` first."

            # Mark as sending
            supabase.table('drafts').update({
                'status': 'sending',
                'provider': provider
            }).eq('id', draft['id']).execute()

            try:
                if provider == 'google':
                    from zylch.tools.gmail import GmailClient

                    gmail = GmailClient(
                        credentials_path="credentials/gmail_oauth.json",
                        account=user_email,
                        owner_id=owner_id
                    )

                    # Build and send message
                    sent_message = gmail.send_message(
                        to=draft['to_addresses'],
                        subject=draft.get('subject', ''),
                        body=draft.get('body', ''),
                        cc=draft.get('cc_addresses'),
                        bcc=draft.get('bcc_addresses'),
                        in_reply_to=draft.get('in_reply_to'),
                        references=draft.get('references'),
                        thread_id=draft.get('thread_id'),
                    )

                    sent_id = sent_message.get('id', '')

                elif provider == 'microsoft':
                    from zylch.tools.outlook import OutlookClient
                    from zylch.api.token_storage import get_graph_token

                    graph_token = get_graph_token(owner_id)
                    if not graph_token:
                        raise Exception("Microsoft token expired. Please reconnect.")

                    outlook = OutlookClient(
                        graph_token=graph_token['access_token'],
                        account=user_email
                    )

                    sent_message = outlook.send_message(
                        to=draft['to_addresses'],
                        subject=draft.get('subject', ''),
                        body=draft.get('body', ''),
                        cc=draft.get('cc_addresses'),
                        bcc=draft.get('bcc_addresses'),
                    )

                    sent_id = sent_message.get('id', '')

                else:
                    raise Exception(f"Unknown provider: {provider}")

                # Mark as sent
                supabase.table('drafts').update({
                    'status': 'sent',
                    'sent_at': datetime.now(timezone.utc).isoformat(),
                    'sent_message_id': sent_id,
                }).eq('id', draft['id']).execute()

                to_str = ', '.join(draft['to_addresses'][:2])
                return f"""✅ **Email sent!**

**To:** {to_str}
**Subject:** {draft.get('subject', '(no subject)')}
**Via:** {provider.title()}

Message ID: `{sent_id[:12] if sent_id else 'N/A'}`"""

            except Exception as e:
                # Mark as failed
                supabase.table('drafts').update({
                    'status': 'failed',
                    'error_message': str(e),
                }).eq('id', draft['id']).execute()

                logger.error(f"Failed to send email: {e}", exc_info=True)
                return f"❌ **Failed to send:** {str(e)}\n\nDraft saved. Fix the issue and try again with `/email send {draft_id}`"

        # --- DELETE DRAFT ---
        if subcommand == 'delete':
            # Get draft_id from first positional arg after 'delete'
            draft_id = sub_args[0] if sub_args and not sub_args[0].startswith('--') else None

            if not draft_id:
                return "❌ Missing draft ID\n\nUsage: `/email delete <draft_id>`"

            result = supabase.table('drafts')\
                .delete()\
                .eq('owner_id', owner_id)\
                .like('id', f'{draft_id}%')\
                .execute()

            if result.data:
                return f"✅ Draft `{draft_id}` deleted"
            else:
                return f"❌ Draft not found: `{draft_id}`"

        # --- SEARCH EMAILS ---
        if subcommand == 'search':
            # Get query from first positional arg after 'search'
            query = sub_args[0] if sub_args and not sub_args[0].startswith('--') else None

            if not query:
                return "❌ Missing search query\n\nUsage: `/email search <query>`"

            sender = parse_flag('--from', '')
            days = int(parse_flag('--days', '30'))
            limit = int(parse_flag('--limit', '10'))
            limit = min(limit, 50)

            # Search in emails table (synced via /sync)
            from datetime import timedelta

            since_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            # Build query
            q = supabase.table('emails')\
                .select('gmail_id, thread_id, subject, from_email, from_name, snippet, date')\
                .eq('owner_id', owner_id)\
                .gte('date', since_date)\
                .order('date', desc=True)\
                .limit(limit)

            # Text search in subject/snippet
            q = q.or_(f'subject.ilike.%{query}%,snippet.ilike.%{query}%')

            if sender:
                q = q.ilike('from_email', f'%{sender}%')

            result = q.execute()

            if not result.data:
                return f"**📭 No emails found** matching `{query}`\n\nTry `/sync` first to fetch recent emails."

            output = f"**🔍 Search Results** ({len(result.data)} found)\n\n"
            for email in result.data:
                subject = email.get('subject', '(no subject)')[:40]
                from_name = email.get('from_name') or email.get('from_email', '?')
                date = email.get('date', '')[:10]
                snippet = (email.get('snippet', '')[:60] + '...') if email.get('snippet') else ''

                output += f"**{subject}**\n"
                output += f"   From: {from_name} | {date}\n"
                if snippet:
                    output += f"   _{snippet}_\n"
                output += "\n"

            return output

        # Unknown subcommand
        return f"❌ Unknown subcommand: `{subcommand}`\n\nUse `/email --help` to see available options."

    except Exception as e:
        logger.error(f"Error in /email command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


# Command help texts - source of truth for all clients (CLI, web, mobile)
COMMAND_HELP = {
    '/help': {
        'summary': 'Show available commands',
        'usage': '/help',
        'description': 'Lists all available slash commands.',
    },
    '/sync': {
        'summary': 'Sync emails and calendar',
        'usage': '/sync [--days <n>] [--status] [--reset]',
        'description': '''Fetches new emails from Gmail and calendar events from Google Calendar.
Also runs Memory Agent to extract facts from emails into entity blobs.

**Arguments:**
- `--days <n>` - Number of days to sync (default: 30 for first sync, incremental after)
- `--status` - Show sync status (last sync time, email count, event count)
- `--reset` - Clear sync state and force full re-sync (warns about memory)

**Examples:**
- `/sync` - Sync with defaults (incremental after first sync)
- `/sync --days 1` - Sync only last 1 day (useful for testing)
- `/sync --days 300` - Sync last 300 days
- `/sync --status` - Check sync status without syncing
- `/sync --reset` - Reset sync state, then run `/sync` to re-sync

**Fresh start:** To rebuild everything from scratch:
1. `/memory --reset` - Clear memory blobs
2. `/sync --reset` - Clear emails/calendar
3. `/sync --days 30` - Re-sync and rebuild memory''',
    },
    '/briefing': {
        'summary': 'Daily briefing of tasks and unanswered conversations',
        'usage': '/briefing [days]',
        'description': '''Show your daily briefing of tasks and unanswered conversations.

Analyzes email threads to detect tasks you need to act on.

**Arguments:**
- `days` - Number of days to analyze (default: 7)

**Examples:**
- `/briefing` - Show today's briefing (last 7 days)
- `/briefing 1` - Yesterday only
- `/briefing 30` - Full month briefing

**Task types detected:**
- **answer** - Someone asked you a question
- **reminder** - You promised to do something

Run `/sync` first to fetch latest emails.''',
    },
    '/model': {
        'summary': 'Switch AI model',
        'usage': '/model [haiku|sonnet|opus]',
        'description': 'Switch between Claude models for different speed/quality tradeoffs.',
    },
    '/memory': {
        'summary': 'Entity memory system',
        'usage': '/memory [process|search|store|stats|list|--reset] <args>',
        'description': '''Process synced data into memory blobs, search, and manage entity memories.

**Processing:**
- `/memory process` - Process all unprocessed data into blobs
- `/memory process email` - Process only unprocessed emails
- `/memory process calendar` - Process only unprocessed calendar events
- `/memory process pipedrive` - Process only unprocessed Pipedrive deals

**Searching:**
- `/memory search <query>` - Search memories (hybrid FTS + semantic)
- `/memory store <content>` - Store new memory (with auto-reconsolidation)

**Management:**
- `/memory stats` - Show memory statistics
- `/memory list [limit]` - List recent memories
- `/memory --reset` - Delete ALL memories AND reset processing timestamps

**Workflow:**
1. `/sync` - Fetches emails/calendar/pipedrive to local DB
2. `/memory process` - Extracts facts into blobs
3. `/memory search <query>` - Finds stored information''',
    },
    '/email': {
        'summary': 'List emails, manage drafts, search',
        'usage': '/email <list|create|send|delete|search> [args]',
        'description': '''List emails, manage drafts, and search.

**List:**
- `/email list [--limit N]` - List recent emails
- `/email list --draft [--limit N]` - List drafts

**Drafts:**
- `/email create --to <email> --subject <text>` - Create draft
- `/email send <draft_id>` - Send via Gmail/Outlook
- `/email delete <draft_id>` - Delete draft

**Search:**
- `/email search <query>` - Search emails
- `/email search <query> --from <sender> --days N --limit N`''',
    },
    '/trigger': {
        'summary': 'Manage event triggers',
        'usage': '/trigger [--list|--add|--remove]',
        'description': 'Configure automated triggers for events like new emails.',
    },
    '/mrcall': {
        'summary': 'MrCall integration',
        'usage': '/mrcall [--status|--sync]',
        'description': 'Manage MrCall telephony integration.',
    },
    '/share': {
        'summary': 'Share access with others',
        'usage': '/share <email>',
        'description': 'Share your Zylch data with another user.',
    },
    '/revoke': {
        'summary': 'Revoke shared access',
        'usage': '/revoke <email>',
        'description': 'Remove shared access from a user.',
    },
    '/clear': {
        'summary': 'Clear conversation history',
        'usage': '/clear',
        'description': 'Clears the conversation history. Note: Server is stateless, this clears client-side history.',
    },
    '/tutorial': {
        'summary': 'Interactive tutorials',
        'usage': '/tutorial [topic]',
        'description': 'Learn how to use Zylch with interactive tutorials.',
    },
    '/connect': {
        'summary': 'Manage external integrations',
        'usage': '/connect [provider]',
        'description': '''View and manage external service connections (Google, Microsoft, Anthropic, etc.).

**Usage:**
- `/connect` - List all available integrations and their status
- `/connect google` - Connect Google (Gmail + Calendar)
- `/connect microsoft` - Connect Microsoft (Outlook + Calendar)
- `/connect anthropic` - Connect Anthropic Claude API

**Examples:**
- `/connect` - Show connection status
- `/connect anthropic` - Add your Anthropic API key''',
    },
    # Phase 1: High-impact commands (replacing tools)
    '/stats': {
        'summary': 'Email statistics',
        'usage': '/stats',
        'description': 'Shows statistics about synced emails: total count, unread, threads, date range, open conversations.',
    },
    '/calendar': {
        'summary': 'Show calendar events',
        'usage': '/calendar [days] [--limit N]',
        'description': 'Shows upcoming calendar events. Default: next 7 days.',
    },
    '/tasks': {
        'summary': 'List open tasks',
        'usage': '/tasks [--limit N]',
        'description': 'Lists open tasks (emails needing response). Shows priority and context.',
    },
    '/jobs': {
        'summary': 'Scheduled jobs and reminders',
        'usage': '/jobs [--cancel <id>]',
        'description': 'Lists scheduled reminders and jobs. Use `--cancel <id>` to cancel a job.',
    },
    '/train': {
        'summary': 'Train personalized prompts from your data',
        'usage': '/train [build|show|reset] <type>',
        'description': '''Build and manage personalized prompts that learn from your email patterns.

**Usage:**
- `/train build memory-email` - Analyze your emails to create personalized extraction prompt
- `/train show memory-email` - Display your current prompt
- `/train reset memory-email` - Delete custom prompt, return to default

**How it works:**
1. Run `/sync` to sync your email history
2. `/train build memory-email` analyzes patterns:
   - Who you reply to (VIP contacts)
   - What you ignore (cold outreach)
   - Your role and business context
3. Creates a personalized prompt stored in your account
4. `/memory process email` uses this prompt for smarter extraction

**Why personalize?**
- Better cold outreach detection specific to YOU
- VIP contacts get detailed fact extraction
- Your role/context understood (founder vs investor vs engineer)
- Significantly improved memory quality''',
    },
}

async def handle_stats(args: List[str], owner_id: str) -> str:
    """Handle /stats command - email statistics."""
    from zylch.storage.supabase_client import SupabaseStorage
    from datetime import datetime, timedelta, timezone

    if '--help' in args:
        return """**📊 Email Statistics**

**Usage:** `/stats`

Shows statistics about your synced emails:
- Total emails and threads
- Unread count
- Date range
- Open conversations needing response"""

    try:
        supabase = SupabaseStorage.get_instance().client

        # Count total emails
        email_result = supabase.table('emails')\
            .select('id', count='exact')\
            .eq('owner_id', owner_id)\
            .execute()
        total_emails = email_result.count if hasattr(email_result, 'count') else 0

        # Count threads
        thread_result = supabase.table('emails')\
            .select('thread_id')\
            .eq('owner_id', owner_id)\
            .execute()
        unique_threads = len(set(e['thread_id'] for e in thread_result.data)) if thread_result.data else 0

        # Get date range
        oldest = supabase.table('emails')\
            .select('date')\
            .eq('owner_id', owner_id)\
            .order('date', desc=False)\
            .limit(1)\
            .execute()
        newest = supabase.table('emails')\
            .select('date')\
            .eq('owner_id', owner_id)\
            .order('date', desc=True)\
            .limit(1)\
            .execute()

        oldest_date = oldest.data[0]['date'][:10] if oldest.data else 'N/A'
        newest_date = newest.data[0]['date'][:10] if newest.data else 'N/A'

        # Count open avatars (need response)
        avatar_result = supabase.table('avatars')\
            .select('id', count='exact')\
            .eq('owner_id', owner_id)\
            .eq('relationship_status', 'open')\
            .execute()
        open_count = avatar_result.count if hasattr(avatar_result, 'count') else 0

        return f"""**📊 Email Statistics**

**Total Emails:** {total_emails:,}
**Threads:** {unique_threads:,}
**Date Range:** {oldest_date} → {newest_date}

**Open Conversations:** {open_count} need response

Run `/sync` to update or `/briefing` for task details."""

    except Exception as e:
        logger.error(f"Error in /stats: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


async def handle_calendar(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /calendar command - list calendar events."""
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.api.token_storage import get_provider, get_email
    from datetime import datetime, timedelta, timezone

    if '--help' in args:
        return """**📅 Calendar**

**Usage:** `/calendar [days] [--limit N]`

Shows your upcoming calendar events.

**Arguments:**
- `days` - Days ahead to show (default: 7)
- `--limit N` - Max events to show (default: 20)

**Examples:**
- `/calendar` - Events for next 7 days
- `/calendar 1` - Today only
- `/calendar 30 --limit 50` - Next month"""

    try:
        # Parse arguments
        days_ahead = 7
        limit = 20

        for i, arg in enumerate(args):
            if arg == '--limit' and i + 1 < len(args):
                try:
                    limit = min(int(args[i + 1]), 50)
                except ValueError:
                    pass
            elif arg.isdigit():
                days_ahead = int(arg)

        # Get from Supabase (synced via /sync)
        supabase = SupabaseStorage.get_instance().client

        now = datetime.now(timezone.utc)
        end_date = now + timedelta(days=days_ahead)

        result = supabase.table('calendar_events')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .gte('start_time', now.isoformat())\
            .lte('start_time', end_date.isoformat())\
            .order('start_time', desc=False)\
            .limit(limit)\
            .execute()

        if not result.data:
            return f"""**📅 Calendar** (next {days_ahead} days)

📭 No events found.

Run `/sync` to fetch calendar events."""

        output = f"**📅 Calendar** ({len(result.data)} events, next {days_ahead} days)\n\n"

        current_date = None
        for event in result.data:
            # Parse start time
            start_str = event.get('start_time', '')
            try:
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                event_date = start_dt.strftime('%A, %B %d')
                event_time = start_dt.strftime('%H:%M')
            except:
                event_date = start_str[:10] if start_str else 'Unknown'
                event_time = ''

            # Group by date
            if event_date != current_date:
                current_date = event_date
                output += f"\n**{event_date}**\n"

            title = event.get('summary', '(no title)')[:50]
            location = event.get('location', '')

            output += f"• {event_time} - {title}"
            if location:
                output += f" 📍 {location[:30]}"
            output += "\n"

        return output

    except Exception as e:
        logger.error(f"Error in /calendar: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


async def handle_tasks(args: List[str], owner_id: str) -> str:
    """Handle /tasks command - list open tasks."""
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.services.task_formatter import filter_own_emails, format_task_list

    if '--help' in args:
        return """**✅ Tasks**

**Usage:** `/tasks [--limit N]`

Shows your open tasks (emails needing response).

**Options:**
- `--limit N` - Max tasks to show (default: all)

**Related:**
- `/briefing` - Full daily briefing with context
- `/sync` - Sync emails to update tasks"""

    try:
        supabase = SupabaseStorage.get_instance().client

        # Parse limit
        limit = 50
        if '--limit' in args:
            idx = args.index('--limit')
            if idx + 1 < len(args):
                try:
                    limit = min(int(args[idx + 1]), 100)
                except ValueError:
                    pass

        result = supabase.table('avatars')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .or_('relationship_status.eq.open,relationship_status.eq.waiting')\
            .gte('relationship_score', 3)\
            .order('relationship_score', desc=True)\
            .limit(limit)\
            .execute()

        avatars = result.data or []
        avatars = filter_own_emails(avatars)

        if not avatars:
            return """**✅ Tasks**

🎉 No open tasks! You're all caught up.

Run `/sync` to check for new emails."""

        return format_task_list(avatars, include_stale_warning=False)

    except Exception as e:
        logger.error(f"Error in /tasks: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


async def handle_jobs(args: List[str], owner_id: str) -> str:
    """Handle /jobs command - list scheduled jobs."""
    from zylch.services.scheduler import ZylchScheduler

    if '--help' in args:
        return """**⏰ Scheduled Jobs**

**Usage:** `/jobs [--cancel <id>]`

Shows your scheduled reminders and jobs.

**Options:**
- `--cancel <id>` - Cancel a job by ID

**Related:**
- "remind me in 2 hours" - Schedule via Claude
- `/trigger` - Event-driven automation"""

    try:
        scheduler = ZylchScheduler(owner_id=owner_id)

        # Handle cancel
        if '--cancel' in args:
            idx = args.index('--cancel')
            if idx + 1 < len(args):
                job_id = args[idx + 1]
                success = scheduler.cancel_job(job_id)
                if success:
                    return f"✅ **Job cancelled:** `{job_id[:8]}`"
                else:
                    return f"❌ **Job not found:** `{job_id[:8]}`"
            else:
                return "❌ Missing job ID. Usage: `/jobs --cancel <id>`"

        # List jobs
        jobs = scheduler.list_jobs()

        if not jobs:
            return """**⏰ Scheduled Jobs**

📭 No scheduled jobs.

**Create one:**
- "remind me in 2 hours to call Mario"
- `/trigger --add session_start "Check my emails"`"""

        output = f"**⏰ Scheduled Jobs** ({len(jobs)} found)\n\n"

        for job in jobs:
            job_id = job.get('id', '')[:8]
            job_type = job.get('type', 'reminder')
            next_run = job.get('next_run', 'N/A')
            description = job.get('description', '')[:50]

            type_emoji = {'reminder': '🔔', 'conditional': '⚡'}.get(job_type, '📋')

            output += f"{type_emoji} **{job_type}** (ID: `{job_id}`)\n"
            output += f"   {description}\n"
            output += f"   Next: {next_run}\n\n"

        output += "_Use `/jobs --cancel <id>` to cancel._"
        return output

    except Exception as e:
        logger.error(f"Error in /jobs: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


async def handle_train(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /train command - train personalized prompts from user data."""
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.services.prompt_builder import PromptBuilder

    if '--help' in args or not args:
        return """**🎓 Train Personalized Prompts**

**Usage:**
• `/train build memory-email` - Analyze your emails and create personalized extraction prompt
• `/train show memory-email` - Show your current email memory prompt
• `/train reset memory-email` - Reset to default prompt

**How it works:**
1. Run `/sync` first to ensure emails are available
2. `/train build memory-email` analyzes your sent/received patterns
3. Creates a personalized prompt that understands:
   - Who matters to you (VIP contacts)
   - What to extract from their emails
   - What to ignore (cold outreach, etc.)
4. `/memory process email` uses this prompt for extraction

**Why personalize?**
- The system learns YOUR patterns, not generic rules
- VIP contacts get detailed extraction
- Cold outreach patterns specific to YOU are filtered
- Your role/context is understood (founder vs investor vs engineer)"""

    try:
        storage = SupabaseStorage.get_instance()
        cmd = args[0].lower()
        prompt_type = args[1].lower() if len(args) > 1 else None

        # Normalize prompt type
        prompt_type_normalized = None
        if prompt_type == 'memory-email':
            prompt_type_normalized = 'memory_email'
        elif prompt_type:
            return f"❌ Unknown prompt type: `{prompt_type}`\n\nAvailable types: `memory-email`"

        if cmd == 'build':
            if not prompt_type_normalized:
                return "❌ Missing prompt type.\n\nUsage: `/train build memory-email`"

            if prompt_type_normalized == 'memory_email':
                # Check sync status first
                sync_state = storage.get_sync_state(owner_id)
                if not sync_state or not sync_state.get('full_sync_completed'):
                    return """❌ **Please sync your emails first**

Run `/sync` to synchronize your email history.
Then run `/train build memory-email` again."""

                # Check email count
                emails = storage.get_emails(owner_id, limit=1)
                if not emails:
                    return """❌ **No emails found**

Run `/sync --days 90` to sync more email history.
Need at least some emails to analyze patterns."""

                # Get Anthropic API key from user's stored key or system settings
                anthropic_key = storage.get_anthropic_key(owner_id) or settings.anthropic_api_key

                if not anthropic_key:
                    return """❌ **Anthropic API key required**

Connect your Anthropic account:
`/connect anthropic`"""

                # Build the prompt
                builder = PromptBuilder(storage, owner_id, anthropic_key)
                prompt_content, metadata = await builder.build_memory_email_prompt()

                # Store in DB
                storage.store_user_prompt(owner_id, 'memory_email', prompt_content, metadata)

                return f"""✅ **Email memory prompt created**

**Analyzed:**
- {metadata.get('replied_threads_analyzed', 0)} threads you replied to
- {metadata.get('ignored_emails_analyzed', 0)} emails you ignored
- {metadata.get('vip_contacts_count', 0)} VIP contacts identified
- {metadata.get('noise_patterns_count', 0)} noise patterns detected

**What was learned:**
- Your role and business context
- VIP contacts who deserve detailed extraction
- Cold outreach patterns specific to you
- Topics you engage with vs ignore

**Next steps:**
- `/train show memory-email` to review the prompt
- `/memory process email` to extract memories using this prompt"""

        elif cmd == 'show':
            if not prompt_type_normalized:
                return "❌ Missing prompt type.\n\nUsage: `/train show memory-email`"

            prompt_content = storage.get_user_prompt(owner_id, prompt_type_normalized)
            if not prompt_content:
                return f"""❌ **No custom prompt found for `{prompt_type}`**

Create one with:
`/train build {prompt_type}`"""

            # Get metadata too
            meta = storage.get_user_prompt_metadata(owner_id, prompt_type_normalized)
            meta_info = ""
            if meta:
                metadata = meta.get('metadata', {})
                created = meta.get('created_at', '')[:10] if meta.get('created_at') else 'unknown'
                meta_info = f"\n_Created: {created} | VIPs: {metadata.get('vip_contacts_count', 'N/A')} | Noise patterns: {metadata.get('noise_patterns_count', 'N/A')}_\n"

            # Truncate if too long for display
            display_content = prompt_content
            if len(prompt_content) > 2000:
                display_content = prompt_content[:2000] + f"\n\n_... ({len(prompt_content) - 2000} more characters)_"

            return f"""**📝 Your Email Memory Prompt**
{meta_info}
---
{display_content}
---

_Use `/train reset memory-email` to delete and return to default._"""

        elif cmd == 'reset':
            if not prompt_type_normalized:
                return "❌ Missing prompt type.\n\nUsage: `/train reset memory-email`"

            deleted = storage.delete_user_prompt(owner_id, prompt_type_normalized)
            if deleted:
                return f"""✅ **Prompt reset**

Your custom `{prompt_type}` prompt has been deleted.
Memory extraction will use the default prompt.

Recreate with: `/train build {prompt_type}`"""
            else:
                return f"❌ No custom prompt found for `{prompt_type}`"

        else:
            return f"""❌ Unknown subcommand: `{cmd}`

**Available commands:**
- `/train build memory-email`
- `/train show memory-email`
- `/train reset memory-email`"""

    except Exception as e:
        logger.error(f"Error in /train: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


# Export all handlers
COMMAND_HANDLERS = {
    '/echo': handle_echo,
    '/help': handle_help,
    '/sync': handle_sync,
    '/clear': handle_clear,
    '/briefing': handle_briefing,
    '/model': handle_model,
    '/memory': handle_memory,
    '/email': handle_email,
    '/trigger': handle_trigger,
    '/mrcall': handle_mrcall,
    '/connect': handle_connect,
    '/share': handle_share,
    '/revoke': handle_revoke,
    '/tutorial': handle_tutorial,
    # Phase 1: High-impact commands (replacing tools)
    '/stats': handle_stats,
    '/calendar': handle_calendar,
    '/tasks': handle_tasks,
    '/jobs': handle_jobs,
    '/train': handle_train,
}


# Natural language triggers for semantic command matching
# Maps commands to phrases that should trigger them
#
# TYPED PARAMETER DSL:
# Use {param_name:type} syntax to extract parameters from natural language
#
# Supported types:
#   int      - integers (e.g., "12", "5", "100")
#   email    - email addresses (e.g., "mario@example.com")
#   text     - free text, greedy (e.g., "the project update")
#   date     - date expressions (e.g., "tomorrow", "next monday", "March 5")
#   time     - time expressions (e.g., "3pm", "15:30", "noon")
#   duration - duration expressions (e.g., "30 minutes", "2 hours")
#   model    - AI model names (e.g., "haiku", "sonnet", "opus")
#
# The semantic matcher:
# 1. Strips placeholders from templates for embedding comparison
# 2. Finds best semantic match using embeddings
# 3. Extracts typed values from the original user input
#
COMMAND_TRIGGERS = {
    # --- Sync & Data ---
    '/sync': [
        "sync",
        "synchronize",
        "sync my data",
        "synchronize everything",
        "fetch my emails",
        "update my emails and calendar",
        "get my latest emails",
        "pull new messages",
        "refresh my inbox",
        "download my emails",
        "sync emails and calendar",
        "update my data",
        "check for new emails",
        "refresh",
        "update",
        # With {days:int} parameter
        "sync the last {days:int} days",
        "sync emails from the last {days:int} days",
        "synchronize the last {days:int} days",
        "synchronize the past {days:int} days",
        "sync the past {days:int} days",
        "sync past {days:int} days",
        "synchronize with the past {days:int} days",
        "sync with the last {days:int} days",
        "get emails from the last {days:int} days",
        "fetch emails from the past {days:int} days",
    ],
    '/memory --reset': [
        "reset memory",
        "clear memory",
        "delete memory",
        "delete all memory",
        "wipe memory",
        "erase memory",
        "clear all memories",
        "delete all blobs",
        "forget everything",
        "clear my memory",
    ],

    # --- Help ---
    '/help': [
        "help",
        "commands",
        "what can you do",
        "show me commands",
        "help me",
        "what commands are available",
        "how do I use this",
        "list available features",
        "?",
        "how to use",
        "aiuto",
        "ayuda",
        "aide",
    ],

    # --- Clear ---
    '/clear': [
        "clear",
        "reset",
        "clear history",
        "reset conversation",
        "start fresh",
        "new conversation",
        "clear chat",
        "erase",
        "start over",
    ],

    # --- Model Selection ---
    '/model': [
        "change AI model",
        "switch model",
        "use faster model",
        "use smarter model",
        "change to {model:model}",
        "switch to {model:model}",
        "use {model:model}",
        "use {model:model} model",
    ],

    # --- Memory System ---
    '/memory': [
        # Process (extract facts from synced data)
        "process memory",
        "process emails into memory",
        "process calendar into memory",
        "process pipedrive into memory",
        "process deals into memory",
        "extract facts from emails",
        "extract facts from pipedrive",
        "build memory from synced data",
        "run memory agent",
        # Search
        "search memory",
        "search memory for {query:text}",
        "who is {query:text}",
        "what do you know about {query:text}",
        "find in memory {query:text}",
        # Store
        "store memory",
        "remember that {content:text}",
        "save to memory {content:text}",
        # Stats & List
        "memory stats",
        "memory statistics",
        "list memories",
        "show memories",
        "show the last {limit:int} memories",
        "list {limit:int} memories",
        # Reset
        "reset memory",
        "clear memory",
        "delete all memories",
        "wipe memory and reprocess",
    ],

    # --- Triggers/Automation ---
    '/trigger': [
        "set up automation",
        "create trigger",
        "automate",
        "when email arrives",
        "create rule",
        "list triggers",
        "show triggers",
        "remove trigger {trigger_id:text}",
        "delete trigger {trigger_id:text}",
    ],

    # --- Connections ---
    '/connect': [
        "connect",
        "connections",
        "integrations",
        "connect my account",
        "link google",
        "link outlook",
        "set up integration",
        "connect email",
        "add calendar",
        "link",
        "setup",
        "connect {provider:text}",
    ],

    # --- Sharing ---
    '/share': [
        "share my data",
        "give someone access",
        "share with {email:email}",
        "grant access to {email:email}",
        "share with {name:text}",
    ],
    '/revoke': [
        "revoke access",
        "remove access",
        "stop sharing",
        "revoke sharing",
        "revoke access from {email:email}",
        "stop sharing with {email:email}",
    ],

    # --- Tutorial ---
    '/tutorial': [
        "show me how",
        "tutorial",
        "learn how to",
        "guide me",
        "getting started",
        "tutorial on {topic:text}",
        "how do I {topic:text}",
    ],

    # --- Briefing/Tasks ---
    '/briefing': [
        "briefing",
        "daily briefing",
        "morning briefing",
        "what's on my plate",
        "today's tasks",
        "show me my briefing",
        "daily update",
        "morning update",
        "daily",
        "today",
        "gaps",
        "tasks",
        "what tasks do I have",
        "show me unanswered emails",
        "what needs my attention",
        "what should I work on",
        "pending tasks",
        "what do I need to respond to",
        "emails waiting for reply",
        "show my open items",
        "analyze my inbox",
        "todos",
        "to-dos",
        "action items",
        "show {limit:int} tasks",
        "top {limit:int} priorities",
    ],

    # --- MrCall/Phone ---
    '/mrcall': [
        "phone integration",
        "mrcall status",
        "telephone integration",
        "starchat integration",
    ],

    # --- Email (NEW - replaces Gmail tools) ---
    '/email': [
        # Drafts - List
        "list drafts",
        "show drafts",
        "my drafts",
        "show my drafts",
        "list my drafts",
        "show the last {limit:int} drafts",
        "list {limit:int} drafts",
        # Drafts - Create
        "create draft",
        "draft email",
        "draft email to {to:email}",
        "draft email to {to:text}",
        "compose email",
        "compose email to {to:email}",
        "write email to {to:email} about {subject:text}",
        # Drafts - Send
        "send draft",
        "send draft {draft_id:text}",
        "send the email",
        "send it",
        # Drafts - Delete
        "delete draft",
        "delete draft {draft_id:text}",
        "discard draft",
        # Search
        "search emails",
        "search emails for {query:text}",
        "search emails from {sender:text}",
        "find emails about {query:text}",
        "find emails from {sender:email}",
        "emails from {sender:text}",
        "emails about {query:text}",
        "show emails from the last {days:int} days",
        "search {limit:int} emails for {query:text}",
    ],

    # --- Calendar (NEW) ---
    '/calendar': [
        # List
        "show calendar",
        "my calendar",
        "calendar for today",
        "calendar for {date:date}",
        "show calendar for {date:date}",
        "what's on my calendar",
        "meetings today",
        "meetings {date:date}",
        "events this week",
        "show the next {limit:int} events",
        # Create
        "create event",
        "schedule meeting",
        "schedule meeting with {attendee:text}",
        "schedule meeting with {attendee:text} on {date:date}",
        "schedule meeting with {attendee:text} at {time:time}",
        "create event on {date:date}",
        "add event {title:text}",
        # Search
        "search calendar",
        "search calendar for {query:text}",
        "find meetings about {query:text}",
        "when is my meeting with {attendee:text}",
    ],

    # --- Reminders (NEW) ---
    '/reminder': [
        "remind me",
        "set reminder",
        "remind me in {duration:duration}",
        "remind me in {duration:duration} to {task:text}",
        "remind me at {time:time}",
        "remind me at {time:time} to {task:text}",
        "remind me on {date:date}",
        "remind me on {date:date} to {task:text}",
        "remind me to {task:text}",
        "list reminders",
        "show reminders",
        "cancel reminder",
        "cancel reminder {reminder_id:text}",
    ],

    # --- Stats (Phase 1 - replaces _EmailStatsTool) ---
    '/stats': [
        "stats",
        "statistics",
        "email stats",
        "email statistics",
        "inbox stats",
        "inbox statistics",
        "how many emails",
        "how many unread",
        "email count",
        "show stats",
        "show statistics",
        "give me stats",
        "email summary",
        "inbox summary",
    ],

    # --- Tasks (Phase 1 - replaces _GetTasksTool) ---
    '/tasks': [
        "tasks",
        "my tasks",
        "show tasks",
        "list tasks",
        "open tasks",
        "pending tasks",
        "what do I need to do",
        "what needs doing",
        "action items",
        "to do list",
        "todo list",
        "to-do list",
        "things to do",
        "show {limit:int} tasks",
        "top {limit:int} tasks",
    ],

    # --- Jobs (Phase 1 - replaces ListScheduledJobsTool) ---
    '/jobs': [
        "jobs",
        "scheduled jobs",
        "my jobs",
        "list jobs",
        "show jobs",
        "pending jobs",
        "scheduled reminders",
        "my reminders",
        "upcoming reminders",
        "what's scheduled",
        "scheduled tasks",
        "cancel job {job_id:text}",
        "cancel {job_id:text}",
    ],

    # --- Training (Personalized extraction prompts) ---
    '/train': [
        # Build
        "train zylch from email",
        # Show
        "let me see your training prompts",
        # Reset
        "reset training",
    ],
}
