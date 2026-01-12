"""Command handlers for slash commands.

All handlers return markdown-formatted strings (no print statements).
No Anthropic API calls in these handlers.
"""
import logging
from datetime import datetime, timezone
from typing import List

from zylch.tools.config import ToolConfig

logger = logging.getLogger(__name__)


def format_relative_date(date_str: str) -> str:
    """Format a date string as relative time (e.g., '3 days ago', 'today').

    Args:
        date_str: ISO format date string or RFC 2822 email date

    Returns:
        Human-readable relative date string, or empty string if parsing fails
    """
    if not date_str:
        return ""

    try:
        # Try ISO format first
        if 'T' in date_str:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        else:
            # Try parsing common email date formats
            from email.utils import parsedate_to_datetime
            try:
                dt = parsedate_to_datetime(date_str)
            except (ValueError, TypeError):
                # Fallback: just return the date portion
                return date_str.split('T')[0] if 'T' in date_str else date_str[:10]

        # Make timezone-aware if not already
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        diff = now - dt

        days = diff.days
        if days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                return "just now"
            elif hours == 1:
                return "1 hour ago"
            else:
                return f"{hours} hours ago"
        elif days == 1:
            return "yesterday"
        elif days < 7:
            return f"{days} days ago"
        elif days < 14:
            return "1 week ago"
        elif days < 30:
            weeks = days // 7
            return f"{weeks} weeks ago"
        elif days < 60:
            return "1 month ago"
        else:
            months = days // 30
            return f"{months} months ago"

    except Exception:
        # If all parsing fails, return empty
        return ""


def format_task_items(tasks: list) -> str:
    """Format task items as numbered list grouped by urgency."""
    if not tasks:
        return "No action needed! You're all caught up."

    lines = ["**Tasks Needing Action**\n"]

    # Group by urgency
    high = [t for t in tasks if t.get('urgency') == 'high']
    medium = [t for t in tasks if t.get('urgency') == 'medium']
    low = [t for t in tasks if t.get('urgency') == 'low']

    idx = 1

    def format_task(task):
        nonlocal idx
        name = task.get('contact_name') or task.get('contact_email', 'Unknown')
        action = task.get('suggested_action', '').strip()
        reason = task.get('reason', '').strip()
        email_date = task.get('email_date', '')

        # Skip tasks with no action
        if not action:
            return None

        # Format relative date for temporal context
        date_str = format_relative_date(email_date) if email_date else ""

        # Format: Name: Action (date) with reason on next line if substantial
        task_line = f"{idx}. **{name}**: {action}"
        if date_str:
            task_line += f" ({date_str})"
        if reason and len(reason) > 10:
            task_line += f"\n   _{reason}_"

        idx += 1
        return task_line

    if high:
        lines.append("**HIGH PRIORITY:**")
        for task in high:
            formatted = format_task(task)
            if formatted:
                lines.append(formatted)
        lines.append("")

    if medium:
        lines.append("**MEDIUM PRIORITY:**")
        for task in medium:
            formatted = format_task(task)
            if formatted:
                lines.append(formatted)
        lines.append("")

    if low:
        lines.append("**LOW PRIORITY:**")
        for task in low:
            formatted = format_task(task)
            if formatted:
                lines.append(formatted)

    total = idx - 1
    if total > 0:
        lines.append(f"\n**Total: {total} items** | `more on #N` for details")
        lines.append("\n_Run `/agent task process` to detect new tasks_")
    else:
        return "No action needed! You're all caught up.\n\n_Run `/agent task process` to detect new tasks_"

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
• `/jobs [status|<id>|cancel]` - View background jobs

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
            from datetime import datetime
            supabase = SupabaseStorage()

            # Count emails
            email_count_result = supabase.client.table('emails').select('id', count='exact').eq('owner_id', owner_id).execute()
            email_count = email_count_result.count if hasattr(email_count_result, 'count') else 0

            # Get newest and oldest email dates
            newest_email = supabase.client.table('emails').select('date').eq('owner_id', owner_id).order('date', desc=True).limit(1).execute()
            oldest_email = supabase.client.table('emails').select('date').eq('owner_id', owner_id).order('date', desc=False).limit(1).execute()

            if not email_count or email_count == 0:
                newest_display = "Never synced"
                oldest_display = "-"
            else:
                if newest_email.data:
                    dt = datetime.fromisoformat(newest_email.data[0]['date'].replace('Z', '+00:00'))
                    newest_display = dt.strftime('%Y-%m-%d %H:%M UTC')
                else:
                    newest_display = "Unknown"

                if oldest_email.data:
                    dt = datetime.fromisoformat(oldest_email.data[0]['date'].replace('Z', '+00:00'))
                    oldest_display = dt.strftime('%Y-%m-%d')
                else:
                    oldest_display = "Unknown"

            # Count calendar events
            event_count_result = supabase.client.table('calendar_events').select('id', count='exact').eq('owner_id', owner_id).execute()
            event_count = event_count_result.count if hasattr(event_count_result, 'count') else 0

            return f"""📊 **Sync Status**

📧 **Emails:** {email_count:,}
   Newest: {newest_display}
   Oldest: {oldest_display}
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

            # Clear emails
            supabase.client.table('emails').delete().eq('owner_id', owner_id).execute()
            logger.info(f"[/sync] Cleared emails")

            # Clear calendar events
            supabase.client.table('calendar_events').delete().eq('owner_id', owner_id).execute()
            logger.info(f"[/sync] Cleared calendar_events")

            return """✅ **Sync reset!**

All emails and calendar events cleared.
Next `/sync` will perform a full re-sync from scratch.

⚠️ **Memory note:** Your memory blobs still exist. If you want fresh memory:
```
/memory reset
```
Then run `/sync --days N` to rebuild memory from re-synced emails."""
        except Exception as e:
            logger.error(f"[/sync] Failed to reset sync data: {e}")
            return f"❌ **Error resetting sync data:** {str(e)}"

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
            channel="all",  # sync always does all channels
            params={"days_back": days_back}
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
        from zylch.api.token_storage import get_active_llm_provider
        llm_merge = None
        llm_provider, api_key = get_active_llm_provider(owner_id)
        if api_key:
            llm_merge = LLMMergeService(api_key=api_key, provider=llm_provider)

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

                    return f"✅ **Memory deleted** (ID: `{blob_id}`)"
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
                for ns in stats['namespaces']:
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
                content_preview = blob['content']
                blob_id_short = blob['id']
                output += f"**{blob_id_short}** {content_preview}\n"
                output += f"   _Updated: {blob['updated_at']}_\n\n"

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


async def handle_mrcall(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /mrcall command - MrCall integration."""
    from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient
    from zylch.api.token_storage import get_mrcall_credentials
    import httpx
    from zylch.config import settings

    # Derive from single source of truth (MrCallConfiguratorTrainer.FEATURES)
    from zylch.agents.mrcall_configurator_trainer import MrCallConfiguratorTrainer
    FEATURE_TO_VARIABLES = {
        name: feature["variables"]
        for name, feature in MrCallConfiguratorTrainer.FEATURES.items()
    }
    SUPPORTED_FEATURES = list(FEATURE_TO_VARIABLES.keys())

    help_text = """**📞 MrCall Integration**

**Commands:**
• `/mrcall list` - List your MrCall assistants
• `/mrcall link <business_id>` - Link to assistant by ID
• `/mrcall variables [get] [--name NAME]` - List/filter variables
• `/mrcall variables set <NAME> <VALUE>` - Set variable value
• `/mrcall show [feature]` - Show current configuration context
• `/mrcall config <feature> "instructions"` - Configure assistant behavior
• `/mrcall unlink` - Unlink current assistant
• `/mrcall` - Show current link status

**Agent commands (preferred):**
• `/agent mrcall train` - Train all features and build unified agent
• `/agent mrcall run "..."` - Configure assistant (auto-detects feature)

**Features:** welcome_message (greeting), booking (appointment scheduling)

**Setup:**
1. Run `/connect mrcall` to authenticate with MrCall
2. Run `/mrcall list` to see your assistants
3. Run `/mrcall link <business_id>` to connect to an assistant"""

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
            # Get the linked business (explicit /mrcall link takes priority over OAuth default)
            current_business_id = client.get_mrcall_link(owner_id)
            logger.debug(f"[/mrcall list] current_business_id={current_business_id}")

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
                    logger.debug(f"[/mrcall list] POST {url} -> status={response.status_code}, businesses={len(businesses)}")
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
                logger.debug(f"[/mrcall list] business {i}: id={biz_id}, nickname={nickname}")
                company = biz.get('companyName') or ''
                service_number = biz.get('serviceNumber') or ''
                email_address = biz.get('emailAddress') or ''
                user_phone = biz.get('userPhoneNumber') or ''
                template = biz.get('template') or ''
                subscription_status = biz.get('subscriptionStatus') or ''

                # Mark if this is the linked business
                linked_marker = " ← LINKED" if biz_id == current_business_id else ""

                # Format: "1. **Nickname** (Company) ← LINKED"
                if company:
                    output += f"{i}. **{nickname}** ({company}){linked_marker}\n"
                else:
                    output += f"{i}. **{nickname}**{linked_marker}\n"

                # Business ID (for /mrcall link)
                output += f"   🆔 `{biz_id}`\n"

                # Email
                if email_address:
                    output += f"   📧 {email_address}\n"

                # User phone number
                if user_phone:
                    output += f"   📱 User: {user_phone}\n"

                # Assistant (service) number - formatted as clickable link
                if service_number:
                    # Clean up service number display (remove duplicates like +39...#+39...)
                    display_number = service_number.split('#')[0] if '#' in service_number else service_number
                    output += f"   ☎️ Assistant: [{display_number}](tel:{display_number})\n"

                # Template (assistant type)
                if template:
                    output += f"   🤖 {template}\n"

                # Subscription status
                if subscription_status:
                    output += f"   📋 {subscription_status}\n"

                output += "\n"

            output += "---\nUse `/mrcall link <business_id>` to connect an assistant."
            return output

        # Subcommand: variables - List all variables
        if subcommand == 'variables':
            logger.debug(f"[/mrcall variables] args={args}")
            # Get credentials
            creds = get_mrcall_credentials(owner_id)
            logger.debug(f"[/mrcall variables] get_mrcall_credentials(owner_id={owner_id}) -> keys={list(creds.keys()) if creds else None}, business_id={creds.get('business_id') if creds else None}")
            if not creds or not creds.get('access_token'):
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first to authenticate."
            
            # Get linked business ID (explicit /mrcall link takes priority over OAuth default)
            business_id = client.get_mrcall_link(owner_id)
            logger.debug(f"[/mrcall variables] get_mrcall_link(owner_id={owner_id}) -> business_id={business_id}")

            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` then `/mrcall link <business_id>` to select one."

            # Check for sub-subcommand (get/set)
            # args[0] is 'variables'. Check args[1]
            var_subcommand = args[1].lower() if len(args) > 1 else 'get'
            logger.debug(f"[/mrcall variables] var_subcommand={var_subcommand}")
            
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
            logger.debug(f"[/mrcall variables] filter: '--name' in args={('--name' in args)}, filter_name={filter_name}")

            # Use factory to get client
            from zylch.tools.starchat import create_starchat_client
            sc_client = await create_starchat_client(owner_id)

            try:
                variables = await sc_client.get_all_variables(business_id)
                logger.debug(f"[/mrcall variables] get_all_variables(business_id={business_id}) -> {len(variables)} vars: {[v['name'] for v in variables]}")
                await sc_client.close()

                if not variables:
                    return f"**📋 MrCall Variables**\n\nNo variables found for business `{business_id}`."

                # Filter if requested
                if filter_name:
                    vars_before = len(variables)
                    variables = [v for v in variables if filter_name.upper() in v['name'].upper()]
                    logger.debug(f"[/mrcall variables] filter applied: before={vars_before}, filter={filter_name}, after={len(variables)}, matches={[v['name'] for v in variables]}")
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

        # Subcommand: link <business_id> - Link to business by ID
        if subcommand == 'link':
            logger.debug(f"[/mrcall link] positional={positional}")
            if len(positional) < 2:
                return "❌ **Usage:** `/mrcall link <business_id>`\n\nCopy the business ID from `/mrcall list`"

            target_business_id = positional[1]
            logger.debug(f"[/mrcall link] target_business_id={target_business_id}")

            # Validate UUID format (basic check - UUIDs are 36 chars with dashes)
            if len(target_business_id) < 20:
                return f"❌ **Invalid business ID:** `{target_business_id}`\n\nCopy the full ID from `/mrcall list`"

            # Get OAuth credentials
            creds = get_mrcall_credentials(owner_id)
            if not creds or not creds.get('access_token'):
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first to authenticate."

            access_token = creds.get('access_token')

            # Fetch businesses to validate the ID exists
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

            # Find business by ID
            logger.debug(f"[/mrcall link] searching for business in {len(businesses)} results")
            business = None
            for biz in businesses:
                biz_id = biz.get('businessId') or biz.get('id')
                if biz_id == target_business_id:
                    business = biz
                    break

            if not business:
                logger.debug(f"[/mrcall link] business not found: {target_business_id}")
                return f"❌ **Business not found:** `{target_business_id}`\n\nRun `/mrcall list` to see your assistants."

            business_id = target_business_id
            nickname = business.get('nickname') or 'Unnamed'
            logger.debug(f"[/mrcall link] found business: nickname={nickname}")

            # Save the link
            result = client.set_mrcall_link(owner_id, business_id)
            logger.debug(f"[/mrcall link] set_mrcall_link(owner_id={owner_id}, business_id={business_id}) -> result={result}")

            if result:
                return f"""✅ **MrCall Linked**

**Assistant:** {nickname}
**Business ID:** `{business_id}`

Your Zylch is now connected to this MrCall assistant!

**Next steps:**
• `/sync mrcall` - Test fetching conversations
• `/agent mrcall train` - Train AI on your assistant"""
            else:
                return "❌ **Error:** Failed to link MrCall business. Please try again."

        # Subcommand: show - Display current configuration context
        if subcommand == 'show':
            # Get linked business
            creds = get_mrcall_credentials(owner_id)
            if not creds or not creds.get('access_token'):
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first."

            # Get linked business ID (explicit /mrcall link takes priority over OAuth default)
            business_id = client.get_mrcall_link(owner_id)
            logger.debug(f"[/mrcall show] get_mrcall_link(owner_id={owner_id}) -> business_id={business_id}")
            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` then `/mrcall link <business_id>` first."

            # Parse feature argument
            feature_name = positional[1] if len(positional) > 1 else "welcome_message"
            agent_type = f"mrcall_{business_id}_{feature_name}"

            # Get stored sub-prompt
            sub_prompt = client.get_agent_prompt(owner_id, agent_type)

            if not sub_prompt:
                return f"""**📋 MrCall Configuration Context**

**Feature:** {feature_name}
**Status:** Not generated yet

Run `/agent mrcall train` to generate configuration context for all features."""

            return f"""**📋 MrCall Configuration Context**

**Feature:** {feature_name}
**Business ID:** `{business_id}`
**Length:** {len(sub_prompt)} characters

---

{sub_prompt}"""

        # Subcommand: config - Configure assistant behavior
        if subcommand == 'config':
            logger.debug(f"[/mrcall config] positional={positional}")
            import asyncio
            from concurrent.futures import ThreadPoolExecutor
            from zylch.api.token_storage import get_active_llm_provider

            # Validate args: config <feature> <instructions>
            if len(positional) < 2:
                return f"""❌ **Missing feature and instructions**

**Usage:** `/mrcall config <feature> "instructions"`

**Example:**
```
/mrcall config welcome_message "use formal tone (lei/Sie), don't ask for name"
```

**Supported features:** {', '.join(SUPPORTED_FEATURES)}"""

            feature_name = positional[1]
            if feature_name not in SUPPORTED_FEATURES:
                return f"""❌ **Unknown feature:** `{feature_name}`

**Supported features:** {', '.join(SUPPORTED_FEATURES)}"""

            # Join remaining args as instructions (handles multi-line quoted strings)
            instructions = ' '.join(positional[2:])
            if not instructions:
                return f"""❌ **Missing instructions**

**Usage:** `/mrcall config {feature_name} "your instructions here"`

**Example:**
```
/mrcall config welcome_message "use formal tone, don't ask for name"
```"""

            # Get MrCall credentials
            creds = get_mrcall_credentials(owner_id)
            if not creds or not creds.get('access_token'):
                return "❌ **MrCall not connected**\n\nRun `/connect mrcall` first."

            # Get linked business ID (explicit /mrcall link takes priority over OAuth default)
            business_id = client.get_mrcall_link(owner_id)
            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` then `/mrcall link <business_id>` first."

            logger.debug(f"[/mrcall config] feature={feature_name}, business_id={business_id}, instructions_len={len(instructions)}")

            # Get LLM credentials
            llm_provider, api_key = get_active_llm_provider(owner_id)
            logger.debug(f"[/mrcall config] llm_provider={llm_provider}, api_key={'present' if api_key else 'absent'}")
            if not api_key:
                return "❌ **No LLM configured**\n\nRun `/connect anthropic` to configure an LLM provider."

            # Get variable names for this feature (can be multiple)
            variable_names = FEATURE_TO_VARIABLES[feature_name]
            logger.debug(f"[/mrcall config] variable_names={variable_names}")

            # Run the config update in executor (involves multiple async calls)
            def _config_feature():
                import asyncio
                from zylch.tools.starchat import create_starchat_client
                from zylch.agents.mrcall_configurator_trainer import MrCallConfiguratorTrainer
                from zylch.tools.mrcall.llm_helper import modify_variables_with_llm

                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Create StarChat client
                    starchat = loop.run_until_complete(create_starchat_client(owner_id))
                    logger.debug(f"[/mrcall config] StarChat client created")

                    # 1. Load context (lazy generate if missing)
                    agent_type = f"mrcall_{business_id}_{feature_name}"
                    context = client.get_agent_prompt(owner_id, agent_type)
                    logger.debug(f"[/mrcall config] get_agent_prompt(agent_type={agent_type}) -> context_len={len(context) if context else 0}")

                    trainer = MrCallConfiguratorTrainer(
                        storage=client,
                        starchat_client=starchat,
                        owner_id=owner_id,
                        api_key=api_key,
                        provider=llm_provider,
                    )

                    if not context:
                        # Generate it first
                        logger.info(f"No context found for {feature_name}, generating...")
                        context, _ = loop.run_until_complete(
                            trainer.train_feature(feature_name, business_id)
                        )
                        logger.debug(f"[/mrcall config] train_feature() -> context_len={len(context) if context else 0}")

                    # 2. Get current values for ALL variables in this feature
                    business_data = loop.run_until_complete(
                        starchat.get_business_config(business_id)
                    )
                    business_variables = business_data.get("variables", {})
                    logger.debug(f"[/mrcall config] get_business_config() -> vars_count={len(business_variables)}")

                    current_values = {}
                    missing_vars = []
                    for var_name in variable_names:
                        value = business_variables.get(var_name, "")
                        if value:
                            current_values[var_name] = value
                        else:
                            missing_vars.append(var_name)

                    if missing_vars:
                        loop.run_until_complete(starchat.close())
                        return None, None, f"Variable(s) not found: {', '.join(missing_vars)}"

                    # 3. Use LLM with function calling to modify ALL variables
                    logger.debug(f"[/mrcall config] calling modify_variables_with_llm(current_values={list(current_values.keys())})")
                    update_result = loop.run_until_complete(
                        modify_variables_with_llm(
                            current_values=current_values,
                            context=context,
                            instructions=instructions,
                            api_key=api_key,
                            provider=llm_provider,
                        )
                    )
                    logger.debug(f"[/mrcall config] modify_variables_with_llm() -> new_values={list(update_result.new_values.keys())}")

                    # 4. Apply ALL new values to StarChat
                    for var_name, new_value in update_result.new_values.items():
                        logger.debug(f"[/mrcall config] update_business_variable({var_name}) -> new_value_len={len(new_value)}")
                        loop.run_until_complete(
                            starchat.update_business_variable(business_id, var_name, new_value)
                        )

                    # 5. Retrain to update sub-prompt
                    logger.debug(f"[/mrcall config] retraining feature {feature_name}")
                    loop.run_until_complete(
                        trainer.train_feature(feature_name, business_id)
                    )

                    # Close starchat client
                    loop.run_until_complete(starchat.close())

                    return update_result.new_values, update_result.behavior_summary, None
                except Exception as e:
                    logger.error(f"Config feature error: {e}", exc_info=True)
                    return None, None, str(e)
                finally:
                    loop.close()

            executor = ThreadPoolExecutor(max_workers=1)
            loop = asyncio.get_event_loop()

            try:
                new_values, behavior_summary, error = await loop.run_in_executor(executor, _config_feature)

                if error:
                    # Check for auth errors
                    if any(code in error for code in ["405", "401", "403", "Unauthorized", "Forbidden"]):
                        return "❌ **MrCall connection expired**\n\nRun `/connect mrcall` to reconnect."
                    return f"❌ **Error configuring assistant:** {error}"

                # Log variables for debugging (internal only)
                logger.debug(f"Variables updated for {feature_name}: {list(new_values.keys())}")

                # Get display name for user-friendly message
                from zylch.agents.mrcall_configurator_trainer import MrCallConfiguratorTrainer
                display_name = MrCallConfiguratorTrainer.FEATURES.get(feature_name, {}).get(
                    "display_name", feature_name
                )

                return f"""✅ **Configuration updated**

**{display_name}**

{behavior_summary}

Run `/mrcall show {feature_name}` to see the full configuration."""

            except Exception as e:
                logger.error(f"Failed to config feature: {e}", exc_info=True)
                error_str = str(e)
                # Check for auth errors
                if any(code in error_str for code in ["405", "401", "403", "Unauthorized", "Forbidden"]):
                    return "❌ **MrCall connection expired**\n\nRun `/connect mrcall` to reconnect."
                return f"❌ **Error configuring assistant:** {error_str}"

        # No subcommand: show status
        if subcommand is None:
            # Get OAuth credentials to check connection
            creds = get_mrcall_credentials(owner_id)

            if creds and creds.get('access_token'):
                # Get linked business ID (explicit /mrcall link takes priority over OAuth default)
                business_id = client.get_mrcall_link(owner_id)
                logger.debug(f"[/mrcall status] get_mrcall_link(owner_id={owner_id}) -> business_id={business_id}")
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
• `/agent mrcall train` - Train AI on your assistant"""
                else:
                    return f"""**📞 MrCall Status**

**Status:** Connected (not linked to an assistant)
**Email:** {email or 'N/A'}

Run `/mrcall list` to see your assistants, then `/mrcall link <business_id>` to connect one."""
            else:
                return """**📞 MrCall Status**

**Status:** Not connected

**To get started:**
1. Run `/connect mrcall` to authenticate
2. Run `/mrcall list` to see your assistants
3. Run `/mrcall link <business_id>` to connect an assistant"""

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
                    to_str = ', '.join(draft.get('to_addresses', []))
                    subject = draft.get('subject', '(no subject)')
                    draft_id = draft['id']
                    updated = draft.get('updated_at', '')

                    output += f"**{i}. {subject}**\n"
                    output += f"   To: {to_str}\n"
                    output += f"   ID: `{draft_id}` | {updated}\n\n"

                output += "_Use `/email send <id>` to send a draft._"
                return output

            # Default: list recent emails - grouped by thread, only RECEIVED
            days = int(parse_flag('--days', '7'))
            since_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            # Get user's email domain to filter out sent emails
            user_email = get_email(owner_id) or ''
            user_domain = user_email.split('@')[1].lower() if user_email and '@' in user_email else ''

            # Fetch more emails to allow filtering, then group by thread
            result = supabase.table('emails')\
                .select('gmail_id, thread_id, subject, from_email, from_name, snippet, body_plain, date')\
                .eq('owner_id', owner_id)\
                .gte('date', since_date)\
                .order('date', desc=True)\
                .limit(limit * 3)\
                .execute()

            if not result.data:
                return f"**📭 No emails** in the last {days} days\n\nTry `/sync` to fetch recent emails."

            emails = result.data

            # Filter: only RECEIVED emails (from_email NOT matching user's domain)
            received_emails = []
            for email in emails:
                from_email_addr = (email.get('from_email') or '').lower()
                if user_domain and user_domain in from_email_addr:
                    continue  # Skip emails sent by user
                received_emails.append(email)

            # Group by thread_id, keep only most recent per thread
            seen_threads = set()
            thread_emails = []
            for email in received_emails:  # Already sorted by date desc
                thread_id = email.get('thread_id') or email.get('gmail_id')
                if thread_id not in seen_threads:
                    seen_threads.add(thread_id)
                    thread_emails.append(email)
                if len(thread_emails) >= limit:
                    break

            if not thread_emails:
                return f"**📭 No received emails** in the last {days} days\n\nTry `/sync` to fetch recent emails."

            output = f"**📧 Recent Conversations** ({len(thread_emails)} threads)\n\n"
            for email in thread_emails:
                subject = email.get('subject') or '(no subject)'
                from_name = email.get('from_name') or email.get('from_email', 'Unknown')
                date_str = (email.get('date') or '')[:10]  # YYYY-MM-DD

                # Body preview: body_plain or snippet, ~200 chars
                body = email.get('body_plain') or email.get('snippet') or ''
                body_preview = body[:200].replace('\n', ' ').strip()
                if len(body) > 200:
                    body_preview += '...'

                output += f"**{subject}**\n"
                output += f"   From: {from_name} | {date_str}\n"
                output += f"   {body_preview}\n\n"

            output += f"_Showing last {days} days. Use `--days N` or `--limit N` to adjust._"
            return output

        # --- CREATE DRAFT (DEPRECATED - use /agent email run) ---
        if subcommand == 'create':
            return """⚠️ **`/email create` is deprecated**

Use the email agent instead:
• `/agent email run "scrivi a mario@example.com un'offerta"`
• `/agent email run "write to John about the meeting"`

The email agent composes contextual emails using your writing style and memory.

For simple drafts without context, use the `compose_email` tool in chat."""

        # --- SEND DRAFT ---
        if subcommand == 'send':
            # Get draft_id from first positional arg after 'send'
            draft_id = sub_args[0] if sub_args and not sub_args[0].startswith('--') else None

            if draft_id:
                # Find the draft by ID
                result = supabase.table('drafts')\
                    .select('*')\
                    .eq('owner_id', owner_id)\
                    .eq('status', 'draft')\
                    .eq('id', draft_id)\
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
                draft_id = draft['id']

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
                # Convert list fields to comma-separated strings for email APIs
                to_str = ', '.join(draft['to_addresses']) if isinstance(draft['to_addresses'], list) else draft['to_addresses']
                cc_str = ', '.join(draft['cc_addresses']) if draft.get('cc_addresses') and isinstance(draft['cc_addresses'], list) else draft.get('cc_addresses')
                bcc_str = ', '.join(draft['bcc_addresses']) if draft.get('bcc_addresses') and isinstance(draft['bcc_addresses'], list) else draft.get('bcc_addresses')

                if provider == 'google':
                    from zylch.tools.gmail import GmailClient

                    gmail = GmailClient(
                        credentials_path="credentials/gmail_oauth.json",
                        account=user_email,
                        owner_id=owner_id
                    )

                    # Build and send message
                    sent_message = gmail.send_message(
                        to=to_str,
                        subject=draft.get('subject', ''),
                        body=draft.get('body', ''),
                        cc=cc_str,
                        bcc=bcc_str,
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
                        to=to_str,
                        subject=draft.get('subject', ''),
                        body=draft.get('body', ''),
                        cc=cc_str,
                        bcc=bcc_str,
                    )

                    sent_id = sent_message.get('id', '')

                else:
                    raise Exception(f"Unknown provider: {provider}")

                # Delete draft after successful send
                supabase.table('drafts').delete().eq('id', draft['id']).execute()

                to_str = ', '.join(draft['to_addresses'])
                return f"""✅ **Email sent!**

**To:** {to_str}
**Subject:** {draft.get('subject', '(no subject)')}
**Via:** {provider.title()}

Message ID: `{sent_id if sent_id else 'N/A'}`"""

            except Exception as e:
                # Restore draft status on failure (so it appears in /email list --draft)
                supabase.table('drafts').update({
                    'status': 'draft',
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
                .eq('id', draft_id)\
                .execute()

            if result.data:
                return f"✅ Draft `{draft_id}` deleted"
            else:
                return f"❌ Draft not found: `{draft_id}`"

        # --- RESET (delete all emails) ---
        if subcommand == 'reset':
            supabase = SupabaseStorage()
            supabase.client.table('emails').delete().eq('owner_id', owner_id).execute()
            return "✅ All emails deleted."

        # --- SEARCH EMAILS (DEPRECATED - use /agent email run) ---
        if subcommand == 'search':
            return """⚠️ **`/email search` is deprecated**

Use the email agent instead:
• `/agent email run "cerca info su Mario"`
• `/agent email run "what do we know about Acme Corp?"`

The email agent searches your memory blobs and can also fetch original emails.

Alternatively, just ask in chat: "cerca le email di Mario" and the assistant will help you."""

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
        'summary': 'List emails, manage drafts, search, reset',
        'usage': '/email <list|create|send|delete|reset|search> [args]',
        'description': '''List emails, manage drafts, and search.

**List:**
- `/email list [--limit N]` - List recent emails
- `/email list --draft [--limit N]` - List drafts

**Drafts:**
- `/email create --to <email> --subject <text>` - Create draft
- `/email send <draft_id>` - Send via Gmail/Outlook
- `/email delete <draft_id>` - Delete draft

**Reset:**
- `/email reset` - Delete ALL emails

**Search:**
- `/email search <query>` - Search emails
- `/email search <query> --from <sender> --days N --limit N`''',
    },
    '/mrcall': {
        'summary': 'MrCall integration',
        'usage': '/mrcall [list|link N|unlink|variables|train|show|config]',
        'description': '''Manage MrCall telephony integration.

**Subcommands:**
- (none) - Show current connection status
- `list` - List your MrCall assistants
- `link <business_id>` - Link to assistant by ID
- `unlink` - Disconnect current assistant
- `variables [get] [--name NAME]` - List/filter variables
- `variables set <NAME> <VALUE>` - Set variable value
- `train [feature]` - Generate configuration context for a feature
- `show [feature]` - Display current configuration context
- `config <feature> "instructions"` - Configure assistant behavior

**Features:** welcome_message (greeting), booking (appointment scheduling)

**Examples:**
- `/mrcall` - Show connection status
- `/mrcall list` - See your assistants
- `/mrcall link <business_id>` - Connect to assistant by ID
- `/agent mrcall train` - Train all features
- `/agent mrcall run "use formal tone"` - Configure behavior
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
        'summary': 'Background jobs',
        'usage': '/jobs [<job_id>|cancel <job_id>|reset|resume|--all]',
        'description': '''Shows your running/pending background jobs.

**Options:**
- `--all` - Show all jobs (including completed/failed)
- `<job_id>` - Show details for specific job
- `cancel <job_id>` - Cancel a pending job
- `reset` - Reset stuck "running" jobs to pending
- `resume` - Execute all pending jobs

**Examples:**
- `/jobs` - Show active jobs only
- `/jobs --all` - List all recent jobs
- `/jobs reset` - Unstick jobs after restart
- `/jobs resume` - Re-run pending jobs''',
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

        oldest_date = oldest.data[0]['date'] if oldest.data else 'N/A'
        newest_date = newest.data[0]['date'] if newest.data else 'N/A'

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

            title = event.get('summary', '(no title)')
            location = event.get('location', '')

            output += f"• {event_time} - {title}"
            if location:
                output += f" 📍 {location}"
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

Run `/agent task process` to recreate all tasks."""

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

        # Check newest email date BEFORE starting analysis
        if refresh:
            try:
                result = storage.client.table('emails').select('date').eq('owner_id', owner_id).order('date', desc=True).limit(1).execute()
                if result.data:
                    newest_email_str = result.data[0].get('date')
                    if newest_email_str:
                        newest_email_dt = datetime.fromisoformat(newest_email_str.replace('Z', '+00:00'))
                        hours_ago = (datetime.now(timezone.utc) - newest_email_dt).total_seconds() / 3600
                        if hours_ago > 6:
                            return f"""⚠️ **Stale Data Warning**

Newest email is **{hours_ago:.1f} hours old**.

Run `/sync` first to get fresh emails, then `/tasks refresh`."""
            except Exception as e:
                logger.warning(f"Could not check newest email date: {e}")

        # Create worker and get tasks
        worker = TaskWorker(storage, owner_id, api_key, llm_provider, user_email)
        tasks, _ = await worker.get_tasks(refresh=refresh)

        if not tasks:
            if refresh:
                return """**✅ Tasks**

🎉 No action needed! You're all caught up.

Analyzed recent emails and calendar - nothing requires your attention.

_Run `/agent task process` to detect new tasks from recent emails._"""
            else:
                return """**✅ Tasks**

🎉 No action needed! You're all caught up.

_Run `/agent task process` to detect new tasks._"""

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
        for blob_id in blob_ids:
            result = storage.client.table('blobs')\
                .select('content')\
                .eq('owner_id', owner_id)\
                .eq('id', blob_id)\
                .limit(1)\
                .execute()
            if result.data:
                contents.append(result.data[0].get('content', ''))

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
                        logger.debug(f"[TASK_DETAIL] Using latest email in thread: {latest.get('subject', '(none)')}")
                        email = latest

            if email:
                logger.debug(f"[TASK_DETAIL] Email subject: {email.get('subject', '(none)')}")
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
            attendee_str = ', '.join(attendees) if attendees else 'None listed'

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
    """Handle /jobs command - list background jobs."""
    from zylch.storage.supabase_client import SupabaseStorage

    help_text = """**📋 Background Jobs**

**Usage:** `/jobs [<job_id>|cancel <job_id>|stop <job_id>|reset|resume|--all]`

Shows your running/pending background jobs.

**Options:**
- `--all` - Show all jobs (including completed/failed)
- `<job_id>` - Show details for specific job
- `cancel <job_id>` - Cancel a pending job
- `stop <job_id>` - Stop a running job (sets to pending)
- `stop --all` - Stop all running jobs
- `reset` - Reset stuck "running" jobs to pending
- `resume` - Execute all pending jobs

**Examples:**
- `/jobs` - Show active jobs only
- `/jobs --all` - List all recent jobs
- `/jobs stop <id>` - Stop a running job
- `/jobs cancel <id>` - Cancel a pending job
- `/jobs reset` - Unstick jobs after restart
- `/jobs resume` - Re-run pending jobs"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    # Separate positional args from options
    show_all = '--all' in args
    positional = [a for a in args if not a.startswith('--')]
    subcommand = positional[0].lower() if positional else None

    try:
        storage = SupabaseStorage.get_instance()

        # Subcommand: cancel
        if subcommand == 'cancel':
            job_id = positional[1] if len(positional) > 1 else None
            if not job_id:
                return "❌ Missing job ID. Usage: `/jobs cancel <id>`"
            success = storage.cancel_background_job(job_id, owner_id)
            if success:
                return f"✅ **Job cancelled:** `{job_id}`"
            return "❌ **Cannot cancel:** Job not found or not pending"

        # Subcommand: stop (stop running job → pending)
        if subcommand == 'stop':
            arg = positional[1] if len(positional) > 1 else None
            if arg == '--all' or '--all' in args:
                count = storage.stop_all_running_jobs(owner_id)
                if count > 0:
                    return f"✅ **Stopped {count} running job(s)** (now pending)\n\nUse `/jobs cancel <id>` to remove."
                return "📭 No running jobs to stop."
            elif arg:
                success = storage.stop_background_job(arg, owner_id)
                if success:
                    return f"✅ **Job stopped:** `{arg}` (now pending)\n\nUse `/jobs cancel {arg}` to remove."
                return "❌ **Cannot stop:** Job not found or not running"
            else:
                return "❌ Missing job ID. Usage: `/jobs stop <id>` or `/jobs stop --all`"

        # Subcommand: reset (force reset running jobs to pending)
        if subcommand == 'reset':
            reset_count = storage.reset_all_running_jobs()
            if reset_count:
                return f"✅ **Reset {reset_count} running jobs** to pending status.\n\nUse `/jobs resume` to re-execute them."
            return "📭 No running jobs to reset."

        # Subcommand: resume (execute pending jobs)
        if subcommand == 'resume':
            import asyncio
            from zylch.services.job_executor import JobExecutor
            from zylch.api.token_storage import get_active_llm_provider, get_email

            # Get pending jobs for this user
            pending_jobs = storage.get_user_background_jobs(owner_id, status='pending', limit=10)

            if not pending_jobs:
                return "📭 No pending jobs to resume."

            # Get LLM credentials
            llm_provider, api_key = get_active_llm_provider(owner_id)
            user_email = get_email(owner_id) or ""

            if not api_key:
                return "❌ No LLM provider configured. Run `/connect anthropic` first."

            # Execute each pending job
            executor = JobExecutor(storage)
            resumed_count = 0

            for job in pending_jobs:
                asyncio.create_task(executor.execute_job(
                    job['id'],
                    owner_id,
                    api_key,
                    llm_provider,
                    user_email
                ))
                resumed_count += 1

            return f"🚀 **Resumed {resumed_count} pending jobs**\n\nUse `/jobs` to monitor progress."

        # Subcommand: specific job by ID
        if subcommand:
            job = storage.get_background_job(subcommand, owner_id)
            if not job:
                return f"❌ Job `{subcommand}` not found"
            return _format_job_detail(job)

        # List jobs - default shows only active (pending/running), --all shows everything
        status_filter = None if show_all else ["pending", "running"]
        jobs = storage.get_user_background_jobs(owner_id, status=status_filter, limit=10)

        if not jobs:
            if show_all:
                return """**📋 Background Jobs**

📭 No background jobs found.

Background jobs are created when you run:
- `/sync` - Email/calendar sync
- `/agent memory process` - Memory processing
- `/agent task process` - Task detection"""
            else:
                return """**📋 Background Jobs**

📭 No active jobs running.

Use `/jobs --all` to see completed jobs."""

        label = "all" if show_all else "active"
        output = f"**📋 Background Jobs** ({len(jobs)} {label})\n\n"

        for job in jobs:
            job_id = job['id']  # Full UUID - never truncate!
            job_type = job['job_type']
            status = job['status']
            progress = job.get('progress_pct', 0)

            emoji = {'pending': '⏳', 'running': '🔄', 'completed': '✅', 'failed': '❌', 'cancelled': '🚫'}.get(status, '📋')

            output += f"{emoji} **{job_type}** (`{job_id}`)\n"
            output += f"   Status: {status}"
            if status == 'running':
                output += f" ({progress}%)"
            output += "\n"
            if job.get('status_message'):
                output += f"   {job['status_message']}\n"
            output += "\n"

        output += "_Use `/jobs <id>` for details, `/jobs cancel <id>` to cancel._"
        return output

    except Exception as e:
        logger.error(f"Error in /jobs: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


def _format_job_detail(job: dict) -> str:
    """Format detailed job info."""
    return f"""**📋 Job Details**

**ID:** `{job['id']}`
**Type:** {job['job_type']}
**Channel:** {job.get('channel', 'all')}
**Status:** {job['status']}
**Progress:** {job.get('progress_pct', 0)}%

**Timing:**
- Created: {job['created_at']}
- Started: {job.get('started_at', 'N/A')}
- Completed: {job.get('completed_at', 'N/A')}

**Message:** {job.get('status_message', 'N/A')}
**Error:** {job.get('last_error', 'None')}"""


async def handle_agent(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /agent command - manage personalized agents for memory and task processing.

    Command structure:
        /agent <domain> <action> [channel]

    Domains: memory, task, email, mrcall
    Actions: train, run, show, reset
    Channels: email (includes calendar automatically), all
    """
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.api.token_storage import get_email

    help_text = """**🤖 Manage AI Agents**

**Memory Agents** (extract facts into memory blobs):
• `/agent memory train email` - Create extraction agent
• `/agent memory run email` - Process emails + calendar into memory
• `/agent memory show email` - Show current agent
• `/agent memory reset email` - Delete agent

**Task Agents** (detect actionable items):
• `/agent task train email` - Create task detection agent (calendar-aware)
• `/agent task process email` - Analyze emails + calendar with context
• `/agent task show email` - Show current agent prompt
• `/agent task reset email` - Delete agent prompt (keeps task items)

**Email Agent** (multi-tool email assistant):
• `/agent email train` - Learn your writing style from sent emails
• `/agent email run "instructions"` - Execute email agent (compose, search, answer)
• `/agent email show` - Show current agent prompt
• `/agent email reset` - Delete agent prompt

**MrCall Agent** (multi-tool MrCall configuration):
• `/agent mrcall train` - Train all features and build unified agent
• `/agent mrcall train <feature>` - Train specific feature (e.g., booking)
• `/agent mrcall run "instructions"` - Configure MrCall (auto-detects feature)
• `/agent mrcall show` - Show current agent prompt
• `/agent mrcall reset` - Delete agent prompt

**Note:** The `email` channel automatically includes calendar events.

**Workflow:**
1. `/sync` - Fetch emails + calendar (calendar syncs 2 weeks ahead)
2. `/agent memory train email` - Create memory agent
3. `/agent memory run email` - Extract facts from emails + calendar
4. `/agent task train email` - Create task agent (calendar-aware)
5. `/agent task process email` - Detect tasks (considers scheduled meetings)
6. `/agent email train` - Learn your writing style
7. `/agent email run "write to Mario about the offer"` - Use email agent"""

    # --help option (check first)
    if '--help' in args:
        return help_text

    if len(args) < 2:
        return help_text

    try:
        storage = SupabaseStorage.get_instance()

        domain = args[0].lower()  # 'memory', 'task', 'email', 'mrcall'
        action = args[1].lower()  # 'train', 'run', 'show', 'reset'

        valid_domains = ['memory', 'task', 'email', 'mrcall']
        valid_actions = ['train', 'run', 'process', 'show', 'reset']  # 'process' kept for backwards compat
        valid_channels = ['email', 'all']

        if domain not in valid_domains:
            return f"❌ Unknown domain: `{domain}`\n\nValid domains: `memory`, `task`, `email`, `mrcall`\n\n{help_text}"

        # Normalize 'process' to 'run' for backwards compatibility
        if action == 'process':
            action = 'run'

        if action not in valid_actions:
            return f"❌ Unknown action: `{action}`\n\nValid actions: `train`, `run`, `show`, `reset`"

        # For email/mrcall: args[2:] are instructions (for run) or feature (for train), not channel
        # For memory/task: args[2] is channel
        if domain in ['email', 'mrcall']:
            channel = None  # Not used for email/mrcall
        else:
            channel = args[2].lower() if len(args) > 2 else 'email'
            # Calendar channel is now included automatically with email
            if channel == 'calendar':
                return (
                    "ℹ️ Calendar events are now processed automatically with emails.\n\n"
                    f"Use `/agent {domain} {action} email` instead."
                )
            if channel not in valid_channels:
                return f"❌ Unknown channel: `{channel}`\n\nValid channels: `email`, `all`"

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

            elif action == 'run':
                return await _handle_memory_run(storage, owner_id, channel, api_key, llm_provider)

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

            elif action == 'run':
                return await _handle_task_run(storage, owner_id, channel, api_key, llm_provider, user_email)

            elif action == 'show':
                return await _handle_agent_show(storage, owner_id, domain, channel)

            elif action == 'reset':
                return await _handle_task_reset(storage, owner_id, channel)

        # =====================
        # EMAIL DOMAIN (Multi-tool Agent)
        # =====================
        elif domain == 'email':
            if action == 'train':
                return await _handle_emailer_train(storage, owner_id, api_key, llm_provider, user_email)

            elif action == 'run':
                instructions = ' '.join(args[2:]) if len(args) > 2 else ''
                return await _handle_emailer_run(storage, owner_id, api_key, llm_provider, instructions)

            elif action == 'show':
                return await _handle_emailer_show(storage, owner_id)

            elif action == 'reset':
                return await _handle_emailer_reset(storage, owner_id)

        # =====================
        # MRCALL DOMAIN (Unified MrCall Agent)
        # =====================
        elif domain == 'mrcall':
            if action == 'train':
                # Optional feature argument: /agent mrcall train [feature]
                feature = args[2] if len(args) > 2 else None
                return await _handle_mrcall_agent_train(storage, owner_id, api_key, llm_provider, user_email, feature=feature)

            elif action == 'run':
                instructions = ' '.join(args[2:]) if len(args) > 2 else ''
                return await _handle_mrcall_agent_run(storage, owner_id, api_key, llm_provider, instructions)

            elif action == 'show':
                return await _handle_mrcall_agent_show(storage, owner_id)

            elif action == 'reset':
                return await _handle_mrcall_agent_reset(storage, owner_id)

        return help_text

    except Exception as e:
        logger.error(f"Error in /agent: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


# =====================
# MEMORY AGENT HELPERS
# =====================

async def _handle_memory_train(storage, owner_id: str, channel: str, api_key: str, llm_provider: str, user_email: str) -> str:
    """Train memory extraction agent for specified channel."""
    from zylch.agents.memory_agent_email_trainer import EmailMemoryAgentTrainer

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    if not user_email:
        return """❌ **User email not found**

Your email address is required to identify sent vs received emails.
Please ensure your account is properly connected via `/connect`."""

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
            results.append(f"📧 **Email:** Agent created ({metadata.get('threads_analyzed', 0)} threads analyzed)")

        elif ch == 'calendar':
            # Calendar memory training - placeholder for future implementation
            results.append(f"📅 **Calendar:** Not yet implemented")

    return f"""✅ **Memory Agent Training Complete**

{chr(10).join(results)}

**Next steps:**
- `/agent memory show {channel}` to review
- `/agent memory process {channel}` to extract facts"""


async def _handle_memory_run(storage, owner_id: str, channel: str, api_key: str, llm_provider: str) -> str:
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
    """Train task detection agent for specified channel (background job).

    Creates a background job that runs in a thread pool, returning immediately.
    The user is notified via user_notifications when the job completes.
    """
    import asyncio
    from zylch.services.job_executor import JobExecutor

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    if not user_email:
        return """❌ **User email not found**

Your email address is required to identify sent vs received emails.
Please ensure your account is properly connected via `/connect`."""

    # Check if there's data to train on
    emails = storage.get_emails(owner_id, limit=1)
    if not emails:
        return """❌ **No emails found**

Run `/sync` to synchronize your emails first.
Then run this command again."""

    # Create background job (returns existing if duplicate pending/running)
    job = storage.create_background_job(
        owner_id=owner_id,
        job_type="task_train",
        channel=channel
    )

    if job["status"] == "running":
        pct = job.get("progress_pct", 0)
        msg = job.get("status_message", "Training in progress...")
        return f"""⏳ **Task agent training already in progress**

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

        return f"""🚀 **Task agent training started**

Training on {channel} data in the background.
You'll receive a notification when complete.

Job ID: `{job['id']}`

**Note:** You can continue working while this runs."""

    # Job exists but completed/failed - should create new one
    return f"Previous job status: {job['status']}. Run the command again to start a new job."


async def _handle_task_run(storage, owner_id: str, channel: str, api_key: str, llm_provider: str, user_email: str) -> str:
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


async def _handle_task_reset(storage, owner_id: str, channel: str) -> str:
    """Delete task agent prompt for specified channel."""
    agent_type = f"task_{channel}"

    deleted = storage.delete_agent_prompt(owner_id, agent_type)
    if deleted:
        return f"""✅ **Task agent deleted**

Your `task {channel}` agent has been deleted.

Recreate with: `/agent task train {channel}`

💡 To reset the actual task items, run `/tasks reset`"""
    else:
        return f"❌ No agent found for `task {channel}`"


# =====================
# EMAILER AGENT HELPERS
# =====================

async def _handle_emailer_train(storage, owner_id: str, api_key: str, llm_provider: str, user_email: str) -> str:
    """Train emailer agent to learn user's writing style."""
    from zylch.agents.emailer_agent_trainer import EmailerAgentTrainer

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    if not user_email:
        return """❌ **User email not found**

Your email address is required to identify your sent emails.
Please ensure your account is properly connected via `/connect`."""

    # Check if there's data to train on
    emails = storage.get_emails(owner_id, limit=1)
    if not emails:
        return """❌ **No emails found**

Run `/sync` to synchronize your emails first.
Then run this command again."""

    try:
        trainer = EmailerAgentTrainer(storage, owner_id, api_key, user_email, llm_provider)
        agent_prompt, metadata = await trainer.build_emailer_prompt()
        storage.store_agent_prompt(owner_id, 'emailer', agent_prompt, metadata)

        return f"""✅ **Emailer Agent Trained**

Analyzed **{metadata.get('sent_emails_analyzed', 0)}** sent emails
Domain: `{metadata.get('user_domain', 'unknown')}`

Your emailer agent now writes emails in your personal style.

**Usage:**
- Ask me to write emails (e.g., "scrivi a Mario un'offerta")
- Use the `compose_email` tool
- Reply to tasks with `/tasks` → select task → "rispondi"

**Tip:** Re-run `/agent email train` periodically to update your style."""

    except ValueError as e:
        return f"❌ **Training failed:** {str(e)}"
    except Exception as e:
        logger.error(f"Emailer training error: {e}", exc_info=True)
        return f"❌ **Training failed:** {str(e)}"


async def _handle_emailer_show(storage, owner_id: str) -> str:
    """Show emailer agent prompt."""
    agent_prompt = storage.get_agent_prompt(owner_id, 'emailer')
    if not agent_prompt:
        return """❌ **No emailer agent found**

Train your emailer agent to learn your writing style:
`/agent email train`"""

    meta = storage.get_agent_prompt_metadata(owner_id, 'emailer')
    meta_info = ""
    if meta:
        metadata = meta.get('metadata', {})
        created = meta.get('created_at', '') if meta.get('created_at') else 'unknown'
        sent_analyzed = metadata.get('sent_emails_analyzed', 'unknown')
        user_domain = metadata.get('user_domain', 'unknown')
        meta_info = f"""
_Created: {created}_
_Emails analyzed: {sent_analyzed}_
_Domain: {user_domain}_
"""

    display_prompt = agent_prompt

    return f"""**✍️ Your Emailer Agent**
{meta_info}
---
{display_prompt}
---

_Use `/agent email reset` to delete and retrain._"""


async def _handle_emailer_reset(storage, owner_id: str) -> str:
    """Delete emailer agent prompt."""
    deleted = storage.delete_agent_prompt(owner_id, 'emailer')
    if deleted:
        return """✅ **Emailer agent deleted**

Your emailer agent has been deleted.
Emails will be composed with generic style.

Retrain with: `/agent email train`"""
    else:
        return "❌ No emailer agent found"


async def _handle_emailer_run(storage, owner_id: str, api_key: str, llm_provider: str, instructions: str) -> str:
    """Execute the email agent with given instructions.

    This is the multi-tool email agent that can:
    - Compose emails (write_email)
    - Search memory (search_memory)
    - Fetch emails (get_email)
    - Answer questions (respond_text)

    The agent decides which tool to use based on the instructions.
    """
    from zylch.agents.emailer_agent import EmailerAgent

    if not instructions.strip():
        return """❌ **Missing instructions**

Usage: `/agent email run "your instructions"`

Examples:
• `/agent email run "scrivi a Mario un'offerta"`
• `/agent email run "What can I answer to this guy?"`
• `/agent email run "cerca info su Acme Corp"`"""

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    try:
        # Initialize the email agent
        agent = EmailerAgent(
            storage=storage,
            owner_id=owner_id,
            api_key=api_key,
            provider=llm_provider
        )

        # Run the agent
        result = await agent.run(instructions=instructions)

        tool_used = result.get('tool_used')
        tool_result = result.get('result', {})

        # Format response based on tool used
        if tool_used == 'write_email':
            subject = tool_result.get('subject', '(no subject)')
            body = tool_result.get('body', '')
            recipient = tool_result.get('recipient_email', '(not specified)')

            # Auto-save draft
            to_addresses = [recipient] if recipient and recipient != '(not specified)' else []
            draft = storage.create_draft(
                owner_id=owner_id,
                to=to_addresses,
                subject=subject,
                body=body,
                in_reply_to=tool_result.get('in_reply_to'),
                references=tool_result.get('references'),
                thread_id=tool_result.get('thread_id'),
            )
            draft_id = draft.get('id', '') if draft else ''

            return f"""**📝 Draft Created** (ID: `{draft_id}`)

**To:** {recipient}
**Subject:** {subject}

{body}

---
Say "send it" or use `/email send {draft_id}` to send."""

        elif tool_used == 'search_memory':
            results = tool_result.get('results', [])
            message = tool_result.get('message', '')
            if not results:
                return f"🔍 {message}\n\nNo results found."

            formatted = []
            for r in results:
                content = r.get('content', '')
                formatted.append(f"```\n{content}\n```")

            return f"""🔍 **{message}**

{chr(10).join(formatted)}"""

        elif tool_used == 'get_email':
            if 'error' in tool_result:
                return f"❌ {tool_result['error']}"

            return f"""📧 **Email Retrieved**

**From:** {tool_result.get('from_email', 'unknown')}
**Subject:** {tool_result.get('subject', '(no subject)')}
**Date:** {tool_result.get('date', 'unknown')}

{tool_result.get('body', '')}"""

        elif tool_used == 'respond_text':
            response = tool_result.get('response', '')
            return f"""💬 **Response**

{response}"""

        else:
            return f"⚠️ Agent returned unexpected result: {result}"

    except Exception as e:
        logger.error(f"Emailer run error: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


# =====================
# MRCALL AGENT HELPERS
# =====================

async def _handle_mrcall_agent_train(storage, owner_id: str, api_key: str, llm_provider: str, user_email: str, feature: str = None) -> str:
    """Train MrCall features and build unified agent.

    Args:
        feature: Optional specific feature to train. If None, trains all features.
    """
    import asyncio
    from zylch.agents.mrcall_agent_trainer import MrCallAgentTrainer
    from zylch.agents.mrcall_configurator_trainer import MrCallConfiguratorTrainer
    from zylch.tools.starchat import create_starchat_client

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    # Check MrCall is linked
    business_id = storage.get_mrcall_link(owner_id)
    if not business_id:
        return """❌ **No MrCall assistant linked**

Link your assistant first:
1. `/mrcall list` - See your assistants
2. `/mrcall link <business_id>` - Link to assistant by ID"""

    # Validate feature if specified
    if feature and feature not in MrCallConfiguratorTrainer.FEATURES:
        available = list(MrCallConfiguratorTrainer.FEATURES.keys())
        return f"""❌ **Unknown feature:** `{feature}`

Available features: {', '.join(available)}

Usage:
• `/agent mrcall train` - Train all features
• `/agent mrcall train {available[0]}` - Train specific feature"""

    try:
        # Create StarChat client
        starchat = await create_starchat_client(owner_id)

        # Train feature(s) using MrCallConfiguratorTrainer
        configurator = MrCallConfiguratorTrainer(
            storage=storage,
            starchat_client=starchat,
            owner_id=owner_id,
            api_key=api_key,
            provider=llm_provider,
        )

        trained_features = []
        if feature:
            # Train specific feature
            await configurator.train_feature(feature, business_id)
            trained_features.append(feature)
        else:
            # Train all features
            for feat_name in MrCallConfiguratorTrainer.FEATURES.keys():
                await configurator.train_feature(feat_name, business_id)
                trained_features.append(feat_name)

        # Build unified agent prompt (combines all feature sub-prompts)
        agent_trainer = MrCallAgentTrainer(
            storage=storage,
            owner_id=owner_id,
            api_key=api_key,
            user_email=user_email or '',
            provider=llm_provider,
            starchat_client=starchat,
        )

        prompt, metadata = await agent_trainer.build_prompt(business_id)

        # Store unified agent prompt
        storage.store_agent_prompt(
            owner_id,
            f"mrcall_{business_id}",
            prompt,
            metadata
        )

        features_included = metadata.get('features_included', trained_features)

        if feature:
            return f"""✅ **Feature '{feature}' Trained**

Agent updated with new '{feature}' configuration knowledge.

**All features:** {', '.join(features_included)}

**Usage:**
`/agent mrcall run "your instructions here"`"""
        else:
            return f"""✅ **MrCall Agent Trained**

Your unified MrCall configuration agent is ready!

**Features trained:** {', '.join(features_included)}

**Usage:**
`/agent mrcall run "enable booking with 30-min appointments"`
`/agent mrcall run "change the welcome message"`
`/agent mrcall run "what are my current settings?"`"""

    except ValueError as e:
        return f"❌ **Error:** {str(e)}"
    except Exception as e:
        logger.error(f"MrCall agent train error: {e}", exc_info=True)
        error_str = str(e).lower()
        if '405' in error_str or '401' in error_str or '403' in error_str or 'unauthorized' in error_str:
            return """❌ **MrCall authentication error**

Please connect your MrCall account:
`/connect mrcall`"""
        return f"❌ **Error:** {str(e)}"


async def _handle_mrcall_agent_run(storage, owner_id: str, api_key: str, llm_provider: str, instructions: str) -> str:
    """Execute the MrCall agent with given instructions."""
    import asyncio
    from zylch.agents.mrcall_agent import MrCallAgent
    from zylch.tools.starchat import create_starchat_client

    if not instructions.strip():
        return """❌ **Missing instructions**

Usage: `/agent mrcall run "your instructions"`

Examples:
• `/agent mrcall run "enable booking"`
• `/agent mrcall run "set 30-minute appointments"`
• `/agent mrcall run "change the welcome message"`
• `/agent mrcall run "what are my current settings?"`"""

    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
`/connect anthropic` or `/connect openai` or `/connect mistral`"""

    try:
        # Create StarChat client
        starchat = await create_starchat_client(owner_id)

        # Initialize the MrCall agent
        agent = MrCallAgent(
            storage=storage,
            owner_id=owner_id,
            api_key=api_key,
            provider=llm_provider,
            starchat_client=starchat,
        )

        # Run the agent
        result = await agent.run(instructions=instructions)

        # Check for errors
        if result.get('error'):
            return f"❌ {result['error']}"

        tool_used = result.get('tool_used')
        tool_result = result.get('result', {})

        # Format response based on tool used
        if tool_used in ('configure_welcome_message', 'configure_booking'):
            if tool_result.get('success'):
                updated = tool_result.get('updated', [])
                feature = tool_result.get('feature', 'unknown')
                return f"""✅ **{feature.replace('_', ' ').title()} Updated**

**Changes applied:**
{chr(10).join(f'• {u}' for u in updated)}"""
            else:
                errors = tool_result.get('errors', ['Unknown error'])
                return f"""❌ **Configuration Failed**

{chr(10).join(f'• {e}' for e in errors)}"""

        elif tool_used == 'get_current_config':
            if 'error' in tool_result:
                return f"❌ {tool_result['error']}"

            config = tool_result.get('config', {})
            feature = tool_result.get('feature')

            if feature:
                # Single feature
                lines = [f"**{feature.replace('_', ' ').title()} Configuration:**", ""]
                for var, val in config.items():
                    # Truncate long values
                    display_val = str(val)[:100] + '...' if len(str(val)) > 100 else str(val)
                    lines.append(f"• `{var}` = `{display_val}`")
                return chr(10).join(lines)
            else:
                # All features
                lines = ["**Current Configuration:**", ""]
                for feat_name, feat_config in config.items():
                    lines.append(f"### {feat_name.replace('_', ' ').title()}")
                    for var, val in feat_config.items():
                        display_val = str(val)[:100] + '...' if len(str(val)) > 100 else str(val)
                        lines.append(f"• `{var}` = `{display_val}`")
                    lines.append("")
                return chr(10).join(lines)

        elif tool_used == 'respond_text':
            response = tool_result.get('response', '')
            return f"""💬 **Response**

{response}"""

        else:
            return f"⚠️ Agent returned unexpected result: {result}"

    except Exception as e:
        logger.error(f"MrCall agent run error: {e}", exc_info=True)
        error_str = str(e).lower()
        if '405' in error_str or '401' in error_str or '403' in error_str or 'unauthorized' in error_str:
            return """❌ **MrCall authentication error**

Please connect your MrCall account:
`/connect mrcall`"""
        return f"❌ **Error:** {str(e)}"


async def _handle_mrcall_agent_show(storage, owner_id: str) -> str:
    """Show MrCall agent prompt."""
    business_id = storage.get_mrcall_link(owner_id)
    if not business_id:
        return """❌ **No MrCall assistant linked**

Link your assistant first:
1. `/mrcall list` - See your assistants
2. `/mrcall link <business_id>` - Link to assistant by ID"""

    agent_prompt = storage.get_agent_prompt(owner_id, f"mrcall_{business_id}")
    if not agent_prompt:
        return """❌ **No MrCall agent found**

Train the agent first:
`/agent mrcall train`"""

    meta = storage.get_agent_prompt_metadata(owner_id, f"mrcall_{business_id}")
    meta_info = ""
    if meta:
        metadata = meta.get('metadata', {})
        created = meta.get('created_at', '')[:10] if meta.get('created_at') else 'unknown'
        features = metadata.get('features_included', [])
        meta_info = f"\n_Created: {created} | Features: {', '.join(features)}_\n"

    return f"""**🤖 Your MrCall Agent**
{meta_info}
---
{agent_prompt}
---

_Use `/agent mrcall reset` to delete._"""


async def _handle_mrcall_agent_reset(storage, owner_id: str) -> str:
    """Delete MrCall agent prompt."""
    business_id = storage.get_mrcall_link(owner_id)
    if not business_id:
        return """❌ **No MrCall assistant linked**

Nothing to reset."""

    deleted = storage.delete_agent_prompt(owner_id, f"mrcall_{business_id}")
    if deleted:
        return """✅ **MrCall agent deleted**

Your MrCall agent has been deleted.

Retrain with: `/agent mrcall train`"""
    else:
        return "❌ No MrCall agent found"


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
        created = meta.get('created_at', '') if meta.get('created_at') else 'unknown'
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

Recreate with: `/agent {domain} train {channel}`

💡 To reset the actual memory blobs, run `/memory reset`"""
    else:
        return f"❌ No agent found for `{domain} {channel}`"


async def handle_reset(args: List[str], owner_id: str) -> str:
    """Handle /reset - Reset all user data."""

    help_text = """**🔄 Reset Command**

**Usage:**
• `/reset` - Show warning
• `/reset --hard` - Delete ALL your data (irreversible!)

**What gets deleted:**
- All synced emails and calendar events
- All memory blobs and extracted facts
- All detected tasks and triggers
- All drafts and trained prompts

**What stays:**
- Your account connections (Google, MrCall, LLM keys)"""

    if '--help' in args:
        return help_text

    if '--hard' not in args:
        return """⚠️ **Data Reset Warning**

For security reasons, please run:

```
/reset --hard
```

**This will permanently delete:**
- All synced emails and calendar events
- All memory blobs and facts
- All tasks and triggers
- All drafts and trained prompts

Your account connections (Google, MrCall) will be preserved.

This action **cannot be undone**."""

    # User confirmed with --hard
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    def _reset_all_data():
        from zylch.storage.supabase_client import SupabaseStorage
        storage = SupabaseStorage.get_instance()
        counts = {}
        tables = [
            'entity_memory_sentences',
            'entity_memory_blobs',
            'task_items',
            'triggers',
            'trigger_events',
            'drafts',
            'emails',
            'calendar_events',
            'background_jobs',
            'user_notifications',
            'agent_prompts',
        ]
        for table in tables:
            try:
                result = storage.client.table(table).delete().eq('owner_id', owner_id).execute()
                counts[table] = len(result.data) if result.data else 0
            except Exception as e:
                counts[table] = f"error: {e}"
        return counts

    executor = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_event_loop()
    counts = await loop.run_in_executor(executor, _reset_all_data)

    lines = ["🗑️ **All Data Deleted**\n", "**Deleted:**"]
    for table, count in counts.items():
        if isinstance(count, int) and count > 0:
            lines.append(f"• {table}: {count}")
    lines.append("\n**Preserved:** Account connections (Google, MrCall, LLM keys)")
    lines.append("\n✅ Start fresh with `/sync`")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Tutorial Command
# ─────────────────────────────────────────────────────────────────────────────


async def handle_tutorial(args: List[str], owner_id: str) -> str:
    """Handle /tutorial command - Getting started guide with topic-specific tutorials."""

    if not args:
        # Default: Show general getting started guide
        return _tutorial_getting_started()

    # Check for --dev flag
    dev_mode = '--dev' in args
    args = [a for a in args if a != '--dev']

    topic = args[0].lower() if args else None

    if topic == 'mrcall':
        if dev_mode:
            return _tutorial_mrcall_dev()
        return _tutorial_mrcall_user()

    return f"Unknown tutorial topic: `{topic}`\n\nRun `/tutorial` to see available topics."


def _tutorial_getting_started() -> str:
    """General getting started guide for new Zylch users."""
    return """# 🚀 Getting Started with Zylch

## Setup Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    ZYLCH SETUP                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1️⃣  CONNECT LLM (Required)                                │
│      /connect anthropic YOUR_API_KEY                        │
│      OR /connect openai YOUR_API_KEY                        │
│                                                             │
│  2️⃣  CONNECT EMAIL & CALENDAR                              │
│      /connect google                                        │
│      (Opens browser for OAuth)                              │
│                                                             │
│  3️⃣  SYNC YOUR DATA                                        │
│      /sync --days 30                                        │
│      (Fetches emails + calendar, calendar +14 days future)  │
│                                                             │
│  4️⃣  TRAIN YOUR AGENTS                                     │
│      /agent memory train email    (learns your style)       │
│      /agent task train email      (learns your priorities)  │
│                                                             │
│  5️⃣  PROCESS YOUR DATA (email auto-includes calendar)      │
│      /agent memory run email      (extracts facts)          │
│      /agent task process email    (detects tasks)           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Daily Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    DAILY ROUTINE                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Morning:                                                   │
│    /sync                    → Get new emails & events       │
│    /agent memory run email  → Update memory (emails+cal)    │
│    /agent task process email→ Detect tasks (emails+cal)     │
│                                                             │
│  Check:                                                     │
│    /tasks                   → See what needs attention      │
│    /calendar                → Today's meetings              │
│    /memory search <name>    → Recall contact info           │
│                                                             │
│  Work:                                                      │
│    "Draft reply to John"    → AI drafts email               │
│    "Who is Maria?"          → Search memory                 │
│    "Summarize today"        → AI summary                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Optional Integrations

| Integration | Command | Purpose |
|-------------|---------|---------|
| MrCall | `/connect mrcall` | Phone call handling |
| Pipedrive | `/connect pipedrive KEY` | CRM sync |

## Quick Tips

• **Natural language works!** Try "show my tasks" instead of `/tasks`
• All commands support `--help` for details
• Run `/stats` to see your data overview
• Use `/reset --hard` to start completely fresh

**More tutorials:** `/tutorial mrcall` for phone assistant setup

**Next:** Run `/connect anthropic YOUR_KEY` to begin!"""


def _tutorial_mrcall_user() -> str:
    """Tutorial for new MrCall users."""
    return """**MrCall Tutorial - User Guide**

MrCall lets you configure your AI phone assistant through natural language.

---

## Step 1: Connect

```
/connect mrcall
```
Opens OAuth login to StarChat. Grant `business:write` permission.

---

## Step 2: List Your Assistants

```
/mrcall list
```
Shows all MrCall assistants linked to your account.

---

## Step 3: Link an Assistant

```
/mrcall link <business_id>
```
Copy the business ID from `/mrcall list` and paste it here.

---

## Step 4: Train the Agent

```
/agent mrcall train
```
Trains the AI agent on your current configuration.
The agent learns your settings and can help you modify them.

---

## Step 5: Use the Agent

Ask natural language questions:

```
/agent mrcall run "enable booking with 30-min appointments"
/agent mrcall run "is booking enabled?"
/agent mrcall run "make the greeting more casual"
```

---

## Other Useful Commands

| Command | Description |
|---------|-------------|
| `/mrcall status` | Check connection status |
| `/mrcall variables` | List all configuration variables |
| `/mrcall unlink` | Disconnect from assistant |
| `/agent mrcall show` | Show agent's current prompt |
| `/agent mrcall reset` | Delete agent (must retrain) |

---

**Tip:** The agent understands context! You can ask things like:
- "how does the assistant greet callers?"
- "what are my current settings?"
- "disable all booking features"
"""


def _tutorial_mrcall_dev() -> str:
    """Tutorial for developers adding MrCall features."""
    return """**MrCall Developer Guide**

How to add new configurable features to MrCall.

---

## Architecture Overview

MrCall uses a **two-tier training architecture**:

```
Layer 1: MrCallConfiguratorTrainer
    | Generates feature sub-prompts from current config
    v
Layer 2: MrCallAgentTrainer
    | Combines sub-prompts into unified agent
    v
MrCallAgent
    | Runs with 4 tools, auto-selects based on intent
    v
StarChat API (updates variables)
```

---

## Single Source of Truth

**CRITICAL:** All feature/variable mappings are defined in ONE place:

```python
# zylch/agents/mrcall_configurator_trainer.py
MrCallConfiguratorTrainer.FEATURES
```

Other files DERIVE from this automatically. Never manually edit mappings elsewhere.

---

## Adding a New Feature

### 1. Define Meta-Prompt

In `zylch/agents/mrcall_configurator_trainer.py`:

```python
MY_FEATURE_META_PROMPT = '''You are analyzing the X configuration...

## VARIABLES CONTEXT:
{variables_context}

OUTPUT ONLY THE SUB-PROMPT TEXT.'''
```

### 2. Add to FEATURES Dict

```python
FEATURES = {
    # ... existing features ...
    "my_feature": {
        "variables": ["VAR1", "VAR2", "VAR3"],
        "description": "What this feature controls",
        "display_name": "User-facing name",
        "meta_prompt": MY_FEATURE_META_PROMPT,
        "dynamic_context": True,  # if multiple variables
    },
}
```

### 3. Add Tool to Agent

In `zylch/agents/mrcall_agent.py`:

```python
MRCALL_AGENT_TOOLS = [
    # ... existing tools ...
    {
        "name": "configure_my_feature",
        "description": "Modify my_feature settings...",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "object",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["changes"]
        }
    },
]
```

### 4. Add Handler

In `MrCallAgent._handle_tool_response()`:

```python
elif block.name == 'configure_my_feature':
    result['result'] = await self._process_configure(
        block.input, 'my_feature'
    )
```

### 5. Update Help Text

In `command_handlers.py`, update the features list in help text.

---

## Testing

```bash
/agent mrcall train my_feature    # Train just the new feature
/agent mrcall train               # Retrain all + rebuild unified agent
/agent mrcall run "modify my_feature settings"
```

---

## Key Files

| File | Purpose |
|------|---------|
| `mrcall_configurator_trainer.py` | FEATURES dict (source of truth) + meta-prompts |
| `mrcall_agent_trainer.py` | Combines sub-prompts into unified agent |
| `mrcall_agent.py` | Tools + handlers for running agent |
| `command_handlers.py` | CLI command routing |

---

**Full guide:** See skill `zylch-mrcall-feature-configuration`
"""


# Export all handlers
COMMAND_HANDLERS = {
    '/echo': handle_echo,
    '/help': handle_help,
    '/tutorial': handle_tutorial,
    '/sync': handle_sync,
    '/memory': handle_memory,
    '/email': handle_email,
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
    '/reset': handle_reset,
    '/tutorial': handle_tutorial,
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

    # --- Reset (Full data reset) ---
    '/reset': [
        "reset",
        "reset all data",
        "delete all my data",
        "start fresh",
        "clear everything",
        "wipe my account",
        "delete everything",
        "reset my account",
    ],

    # --- Tutorial (Onboarding + MrCall) ---
    '/tutorial': [
        # Generic onboarding
        "tutorial",
        "getting started",
        "how to use",
        "help me start",
        "onboarding",
        "setup guide",
        "how do I start",
        "new user guide",
        "quick start",
        "first steps",
        # MrCall-specific
        "show tutorial",
        "how to use mrcall",
        "mrcall tutorial",
        "mrcall guide",
        "how do I set up mrcall",
        "tutorial mrcall",
        "tutorial {topic:text}",
        "guide",
        "help with mrcall",
        "mrcall help",
    ],
}
