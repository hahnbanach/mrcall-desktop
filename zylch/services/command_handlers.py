"""Command handlers for slash commands.

All handlers return markdown-formatted strings (no print statements).
No Anthropic API calls in these handlers.
"""
import logging
from datetime import datetime, timezone
from typing import List

from zylch.tools.config import ToolConfig

logger = logging.getLogger(__name__)


def format_task_items(tasks: list) -> str:
    """Format task items as numbered list grouped by urgency."""
    if not tasks:
        return "🎉 No action needed! You're all caught up."

    lines = ["**📋 Tasks Needing Action**\n"]

    # Group by urgency
    high = [t for t in tasks if t.get('urgency') == 'high']
    medium = [t for t in tasks if t.get('urgency') == 'medium']
    low = [t for t in tasks if t.get('urgency') == 'low']

    idx = 1
    if high:
        lines.append("🔴 **HIGH PRIORITY:**")
        for task in high:
            name = task.get('contact_name') or task.get('contact_email', 'Unknown')
            action = task.get('suggested_action', 'Review')
            lines.append(f"{idx}. **{name}**: {action}")
            idx += 1
        lines.append("")

    if medium:
        lines.append("⚡ **MEDIUM PRIORITY:**")
        for task in medium:
            name = task.get('contact_name') or task.get('contact_email', 'Unknown')
            action = task.get('suggested_action', 'Review')
            lines.append(f"{idx}. **{name}**: {action}")
            idx += 1
        lines.append("")

    if low:
        lines.append("💤 **LOW PRIORITY:**")
        for task in low:
            name = task.get('contact_name') or task.get('contact_email', 'Unknown')
            action = task.get('suggested_action', 'Review')
            lines.append(f"{idx}. **{name}**: {action}")
            idx += 1

    lines.append(f"\n**Total: {idx - 1} items** | `more on #N` for details")
    return "\n".join(lines)


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
• `/sync [days <n>|status|reset]` - Sync email and calendar
• `/stats` - Email statistics (count, unread, threads)
• `/email list|create|send|delete|search` - Manage drafts and search

**📅 Calendar & Tasks:**
• `/calendar [days]` - Show upcoming events
• `/tasks` - List open tasks (needs response)
• `/jobs` - Scheduled reminders and jobs

**🧠 Memory & Agents:**
• `/agent [train|process|show|reset]` - Train agents and process data into memory
• `/memory [search|store|stats|list]` - Search and manage entity memories
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
• `/clear` - Clear conversation history
• `/help` - Show this message

**💡 Tip:** Chat naturally! "show my tasks", "email stats", "what's on my calendar"."""


async def handle_sync(args: List[str], config, owner_id: str) -> str:
    """Handle /sync command - now using background job system."""
    from zylch.api.token_storage import get_provider
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.services.sync_service import SyncService  # Used for mrcall subcommand

    help_text = """**🔄 Sync**

**Usage:**
• `/sync` - Sync emails and calendar (incremental)
• `/sync status` - Show sync status
• `/sync reset` - Clear all synced data
• `/sync --days N` - Sync last N days
• `/sync mrcall` - Test MrCall conversation fetch (debug)

**Examples:**
• `/sync` - Quick incremental sync
• `/sync --days 90` - Sync last 90 days
• `/sync status` - Check last sync time
• `/sync mrcall` - Fetch latest MrCall conversation"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    # Separate positional args from options
    positional = [a for a in args if not a.startswith('--')]
    subcommand = positional[0].lower() if positional else None

    # Subcommand: status
    if subcommand == 'status':
        logger.info(f"[/sync] Status check for owner_id={owner_id}")
        try:
            supabase = SupabaseStorage()
            result = supabase.client.table('sync_state').select('*').eq('owner_id', owner_id).execute()

            if not result.data:
                return "📊 **Sync Status**\n\n❌ No sync state found - never synced.\n\nRun `/sync` or `/sync days <n>` to start."

            sync_state = result.data[0]
            last_sync = sync_state.get('last_sync')

            # Format last sync time or show "Never" if missing
            if last_sync:
                # Parse and format the timestamp nicely
                from datetime import datetime
                if isinstance(last_sync, str):
                    dt = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))
                    last_sync_display = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    last_sync_display = last_sync.strftime('%Y-%m-%d %H:%M:%S UTC')
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

Run `/sync` or `/sync --days N` to sync more data."""
        except Exception as e:
            logger.error(f"[/sync] Failed to get sync status: {e}")
            return f"❌ **Error getting sync status:** {str(e)}"

    # Subcommand: reset
    if subcommand == 'reset':
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
/memory reset
```
Then run `/sync --days N` to rebuild memory from re-synced emails."""
        except Exception as e:
            logger.error(f"[/sync] Failed to reset sync state: {e}")
            return f"❌ **Error resetting sync state:** {str(e)}"

    # Subcommand: mrcall - Test MrCall API integration
    if subcommand == 'mrcall':
        logger.info(f"[/sync] MrCall test for owner_id={owner_id}")
        try:
            from zylch.api.token_storage import get_mrcall_credentials
            supabase = SupabaseStorage()

            # Get MrCall OAuth credentials (includes access_token and business_id)
            mrcall_creds = get_mrcall_credentials(owner_id)
            if not mrcall_creds or not mrcall_creds.get('access_token'):
                # Check if there's a simple mrcall link (without OAuth)
                business_id = supabase.get_mrcall_link(owner_id)
                if business_id:
                    return f"""📞 **MrCall Sync (Debug)**

⚠️ **MrCall linked but no OAuth token**

Your MrCall is linked to business `{business_id}` but OAuth credentials are missing.

**To complete setup:**
1. Run `/connect mrcall` to authenticate with MrCall
2. Then run `/sync mrcall` again"""
                else:
                    return """📞 **MrCall Sync (Debug)**

⚠️ **MrCall not connected**

**To connect MrCall:**
1. Run `/mrcall <business_id>` to link your business
2. Or run `/connect mrcall` for full OAuth setup"""

            # Create minimal SyncService for MrCall test
            sync_service = SyncService(
                owner_id=owner_id,
                supabase_storage=supabase
            )

            # Run MrCall sync (debug mode) - use access_token for API auth
            result = await sync_service.sync_mrcall(
                limit=1,
                debug=True,
                firebase_token=mrcall_creds.get('access_token'),
                business_id=mrcall_creds.get('business_id')
            )

            if result.get('skipped'):
                return f"""📞 **MrCall Sync (Debug)**

⚠️ **Skipped:** {result.get('reason', 'Unknown reason')}

**To link MrCall:**
1. Get your MrCall business ID
2. Run `/mrcall <business_id>`"""

            if result.get('success'):
                return f"""📞 **MrCall Sync (Debug)**

✅ **Success!**
• Business ID: `{result.get('business_id')}`
• Conversations fetched: {result.get('conversations_fetched')}
• Total available: {result.get('total_available', 'N/A')}

Check the console/logs for conversation details."""
            else:
                return f"""📞 **MrCall Sync (Debug)**

❌ **Error:** {result.get('error', 'Unknown error')}"""

        except Exception as e:
            logger.error(f"[/sync] MrCall test failed: {e}", exc_info=True)
            return f"❌ **MrCall test failed:** {str(e)}"

    # Parse --days option (kept for future use, not currently used with background jobs)
    days_back = 30
    for i, arg in enumerate(args):
        if arg == '--days' and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                return f"❌ **Error:** `{args[i + 1]}` is not a valid number\n\n**Usage:** `/sync --days N`"
            break

    try:
        # Get user's auth provider to validate before creating job
        logger.info(f"[/sync] Starting sync for owner_id={owner_id}")
        provider = get_provider(owner_id)

        if not provider:
            logger.warning(f"[/sync] No provider found for owner_id={owner_id}")
            return """❌ **Error:** Zylch has no access to any channel!
  Run /connect to see available connections
  Run /connect {provider} to connect"""

        # Use background job system for sync
        from zylch.services.job_executor import JobExecutor
        import asyncio

        storage = SupabaseStorage.get_instance()

        # Create job (returns existing if duplicate pending/running)
        job = storage.create_background_job(
            owner_id=owner_id,
            job_type="sync",
            channel="all"  # sync always does all channels
        )

        logger.info(f"[/sync] Job request: sync/all for user {owner_id} -> {job['status']}")

        if job["status"] == "running":
            return f"""⏳ **Sync already in progress**

Job ID: `{job['id']}`
Progress: {job.get('progress_pct', 0)}%
{job.get('status_message', '')}

Please wait for the current sync to complete."""

        if job["status"] == "pending":
            # Get LLM credentials for calendar sync
            from zylch.api.token_storage import get_active_llm_provider
            llm_provider, api_key = get_active_llm_provider(owner_id)

            # Schedule execution in background
            executor = JobExecutor(storage)
            asyncio.create_task(executor.execute_job(
                job["id"],
                owner_id,
                api_key or "",
                llm_provider or ""
            ))

            logger.info(f"[/sync] Scheduled background job {job['id']}")

            return f"""🚀 **Sync started in background**

Job ID: `{job['id']}`

Your sync is running in the background. You'll be notified when complete.

**Tip:** Continue using Zylch - the sync won't block you!"""

        # Job exists but not pending/running (shouldn't happen due to unique index)
        return f"Job status: {job['status']}"

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return f"❌ **Sync failed:** {str(e)}"


async def handle_memory(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /memory command - entity-centric memory management."""
    help_text = """**🧠 Entity Memory System**

**Usage:**
• `/memory search <query>` - Search memories (hybrid FTS + semantic)
• `/memory store <content>` - Store new memory (with auto-reconsolidation)
• `/memory store --force <content>` - Force create new blob (skip merge)
• `/memory delete <blob_id>` - Delete a specific memory blob
• `/memory stats` - Show memory statistics
• `/memory list [limit]` - List recent memories
• `/memory reset` - Delete ALL memories AND reset processing timestamps

**Examples:**
• `/memory search John Smith`
• `/memory store "Mario prefers formal Italian in emails"`
• `/memory store --force "New entity that must be separate"`

**Processing data into memory:**
Use `/agent process` to extract facts from synced data:
• `/agent process` - Process all data
• `/agent process email` - Process only emails"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    if not args:
        return help_text

    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.memory import BlobStorage, HybridSearchEngine, EmbeddingEngine, MemoryConfig, LLMMergeService

    try:
        # Initialize services
        storage = SupabaseStorage.get_instance()
        supabase = storage.client
        mem_config = MemoryConfig()
        embedding_engine = EmbeddingEngine(mem_config)
        blob_storage = BlobStorage(supabase, embedding_engine)
        search_engine = HybridSearchEngine(supabase, embedding_engine)

        # Initialize LLM merge service (for reconsolidation)
        llm_merge = None
        if config.anthropic_api_key:
            llm_merge = LLMMergeService(api_key=config.anthropic_api_key)

        namespace = f"user:{owner_id}"

        # Normalize args - accept both 'search' and '--search'
        cmd = args[0].lstrip('-') if args else ''

        if cmd == 'search':
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
                if r.exact_score > 0:
                    score_info = f"hybrid: {r.hybrid_score:.2f} (exact: {r.exact_score:.1f}, FTS: {r.fts_score:.2f}, semantic: {r.semantic_score:.2f})"
                else:
                    score_info = f"hybrid: {r.hybrid_score:.2f} (FTS: {r.fts_score:.2f}, semantic: {r.semantic_score:.2f})"
                # Show full blob content with ID (no truncation)
                output += f"**{i}.** (ID: `{r.blob_id}`) {r.content}\n"
                output += f"   _Score: {score_info}_\n\n"

            return output

        elif cmd == 'store':
            # Store new memory (with optional auto-reconsolidation)
            # Check for --force flag to skip consolidation
            force_new = '--force' in args
            args_content = [a for a in args[1:] if a != '--force']

            if not args_content:
                return "❌ Missing content\n\nUsage: `/memory store <content>` or `/memory store --force <content>`"

            content = ' '.join(args_content)

            # Skip reconsolidation if --force flag is set
            if force_new:
                # Create new blob (forced)
                result = blob_storage.store_blob(
                    owner_id=owner_id,
                    namespace=namespace,
                    content=content,
                    event_description="Created via /memory store (forced)"
                )
                return f"""✅ **Memory stored (forced new blob)** (ID: {result['id']})

**Content:** {content}

Memory will be searchable via hybrid search."""

            # Get top 3 candidates above threshold (same logic as memory_agent.py)
            existing_blobs = search_engine.find_candidates_for_reconsolidation(
                owner_id=owner_id,
                content=content,
                namespace=namespace,
                limit=3
            )

            upserted = False
            upserted_result = None
            matched_blob = None

            # Fail if candidates exist but no API key for LLM merge
            if existing_blobs and not llm_merge:
                return "❌ **Cannot reconsolidate**: Anthropic API key not configured. Use `--force` to create a new blob instead."

            for existing in existing_blobs:
                merged_content = llm_merge.merge(existing.content, content)

                # If LLM says INSERT (entities don't match), try next candidate
                if 'INSERT' in merged_content.upper() and len(merged_content) < 10:
                    logger.debug(f"Skipping blob {existing.blob_id} - entities don't match")
                    continue

                # Successful merge
                upserted_result = blob_storage.update_blob(
                    blob_id=existing.blob_id,
                    owner_id=owner_id,
                    content=merged_content,
                    event_description="Reconsolidated via /memory store"
                )
                matched_blob = existing
                upserted = True
                break

            if upserted:
                return f"""✅ **Memory reconsolidated** (ID: {upserted_result['id']})

**Merged with existing memory** (score: {matched_blob.hybrid_score:.2f})

New content merged into existing entity blob."""

            else:
                # No suitable blob found, create new
                result = blob_storage.store_blob(
                    owner_id=owner_id,
                    namespace=namespace,
                    content=content,
                    event_description="Created via /memory store"
                )
                return f"""✅ **Memory stored** (ID: {result['id']})

**Content:** {content}

Memory will be searchable via hybrid search."""

        elif cmd == 'delete':
            # Delete a specific memory blob
            if len(args) < 2:
                return "❌ Missing blob ID\n\nUsage: `/memory delete <blob_id>`"

            blob_id = args[1]

            try:
                # Delete the blob (owner_id check ensures user can only delete their own)
                result = supabase.table('blobs')\
                    .delete()\
                    .eq('owner_id', owner_id)\
                    .eq('id', blob_id)\
                    .execute()

                if result.data:
                    # Also delete associated sentences
                    supabase.table('blob_sentences')\
                        .delete()\
                        .eq('blob_id', blob_id)\
                        .execute()

                    return f"✅ **Memory deleted** (ID: `{blob_id[:8]}...`)"
                else:
                    return f"❌ Blob not found: `{blob_id}`\n\nMake sure you're using the full blob ID from `/memory search`."

            except Exception as e:
                logger.error(f"Failed to delete blob {blob_id}: {e}")
                return f"❌ Failed to delete: {str(e)}"

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

Run `/agent process` to rebuild memory from your synced data."""

        else:
            # Unknown subcommand - show error + help
            return f"❌ Unknown subcommand: `{args[0]}`\n\n{help_text}"

    except Exception as e:
        logger.error(f"Error in /memory command: {e}", exc_info=True)
        return f"**❌ Error:** {str(e)}\n\n{help_text}"


async def handle_trigger(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /trigger command - triggered instructions."""
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient

    TRIGGER_TYPES = ['session_start', 'email_received', 'sms_received', 'call_received']

    help_text = """**⚡ Triggered Instructions**

**Usage:**
• `/trigger` or `/trigger list` - List all triggers
• `/trigger types` - Show trigger types
• `/trigger add <type> <instruction>` - Add trigger
• `/trigger remove <id>` - Remove trigger
• `/trigger toggle <id>` - Enable/disable trigger

**Trigger types:**
• `session_start` - When starting conversation
• `email_received` - When email arrives
• `sms_received` - When SMS arrives
• `call_received` - When call comes in

**Examples:**
```
/trigger add session_start "Say good morning and list my meetings for today"
/trigger add email_received "Summarize important emails from unknown senders"
/trigger remove abc123
```"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    # Separate positional args from options
    positional = [a for a in args if not a.startswith('--')]
    subcommand = positional[0].lower() if positional else None

    try:
        client = SupabaseClient()

        # Subcommand: types
        if subcommand == 'types':
            return """**⚡ Available Trigger Types**

• `session_start` - Fires when you start a new conversation
• `email_received` - Fires when new email arrives (via /sync)
• `sms_received` - Fires when SMS arrives (via MrCall)
• `call_received` - Fires when phone call comes in (via MrCall)

**Usage:** `/trigger add <type> <instruction>`"""

        # Subcommand: list (or no subcommand)
        if subcommand == 'list' or subcommand is None:
            triggers = client.list_triggers(owner_id)

            if not triggers:
                return """**⚡ No Triggers**

You haven't created any triggers yet.

**Get started:**
`/trigger add session_start "Summarize my unread emails"`

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

            output += "**Commands:** `/trigger remove <id>` | `/trigger toggle <id>`"
            return output

        # Subcommand: add
        if subcommand == 'add':
            if len(positional) < 3:
                return "❌ **Error:** Missing arguments\n\n**Usage:** `/trigger add <type> <instruction>`\n\nExample: `/trigger add session_start \"Say good morning\"`"

            trigger_type = positional[1]
            instruction = ' '.join(positional[2:])

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

        # Subcommand: remove
        if subcommand == 'remove':
            trigger_id = positional[1] if len(positional) > 1 else None

            if not trigger_id:
                return "❌ **Error:** Missing trigger ID\n\n**Usage:** `/trigger remove <id>`"

            success = client.remove_trigger(owner_id, trigger_id)

            if success:
                return f"✅ **Trigger Removed** (ID: `{trigger_id[:8]}`)"
            else:
                return f"❌ **Error:** Could not find trigger with ID `{trigger_id[:8]}`"

        # Subcommand: toggle
        if subcommand == 'toggle':
            trigger_id = positional[1] if len(positional) > 1 else None

            if not trigger_id:
                return "❌ **Error:** Missing trigger ID\n\n**Usage:** `/trigger toggle <id>`"

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

        # Unknown subcommand
        return f"❌ Unknown subcommand: `{subcommand}`\n\n{help_text}"

    except Exception as e:
        logger.error(f"Error in /trigger command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


async def handle_mrcall(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /mrcall command - MrCall integration."""
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient
    from zylch.api.token_storage import get_mrcall_credentials
    import httpx
    from zylch.config import settings

    help_text = """**📞 MrCall Integration**

**Commands:**
• `/mrcall list` - List your MrCall assistants
• `/mrcall link N` - Link to assistant #N from the list
• `/mrcall variables [get] [--name NAME]` - List/filter variables
• `/mrcall variables set <NAME> <VALUE>` - Set variable value
• `/mrcall train [feature]` - Generate/refresh configuration context
• `/mrcall show [feature]` - Show current configuration context
• `/mrcall unlink` - Unlink current assistant
• `/mrcall` - Show current link status

**Features:** welcome_message (how the assistant answers the phone)

**Setup:**
1. Run `/connect mrcall` to authenticate with MrCall
2. Run `/mrcall list` to see your assistants
3. Run `/mrcall link N` to connect to an assistant"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    # Separate positional args from options
    positional = [a for a in args if not a.startswith('--')]
    subcommand = positional[0].lower() if positional else None

    try:
        client = SupabaseClient()

        # Subcommand: unlink
        if subcommand == 'unlink':
            success = client.remove_mrcall_link(owner_id)
            if success:
                return "✅ **MrCall Unlinked**\n\nYour Zylch is no longer connected to a MrCall business."
            else:
                return "❌ **Error:** No MrCall link found to remove."

        # Subcommand: list - List all businesses
        if subcommand == 'list':
            # Get OAuth credentials
            creds = get_mrcall_credentials(owner_id)
            logger.info(f"handle_mrcall list: creds keys = {list(creds.keys()) if creds else None}")
            if not creds or not creds.get('access_token'):
                logger.info(f"handle_mrcall list: access_token missing, creds = {creds}")
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first to authenticate."

            access_token = creds.get('access_token')
            logger.info(f"handle_mrcall list: access_token exists = {bool(access_token)}, len = {len(access_token) if access_token else 0}")
            current_business_id = creds.get('business_id')

            # Fetch businesses from StarChat API
            try:
                url = f"{settings.mrcall_base_url.rstrip('/')}/mrcall/v1/delegated_{settings.mrcall_realm}/crm/business/search"
                logger.info(f"handle_mrcall list: Fetching from {url}")
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    response = await http_client.post(
                        url,
                        headers={"auth": access_token, "Content-Type": "application/json"},
                        json={"from": 0, "size": 50}
                    )
                    response.raise_for_status()
                    businesses = response.json()
            except Exception as e:
                logger.error(f"Failed to fetch MrCall businesses: {e}")
                return f"❌ **Error fetching businesses:** {str(e)}\n\nTry `/connect mrcall` to refresh your connection."

            if not businesses:
                return "**📞 Your MrCall Assistants**\n\nNo assistants found.\n\nCreate one at https://dashboard.mrcall.ai"

            # Build list output
            output = "**📞 Your MrCall Assistants**\n\n"
            for i, biz in enumerate(businesses, 1):
                biz_id = biz.get('businessId') or biz.get('id')
                nickname = biz.get('nickname') or 'Unnamed'
                company = biz.get('companyName') or ''
                service_number = biz.get('serviceNumber') or ''

                # Mark if this is the linked business
                linked_marker = " ← LINKED" if biz_id == current_business_id else ""

                # Format: "1. **Nickname** (Company) ← LINKED"
                if company:
                    output += f"{i}. **{nickname}** ({company}){linked_marker}\n"
                else:
                    output += f"{i}. **{nickname}**{linked_marker}\n"

                if service_number:
                    # Clean up service number display (remove duplicates like +39...#+39...)
                    display_number = service_number.split('#')[0] if '#' in service_number else service_number
                    output += f"   📱 {display_number}\n"

                output += "\n"

            output += "---\nUse `/mrcall link N` to connect an assistant."
            return output

        # Subcommand: variables - List all variables
        if subcommand == 'variables':
            # Get credentials
            creds = get_mrcall_credentials(owner_id)
            if not creds or not creds.get('access_token'):
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first to authenticate."
            
            # Get linked business ID
            business_id = creds.get('business_id')
            if not business_id:
                # Try simple link
                business_id = client.get_mrcall_link(owner_id)
                
            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` then `/mrcall link N` to select one."

            # Check for sub-subcommand (get/set)
            # args[0] is 'variables'. Check args[1]
            var_subcommand = args[1].lower() if len(args) > 1 else 'get'
            
            # Sub-subcommand: set VARIABLE value
            if var_subcommand == 'set':
                if len(args) < 4:
                    return "❌ **Usage:** `/mrcall variables set <VARIABLE_NAME> <value>`"
                
                var_name = args[2]
                # Join all remaining args to allow spaces without strict quoting if user prefers
                # But since shlex split the input, quotes are already handled.
                # If user typed: set VAR "my value", args=['variables', 'set', 'VAR', 'my value'] -> value='my value'
                # If user typed: set VAR my value, args=['variables', 'set', 'VAR', 'my', 'value'] -> value='my value'
                var_value = " ".join(args[3:])
                
                # Use factory to get client
                from zylch.tools.starchat import create_starchat_client
                sc_client = await create_starchat_client(owner_id)
                
                try:
                    await sc_client.update_business_variable(business_id, var_name, var_value)
                    await sc_client.close()
                    return f"✅ **Variable Updated**\n\n**{var_name}** set to: `{var_value}`"
                except Exception as e:
                    await sc_client.close()
                    logger.error(f"Failed to update variable: {e}")
                    return f"❌ **Error updating variable:** {str(e)}"

            # Sub-subcommand: get (default)
            # Usage: /mrcall variables get [--name FILTER]
            filter_name = None
            if '--name' in args:
                try:
                    name_idx = args.index('--name')
                    if name_idx + 1 < len(args):
                        filter_name = args[name_idx + 1]
                except ValueError:
                    pass

            # Use factory to get client
            from zylch.tools.starchat import create_starchat_client
            sc_client = await create_starchat_client(owner_id)
            
            try:
                variables = await sc_client.get_all_variables(business_id)
                await sc_client.close()
                
                if not variables:
                    return f"**📋 MrCall Variables**\n\nNo variables found for business `{business_id}`."
                
                # Filter if requested
                if filter_name:
                    variables = [v for v in variables if filter_name.upper() in v['name'].upper()]
                    if not variables:
                        return f"**📋 MrCall Variables**\n\nNo variables matching `*{filter_name}*` found."

                output = f"**📋 MrCall Variables** ({len(variables)} found)\n\n"
                for var in variables:
                    name = var['name']
                    desc = var['description']
                    val = var['value']
                    
                    output += f"**{name}**: {desc}. Value: `{val}`\n\n"
                    
                return output

            except Exception as e:
                await sc_client.close()
                logger.error(f"Failed to fetch variables: {e}")
                return f"❌ **Error:** {str(e)}"

        # Subcommand: link N - Link to business by number
        if subcommand == 'link':
            if len(positional) < 2:
                return "❌ **Usage:** `/mrcall link N`\n\nWhere N is the assistant number from `/mrcall list`"

            try:
                index = int(positional[1]) - 1  # Convert to 0-based index
                if index < 0:
                    raise ValueError("Index must be positive")
            except ValueError:
                return f"❌ **Invalid number:** `{positional[1]}`\n\nUse a number from `/mrcall list`"

            # Get OAuth credentials
            creds = get_mrcall_credentials(owner_id)
            if not creds or not creds.get('access_token'):
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first to authenticate."

            access_token = creds.get('access_token')

            # Fetch businesses to get the one at index
            try:
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    response = await http_client.post(
                        f"{settings.mrcall_base_url.rstrip('/')}/mrcall/v1/delegated_{settings.mrcall_realm}/crm/business/search",
                        headers={"auth": access_token, "Content-Type": "application/json"},
                        json={"from": 0, "size": 50}
                    )
                    response.raise_for_status()
                    businesses = response.json()
            except Exception as e:
                logger.error(f"Failed to fetch MrCall businesses: {e}")
                return f"❌ **Error:** {str(e)}"

            if index >= len(businesses):
                return f"❌ **Invalid number:** {index + 1}\n\nYou have {len(businesses)} assistant(s). Use `/mrcall list` to see them."

            business = businesses[index]
            business_id = business.get('businessId') or business.get('id')
            nickname = business.get('nickname') or 'Unnamed'

            # Save the link
            result = client.set_mrcall_link(owner_id, business_id)

            if result:
                return f"""✅ **MrCall Linked**

**Assistant:** {nickname}
**Business ID:** `{business_id}`

Your Zylch is now connected to this MrCall assistant!

**Next steps:**
• `/trigger add call_received "Summarize the call"`
• `/sync mrcall` - Test fetching conversations"""
            else:
                return "❌ **Error:** Failed to link MrCall business. Please try again."

        # Subcommand: train - Generate/refresh configuration context
        if subcommand == 'train':
            import asyncio
            from concurrent.futures import ThreadPoolExecutor
            from zylch.api.token_storage import get_active_llm_provider

            # Get linked business
            creds = get_mrcall_credentials(owner_id)
            if not creds or not creds.get('access_token'):
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first."

            business_id = creds.get('business_id')
            if not business_id:
                business_id = client.get_mrcall_link(owner_id)
            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` then `/mrcall link N` first."

            # Get LLM credentials
            llm_provider, api_key = get_active_llm_provider(owner_id)
            if not api_key:
                return "❌ **No LLM configured**\n\nRun `/connect anthropic` to configure an LLM provider."

            # Parse feature argument
            feature_name = positional[1] if len(positional) > 1 else "welcome_message"

            # Create trainer and generate sub-prompt (uses run_in_executor for 3-5s LLM call)
            def _train_feature():
                import asyncio
                from zylch.tools.starchat import create_starchat_client
                from zylch.agents.mrcall_configurator_trainer import MrCallConfiguratorTrainer

                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Create StarChat client
                    starchat = loop.run_until_complete(create_starchat_client(owner_id))

                    trainer = MrCallConfiguratorTrainer(
                        storage=client,
                        starchat_client=starchat,
                        owner_id=owner_id,
                        api_key=api_key,
                        provider=llm_provider,
                    )

                    # Generate sub-prompt
                    sub_prompt, metadata = loop.run_until_complete(
                        trainer.train_feature(feature_name, business_id)
                    )

                    # Close starchat client
                    loop.run_until_complete(starchat.close())

                    return sub_prompt, metadata
                finally:
                    loop.close()

            executor = ThreadPoolExecutor(max_workers=1)
            loop = asyncio.get_event_loop()

            try:
                sub_prompt, metadata = await loop.run_in_executor(executor, _train_feature)
                return f"""✅ **Configuration Context Generated**

**Feature:** {feature_name}
**Business ID:** `{business_id}`
**Length:** {len(sub_prompt)} characters

The context is now ready. When you ask about configuring the assistant,
Zylch will use this analysis to understand the current behavior.

Run `/mrcall show {feature_name}` to see the generated context."""
            except Exception as e:
                logger.error(f"Failed to train feature: {e}", exc_info=True)
                error_str = str(e)
                # Check for auth errors (405/401/403) and suggest reconnection
                if any(code in error_str for code in ["405", "401", "403", "Unauthorized", "Forbidden"]):
                    return "❌ **MrCall connection expired**\n\nRun `/connect mrcall` to reconnect."
                return f"❌ **Error generating context:** {error_str}"

        # Subcommand: show - Display current configuration context
        if subcommand == 'show':
            # Get linked business
            creds = get_mrcall_credentials(owner_id)
            if not creds or not creds.get('access_token'):
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first."

            business_id = creds.get('business_id')
            if not business_id:
                business_id = client.get_mrcall_link(owner_id)
            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` then `/mrcall link N` first."

            # Parse feature argument
            feature_name = positional[1] if len(positional) > 1 else "welcome_message"
            agent_type = f"mrcall_{business_id}_{feature_name}"

            # Get stored sub-prompt
            sub_prompt = client.get_agent_prompt(owner_id, agent_type)

            if not sub_prompt:
                return f"""**📋 MrCall Configuration Context**

**Feature:** {feature_name}
**Status:** Not generated yet

Run `/mrcall train {feature_name}` to generate the configuration context."""

            return f"""**📋 MrCall Configuration Context**

**Feature:** {feature_name}
**Business ID:** `{business_id}`
**Length:** {len(sub_prompt)} characters

---

{sub_prompt}"""

        # No subcommand: show status
        if subcommand is None:
            # Get OAuth credentials to check connection
            creds = get_mrcall_credentials(owner_id)

            if creds and creds.get('access_token'):
                business_id = creds.get('business_id')
                email = creds.get('metadata', {}).get('email') if isinstance(creds.get('metadata'), dict) else None

                if business_id:
                    return f"""**📞 MrCall Status**

**Status:** Connected and linked
**Business ID:** `{business_id}`
**Email:** {email or 'N/A'}

**Commands:**
• `/mrcall list` - See all your assistants
• `/mrcall unlink` - Disconnect this assistant
• `/sync mrcall` - Test API connection
• `/trigger add call_received "..."` - Add call automation"""
                else:
                    return f"""**📞 MrCall Status**

**Status:** Connected (not linked to an assistant)
**Email:** {email or 'N/A'}

Run `/mrcall list` to see your assistants, then `/mrcall link N` to connect one."""
            else:
                return """**📞 MrCall Status**

**Status:** Not connected

**To get started:**
1. Run `/connect mrcall` to authenticate
2. Run `/mrcall list` to see your assistants
3. Run `/mrcall link N` to connect an assistant"""

        # Unknown subcommand
        return f"❌ **Unknown subcommand:** `{subcommand}`\n\n{help_text}"

    except Exception as e:
        logger.error(f"Error in /mrcall command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


async def handle_share(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /share command - data sharing."""
    import re
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient

    help_text = """**🔗 Data Sharing**

**Usage:** `/share <email>`

Registers a recipient to receive shared data from you.

**Example:** `/share colleague@example.com`

**What gets shared:**
• Contact information
• Email intelligence
• Relationship context

**How it works:**
1. You send a share request with `/share <email>`
2. Recipient sees the request in their `/sharing`
3. They authorize with their Zylch
4. Your relational data flows to them

**Commands:**
• `/share <email>` - Send share request
• `/revoke <email>` - Cancel sharing"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    if not args:
        return help_text

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
• Task data

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
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


async def handle_revoke(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /revoke command - revoke sharing access."""
    import re
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient

    help_text = """**❌ Revoke Sharing**

**Usage:** `/revoke <email>`

Revokes data sharing access for a recipient.

**Example:** `/revoke colleague@example.com`

This stops sharing your data with the specified user.
They will no longer receive updates from you."""

    # --help option (check first)
    if '--help' in args:
        return help_text

    if not args:
        return help_text

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
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


async def handle_connect(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /connect command - list available connections and initiate connection flow.

    Usage:
    - /connect - List all available providers
    - /connect <provider> - Initiate connection for specific provider
    - /connect status - Show connection status
    - /connect reset <provider> - Disconnect a provider
    """
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.integrations.registry import get_available_providers, get_category_emoji, get_connection_status

    help_text = """**📡 Connections**

**Usage:**
• `/connect` - List available providers
• `/connect <provider>` - Connect to a provider
• `/connect status` - Show all connection statuses
• `/connect reset <provider>` - Disconnect a provider

**Providers:**
• `google` - Gmail & Google Calendar
• `microsoft` - Outlook & Calendar
• `mrcall` - MrCall/StarChat phone
• `anthropic` - Claude AI (BYOK) - includes web search & prompt caching
• `openai` - OpenAI GPT-4 (BYOK)
• `mistral` - Mistral AI (BYOK) - EU-based for GDPR
• `pipedrive` - Pipedrive CRM
• `vonage` - Vonage SMS

**Examples:**
• `/connect mrcall` - Connect MrCall
• `/connect status` - Check what's connected
• `/connect reset google` - Disconnect Google"""

    # DEBUG: Log what args we received
    logger.debug(f"[CONNECT] Received args: {args}, type: {type(args)}")
    logger.debug(f"[CONNECT] '--help' in args: {'--help' in args}")

    # --help option (check first, before any processing)
    if '--help' in args:
        return help_text

    # Separate positional args from options
    positional = [a for a in args if not a.startswith('--')]
    subcommand = positional[0].lower() if positional else None

    try:
        supabase = SupabaseStorage()

        # Subcommand: status
        if subcommand == 'status':
            status_data = get_connection_status(supabase, owner_id, include_unavailable=False)
            connections = status_data.get('connections', [])

            if not connections:
                return "**📡 Connection Status**\n\n❌ No providers available"

            output = f"**📡 Connection Status** ({status_data['connected_count']}/{status_data['available_count']} connected)\n\n"

            for conn in connections:
                emoji = get_category_emoji(conn.get('category', ''))
                status = conn.get('status', 'disconnected')
                name = conn['display_name']

                if status == 'connected':
                    email = conn.get('connected_email', '')
                    output += f"✅ {emoji} **{name}**"
                    if email:
                        output += f" ({email})"
                    output += "\n"
                else:
                    output += f"⬚ {emoji} {name} - `/connect {conn['provider_key']}`\n"

            return output

        # Subcommand: reset
        if subcommand == 'reset':
            provider_key = positional[1].lower() if len(positional) > 1 else None

            if not provider_key:
                return "❌ Missing provider\n\n**Usage:** `/connect reset <provider>`\n\nExample: `/connect reset google`"

            from zylch.api.token_storage import (
                delete_user_credentials,
                delete_mrcall_credentials,
                delete_anthropic_key,
                delete_pipedrive_key,
                delete_vonage_keys,
                delete_llm_provider_key,
            )

            # Note: delete_user_credentials deletes both google and microsoft
            # For microsoft-only deletion, use supabase.delete_oauth_token directly
            delete_funcs = {
                'google': delete_user_credentials,
                'microsoft': lambda oid: supabase.delete_oauth_token(oid, 'microsoft'),
                'mrcall': delete_mrcall_credentials,
                'anthropic': delete_anthropic_key,
                'openai': lambda oid: delete_llm_provider_key(oid, 'openai'),
                'mistral': lambda oid: delete_llm_provider_key(oid, 'mistral'),
                'pipedrive': delete_pipedrive_key,
                'vonage': delete_vonage_keys,
            }

            if provider_key not in delete_funcs:
                supported = ', '.join(sorted(delete_funcs.keys()))
                return f"❌ Cannot reset `{provider_key}`\n\nSupported: {supported}"

            try:
                success = delete_funcs[provider_key](owner_id)
                if success:
                    return f"✅ **{provider_key.title()}** disconnected\n\nRun `/connect {provider_key}` to reconnect."
                else:
                    return f"❌ Failed to disconnect {provider_key} (may not be connected)"
            except Exception as e:
                return f"❌ Error disconnecting {provider_key}: {str(e)}"

        # No subcommand: list all available providers
        if subcommand is None:
            providers = get_available_providers(supabase, include_unavailable=False)

            if not providers:
                return "❌ **Error:** No providers available"

            output = "**📡 Available Connections**\n\n"
            output += "Select a provider to connect:\n\n"

            for i, provider in enumerate(providers, 1):
                emoji = get_category_emoji(provider['category'])
                output += f"{i}. {emoji} **{provider['display_name']}** - `/connect {provider['provider_key']}`\n"

            return output

        # Connect to specific provider (subcommand is the provider key)
        provider_key = subcommand

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

Run `/connect` to verify connection."""

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
3. Run `/connect` to verify connection

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

    help_text = """**📧 Email Command**

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

    # --help option (check first)
    if '--help' in args:
        return help_text

    if not args:
        return help_text

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

            if draft_id:
                # Find the draft by ID (support partial ID)
                result = supabase.table('drafts')\
                    .select('*')\
                    .eq('owner_id', owner_id)\
                    .eq('status', 'draft')\
                    .like('id', f'{draft_id}%')\
                    .execute()

                if not result.data:
                    return f"❌ Draft not found: `{draft_id}`\n\nUse `/email list` to see your drafts."

                draft = result.data[0]
            else:
                # No draft_id provided - use the most recent draft
                result = supabase.table('drafts')\
                    .select('*')\
                    .eq('owner_id', owner_id)\
                    .eq('status', 'draft')\
                    .order('updated_at', desc=True)\
                    .limit(1)\
                    .execute()

                if not result.data:
                    return "❌ No drafts found.\n\nCreate a draft first with `/email create` or use the `compose_email` tool."

                draft = result.data[0]
                draft_id = draft['id'][:8]  # For display in error messages

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

        # Unknown subcommand - show error + help
        return f"❌ Unknown subcommand: `{subcommand}`\n\n{help_text}"

    except Exception as e:
        logger.error(f"Error in /email command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


# Command help texts - source of truth for all clients (CLI, web, mobile)
COMMAND_HELP = {
    '/help': {
        'summary': 'Show available commands',
        'usage': '/help',
        'description': 'Lists all available slash commands.',
    },
    '/sync': {
        'summary': 'Sync emails and calendar',
        'usage': '/sync [status|reset] [--days N]',
        'description': '''Fetches new emails from Gmail and calendar events from Google Calendar.

**Subcommands:**
- `status` - Show sync status (last sync time, email count, event count)
- `reset` - Clear sync state and force full re-sync (warns about memory)

**Options:**
- `--days N` - Number of days to sync (default: 30 for first sync, incremental after)

**Examples:**
- `/sync` - Sync with defaults (incremental after first sync)
- `/sync --days 1` - Sync only last 1 day (useful for testing)
- `/sync --days 300` - Sync last 300 days
- `/sync status` - Check sync status without syncing
- `/sync reset` - Reset sync state, then run `/sync` to re-sync

**Fresh start:** To rebuild everything from scratch:
1. `/memory reset` - Clear memory blobs
2. `/sync reset` - Clear emails/calendar
3. `/sync --days 30` - Re-sync and rebuild memory''',
    },
    '/memory': {
        'summary': 'Entity memory system',
        'usage': '/memory [search|store|stats|list|reset] <args>',
        'description': '''Search and manage entity memories.

**Searching:**
- `/memory search <query>` - Search memories (hybrid FTS + semantic)
- `/memory store <content>` - Store new memory (with auto-reconsolidation)

**Management:**
- `/memory stats` - Show memory statistics
- `/memory list [limit]` - List recent memories
- `/memory reset` - Delete ALL memories AND reset processing timestamps

**Processing:**
Use `/agent process` to extract facts from synced data into memory.''',
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
        'usage': '/trigger [types|list|add|remove|enable|disable] [args]',
        'description': '''Configure automated triggers for events like new emails.

**Subcommands:**
- `types` - Show available trigger types
- `list` - List configured triggers (default)
- `add <type> <instruction>` - Add a new trigger
- `remove <id>` - Remove a trigger by ID
- `enable <id>` - Enable a trigger
- `disable <id>` - Disable a trigger

**Examples:**
- `/trigger` - List all triggers
- `/trigger types` - Show trigger types
- `/trigger add email_received "Summarize new emails"` - Add trigger
- `/trigger remove 123` - Remove trigger''',
    },
    '/mrcall': {
        'summary': 'MrCall integration',
        'usage': '/mrcall [list|link N|unlink|variables|train|show]',
        'description': '''Manage MrCall telephony integration.

**Subcommands:**
- (none) - Show current connection status
- `list` - List your MrCall assistants
- `link N` - Link to assistant #N from the list
- `unlink` - Disconnect current assistant
- `variables [get] [--name NAME]` - List/filter variables
- `variables set <NAME> <VALUE>` - Set variable value
- `train [feature]` - Generate configuration context for a feature
- `show [feature]` - Display current configuration context

**Features:** welcome_message (how the assistant answers the phone)

**Examples:**
- `/mrcall` - Show connection status
- `/mrcall list` - See your assistants
- `/mrcall link 1` - Connect to first assistant
- `/mrcall train` - Generate context for welcome_message
- `/mrcall show welcome_message` - Show current context
- `/mrcall variables` - List all variables''',
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
    # NOTE: /connect is partially handled client-side by the CLI for OAuth (requires local browser).
    # The CLI intercepts /connect and /connect <provider> for OAuth flows.
    # Only /connect --help, /connect reset, and /connect status reach the backend.
    # See zylch-cli/zylch_cli/cli.py lines 419-434 for client-side handling.
    '/connect': {
        'summary': 'Manage external integrations',
        'usage': '/connect [status|reset <provider>|<provider>] [--help]',
        'description': '''View and manage external service connections.

**Subcommands:**
- (none) - List available providers
- `status` - Show all connection statuses
- `reset <provider>` - Disconnect a provider
- `<provider>` - Connect to a provider

**Options:**
- `--help` - Show this help

**Examples:**
- `/connect` - List providers
- `/connect mrcall` - Connect MrCall
- `/connect status` - Check connections
- `/connect reset google` - Disconnect Google''',
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
        'usage': '/jobs [cancel <id>]',
        'description': '''Lists scheduled reminders and jobs.

**Subcommands:**
- (none) - List all scheduled jobs
- `cancel <id>` - Cancel a specific job by ID

**Examples:**
- `/jobs` - Show all scheduled jobs
- `/jobs cancel abc123` - Cancel job abc123''',
    },
    '/agent': {
        'summary': 'Train agents and process data into memory or tasks',
        'usage': '/agent <domain> <action> [channel]',
        'description': '''Train personalized agents and process synced data.

**Domains:**
- `memory` - Extract facts and entities into memory blobs
- `task` - Detect actionable items and create tasks

**Actions:**
- `train` - Create personalized agent from your patterns
- `process` - Run agent on unprocessed data
- `show` - Display current agent prompt
- `reset` - Delete custom agent

**Channels:**
- `email` - Email data only
- `calendar` - Calendar data only
- `all` - Both email and calendar (train/process only)

**Memory commands:**
- `/agent memory train [email|calendar|all]`
- `/agent memory process [email|calendar|all]`
- `/agent memory show [email|calendar]`
- `/agent memory reset [email|calendar]`

**Task commands:**
- `/agent task train [email|calendar|all]`
- `/agent task process [email|calendar|all]`
- `/agent task show [email|calendar]`
- `/agent task reset [email|calendar]`

**Workflow:**
1. `/sync` - Fetch emails/calendar
2. `/agent memory train email` - Create memory extraction agent
3. `/agent memory process email` - Extract entities into memory
4. `/agent task train email` - Create task detection agent
5. `/agent task process email` - Detect actionable items''',
    },
}

async def handle_stats(args: List[str], owner_id: str) -> str:
    """Handle /stats command - email statistics."""
    from zylch.storage.supabase_client import SupabaseStorage

    help_text = """**📊 Email Statistics**

**Usage:** `/stats`

Shows statistics about your synced emails:
- Total emails and threads
- Unread count
- Date range
- Open conversations needing response"""

    # --help option (check first)
    if '--help' in args:
        return help_text

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

        # Count open tasks
        task_result = supabase.table('task_items')\
            .select('id', count='exact')\
            .eq('owner_id', owner_id)\
            .eq('action_required', True)\
            .execute()
        open_count = task_result.count if hasattr(task_result, 'count') else 0

        return f"""**📊 Email Statistics**

**Total Emails:** {total_emails:,}
**Threads:** {unique_threads:,}
**Date Range:** {oldest_date} → {newest_date}

**Open Tasks:** {open_count} need action

Run `/sync` to update or `/tasks` for details."""

    except Exception as e:
        logger.error(f"Error in /stats: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


async def handle_calendar(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /calendar command - list calendar events."""
    from zylch.storage.supabase_client import SupabaseStorage
    from datetime import datetime, timedelta, timezone

    help_text = """**📅 Calendar**

**Usage:** `/calendar [days] [--limit N]`

Shows your upcoming calendar events.

**Arguments:**
- `days` - Days ahead to show (default: 7)
- `--limit N` - Max events to show (default: 20)

**Examples:**
- `/calendar` - Events for next 7 days
- `/calendar 1` - Today only
- `/calendar 30 --limit 50` - Next month"""

    # --help option (check first)
    if '--help' in args:
        return help_text

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
            start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            event_date = start_dt.strftime('%A, %B %d')
            event_time = start_dt.strftime('%H:%M')

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
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


async def handle_tasks(args: List[str], owner_id: str) -> str:
    """Handle /tasks command - list items needing action using LLM analysis."""
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.agents.task_agent import TaskWorker
    from zylch.api.token_storage import get_email

    help_text = """**✅ Tasks**

**Usage:** `/tasks [subcommand]`

Shows items needing your action, analyzed by AI.

**Subcommands:**
- (none) - Show current task items
- `refresh` - Re-analyze events with fresh LLM call
- `status` - Show task analysis statistics
- `reset` - Clear task cache

**Setup:**
1. `/sync` - Fetch emails and calendar
2. `/agent train tasks` - Train task detection agent
3. `/tasks` - View actionable items

**Related:**
- `/agent train tasks` - Train/retrain task detection
- `/agent show tasks` - View trained agent"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    try:
        storage = SupabaseStorage.get_instance()

        # Handle subcommands
        if args and args[0] == 'status':
            # Get task statistics
            stats = storage.get_task_items_stats(owner_id)
            if not stats:
                return """**📊 Task Status**

No task items found. Run `/tasks refresh` to analyze your events."""

            return f"""**📊 Task Status**

| Metric | Value |
|--------|-------|
| Total analyzed | {stats.get('total', 0)} |
| Action required | {stats.get('action_required', 0)} |
| Completed | {stats.get('completed', 0)} |
| Last analyzed | {stats.get('last_analyzed', 'Never')} |

Run `/tasks` to see items needing action."""

        if args and args[0] == 'reset':
            # Clear task cache AND reset processing timestamps
            deleted_count = storage.clear_task_items(owner_id)
            ts_counts = storage.reset_task_processing_timestamps(owner_id, 'all')

            return f"""**✅ Task Data Reset**

- {deleted_count} task items deleted
- {ts_counts.get('emails', 0)} emails reset
- {ts_counts.get('calendar_events', 0)} calendar events reset

Run `/agent task process` to re-analyze."""

        # Check if task agent is trained
        task_prompt = storage.get_agent_prompt(owner_id, 'tasks')
        if not task_prompt:
            return """⚠️ **Task agent not trained yet**

Train your personalized task detection agent first:

```
/agent train tasks
```

This analyzes your email patterns to understand:
- How quickly you respond to different contacts
- What types of emails you ignore
- VIP contacts who need quick responses

Then run `/tasks` again."""

        # Get LLM provider and API key
        from zylch.api.token_storage import get_active_llm_provider
        llm_provider, api_key = get_active_llm_provider(owner_id)
        if not api_key or not llm_provider:
            return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

        # Get user email
        user_email = get_email(owner_id) or ''

        # Check for refresh flag
        refresh = 'refresh' in args

        # Check last sync time BEFORE starting analysis
        if refresh:
            try:
                result = storage.client.table('sync_state').select('last_sync').eq('owner_id', owner_id).execute()
                if result.data:
                    last_sync_str = result.data[0].get('last_sync')
                    if last_sync_str:
                        last_sync_dt = datetime.fromisoformat(last_sync_str.replace('Z', '+00:00'))
                        hours_ago = (datetime.now(timezone.utc) - last_sync_dt).total_seconds() / 3600
                        if hours_ago > 6:
                            return f"""⚠️ **Stale Data Warning**

Last sync was **{hours_ago:.1f} hours ago**.

Run `/sync` first to get fresh emails, then `/tasks refresh`."""
            except Exception as e:
                logger.warning(f"Could not check last sync: {e}")

        # Create worker and get tasks
        worker = TaskWorker(storage, owner_id, api_key, llm_provider, user_email)
        tasks, _ = await worker.get_tasks(refresh=refresh)

        if not tasks:
            if refresh:
                return """**✅ Tasks**

🎉 No action needed! You're all caught up.

Analyzed recent emails and calendar - nothing requires your attention."""
            else:
                return """**✅ Tasks**

🎉 No action needed! You're all caught up.

Run `/tasks refresh` to re-analyze with fresh AI check."""

        result = format_task_items(tasks)
        if refresh:
            result += "\n\n_Freshly analyzed with AI_"
        return result

    except ValueError as e:
        # Task prompt not found
        return f"⚠️ {str(e)}"
    except Exception as e:
        logger.error(f"Error in /tasks: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


def _load_blob_context(storage, owner_id: str, blob_ids: list) -> str:
    """Load blob content from sources for task detail display.

    Args:
        storage: SupabaseStorage instance
        owner_id: Firebase UID
        blob_ids: List of blob UUIDs from task sources

    Returns:
        Concatenated blob content, or empty string if none found
    """
    if not blob_ids:
        return ""

    try:
        contents = []
        for blob_id in blob_ids[:3]:  # Limit to 3 blobs
            result = storage.client.table('blobs')\
                .select('content')\
                .eq('owner_id', owner_id)\
                .eq('id', blob_id)\
                .limit(1)\
                .execute()
            if result.data:
                contents.append(result.data[0].get('content', '')[:500])  # Truncate

        return "\n\n".join(contents)
    except Exception as e:
        logger.warning(f"Failed to load blob context: {e}")
        return ""


async def handle_task_close(task_num: int, owner_id: str) -> str:
    """Close/complete a task by its display number.

    Args:
        task_num: 1-indexed task number from /tasks output
        owner_id: Firebase UID

    Returns:
        Confirmation message or error
    """
    from zylch.storage.supabase_client import SupabaseStorage
    storage = SupabaseStorage.get_instance()

    # Get all tasks (same order as displayed in /tasks)
    tasks = storage.get_task_items(owner_id, action_required=True)

    if not tasks:
        return "No tasks found."

    # Group by urgency: high -> medium -> low (same as display)
    high_medium = [t for t in tasks if t.get('urgency') in ('high', 'medium')]
    low = [t for t in tasks if t.get('urgency') == 'low']
    tasks = high_medium + low

    if task_num < 1 or task_num > len(tasks):
        return f"Task #{task_num} not found. Valid range: #1 - #{len(tasks)}"

    task = tasks[task_num - 1]  # 0-indexed
    task_id = task.get('id')
    contact = task.get('contact_name') or task.get('contact_email') or 'Unknown'
    action = task.get('suggested_action', '')

    # Mark as complete
    success = storage.mark_task_complete(owner_id, task_id)

    if success:
        return f"**✅ Task #{task_num} closed**\n\n**{contact}** - marked as complete."
    else:
        return f"**❌ Failed to close task #{task_num}**"


async def get_task_by_number(task_num: int, owner_id: str) -> dict | None:
    """Get a task by its 1-indexed display number from /tasks output.

    The task list is ordered by urgency (high, medium first, then low).
    This function is shared by handle_task_detail and compose_email tool.

    Args:
        task_num: 1-indexed task number from /tasks output
        owner_id: Firebase UID

    Returns:
        Task dict if found, None otherwise
    """
    from zylch.storage.supabase_client import SupabaseStorage

    storage = SupabaseStorage.get_instance()

    # Get all tasks (same order as displayed in /tasks)
    tasks = storage.get_task_items(owner_id, action_required=True)

    if not tasks:
        return None

    # Group by urgency: high -> medium -> low (no limits)
    high_medium = [t for t in tasks if t.get('urgency') in ('high', 'medium')]
    low = [t for t in tasks if t.get('urgency') == 'low']
    tasks = high_medium + low

    if task_num < 1 or task_num > len(tasks):
        return None

    return tasks[task_num - 1]  # 0-indexed


async def handle_task_detail(task_num: int, owner_id: str) -> str:
    """Handle 'more on #N' - show full email/event for a task.

    Args:
        task_num: 1-indexed task number from /tasks output
        owner_id: Firebase UID

    Returns:
        Formatted task detail or error message
    """
    from zylch.storage.supabase_client import SupabaseStorage

    logger.debug(f"[TASK_DETAIL] Requested task #{task_num} for owner {owner_id}")

    try:
        task = await get_task_by_number(task_num, owner_id)
        if not task:
            return f"Task #{task_num} not found. Run `/tasks refresh` first."

        storage = SupabaseStorage.get_instance()
        event_type = task.get('event_type')
        event_id = task.get('event_id')
        sources = task.get('sources', {})
        logger.debug(f"[TASK_DETAIL] Task #{task_num}: event_type={event_type}, event_id={event_id}, sources={sources}")

        if event_type == 'email':
            # Fetch full email from emails table using Supabase UUID
            email = storage.get_email_by_supabase_id(owner_id, event_id)
            logger.debug(f"[TASK_DETAIL] get_email_by_supabase_id result: {'found' if email else 'NOT FOUND'}")

            # If found, get the latest email in the same thread (for older task items)
            if email and email.get('thread_id'):
                thread_emails = storage.get_thread_emails(owner_id, email['thread_id'])
                if thread_emails and len(thread_emails) > 1:
                    # get_thread_emails returns ASC order, so last is latest
                    latest = thread_emails[-1]
                    if latest.get('id') != email.get('id'):
                        logger.debug(f"[TASK_DETAIL] Using latest email in thread: {latest.get('subject', '(none)')[:50]}")
                        email = latest

            if email:
                logger.debug(f"[TASK_DETAIL] Email subject: {email.get('subject', '(none)')[:50]}")
            if not email:
                return f"Email not found for task #{task_num}. It may have been deleted."

            # Format email details
            from_display = email.get('from_name') or email.get('from_email', 'Unknown')
            from_email = email.get('from_email', '')
            subject = email.get('subject', '(no subject)')
            date = email.get('date', '')
            body = email.get('body_plain') or email.get('snippet', '(no content)')

            # Build response
            output = f"""**📧 Task #{task_num} - Email Details**

**From:** {from_display} <{from_email}>
**Subject:** {subject}
**Date:** {date}

---
{body}
---

**🎯 Suggested Action:** {task.get('suggested_action', 'Review and respond')}
**📋 Reason:** {task.get('reason', 'Requires your attention')}
**⚡ Urgency:** {task.get('urgency', 'medium')}"""

            # Add blob context if available in sources
            blob_ids = sources.get('blobs', [])
            if blob_ids:
                blob_content = _load_blob_context(storage, owner_id, blob_ids)
                if blob_content:
                    output += f"\n\n**🧠 Context (from memory):**\n{blob_content}"

            return output

        elif event_type == 'calendar':
            # Fetch calendar event by google_event_id
            result = storage.client.table('calendar_events')\
                .select('*')\
                .eq('owner_id', owner_id)\
                .eq('google_event_id', event_id)\
                .limit(1)\
                .execute()
            logger.debug(f"[TASK_DETAIL] Calendar query result: {len(result.data) if result.data else 0} events")

            if not result.data:
                return f"Calendar event not found for task #{task_num}."

            event = result.data[0]
            summary = event.get('summary', '(no title)')
            description = event.get('description', '(no description)')
            start_time = event.get('start_time', '')
            end_time = event.get('end_time', '')
            location = event.get('location', '')
            attendees = event.get('attendees', [])

            # Format attendees
            attendee_str = ', '.join(attendees[:5]) if attendees else 'None listed'
            if len(attendees) > 5:
                attendee_str += f" (+{len(attendees) - 5} more)"

            output = f"""**📅 Task #{task_num} - Calendar Event**

**Event:** {summary}
**When:** {start_time} - {end_time}
**Location:** {location or 'Not specified'}
**Attendees:** {attendee_str}

**Description:**
{description}

---

**🎯 Suggested Action:** {task.get('suggested_action', 'Review and prepare')}
**📋 Reason:** {task.get('reason', 'Requires your attention')}
**⚡ Urgency:** {task.get('urgency', 'medium')}"""

            # Add blob context if available in sources
            blob_ids = sources.get('blobs', [])
            if blob_ids:
                blob_content = _load_blob_context(storage, owner_id, blob_ids)
                if blob_content:
                    output += f"\n\n**🧠 Context (from memory):**\n{blob_content}"

            return output

        else:
            return f"Unknown event type: {event_type}"

    except Exception as e:
        logger.error(f"Error in handle_task_detail: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


async def handle_jobs(args: List[str], owner_id: str) -> str:
    """Handle /jobs command - list scheduled jobs."""
    from zylch.services.scheduler import ZylchScheduler

    help_text = """**⏰ Scheduled Jobs**

**Usage:** `/jobs [cancel <id>]`

Shows your scheduled reminders and jobs.

**Subcommands:**
- `cancel <id>` - Cancel a job by ID

**Related:**
- "remind me in 2 hours" - Schedule via Claude
- `/trigger` - Event-driven automation"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    # Separate positional args from options
    positional = [a for a in args if not a.startswith('--')]
    subcommand = positional[0].lower() if positional else None

    try:
        scheduler = ZylchScheduler(owner_id=owner_id)

        # Subcommand: cancel
        if subcommand == 'cancel':
            job_id = positional[1] if len(positional) > 1 else None
            if job_id:
                success = scheduler.cancel_job(job_id)
                if success:
                    return f"✅ **Job cancelled:** `{job_id[:8]}`"
                else:
                    return f"❌ **Job not found:** `{job_id[:8]}`"
            else:
                return "❌ Missing job ID. Usage: `/jobs cancel <id>`"

        # List jobs
        jobs = scheduler.list_jobs()

        if not jobs:
            return """**⏰ Scheduled Jobs**

📭 No scheduled jobs.

**Create one:**
- "remind me in 2 hours to call Mario"
- `/trigger add session_start "Check my emails"`"""

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

        output += "_Use `/jobs cancel <id>` to cancel._"
        return output

    except Exception as e:
        logger.error(f"Error in /jobs: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


async def handle_agent(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /agent command - manage personalized agents for memory and task processing.

    Command structure:
        /agent <domain> <action> [channel]

    Domains: memory, task
    Actions: train, process, show, reset
    Channels: email, calendar, all (default)
    """
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.api.token_storage import get_email

    help_text = """**🤖 Manage AI Agents**

**Memory Agents** (extract facts into memory blobs):
• `/agent memory train [email|calendar]` - Create extraction agent
• `/agent memory process [email|calendar]` - Process data into memory
• `/agent memory show [email|calendar]` - Show current agent
• `/agent memory reset [email|calendar]` - Delete agent

**Task Agents** (detect actionable items):
• `/agent task train [email|calendar]` - Create task detection agent
• `/agent task process [email|calendar]` - Analyze and create tasks
• `/agent task show [email|calendar]` - Show current agent
• `/agent task reset [email|calendar]` - Delete agent

**Workflow:**
1. `/sync` - Fetch emails/calendar
2. `/agent memory train email` - Create memory agent
3. `/agent memory process email` - Extract facts
4. `/agent task train email` - Create task agent
5. `/agent task process email` - Detect tasks"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    if len(args) < 2:
        return help_text

    try:
        storage = SupabaseStorage.get_instance()

        domain = args[0].lower()  # 'memory' or 'task'
        action = args[1].lower()  # 'train', 'process', 'show', 'reset'
        channel = args[2].lower() if len(args) > 2 else 'email'  # 'email', 'calendar', 'all'

        valid_domains = ['memory', 'task']
        valid_actions = ['train', 'process', 'show', 'reset']
        valid_channels = ['email', 'calendar', 'all']

        if domain not in valid_domains:
            return f"❌ Unknown domain: `{domain}`\n\nValid domains: `memory`, `task`\n\n{help_text}"

        if action not in valid_actions:
            return f"❌ Unknown action: `{action}`\n\nValid actions: `train`, `process`, `show`, `reset`"

        if channel not in valid_channels:
            return f"❌ Unknown channel: `{channel}`\n\nValid channels: `email`, `calendar`, `all`"

        # Get common requirements
        from zylch.api.token_storage import get_active_llm_provider
        llm_provider, api_key = get_active_llm_provider(owner_id)
        user_email = get_email(owner_id)

        # Build agent_type for DB storage (e.g., 'memory_email', 'task_calendar')
        def get_agent_type(domain: str, channel: str) -> str:
            return f"{domain}_{channel}"

        # =====================
        # MEMORY DOMAIN
        # =====================
        if domain == 'memory':
            if action == 'train':
                return await _handle_memory_train(storage, owner_id, channel, api_key, llm_provider, user_email)

            elif action == 'process':
                return await _handle_memory_process(storage, owner_id, channel, api_key, llm_provider)

            elif action == 'show':
                return await _handle_agent_show(storage, owner_id, domain, channel)

            elif action == 'reset':
                return await _handle_agent_reset(storage, owner_id, domain, channel)

        # =====================
        # TASK DOMAIN
        # =====================
        elif domain == 'task':
            if action == 'train':
                return await _handle_task_train(storage, owner_id, channel, api_key, llm_provider, user_email)

            elif action == 'process':
                return await _handle_task_process(storage, owner_id, channel, api_key, llm_provider, user_email)

            elif action == 'show':
                return await _handle_agent_show(storage, owner_id, domain, channel)

            elif action == 'reset':
                return await _handle_agent_reset(storage, owner_id, domain, channel)

        return help_text

    except Exception as e:
        logger.error(f"Error in /agent: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


# =====================
# MEMORY AGENT HELPERS
# =====================

async def _handle_memory_train(storage, owner_id: str, channel: str, api_key: str, llm_provider: str, user_email: str) -> str:
    """Train memory extraction agent for specified channel."""
    from zylch.agents.email_memory_agent_trainer import EmailMemoryAgentTrainer

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    if not user_email:
        return """❌ **User email not found**

Your email address is required to identify sent vs received emails.
Please ensure your account is properly connected via `/connect`."""

    # Check sync status
    sync_state = storage.get_sync_state(owner_id)
    if not sync_state or not sync_state.get('full_sync_completed'):
        return """❌ **Please sync first**

Run `/sync` to synchronize your data.
Then run this command again."""

    channels_to_train = [channel] if channel != 'all' else ['email', 'calendar']
    results = []

    for ch in channels_to_train:
        if ch == 'email':
            emails = storage.get_emails(owner_id, limit=1)
            if not emails:
                results.append(f"📧 **Email:** No emails found - skipped")
                continue

            builder = EmailMemoryAgentTrainer(storage, owner_id, api_key, user_email, llm_provider)
            agent_prompt, metadata = await builder.build_memory_email_prompt()
            storage.store_agent_prompt(owner_id, 'memory_email', agent_prompt, metadata)
            results.append(f"📧 **Email:** Agent created ({metadata.get('emails_analyzed', 0)} emails analyzed)")

        elif ch == 'calendar':
            # Calendar memory training - placeholder for future implementation
            results.append(f"📅 **Calendar:** Not yet implemented")

    return f"""✅ **Memory Agent Training Complete**

{chr(10).join(results)}

**Next steps:**
- `/agent memory show {channel}` to review
- `/agent memory process {channel}` to extract facts"""


async def _handle_memory_process(storage, owner_id: str, channel: str, api_key: str, llm_provider: str) -> str:
    """Start memory processing as a background job.

    Creates a background job that runs in a thread pool, returning immediately.
    The user is notified via user_notifications when the job completes.
    """
    import asyncio
    from zylch.services.job_executor import JobExecutor

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    # Check for custom agent before starting job
    if channel in ['email', 'all']:
        if not storage.get_agent_prompt(owner_id, 'memory_email'):
            return """⚠️ **No memory agent found for email**

Train your memory agent first:
`/agent memory train email`"""

    # Create background job (returns existing if duplicate)
    job = storage.create_background_job(
        owner_id=owner_id,
        job_type="memory_process",
        channel=channel
    )

    if job["status"] == "running":
        pct = job.get("progress_pct", 0)
        msg = job.get("status_message", "Processing...")
        return f"""⏳ **Memory processing already in progress**

**Progress:** {pct}%
**Status:** {msg}

Job ID: `{job['id']}`"""

    if job["status"] == "pending":
        # Schedule execution in background (fire-and-forget)
        executor = JobExecutor(storage)
        asyncio.create_task(executor.execute_job(
            job["id"],
            owner_id,
            api_key,
            llm_provider,
            ""  # user_email not needed for memory processing
        ))

        return f"""🚀 **Memory processing started**

Processing {channel} data in the background.
You'll receive a notification when complete.

Job ID: `{job['id']}`

**Note:** You can continue working while this runs."""

    # Job exists but is completed/failed/cancelled - should create new one
    # The unique index allows new jobs if previous is not pending/running
    return f"Previous job status: {job['status']}. Run the command again to start a new job."


# =====================
# TASK AGENT HELPERS
# =====================

async def _handle_task_train(storage, owner_id: str, channel: str, api_key: str, llm_provider: str, user_email: str) -> str:
    """Train task detection agent for specified channel."""
    from zylch.agents.email_task_agent_trainer import EmailTaskAgentTrainer

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    if not user_email:
        return """❌ **User email not found**

Your email address is required to identify sent vs received emails.
Please ensure your account is properly connected via `/connect`."""

    # Check sync status
    sync_state = storage.get_sync_state(owner_id)
    if not sync_state or not sync_state.get('full_sync_completed'):
        return """❌ **Please sync first**

Run `/sync` to synchronize your data.
Then run this command again."""

    channels_to_train = [channel] if channel != 'all' else ['email', 'calendar']
    results = []

    for ch in channels_to_train:
        if ch == 'email':
            emails = storage.get_emails(owner_id, limit=1)
            if not emails:
                results.append(f"📧 **Email:** No emails found - skipped")
                continue

            builder = EmailTaskAgentTrainer(storage, owner_id, api_key, user_email, llm_provider)
            agent_prompt, metadata = await builder.build_task_prompt()
            storage.store_agent_prompt(owner_id, 'task_email', agent_prompt, metadata)
            results.append(f"📧 **Email:** Agent created ({metadata.get('threads_analyzed', 0)} threads analyzed)")

        elif ch == 'calendar':
            # Calendar task training - placeholder for future implementation
            results.append(f"📅 **Calendar:** Not yet implemented")

    return f"""✅ **Task Agent Training Complete**

{chr(10).join(results)}

**Next steps:**
- `/agent task show {channel}` to review
- `/agent task process {channel}` to detect tasks"""


async def _handle_task_process(storage, owner_id: str, channel: str, api_key: str, llm_provider: str, user_email: str) -> str:
    """Start task detection as a background job.

    Creates a background job that runs in a thread pool, returning immediately.
    The user is notified via user_notifications when the job completes.
    """
    import asyncio
    from zylch.services.job_executor import JobExecutor

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    # Check for custom agent before starting job
    if channel in ['email', 'all']:
        if not storage.get_agent_prompt(owner_id, 'task_email'):
            return """⚠️ **No task agent found for email**

Train your task agent first:
`/agent task train email`"""

    # Create background job (returns existing if duplicate)
    job = storage.create_background_job(
        owner_id=owner_id,
        job_type="task_process",
        channel=channel
    )

    if job["status"] == "running":
        pct = job.get("progress_pct", 0)
        msg = job.get("status_message", "Detecting tasks...")
        return f"""⏳ **Task detection already in progress**

**Progress:** {pct}%
**Status:** {msg}

Job ID: `{job['id']}`"""

    if job["status"] == "pending":
        # Schedule execution in background (fire-and-forget)
        executor = JobExecutor(storage)
        asyncio.create_task(executor.execute_job(
            job["id"],
            owner_id,
            api_key,
            llm_provider,
            user_email or ""
        ))

        return f"""🚀 **Task detection started**

Analyzing {channel} data in the background.
You'll receive a notification when complete.

Job ID: `{job['id']}`

**Note:** You can continue working while this runs."""

    # Job exists but is completed/failed/cancelled - should create new one
    return f"Previous job status: {job['status']}. Run the command again to start a new job."


# =====================
# SHARED AGENT HELPERS
# =====================

async def _handle_agent_show(storage, owner_id: str, domain: str, channel: str) -> str:
    """Show agent prompt for specified domain and channel."""
    agent_type = f"{domain}_{channel}"

    agent_prompt = storage.get_agent_prompt(owner_id, agent_type)
    if not agent_prompt:
        return f"""❌ **No agent found for `{domain} {channel}`**

Create one with:
`/agent {domain} train {channel}`"""

    meta = storage.get_agent_prompt_metadata(owner_id, agent_type)
    meta_info = ""
    if meta:
        metadata = meta.get('metadata', {})
        created = meta.get('created_at', '')[:10] if meta.get('created_at') else 'unknown'
        meta_info = f"\n_Created: {created}_\n"

    return f"""**🤖 Your {domain.title()} Agent ({channel})**
{meta_info}
---
{agent_prompt}
---

_Use `/agent {domain} reset {channel}` to delete._"""


async def _handle_agent_reset(storage, owner_id: str, domain: str, channel: str) -> str:
    """Delete agent prompt for specified domain and channel."""
    agent_type = f"{domain}_{channel}"

    deleted = storage.delete_agent_prompt(owner_id, agent_type)
    if deleted:
        return f"""✅ **Agent deleted**

Your `{domain} {channel}` agent has been deleted.

Recreate with: `/agent {domain} train {channel}`"""
    else:
        return f"❌ No agent found for `{domain} {channel}`"


# Export all handlers
COMMAND_HANDLERS = {
    '/echo': handle_echo,
    '/help': handle_help,
    '/sync': handle_sync,
    '/memory': handle_memory,
    '/email': handle_email,
    '/trigger': handle_trigger,
    '/mrcall': handle_mrcall,
    # NOTE: /connect is partially handled client-side by CLI for OAuth. Only --help, reset, status reach backend.
    '/connect': handle_connect,
    '/share': handle_share,
    '/revoke': handle_revoke,
    # Phase 1: High-impact commands (replacing tools)
    '/stats': handle_stats,
    '/calendar': handle_calendar,
    '/tasks': handle_tasks,
    '/jobs': handle_jobs,
    '/agent': handle_agent,
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
COMMAND_PATTERNS = {
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
    '/memory reset': [
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
        "update everything",
        "synchronize",
    ],

    # --- Memory ---
    '/memory': [
        "who is {name:text}",
        "what do you know about {name:text}",
        "search memory for {query:text}",
        "find in memory {query:text}",
        "remember that {content:text}",
        "save to memory that {content:text}",
        "store in memory {content:text}",
        "memory stats",
        "memory statistics",
        "show memories",
        "list memories",
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
        "link mrcall",
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

    # --- Tasks ---
    '/tasks': [
        "tasks",
        "my tasks",
        "what's on my plate",
        "today's tasks",
        "show me my tasks",
        "daily update",
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
        # Variables
        "show mrcall variables",
        "list mrcall variables",
        "what are the mrcall variables",
        "show mrcall variable {name:text}",
        "get mrcall variable {name:text}",
        "what is the value of mrcall variable {name:text}",
        "value of mrcall variable {name:text}",
        "search mrcall variable {name:text}",
    ],

    # --- Email ---
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

    # --- Agent (Training and processing) ---
    '/agent': [
        # Memory train
        "train memory agent",
        "train email memory agent",
        "create memory extraction agent",
        "train agent to extract memory",
        # Memory process
        "process emails into memory",
        "process calendar into memory",
        "extract facts from emails",
        "extract entities from emails",
        "build memory from emails",
        "run memory agent",
        # Task train
        "train task agent",
        "train email task agent",
        "create task detection agent",
        "train agent to detect tasks",
        # Task process
        "detect tasks from emails",
        "find tasks in emails",
        "process emails into tasks",
        "run task agent",
        "what tasks do I have",
        # Show
        "show memory agent",
        "show task agent",
        "show email agent",
        "let me see your agents",
        # Reset
        "reset memory agent",
        "reset task agent",
        "delete memory agent",
        "delete task agent",
    ],
}
