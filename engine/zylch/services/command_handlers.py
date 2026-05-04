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
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            # Try parsing common email date formats
            from email.utils import parsedate_to_datetime

            try:
                dt = parsedate_to_datetime(date_str)
            except (ValueError, TypeError):
                # Fallback: just return the date portion
                return date_str.split("T")[0] if "T" in date_str else date_str[:10]

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
    """Format task items as numbered list grouped by urgency.

    Each task shows:
    - Number, contact name, suggested action
    - Full task ID for /tasks open <ID> command
    """
    if not tasks:
        return "No action needed! You're all caught up."

    lines = ["**Tasks Needing Action**\n"]

    # Group by urgency
    high = [t for t in tasks if t.get("urgency") == "high"]
    medium = [t for t in tasks if t.get("urgency") == "medium"]
    low = [t for t in tasks if t.get("urgency") == "low"]

    idx = 1

    def format_task(task):
        nonlocal idx
        name = task.get("contact_name") or task.get("contact_email", "Unknown")
        action = task.get("suggested_action", "").strip()
        reason = task.get("reason", "").strip()
        email_date = task.get("email_date", "")
        task_id = task.get("id", "")  # Full UUID

        # Skip tasks with no action
        if not action:
            return None

        # Format relative date for temporal context
        date_str = format_relative_date(email_date) if email_date else ""

        # Format: Name: Action (date) with ID on next line
        task_line = f"{idx}. **{name}**: {action}"
        if date_str:
            task_line += f" ({date_str})"
        if reason and len(reason) > 10:
            task_line += f"\n   _{reason}_"
        # Always show full ID for /tasks open <ID>
        if task_id:
            task_line += f"\n   `ID: {task_id}`"

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
        lines.append(f"\n**Total: {total} items**")
    else:
        return "No action needed! You're all caught up."

    return "\n".join(lines)


async def handle_echo(args: List[str] = None) -> str:
    """Echo back the provided text."""
    if not args:
        return ""
    return " ".join(args)


async def handle_help() -> str:
    """Return help message."""
    # Check if in sandbox mode - show sandbox-specific help
    from zylch.tools.factory import ToolFactory

    sandbox_mode = ToolFactory._session_state.sandbox_mode if ToolFactory._session_state else None
    if sandbox_mode:
        from zylch.services.sandbox_service import get_sandbox_help

        return get_sandbox_help(sandbox_mode)

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
• `/model` - Show current AI model

**📚 Utility:**
• `/clear` - Clear conversation history
• `/help` - Show this message

**💡 Tip:** Chat naturally! "show my tasks", "email stats", "what's on my calendar"."""


async def handle_sync(args: List[str], config, owner_id: str) -> str:
    """Handle /sync command - now using background job system."""
    from zylch.api.token_storage import get_provider
    from zylch.storage import Storage
    from zylch.services.sync_service import SyncService  # Used for mrcall subcommand

    help_text = """**🔄 Sync**

**Usage:**
• `/sync` - Sync emails and calendar (incremental, process only new)
• `/sync --force` - Sync and reprocess ALL emails (even already processed)
• `/sync status` - Show sync status
• `/sync reset` - Clear all synced data
• `/sync --days N` - Sync last N days
• `/sync --days N --force` - Sync last N days and reprocess all
• `/sync mrcall` - Test MrCall conversation fetch (debug)

**Examples:**
• `/sync` - Quick incremental sync
• `/sync --days 90` - Sync last 90 days
• `/sync --force` - Force reprocess everything
• `/sync --days 90 --force` - Sync 90 days and reprocess all
• `/sync status` - Check last sync time
• `/sync mrcall` - Fetch latest MrCall conversation"""

    # --help option (check first)
    if "--help" in args:
        return help_text

    # Separate positional args from options
    positional = [a for a in args if not a.startswith("--")]
    subcommand = positional[0].lower() if positional else None

    # Subcommand: status
    if subcommand == "status":
        logger.info(f"[/sync] Status check for owner_id={owner_id}")
        try:
            from sqlalchemy import func as sa_func
            from zylch.storage.database import get_session
            from zylch.storage.models import Email, CalendarEvent

            # Count emails
            with get_session() as session:
                email_count = (
                    session.query(sa_func.count(Email.id))
                    .filter(Email.owner_id == owner_id)
                    .scalar()
                    or 0
                )

                # Get newest and oldest email dates
                newest_row = (
                    session.query(Email.date)
                    .filter(Email.owner_id == owner_id)
                    .order_by(Email.date.desc())
                    .limit(1)
                    .one_or_none()
                )
                oldest_row = (
                    session.query(Email.date)
                    .filter(Email.owner_id == owner_id)
                    .order_by(Email.date.asc())
                    .limit(1)
                    .one_or_none()
                )

            if not email_count or email_count == 0:
                newest_display = "Never synced"
                oldest_display = "-"
            else:
                if newest_row:
                    dt = (
                        newest_row[0]
                        if newest_row[0].tzinfo
                        else newest_row[0].replace(tzinfo=timezone.utc)
                    )
                    newest_display = dt.strftime("%Y-%m-%d %H:%M UTC")
                else:
                    newest_display = "Unknown"

                if oldest_row:
                    dt = (
                        oldest_row[0]
                        if oldest_row[0].tzinfo
                        else oldest_row[0].replace(tzinfo=timezone.utc)
                    )
                    oldest_display = dt.strftime("%Y-%m-%d")
                else:
                    oldest_display = "Unknown"

            # Count calendar events
            with get_session() as session:
                event_count = (
                    session.query(sa_func.count(CalendarEvent.id))
                    .filter(CalendarEvent.owner_id == owner_id)
                    .scalar()
                    or 0
                )

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
    if subcommand == "reset":
        logger.info(f"[/sync] Reset flag detected, clearing all sync data for owner_id={owner_id}")
        try:
            from zylch.storage.database import get_session
            from zylch.storage.models import Email, CalendarEvent

            # Clear emails
            with get_session() as session:
                session.query(Email).filter(Email.owner_id == owner_id).delete()
            logger.info("[/sync] Cleared emails")

            # Clear calendar events
            with get_session() as session:
                session.query(CalendarEvent).filter(CalendarEvent.owner_id == owner_id).delete()
            logger.info("[/sync] Cleared calendar_events")

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

    # Subcommand: mrcall - Sync MrCall phone call transcriptions
    if subcommand == "mrcall":
        logger.info(f"[/sync] MrCall sync for owner_id={owner_id}")
        try:
            from zylch.api.token_storage import get_mrcall_credentials

            supabase = Storage()

            # Parse --days option
            days_back = 30
            debug_mode = False
            for i, arg in enumerate(args):
                if arg == "--days" and i + 1 < len(args):
                    try:
                        days_back = int(args[i + 1])
                    except ValueError:
                        return f"❌ **Error:** `{args[i + 1]}` is not a valid number"
                elif arg == "--debug":
                    debug_mode = True

            # Get MrCall OAuth credentials (includes access_token and business_id)
            mrcall_creds = get_mrcall_credentials(owner_id)
            if not mrcall_creds or not mrcall_creds.get("access_token"):
                # Check if there's a simple mrcall link (without OAuth)
                business_id = supabase.get_mrcall_link(owner_id)
                if business_id:
                    return f"""📞 **MrCall Sync**

⚠️ **MrCall linked but no OAuth token**

Your MrCall is linked to business `{business_id}` but OAuth credentials are missing.

**To complete setup:**
1. Run `/connect mrcall` to authenticate with MrCall
2. Then run `/sync mrcall` again"""
                else:
                    return """📞 **MrCall Sync**

⚠️ **MrCall not connected**

**To connect MrCall:**
1. Run `/connect mrcall` to authenticate
2. Run `/mrcall link` to link your assistant"""

            # Create SyncService for MrCall
            sync_service = SyncService(owner_id=owner_id, supabase_storage=supabase)

            # Use explicitly linked business_id, not OAuth-stored one
            business_id = supabase.get_mrcall_link(owner_id)
            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` to see available assistants, then `/mrcall link <ID>` to link one."

            # Run MrCall sync
            result = await sync_service.sync_mrcall(
                days_back=days_back,
                debug=debug_mode,
                firebase_token=mrcall_creds.get("access_token"),
                business_id=business_id,
                realm=mrcall_creds.get("realm"),
            )

            if result.get("skipped"):
                return f"""📞 **MrCall Sync**

⚠️ **Skipped:** {result.get('reason', 'Unknown reason')}

**To link MrCall:**
1. Run `/connect mrcall` to authenticate
2. Run `/mrcall link` to link your assistant"""

            if result.get("success"):
                return f"""📞 **MrCall Sync**

✅ **Synced {result.get('synced', 0)} phone call(s)**

• Business ID: `{result.get('business_id')}`
• Days back: {result.get('days_back')}
• Total available: {result.get('total_available', 'N/A')}
• Skipped: {result.get('skipped', 0)}

**Next steps:**
• `/agent memory train mrcall` - Train memory extraction
• `/agent memory process mrcall` - Extract entities from calls"""
            else:
                return f"""📞 **MrCall Sync**

❌ **Error:** {result.get('error', 'Unknown error')}"""

        except Exception as e:
            logger.error(f"[/sync] MrCall sync failed: {e}", exc_info=True)
            return f"❌ **MrCall sync failed:** {str(e)}"

    # Parse --days and --force options
    days_back = 30
    force = "--force" in args
    for i, arg in enumerate(args):
        if arg == "--days" and i + 1 < len(args):
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

        storage = Storage.get_instance()

        # Create job (returns existing if duplicate pending/running)
        job = storage.create_background_job(
            owner_id=owner_id,
            job_type="sync",
            channel="all",  # sync always does all channels
            params={"days_back": days_back, "force": force},
        )

        logger.info(f"[/sync] Job request: sync/all for user {owner_id} -> {job['status']}")

        if job["status"] == "running":
            return f"""⏳ **Sync already in progress**

Job ID: `{job['id']}`
Progress: {job.get('progress_pct', 0)}%
{job.get('status_message', '')}

Please wait for the current sync to complete."""

        if job["status"] == "pending":
            # Schedule execution in background. Each worker resolves its
            # own LLM transport via `make_llm_client()`.
            executor = JobExecutor(storage)
            asyncio.create_task(executor.execute_job(job["id"], owner_id))

            logger.info(f"[/sync] Scheduled background job {job['id']} (force={force})")

            force_note = (
                "\n**Mode:** Force reprocess" " (all emails will be re-analyzed)" if force else ""
            )

            return f"""🚀 **Sync started in background**

Job ID: `{job['id']}`{force_note}

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
    if "--help" in args:
        return help_text

    if not args:
        return help_text

    from zylch.storage import Storage
    from zylch.storage.database import get_session
    from zylch.memory import (
        BlobStorage,
        HybridSearchEngine,
        EmbeddingEngine,
        MemoryConfig,
        LLMMergeService,
    )

    try:
        # Initialize services
        storage = Storage.get_instance()
        mem_config = MemoryConfig()
        embedding_engine = EmbeddingEngine(mem_config)
        blob_storage = BlobStorage(get_session, embedding_engine)
        search_engine = HybridSearchEngine(get_session, embedding_engine)

        # Initialize LLM merge service (for reconsolidation). Skip if
        # no LLM transport is configured.
        from zylch.llm import try_make_llm_client

        llm_merge = LLMMergeService() if try_make_llm_client() is not None else None

        namespace = f"user:{owner_id}"

        # Normalize args - accept both 'search' and '--search'
        cmd = args[0].lstrip("-") if args else ""

        if cmd == "search":
            # Search memories
            if len(args) < 2:
                return "❌ Missing query\n\nUsage: `/memory search <query>`"

            query = " ".join(args[1:])
            results = search_engine.search(
                owner_id=owner_id, query=query, namespace=namespace, limit=5
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

        elif cmd == "store":
            # Store new memory (with optional auto-reconsolidation)
            # Check for --force flag to skip consolidation
            force_new = "--force" in args
            args_content = [a for a in args[1:] if a != "--force"]

            if not args_content:
                return "❌ Missing content\n\nUsage: `/memory store <content>` or `/memory store --force <content>`"

            content = " ".join(args_content)

            # Skip reconsolidation if --force flag is set
            if force_new:
                # Create new blob (forced)
                result = blob_storage.store_blob(
                    owner_id=owner_id,
                    namespace=namespace,
                    content=content,
                    event_description="Created via /memory store (forced)",
                )
                return f"""✅ **Memory stored (forced new blob)** (ID: {result['id']})

**Content:** {content}

Memory will be searchable via hybrid search."""

            # Get top 3 candidates above threshold (same logic as memory_agent.py)
            existing_blobs = search_engine.find_candidates_for_reconsolidation(
                owner_id=owner_id, content=content, namespace=namespace, limit=3
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
                if "INSERT" in merged_content.upper() and len(merged_content) < 10:
                    logger.debug(f"Skipping blob {existing.blob_id} - entities don't match")
                    continue

                # Successful merge
                upserted_result = blob_storage.update_blob(
                    blob_id=existing.blob_id,
                    owner_id=owner_id,
                    content=merged_content,
                    event_description="Reconsolidated via /memory store",
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
                    event_description="Created via /memory store",
                )
                return f"""✅ **Memory stored** (ID: {result['id']})

**Content:** {content}

Memory will be searchable via hybrid search."""

        elif cmd == "delete":
            # Delete a specific memory blob
            if len(args) < 2:
                return "❌ Missing blob ID\n\nUsage: `/memory delete <blob_id>`"

            blob_id = args[1]

            try:
                deleted = blob_storage.delete_blob(blob_id, owner_id)
                if deleted:
                    return f"✅ **Memory deleted** (ID: `{blob_id}`)"
                else:
                    return f"❌ Blob not found: `{blob_id}`\n\nMake sure you're using the full blob ID from `/memory search`."

            except Exception as e:
                logger.error(f"Failed to delete blob {blob_id}: {e}")
                return f"❌ Failed to delete: {str(e)}"

        elif cmd == "stats":
            # Memory statistics
            stats = blob_storage.get_stats(owner_id)

            output = "**🧠 Memory Statistics**\n\n"
            output += f"**Total Blobs:** {stats['total_blobs']}\n"
            output += f"**Total Sentences:** {stats['total_sentences']}\n"
            output += f"**Avg Sentences/Blob:** {stats['avg_blob_size']}\n"
            output += f"**Namespaces:** {len(stats['namespaces'])}\n"

            if stats["namespaces"]:
                output += "\n**Namespaces:**\n"
                for ns in stats["namespaces"]:
                    output += f"• `{ns}`\n"

            return output

        elif cmd == "list":
            # List recent memories
            limit = 10
            if len(args) > 1:
                try:
                    limit = int(args[1])
                    limit = min(limit, 50)  # Cap at 50
                except ValueError:
                    pass

            # Get recent blobs
            blobs = blob_storage.list_blobs(owner_id, limit=limit)

            if not blobs:
                return "**📭 No memories found**\n\nUse `/memory store <content>` to add memories."

            output = f"**🧠 Recent Memories** ({len(blobs)} shown)\n\n"
            for blob in blobs:
                content_preview = blob["content"]
                blob_id_short = blob["id"]
                output += f"**{blob_id_short}** {content_preview}\n"
                output += f"   _Updated: {blob.get('updated_at', '')}_\n\n"

            return output

        elif cmd == "reset":
            # Delete ALL user memories AND reset processing timestamps
            deleted_count = blob_storage.delete_all_blobs(owner_id)

            # Reset processing timestamps so data can be reprocessed
            reset_counts = storage.reset_memory_processing_timestamps(owner_id)

            return f"""🗑️ **Memory reset complete**

**Deleted:**
• {deleted_count} memory blobs and all associated sentences

**Reset timestamps:**
• {reset_counts.get('emails', 0)} emails marked as unprocessed
• {reset_counts.get('calendar_events', 0)} calendar events marked as unprocessed

Run `/agent process` to rebuild memory from your synced data."""

        else:
            # Unknown subcommand - show error + help
            return f"❌ Unknown subcommand: `{args[0]}`\n\n{help_text}"

    except Exception as e:
        logger.error(f"Error in /memory command: {e}", exc_info=True)
        return f"**❌ Error:** {str(e)}\n\n{help_text}"


async def handle_mrcall(
    args: List[str], owner_id: str, user_email: str = None, context: dict = None
) -> str:
    """Handle /mrcall command - MrCall integration.

    Args:
        args: Command arguments
        owner_id: User's Owner ID
        user_email: User's email (optional)
        context: Request context containing source, firebase_token, etc.
    """
    from zylch.storage import Storage
    from zylch.api.token_storage import get_mrcall_credentials
    import httpx
    from zylch.config import settings

    # Dashboard detection: use firebase_token instead of OAuth
    is_dashboard = context and context.get("source") in ("dashboard", "mrcall_dashboard")
    firebase_token = context.get("firebase_token") if context else None
    logger.debug(
        f"[/mrcall] is_dashboard={is_dashboard}, has_firebase_token={bool(firebase_token)}"
    )

    help_text = """**📞 MrCall Integration**

This desktop is a *consumer* of your MrCall assistants.
Configure them at https://dashboard.mrcall.ai

**Quick Commands:**
• `/mrcall list` - List your MrCall assistants
• `/mrcall link <business_id>` - Link to assistant by ID
• `/mrcall unlink` - Unlink current assistant
• `/mrcall variables [get] [--name NAME]` - List/filter variables
• `/mrcall` - Show current link status

**Setup:**
1. Run `/connect mrcall` to authenticate with MrCall
2. Run `/mrcall list` to see your assistants
3. Run `/mrcall link <business_id>` to connect to an assistant"""

    # --help option (check first)
    if "--help" in args:
        return help_text

    # Separate positional args from options
    positional = [a for a in args if not a.startswith("--")]
    subcommand = positional[0].lower() if positional else None

    try:
        client = Storage()

        # Subcommand: unlink
        if subcommand == "unlink":
            success = client.remove_mrcall_link(owner_id)
            if success:
                return "✅ **MrCall Unlinked**\n\nYour Zylch is no longer connected to a MrCall business."
            else:
                return "❌ **Error:** No MrCall link found to remove."

        # Subcommand: list - List all businesses
        if subcommand == "list":
            # Dashboard: use firebase_token; CLI: use OAuth credentials
            if is_dashboard and firebase_token:
                access_token = firebase_token
                logger.debug("[/mrcall list] Using firebase_token (dashboard)")
            else:
                # Get OAuth credentials (CLI)
                creds = get_mrcall_credentials(owner_id)
                logger.debug(
                    f"handle_mrcall list: creds_keys={list(creds.keys()) if creds else None}"
                )
                if not creds or not creds.get("access_token"):
                    logger.debug(
                        f"handle_mrcall list: access_token missing, creds_keys={list(creds.keys()) if creds else None}, "
                        + ", ".join(
                            (
                                f"{k}={v[:2]}...{v[-2:]}"
                                if isinstance(v, str) and len(v) > 4
                                else f"{k}=<short>"
                            )
                            for k, v in (creds or {}).items()
                            if k in ("access_token", "refresh_token", "client_secret")
                        )
                    )
                    return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first to authenticate."
                access_token = creds.get("access_token")
                logger.debug(
                    f"handle_mrcall list: access_token={access_token[:2]}...{access_token[-2:]} (len={len(access_token)})"
                    if access_token and len(access_token) > 4
                    else "handle_mrcall list: access_token=<short or missing>"
                )

            # Get the linked business (explicit /mrcall link takes priority over OAuth default)
            current_business_id = client.get_mrcall_link(owner_id)
            logger.debug(f"[/mrcall list] current_business_id={current_business_id}")

            # Fetch businesses from StarChat API
            try:
                url = f"{settings.mrcall_base_url.rstrip('/')}/mrcall/v1/{settings.mrcall_realm}/crm/business/search"
                logger.info(f"handle_mrcall list: Fetching from {url}")
                async with httpx.AsyncClient(
                    timeout=30.0, verify=settings.starchat_verify_ssl
                ) as http_client:
                    response = await http_client.post(
                        url,
                        headers={"auth": access_token, "Content-Type": "application/json"},
                        json={"from": 0, "size": 50},
                    )
                    response.raise_for_status()
                    businesses = response.json()
                    logger.debug(
                        f"[/mrcall list] POST {url} -> status={response.status_code}, businesses={len(businesses)}"
                    )
            except Exception as e:
                logger.error(f"Failed to fetch MrCall businesses: {e}")
                return f"❌ **Error fetching businesses:** {str(e)}\n\nTry `/connect mrcall` to refresh your connection."

            if not businesses:
                return "**📞 Your MrCall Assistants**\n\nNo assistants found.\n\nCreate one at https://dashboard.mrcall.ai"

            # Build list output
            output = "**📞 Your MrCall Assistants**\n\n"
            for i, biz in enumerate(businesses, 1):
                biz_id = biz.get("businessId") or biz.get("id")
                nickname = biz.get("nickname") or "Unnamed"
                logger.debug(f"[/mrcall list] business {i}: id={biz_id}, nickname={nickname}")
                company = biz.get("companyName") or ""
                service_number = biz.get("serviceNumber") or ""
                email_address = biz.get("emailAddress") or ""
                user_phone = biz.get("userPhoneNumber") or ""
                template = biz.get("template") or ""
                subscription_status = biz.get("subscriptionStatus") or ""

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
                    display_number = (
                        service_number.split("#")[0] if "#" in service_number else service_number
                    )
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
        if subcommand == "variables":
            logger.debug(f"[/mrcall variables] args={args}")

            # Dashboard: skip OAuth check (use firebase_token)
            if not is_dashboard:
                # CLI: verify OAuth credentials exist
                creds = get_mrcall_credentials(owner_id)
                logger.debug(
                    f"[/mrcall variables] get_mrcall_credentials(owner_id={owner_id}) -> keys={list(creds.keys()) if creds else None}, has_business_id={bool(creds.get('business_id')) if creds else None}"
                )
                if not creds or not creds.get("access_token"):
                    return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first to authenticate."

            # Get linked business ID (explicit /mrcall link takes priority over OAuth default)
            business_id = client.get_mrcall_link(owner_id)
            logger.debug(
                f"[/mrcall variables] get_mrcall_link(owner_id={owner_id}) -> business_id={business_id}"
            )

            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` to see available assistants, then `/mrcall link <ID>` to link one."

            # Create StarChat client (dashboard vs CLI)
            from zylch.tools.starchat import StarChatClient, create_starchat_client

            if is_dashboard and firebase_token:
                sc_client = StarChatClient(
                    base_url=settings.mrcall_base_url.rstrip("/"),
                    auth_type="firebase",
                    jwt_token=firebase_token,
                    realm=settings.mrcall_realm,
                    owner_id=owner_id,
                    verify_ssl=settings.starchat_verify_ssl,
                )
                logger.debug("[/mrcall variables] Created StarChatClient with firebase_token")
            else:
                sc_client = await create_starchat_client(owner_id)
                logger.debug("[/mrcall variables] Created StarChatClient with OAuth")

            # Check for sub-subcommand (get/set)
            # args[0] is 'variables'. Check args[1]
            var_subcommand = args[1].lower() if len(args) > 1 else "get"
            logger.debug(f"[/mrcall variables] var_subcommand={var_subcommand}")

            # Sub-subcommand: set VARIABLE value
            if var_subcommand == "set":
                if len(args) < 4:
                    return "❌ **Usage:** `/mrcall variables set <VARIABLE_NAME> <value>`"

                var_name = args[2]
                # Join all remaining args to allow spaces without strict quoting if user prefers
                # But since shlex split the input, quotes are already handled.
                # If user typed: set VAR "my value", args=['variables', 'set', 'VAR', 'my value'] -> value='my value'
                # If user typed: set VAR my value, args=['variables', 'set', 'VAR', 'my', 'value'] -> value='my value'
                var_value = " ".join(args[3:])

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
            if "--name" in args:
                try:
                    name_idx = args.index("--name")
                    if name_idx + 1 < len(args):
                        filter_name = args[name_idx + 1]
                except ValueError:
                    pass
            logger.debug(
                f"[/mrcall variables] filter: '--name' in args={('--name' in args)}, filter_name={filter_name}"
            )

            try:
                variables = await sc_client.get_all_variables(business_id)
                logger.debug(
                    f"[/mrcall variables] get_all_variables(business_id={business_id}) -> {len(variables)} vars: {[v['name'] for v in variables]}"
                )
                await sc_client.close()

                if not variables:
                    return f"**📋 MrCall Variables**\n\nNo variables found for business `{business_id}`."

                # Filter if requested
                if filter_name:
                    vars_before = len(variables)
                    variables = [v for v in variables if filter_name.upper() in v["name"].upper()]
                    logger.debug(
                        f"[/mrcall variables] filter applied: before={vars_before}, filter={filter_name}, after={len(variables)}, matches={[v['name'] for v in variables]}"
                    )
                    if not variables:
                        return f"**📋 MrCall Variables**\n\nNo variables matching `*{filter_name}*` found."

                output = f"**📋 MrCall Variables** ({len(variables)} found)\n\n"
                for var in variables:
                    name = var["name"]
                    desc = var["description"]
                    val = var["value"]

                    output += f"**{name}**: {desc}. Value: `{val}`\n\n"

                return output

            except Exception as e:
                await sc_client.close()
                logger.error(f"Failed to fetch variables: {e}")
                return f"❌ **Error:** {str(e)}"

        # Subcommand: link <business_id> - Link to business by ID
        if subcommand == "link":
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
            if not creds or not creds.get("access_token"):
                return (
                    "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first to authenticate."
                )

            access_token = creds.get("access_token")

            # Fetch businesses to validate the ID exists
            try:
                async with httpx.AsyncClient(
                    timeout=30.0, verify=settings.starchat_verify_ssl
                ) as http_client:
                    response = await http_client.post(
                        f"{settings.mrcall_base_url.rstrip('/')}/mrcall/v1/delegated_{settings.mrcall_realm}/crm/business/search",
                        headers={"auth": access_token, "Content-Type": "application/json"},
                        json={"from": 0, "size": 50},
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
                biz_id = biz.get("businessId") or biz.get("id")
                if biz_id == target_business_id:
                    business = biz
                    break

            if not business:
                logger.debug(f"[/mrcall link] business not found: {target_business_id}")
                return f"❌ **Business not found:** `{target_business_id}`\n\nRun `/mrcall list` to see your assistants."

            business_id = target_business_id
            nickname = business.get("nickname") or "Unnamed"
            logger.debug(f"[/mrcall link] found business: nickname={nickname}")

            # Save the link
            result = client.set_mrcall_link(owner_id, business_id)
            logger.debug(
                f"[/mrcall link] set_mrcall_link(owner_id={owner_id}, business_id={business_id}) -> result={result}"
            )

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
        if subcommand == "show":
            # Get linked business
            creds = get_mrcall_credentials(owner_id)
            if not creds or not creds.get("access_token"):
                return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first."

            # Get linked business ID (explicit /mrcall link takes priority over OAuth default)
            business_id = client.get_mrcall_link(owner_id)
            logger.debug(
                f"[/mrcall show] get_mrcall_link(owner_id={owner_id}) -> business_id={business_id}"
            )
            if not business_id:
                return "❌ **No assistant linked**\n\nRun `/mrcall list` to see available assistants, then `/mrcall link <ID>` to link one."

            # Parse feature argument
            feature_name = positional[1] if len(positional) > 1 else "welcome_inbound"
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

        # Subcommand: config — moved to the dashboard.
        if subcommand == "config":
            logger.debug(f"[/mrcall config] positional={positional}")
            return (
                "**Configure your MrCall assistant from the dashboard:**\n\n"
                "https://dashboard.mrcall.ai\n\n"
                "Local desktop configuration was removed — the desktop is a "
                "consumer of MrCall via StarChat (see `/mrcall list`, "
                "`/mrcall link`)."
            )

        # Subcommand: feature — moved to the dashboard.
        if subcommand == "feature":
            return (
                "**Manage MrCall features from the dashboard:**\n\n"
                "https://dashboard.mrcall.ai"
            )

        # No subcommand: show status
        if subcommand is None:
            # Get OAuth credentials to check connection
            creds = get_mrcall_credentials(owner_id)

            if creds and creds.get("access_token"):
                # Get linked business ID (explicit /mrcall link takes priority over OAuth default)
                business_id = client.get_mrcall_link(owner_id)
                logger.debug(
                    f"[/mrcall status] get_mrcall_link(owner_id={owner_id}) -> business_id={business_id}"
                )
                email = (
                    creds.get("metadata", {}).get("email")
                    if isinstance(creds.get("metadata"), dict)
                    else None
                )

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
    """Handle /share command - data sharing (disabled in standalone)."""
    return "Sharing is not available in standalone mode."


async def handle_revoke(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /revoke command - revoke sharing access (disabled in standalone)."""
    return "Sharing is not available in standalone mode."


async def handle_connect(args: List[str], owner_id: str, user_email: str = None) -> str:
    """Handle /connect command - list available connections and initiate connection flow.

    Usage:
    - /connect - List all available providers
    - /connect <provider> - Initiate connection for specific provider
    - /connect status - Show connection status
    - /connect reset <provider> - Disconnect a provider
    """
    from zylch.storage import Storage

    def get_category_emoji(category: str) -> str:
        """Return emoji for provider category."""
        return {
            "email": "📧",
            "calendar": "📅",
            "crm": "📊",
            "sms": "📱",
            "phone": "📞",
            "llm": "🤖",
        }.get(category, "🔌")

    def get_available_providers(storage, include_unavailable=False):
        """Return list of connectable providers."""
        # IntegrationProvider table removed; return
        # hardcoded list for now.
        return []

    def get_connection_status(storage, owner_id, include_unavailable=False):
        """Return connection status dict."""
        return {
            "connections": [],
            "connected_count": 0,
            "available_count": 0,
        }

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
    if "--help" in args:
        return help_text

    # Separate positional args from options
    positional = [a for a in args if not a.startswith("--")]
    subcommand = positional[0].lower() if positional else None

    try:
        supabase = Storage()

        # Subcommand: status
        if subcommand == "status":
            status_data = get_connection_status(supabase, owner_id, include_unavailable=False)
            connections = status_data.get("connections", [])

            if not connections:
                return "**📡 Connection Status**\n\n❌ No providers available"

            output = f"**📡 Connection Status** ({status_data['connected_count']}/{status_data['available_count']} connected)\n"
            if user_email:
                output += f"**Login:** {user_email}\n"
            output += "\n"

            for conn in connections:
                emoji = get_category_emoji(conn.get("category", ""))
                status = conn.get("status", "disconnected")
                name = conn["display_name"]

                if status == "connected":
                    email = conn.get("connected_email", "")
                    output += f"✅ {emoji} **{name}**"
                    if email:
                        output += f" ({email})"
                    output += "\n"
                else:
                    output += f"⬚ {emoji} {name} - `/connect {conn['provider_key']}`\n"

            return output

        # Subcommand: reset
        if subcommand == "reset":
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
                "google": delete_user_credentials,
                "microsoft": lambda oid: supabase.delete_oauth_token(oid, "microsoft"),
                "mrcall": delete_mrcall_credentials,
                "anthropic": delete_anthropic_key,
                "openai": lambda oid: delete_llm_provider_key(oid, "openai"),
                "mistral": lambda oid: delete_llm_provider_key(oid, "mistral"),
                "pipedrive": delete_pipedrive_key,
                "vonage": delete_vonage_keys,
            }

            if provider_key not in delete_funcs:
                supported = ", ".join(sorted(delete_funcs.keys()))
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
                emoji = get_category_emoji(provider["category"])
                output += f"{i}. {emoji} **{provider['display_name']}** - `/connect {provider['provider_key']}`\n"

            return output

        # Connect to specific provider (subcommand is the provider key)
        provider_key = subcommand

        # IntegrationProvider table removed; provider lookup
        # is not available. Return a helpful message.
        logger.info(f"[/connect] provider_key='{provider_key}'" " (IntegrationProvider removed)")
        return (
            f"Provider '{provider_key}' lookup is not"
            " available (IntegrationProvider removed)."
            "\n\nUse `/connect status` or"
            " `/connect reset <provider>` instead."
        )

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
    from zylch.storage.database import get_session
    from zylch.storage.models import Email, Draft
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
    if "--help" in args:
        return help_text

    if not args:
        return help_text

    try:

        # Get the subcommand (first positional arg)
        subcommand = args[0].lower() if args else ""
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
        if subcommand == "list":
            limit = int(parse_flag("--limit", "20"))
            limit = min(limit, 50)

            # If --draft flag, list drafts
            if has_flag("--draft"):
                with get_session() as session:
                    drafts = (
                        session.query(Draft)
                        .filter(Draft.owner_id == owner_id, Draft.status == "draft")
                        .order_by(Draft.updated_at.desc())
                        .limit(limit)
                        .all()
                    )
                    drafts_data = [d.to_dict() for d in drafts]

                if not drafts_data:
                    return "**📭 No drafts**\n\nCreate one with `/email create --to <email> --subject <text>`"

                output = f"**📝 Drafts** ({len(drafts_data)} found)\n\n"
                for i, draft in enumerate(drafts_data, 1):
                    to_str = ", ".join(draft.get("to_addresses", []) or [])
                    subject = draft.get("subject", "(no subject)")
                    draft_id = draft["id"]
                    updated = draft.get("updated_at", "")

                    output += f"**{i}. {subject}**\n"
                    output += f"   To: {to_str}\n"
                    output += f"   ID: `{draft_id}` | {updated}\n\n"

                output += "_Use `/email send <id>` to send a draft._"
                return output

            # Default: list recent emails - grouped by thread, only RECEIVED
            days = int(parse_flag("--days", "7"))
            since_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            # Get user's email domain to filter out sent emails
            user_email = get_email(owner_id) or ""
            user_domain = (
                user_email.split("@")[1].lower() if user_email and "@" in user_email else ""
            )

            # Fetch more emails to allow filtering, then group by thread
            with get_session() as session:
                rows = (
                    session.query(
                        Email.gmail_id,
                        Email.thread_id,
                        Email.subject,
                        Email.from_email,
                        Email.from_name,
                        Email.snippet,
                        Email.body_plain,
                        Email.date,
                    )
                    .filter(Email.owner_id == owner_id, Email.date >= since_date)
                    .order_by(Email.date.desc())
                    .limit(limit * 3)
                    .all()
                )
                emails = [
                    {
                        "gmail_id": r.gmail_id,
                        "thread_id": r.thread_id,
                        "subject": r.subject,
                        "from_email": r.from_email,
                        "from_name": r.from_name,
                        "snippet": r.snippet,
                        "body_plain": r.body_plain,
                        "date": r.date.isoformat() if r.date else None,
                    }
                    for r in rows
                ]

            if not emails:
                return f"**📭 No emails** in the last {days} days\n\nTry `/sync` to fetch recent emails."

            # Filter: only RECEIVED emails (from_email NOT matching user's domain)
            received_emails = []
            for email in emails:
                from_email_addr = (email.get("from_email") or "").lower()
                if user_domain and user_domain in from_email_addr:
                    continue  # Skip emails sent by user
                received_emails.append(email)

            # Group by thread_id, keep only most recent per thread
            seen_threads = set()
            thread_emails = []
            for email in received_emails:  # Already sorted by date desc
                thread_id = email.get("thread_id") or email.get("gmail_id")
                if thread_id not in seen_threads:
                    seen_threads.add(thread_id)
                    thread_emails.append(email)
                if len(thread_emails) >= limit:
                    break

            if not thread_emails:
                return f"**📭 No received emails** in the last {days} days\n\nTry `/sync` to fetch recent emails."

            output = f"**📧 Recent Conversations** ({len(thread_emails)} threads)\n\n"
            for email in thread_emails:
                subject = email.get("subject") or "(no subject)"
                from_name = email.get("from_name") or email.get("from_email", "Unknown")
                date_str = (email.get("date") or "")[:10]  # YYYY-MM-DD

                body = email.get("body_plain") or email.get("snippet") or ""
                body_preview = body.replace("\n", " ").strip()

                output += f"**{subject}**\n"
                output += f"   From: {from_name} | {date_str}\n"
                output += f"   {body_preview}\n\n"

            output += f"_Showing last {days} days. Use `--days N` or `--limit N` to adjust._"
            return output

        # --- CREATE DRAFT (DEPRECATED - use /agent email run) ---
        if subcommand == "create":
            return """⚠️ **`/email create` is deprecated**

Use the email agent instead:
• `/agent email run "scrivi a mario@example.com un'offerta"`
• `/agent email run "write to John about the meeting"`

The email agent composes contextual emails using your writing style and memory.

For simple drafts without context, use the `compose_email` tool in chat."""

        # --- SEND DRAFT ---
        if subcommand == "send":
            # Get draft_id from first positional arg after 'send'
            draft_id = sub_args[0] if sub_args and not sub_args[0].startswith("--") else None

            if draft_id:
                # Find the draft by ID
                with get_session() as session:
                    draft_row = (
                        session.query(Draft)
                        .filter(
                            Draft.owner_id == owner_id,
                            Draft.status == "draft",
                            Draft.id == draft_id,
                        )
                        .first()
                    )
                    draft = draft_row.to_dict() if draft_row else None

                if not draft:
                    return (
                        f"❌ Draft not found: `{draft_id}`\n\nUse `/email list` to see your drafts."
                    )
            else:
                # No draft_id provided - use the most recent draft
                with get_session() as session:
                    draft_row = (
                        session.query(Draft)
                        .filter(Draft.owner_id == owner_id, Draft.status == "draft")
                        .order_by(Draft.updated_at.desc())
                        .first()
                    )
                    draft = draft_row.to_dict() if draft_row else None

                if not draft:
                    return "❌ No drafts found.\n\nCreate a draft first with `/email create` or use the `compose_email` tool."

                draft_id = draft["id"]

            # Get user's email provider
            provider = get_provider(owner_id)
            user_email = get_email(owner_id)

            if not provider:
                return "❌ No email provider connected\n\nUse `/connect google` or `/connect microsoft` first."

            # Mark as sending.
            # NOTE: only persist `provider` for OAuth providers. The drafts
            # table has CHECK (provider IN ('google','microsoft')), so writing
            # 'imap' would raise sqlite3.IntegrityError. For IMAP the provider
            # is recoverable at runtime via get_provider(owner_id).
            with get_session() as session:
                update_fields = {"status": "sending"}
                if provider in ("google", "microsoft"):
                    update_fields["provider"] = provider
                session.query(Draft).filter(Draft.id == draft["id"]).update(update_fields)

            try:
                # Convert list fields to comma-separated strings for email APIs
                to_str = (
                    ", ".join(draft["to_addresses"])
                    if isinstance(draft["to_addresses"], list)
                    else draft["to_addresses"]
                )
                cc_str = (
                    ", ".join(draft["cc_addresses"])
                    if draft.get("cc_addresses") and isinstance(draft["cc_addresses"], list)
                    else draft.get("cc_addresses")
                )
                bcc_str = (
                    ", ".join(draft["bcc_addresses"])
                    if draft.get("bcc_addresses") and isinstance(draft["bcc_addresses"], list)
                    else draft.get("bcc_addresses")
                )

                if provider == "google":
                    from zylch.tools.gmail import GmailClient

                    gmail = GmailClient(account=user_email, owner_id=owner_id)

                    # Build and send message
                    sent_message = gmail.send_message(
                        to=to_str,
                        subject=draft.get("subject", ""),
                        body=draft.get("body", ""),
                        cc=cc_str,
                        bcc=bcc_str,
                        in_reply_to=draft.get("in_reply_to"),
                        references=draft.get("references"),
                        thread_id=draft.get("thread_id"),
                    )

                    sent_id = sent_message.get("id", "")

                elif provider == "microsoft":
                    from zylch.tools.outlook import OutlookClient
                    from zylch.api.token_storage import get_graph_token

                    graph_token = get_graph_token(owner_id)
                    if not graph_token:
                        raise Exception("Microsoft token expired. Please reconnect.")

                    outlook = OutlookClient(
                        graph_token=graph_token["access_token"], account=user_email
                    )

                    sent_message = outlook.send_message(
                        to=to_str,
                        subject=draft.get("subject", ""),
                        body=draft.get("body", ""),
                        cc=cc_str,
                        bcc=bcc_str,
                    )

                    sent_id = sent_message.get("id", "")

                elif provider == "imap":
                    import os as _os
                    from zylch.email.imap_client import IMAPClient

                    email_addr = _os.environ.get("EMAIL_ADDRESS", "") or user_email or ""
                    email_pass = _os.environ.get("EMAIL_PASSWORD", "")
                    if not email_addr or not email_pass:
                        raise Exception(
                            "IMAP not configured: EMAIL_ADDRESS or EMAIL_PASSWORD missing."
                        )

                    imap_port_str = _os.environ.get("IMAP_PORT")
                    smtp_port_str = _os.environ.get("SMTP_PORT")
                    imap_client = IMAPClient(
                        email_addr=email_addr,
                        password=email_pass,
                        imap_host=_os.environ.get("IMAP_HOST") or None,
                        imap_port=(int(imap_port_str) if imap_port_str else None),
                        smtp_host=_os.environ.get("SMTP_HOST") or None,
                        smtp_port=(int(smtp_port_str) if smtp_port_str else None),
                    )

                    # IMAPClient.send_message expects cc/bcc as List[str] (or None)
                    # — pass the original list fields, not the comma-joined strings.
                    cc_list = (
                        draft["cc_addresses"]
                        if draft.get("cc_addresses") and isinstance(draft["cc_addresses"], list)
                        else None
                    )
                    bcc_list = (
                        draft["bcc_addresses"]
                        if draft.get("bcc_addresses") and isinstance(draft["bcc_addresses"], list)
                        else None
                    )

                    refs = draft.get("references")
                    if isinstance(refs, list):
                        refs = " ".join(refs) if refs else None

                    sent_message = imap_client.send_message(
                        to=to_str,
                        subject=draft.get("subject", ""),
                        body=draft.get("body", ""),
                        cc=cc_list,
                        bcc=bcc_list,
                        in_reply_to=draft.get("in_reply_to"),
                        references=refs,
                        attachment_paths=draft.get("attachment_paths") or None,
                    )

                    sent_id = sent_message.get("id", "")

                    # Mark draft as sent (status='sent', sent_at, sent_message_id).
                    # Do NOT delete — per task spec, status must become 'sent'.
                    from zylch.storage import Storage as _Storage

                    _Storage().mark_draft_sent(owner_id, draft["id"], sent_id)

                    to_str = ", ".join(draft["to_addresses"])
                    return f"""✅ **Email sent!**

**To:** {to_str}
**Subject:** {draft.get('subject', '(no subject)')}
**Via:** IMAP/SMTP

Message ID: `{sent_id if sent_id else 'N/A'}`"""

                else:
                    raise Exception(f"Unknown provider: {provider}")

                # Delete draft after successful send (google/microsoft only — IMAP
                # branch already returned above after mark_draft_sent).
                with get_session() as session:
                    session.query(Draft).filter(Draft.id == draft["id"]).delete()

                to_str = ", ".join(draft["to_addresses"])
                return f"""✅ **Email sent!**

**To:** {to_str}
**Subject:** {draft.get('subject', '(no subject)')}
**Via:** {provider.title()}

Message ID: `{sent_id if sent_id else 'N/A'}`"""

            except Exception as e:
                # Restore draft status on failure (so it appears in /email list --draft)
                with get_session() as session:
                    session.query(Draft).filter(Draft.id == draft["id"]).update(
                        {
                            "status": "draft",
                            "error_message": str(e),
                        }
                    )

                logger.error(f"Failed to send email: {e}", exc_info=True)
                return f"❌ **Failed to send:** {str(e)}\n\nDraft saved. Fix the issue and try again with `/email send {draft_id}`"

        # --- DELETE DRAFT ---
        if subcommand == "delete":
            # Get draft_id from first positional arg after 'delete'
            draft_id = sub_args[0] if sub_args and not sub_args[0].startswith("--") else None

            if not draft_id:
                return "❌ Missing draft ID\n\nUsage: `/email delete <draft_id>`"

            with get_session() as session:
                deleted_count = (
                    session.query(Draft)
                    .filter(Draft.owner_id == owner_id, Draft.id == draft_id)
                    .delete()
                )

            if deleted_count:
                return f"✅ Draft `{draft_id}` deleted"
            else:
                return f"❌ Draft not found: `{draft_id}`"

        # --- RESET (delete all emails) ---
        if subcommand == "reset":
            from zylch.storage.database import get_session
            from zylch.storage.models import Email as EmailModel

            with get_session() as session:
                session.query(EmailModel).filter(EmailModel.owner_id == owner_id).delete()
            return "✅ All emails deleted."

        # --- SEARCH EMAILS (PostgreSQL FTS) ---
        if subcommand == "search":
            from sqlalchemy import text

            # Parse args: query text, --limit N, --days N, --from <sender>
            query_parts = []
            limit = 10
            days = None
            from_filter = None
            i = 0
            while i < len(sub_args):
                if sub_args[i] == "--limit" and i + 1 < len(sub_args):
                    limit = min(int(sub_args[i + 1]), 50)
                    i += 2
                elif sub_args[i] == "--days" and i + 1 < len(sub_args):
                    days = int(sub_args[i + 1])
                    i += 2
                elif sub_args[i] == "--from" and i + 1 < len(sub_args):
                    from_filter = sub_args[i + 1]
                    i += 2
                else:
                    query_parts.append(sub_args[i])
                    i += 1

            query = " ".join(query_parts).strip()
            if not query:
                return (
                    "❌ Missing search query\n\n"
                    "Usage: `/email search <query> "
                    "[--from sender] [--days N] [--limit N]`"
                )

            logger.debug(
                f"[/email search] query={query}, " f"days={days}, from={from_filter}, limit={limit}"
            )

            # Build SQL with FTS on fts_document column
            where_clauses = [
                "owner_id = :owner_id",
                "fts_document @@ plainto_tsquery('english', :query)",
            ]
            params: dict = {
                "owner_id": owner_id,
                "query": query,
                "limit": limit,
            }

            if days:
                where_clauses.append("date > now() - make_interval(days => :days)")
                params["days"] = days

            if from_filter:
                where_clauses.append("from_email ILIKE :from_pattern")
                params["from_pattern"] = f"%{from_filter}%"

            where_sql = " AND ".join(where_clauses)
            sql = text(
                f"SELECT date, from_email, from_name, "
                f"subject, snippet "
                f"FROM emails "
                f"WHERE {where_sql} "
                f"ORDER BY date DESC "
                f"LIMIT :limit"
            )

            with get_session() as session:
                result = session.execute(sql, params)
                rows = result.fetchall()

            # ILIKE fallback when FTS returns nothing
            # (covers person name searches like "sorvillo")
            if not rows:
                fallback_clauses = [
                    "owner_id = :owner_id",
                    "(from_email ILIKE :name_pattern " "OR from_name ILIKE :name_pattern)",
                ]
                fallback_params: dict = {
                    "owner_id": owner_id,
                    "name_pattern": f"%{query}%",
                    "limit": limit,
                }
                if days:
                    fallback_clauses.append("date > now() - make_interval(" "days => :days)")
                    fallback_params["days"] = days
                if from_filter:
                    fallback_clauses.append("from_email ILIKE :from_pattern")
                    fallback_params["from_pattern"] = f"%{from_filter}%"

                fallback_where = " AND ".join(fallback_clauses)
                fallback_sql = text(
                    f"SELECT date, from_email, from_name, "
                    f"subject, snippet "
                    f"FROM emails "
                    f"WHERE {fallback_where} "
                    f"ORDER BY date DESC "
                    f"LIMIT :limit"
                )
                with get_session() as session:
                    result = session.execute(fallback_sql, fallback_params)
                    rows = result.fetchall()

            logger.debug(f"[/email search] query={query}, " f"results={len(rows)}")

            if not rows:
                return f"📧 No emails found for " f'**"{query}"**'

            # Format results
            lines = [f"**📧 Search Results** ({len(rows)} found)\n"]
            for idx, row in enumerate(rows, 1):
                date_val = row[0]
                from_email = row[1] or ""
                from_name = row[2] or ""
                subject = row[3] or "(no subject)"
                snippet = row[4] or ""

                # Format date
                if hasattr(date_val, "strftime"):
                    date_str = date_val.strftime("%Y-%m-%d %H:%M")
                else:
                    date_str = str(date_val)[:16] if date_val else ""

                snip = snippet

                sender = from_name or from_email
                if from_name and from_email:
                    sender = f"{from_name} <{from_email}>"

                lines.append(f"{idx}. **{subject}** — {sender}\n" f"   {date_str} | {snip}")

            return "\n\n".join(lines)

        # Unknown subcommand - show error + help
        return f"❌ Unknown subcommand: `{subcommand}`\n\n{help_text}"

    except Exception as e:
        logger.error(f"Error in /email command: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


# Command help texts - source of truth for all clients (CLI, web, mobile)
COMMAND_HELP = {
    "/help": {
        "summary": "Show available commands",
        "usage": "/help",
        "description": "Lists all available slash commands.",
    },
    # All other commands handle --help internally via their help_text variable.
    # This avoids duplication and ensures help is always up-to-date.
    # See handle_sync(), handle_memory(), handle_agent(), etc.
}


async def handle_stats(args: List[str], owner_id: str) -> str:
    """Handle /stats command - email statistics."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Email, TaskItem
    from sqlalchemy import func, distinct

    help_text = """**📊 Email Statistics**

**Usage:** `/stats`

Shows statistics about your synced emails:
- Total emails and threads
- Unread count
- Date range
- Open conversations needing response"""

    # --help option (check first)
    if "--help" in args:
        return help_text

    try:
        with get_session() as session:
            # Count total emails
            total_emails = (
                session.query(func.count(Email.id)).filter(Email.owner_id == owner_id).scalar() or 0
            )

            # Count unique threads
            unique_threads = (
                session.query(func.count(distinct(Email.thread_id)))
                .filter(Email.owner_id == owner_id)
                .scalar()
                or 0
            )

            # Get date range
            oldest_date_val = (
                session.query(func.min(Email.date)).filter(Email.owner_id == owner_id).scalar()
            )
            newest_date_val = (
                session.query(func.max(Email.date)).filter(Email.owner_id == owner_id).scalar()
            )

            oldest_date = oldest_date_val.isoformat() if oldest_date_val else "N/A"
            newest_date = newest_date_val.isoformat() if newest_date_val else "N/A"

            # Count open tasks
            open_count = (
                session.query(func.count(TaskItem.id))
                .filter(TaskItem.owner_id == owner_id, TaskItem.action_required.is_(True))
                .scalar()
                or 0
            )

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
    from zylch.storage.database import get_session
    from zylch.storage.models import CalendarEvent
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
    if "--help" in args:
        return help_text

    try:
        # Parse arguments
        days_ahead = 7
        limit = 20

        for i, arg in enumerate(args):
            if arg == "--limit" and i + 1 < len(args):
                try:
                    limit = min(int(args[i + 1]), 50)
                except ValueError:
                    pass
            elif arg.isdigit():
                days_ahead = int(arg)

        now = datetime.now(timezone.utc)
        end_date = now + timedelta(days=days_ahead)

        with get_session() as session:
            events = (
                session.query(CalendarEvent)
                .filter(
                    CalendarEvent.owner_id == owner_id,
                    CalendarEvent.start_time >= now,
                    CalendarEvent.start_time <= end_date,
                )
                .order_by(CalendarEvent.start_time.asc())
                .limit(limit)
                .all()
            )
            events_data = [e.to_dict() for e in events]

        if not events_data:
            return f"""**📅 Calendar** (next {days_ahead} days)

📭 No events found.

Run `/sync` to fetch calendar events."""

        output = f"**📅 Calendar** ({len(events_data)} events, next {days_ahead} days)\n\n"

        current_date = None
        for event in events_data:
            # Parse start time
            start_str = event.get("start_time", "")
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            event_date = start_dt.strftime("%A, %B %d")
            event_time = start_dt.strftime("%H:%M")

            # Group by date
            if event_date != current_date:
                current_date = event_date
                output += f"\n**{event_date}**\n"

            title = event.get("summary", "(no title)")
            location = event.get("location", "")

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
    from zylch.storage import Storage
    from zylch.workers import TaskWorker
    from zylch.api.token_storage import get_email

    help_text = """**✅ Tasks**

**Usage:** `/tasks [subcommand]`

Shows items needing your action, analyzed by AI.

**Subcommands:**
- (none) - Show current task items
- `interactive` - Walk through tasks one by one (skip/done/solve/instruct)
- `refresh` - Re-analyze events with fresh LLM call
- `status` - Show task analysis statistics
- `reset` - Clear task cache

**Setup:**
1. `/sync` - Fetch emails and calendar
2. `/tasks` - View actionable items

**Related:**
- `/agent task train email` - Force-regenerate detection prompt
- `/agent show tasks` - View trained agent"""

    # --help option (check first)
    if "--help" in args:
        return help_text

    try:
        storage = Storage.get_instance()

        # Interactive mode — runs its own input loop
        if args and args[0] == "interactive":
            from zylch.services.task_interactive import (
                run_interactive_tasks,
            )

            user_email = get_email(owner_id) or ""
            run_interactive_tasks(owner_id, storage, user_email)
            return ""

        # Handle subcommands
        if args and args[0] == "status":
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

        if args and args[0] == "reset":
            # Clear task cache AND reset processing timestamps
            deleted_count = storage.clear_task_items(owner_id)
            ts_counts = storage.reset_task_processing_timestamps(owner_id, "all")

            return f"""**✅ Task Data Reset**

- {deleted_count} task items deleted
- {ts_counts.get('emails', 0)} emails reset
- {ts_counts.get('calendar_events', 0)} calendar events reset

Run `/agent task process` to recreate all tasks."""

        # Verify an LLM transport is available
        from zylch.llm import try_make_llm_client

        if try_make_llm_client() is None:
            return """❌ **No LLM configured**

Set `ANTHROPIC_API_KEY` in the profile `.env`, or sign in with Firebase
to use MrCall credits."""

        # Get user email
        user_email = get_email(owner_id) or ""

        # Check for refresh flag
        refresh = "refresh" in args

        # Check newest email date BEFORE starting analysis
        if refresh:
            try:
                from zylch.storage.database import get_session
                from zylch.storage.models import Email as EmailModel

                with get_session() as session:
                    newest_row = (
                        session.query(EmailModel.date)
                        .filter(EmailModel.owner_id == owner_id)
                        .order_by(EmailModel.date.desc())
                        .limit(1)
                        .one_or_none()
                    )
                if newest_row:
                    newest_email_dt = (
                        newest_row[0]
                        if newest_row[0].tzinfo
                        else newest_row[0].replace(tzinfo=timezone.utc)
                    )
                    hours_ago = (
                        datetime.now(timezone.utc) - newest_email_dt
                    ).total_seconds() / 3600
                    if hours_ago > 6:
                        return f"""⚠️ **Stale Data Warning**

Newest email is **{hours_ago:.1f} hours old**.

Run `/sync` first to get fresh emails, then `/tasks refresh`."""
            except Exception as e:
                logger.warning(f"Could not check newest email date: {e}")

        # Create worker and get tasks
        worker = TaskWorker(storage, owner_id, user_email)
        tasks, _ = await worker.get_tasks(refresh=refresh)

        if not tasks:
            return "No action needed! You're all caught up."

        return format_task_items(tasks)

    except ValueError as e:
        # Task prompt not found
        return f"⚠️ {str(e)}"
    except Exception as e:
        logger.error(f"Error in /tasks: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


def _load_blob_context(storage, owner_id: str, blob_ids: list) -> str:
    """Load blob content from sources for task detail display.

    Args:
        storage: Storage instance
        owner_id: Owner ID
        blob_ids: List of blob UUIDs from task sources

    Returns:
        Concatenated blob content, or empty string if none found
    """
    if not blob_ids:
        return ""

    try:
        from zylch.storage.database import get_session
        from zylch.storage.models import Blob

        contents = []
        with get_session() as session:
            for blob_id in blob_ids:
                row = (
                    session.query(Blob.content)
                    .filter(Blob.owner_id == owner_id, Blob.id == blob_id)
                    .one_or_none()
                )
                if row:
                    contents.append(row[0] or "")

        return "\n\n".join(contents)
    except Exception as e:
        logger.warning(f"Failed to load blob context: {e}")
        return ""


async def handle_task_close(task_num: int, owner_id: str) -> str:
    """Close/complete a task by its display number.

    Args:
        task_num: 1-indexed task number from /tasks output
        owner_id: Owner ID

    Returns:
        Confirmation message or error
    """
    from zylch.storage import Storage

    storage = Storage.get_instance()

    # Get all tasks (same order as displayed in /tasks)
    tasks = storage.get_task_items(owner_id, action_required=True)

    if not tasks:
        return "No tasks found."

    # Group by urgency: high -> medium -> low (same as display)
    high_medium = [t for t in tasks if t.get("urgency") in ("high", "medium")]
    low = [t for t in tasks if t.get("urgency") == "low"]
    tasks = high_medium + low

    if task_num < 1 or task_num > len(tasks):
        return f"Task #{task_num} not found. Valid range: #1 - #{len(tasks)}"

    task = tasks[task_num - 1]  # 0-indexed
    task_id = task.get("id")
    contact = task.get("contact_name") or task.get("contact_email") or "Unknown"

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
        owner_id: Owner ID

    Returns:
        Task dict if found, None otherwise
    """
    from zylch.storage import Storage

    storage = Storage.get_instance()

    # Get all tasks (same order as displayed in /tasks)
    tasks = storage.get_task_items(owner_id, action_required=True)

    if not tasks:
        return None

    # Group by urgency: high -> medium -> low (no limits)
    high_medium = [t for t in tasks if t.get("urgency") in ("high", "medium")]
    low = [t for t in tasks if t.get("urgency") == "low"]
    tasks = high_medium + low

    if task_num < 1 or task_num > len(tasks):
        return None

    return tasks[task_num - 1]  # 0-indexed


async def handle_task_detail(task_num: int, owner_id: str) -> str:
    """Handle 'more on #N' - show full email/event for a task.

    Args:
        task_num: 1-indexed task number from /tasks output
        owner_id: Owner ID

    Returns:
        Formatted task detail or error message
    """
    from zylch.storage import Storage

    logger.debug(f"[TASK_DETAIL] Requested task #{task_num} for owner {owner_id}")

    try:
        task = await get_task_by_number(task_num, owner_id)
        if not task:
            return f"Task #{task_num} not found. Run `/tasks refresh` first."

        storage = Storage.get_instance()
        event_type = task.get("event_type")
        event_id = task.get("event_id")
        sources = task.get("sources", {})
        logger.debug(
            f"[TASK_DETAIL] Task #{task_num}: event_type={event_type}, event_id={event_id}, sources={sources}"
        )

        if event_type == "email":
            # Fetch full email from emails table using Supabase UUID
            email = storage.get_email_by_supabase_id(owner_id, event_id)
            logger.debug(
                f"[TASK_DETAIL] get_email_by_supabase_id result: {'found' if email else 'NOT FOUND'}"
            )

            # If found, get the latest email in the same thread (for older task items)
            if email and email.get("thread_id"):
                thread_emails = storage.get_thread_emails(owner_id, email["thread_id"])
                if thread_emails and len(thread_emails) > 1:
                    # get_thread_emails returns ASC order, so last is latest
                    latest = thread_emails[-1]
                    if latest.get("id") != email.get("id"):
                        logger.debug(
                            f"[TASK_DETAIL] Using latest email in thread: {latest.get('subject', '(none)')}"
                        )
                        email = latest

            if email:
                logger.debug(f"[TASK_DETAIL] Email subject: {email.get('subject', '(none)')}")
            if not email:
                return f"Email not found for task #{task_num}. It may have been deleted."

            # Format email details
            from_display = email.get("from_name") or email.get("from_email", "Unknown")
            from_email = email.get("from_email", "")
            subject = email.get("subject", "(no subject)")
            date = email.get("date", "")
            body = email.get("body_plain") or email.get("snippet", "(no content)")

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
            blob_ids = sources.get("blobs", [])
            if blob_ids:
                blob_content = _load_blob_context(storage, owner_id, blob_ids)
                if blob_content:
                    output += f"\n\n**🧠 Context (from memory):**\n{blob_content}"

            return output

        elif event_type == "calendar":
            # Fetch calendar event by google_event_id
            from zylch.storage.database import get_session
            from zylch.storage.models import CalendarEvent

            with get_session() as session:
                cal_row = (
                    session.query(CalendarEvent)
                    .filter(
                        CalendarEvent.owner_id == owner_id,
                        CalendarEvent.google_event_id == event_id,
                    )
                    .one_or_none()
                )
            logger.debug(
                f"[TASK_DETAIL] Calendar query result: {'found' if cal_row else 'not found'}"
            )

            if not cal_row:
                return f"Calendar event not found for task #{task_num}."

            event = cal_row.to_dict()
            summary = event.get("summary", "(no title)")
            description = event.get("description", "(no description)")
            start_time = event.get("start_time", "")
            end_time = event.get("end_time", "")
            location = event.get("location", "")
            attendees = event.get("attendees", [])

            # Format attendees
            attendee_str = ", ".join(attendees) if attendees else "None listed"

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
            blob_ids = sources.get("blobs", [])
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
    from zylch.storage import Storage

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
    if "--help" in args:
        return help_text

    # Separate positional args from options
    show_all = "--all" in args
    positional = [a for a in args if not a.startswith("--")]
    subcommand = positional[0].lower() if positional else None

    try:
        storage = Storage.get_instance()

        # Subcommand: cancel
        if subcommand == "cancel":
            job_id = positional[1] if len(positional) > 1 else None
            if not job_id:
                return "❌ Missing job ID. Usage: `/jobs cancel <id>`"
            success = storage.cancel_background_job(job_id, owner_id)
            if success:
                return f"✅ **Job cancelled:** `{job_id}`"
            return "❌ **Cannot cancel:** Job not found or not pending"

        # Subcommand: stop (stop running job → pending)
        if subcommand == "stop":
            arg = positional[1] if len(positional) > 1 else None
            if arg == "--all" or "--all" in args:
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
        if subcommand == "reset":
            reset_count = storage.reset_all_running_jobs()
            if reset_count:
                return f"✅ **Reset {reset_count} running jobs** to pending status.\n\nUse `/jobs resume` to re-execute them."
            return "📭 No running jobs to reset."

        # Subcommand: resume (execute pending jobs)
        if subcommand == "resume":
            import asyncio
            from zylch.services.job_executor import JobExecutor
            from zylch.api.token_storage import get_email
            from zylch.llm import try_make_llm_client

            # Get pending jobs for this user
            pending_jobs = storage.get_user_background_jobs(owner_id, status="pending", limit=10)

            if not pending_jobs:
                return "📭 No pending jobs to resume."

            if try_make_llm_client() is None:
                return (
                    "❌ No LLM configured. Set ANTHROPIC_API_KEY in the "
                    "profile .env, or sign in with Firebase to use MrCall credits."
                )

            user_email = get_email(owner_id) or ""

            # Execute each pending job — each worker resolves its own
            # transport via `make_llm_client()`.
            executor = JobExecutor(storage)
            resumed_count = 0

            for job in pending_jobs:
                asyncio.create_task(
                    executor.execute_job(job["id"], owner_id, user_email)
                )
                resumed_count += 1

            return (
                f"🚀 **Resumed {resumed_count} pending jobs**\n\nUse `/jobs` to monitor progress."
            )

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
            job_id = job["id"]  # Full UUID - never truncate!
            job_type = job["job_type"]
            status = job["status"]
            progress = job.get("progress_pct", 0)

            emoji = {
                "pending": "⏳",
                "running": "🔄",
                "completed": "✅",
                "failed": "❌",
                "cancelled": "🚫",
            }.get(status, "📋")

            output += f"{emoji} **{job_type}** (`{job_id}`)\n"
            output += f"   Status: {status}"
            if status == "running":
                output += f" ({progress}%)"
            output += "\n"
            if job.get("status_message"):
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


async def handle_agent(
    args: List[str], config: ToolConfig, owner_id: str, context: dict = None
) -> str:
    """Handle /agent command - manage personalized agents for memory and task processing.

    Command structure:
        /agent <domain> <action> [channel]

    Domains: memory, task, email, mrcall
    Actions: train, run, show, reset
    Channels: email (includes calendar automatically), all

    Args:
        args: Command arguments
        config: Tool configuration
        owner_id: User's Owner ID
        context: Request context (for dashboard detection)
    """
    from zylch.storage import Storage
    from zylch.api.token_storage import get_email

    help_text = """**🤖 Manage AI Agents**

**Memory Agents** (extract facts into memory blobs):
• `/agent memory train email` - Create email extraction agent
• `/agent memory train mrcall` - Create phone call extraction agent
• `/agent memory run email` - Process emails + calendar into memory
• `/agent memory run mrcall` - Process phone calls into memory
• `/agent memory show email` - Show current agent
• `/agent memory reset email` - Delete agent

**Task Agents** (detect actionable items):
• `/agent task train email` - Force-regenerate task detection prompt (auto-runs after sync)
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
• `/agent mrcall train <feature>` - Train specific feature (e.g., booking, call_transfer)
• `/agent mrcall run "instructions"` - Configure MrCall (auto-detects feature)
• `/agent mrcall show` - Show current agent prompt
• `/agent mrcall reset` - Delete agent prompt

  Available features: welcome_inbound, welcome_outbound, booking, caller_followup, conversation, knowledge_base, notifications_business, runtime_data, call_transfer

**Channels:** `email` (includes calendar), `mrcall` (phone calls), `all`

**Workflow:**
1. `/sync` - Fetch emails + calendar + MrCall (if connected)
2. `/agent memory train email` - Create email memory agent
3. `/agent memory run email` - Extract facts from emails + calendar
4. `/sync mrcall` - Sync phone call transcriptions
5. `/agent memory train mrcall` - Create phone call memory agent
6. `/agent memory run mrcall` - Extract facts from phone calls
7. `/agent email train` - Learn your writing style
8. `/agent email run "write to Mario about the offer"` - Use email agent"""

    # --help option (check first)
    if "--help" in args:
        return help_text

    if len(args) < 2:
        return help_text

    try:
        storage = Storage.get_instance()

        domain = args[0].lower()  # 'memory', 'task', 'email', 'mrcall'
        action = args[1].lower()  # 'train', 'run', 'show', 'reset'

        valid_domains = ["memory", "task", "email", "mrcall"]
        valid_actions = [
            "train",
            "run",
            "process",
            "show",
            "reset",
        ]  # 'process' kept for backwards compat
        valid_channels = ["email", "mrcall", "all"]

        if domain not in valid_domains:
            return f"❌ Unknown domain: `{domain}`\n\nValid domains: `memory`, `task`, `email`, `mrcall`\n\n{help_text}"

        # Normalize 'process' to 'run' for backwards compatibility
        if action == "process":
            action = "run"

        if action not in valid_actions:
            return (
                f"❌ Unknown action: `{action}`\n\nValid actions: `train`, `run`, `show`, `reset`"
            )

        # For email/mrcall: args[2:] are instructions (for run) or feature (for train), not channel
        # For memory/task: args[2] is channel
        if domain in ["email", "mrcall"]:
            channel = None  # Not used for email/mrcall
        else:
            channel = args[2].lower() if len(args) > 2 else "email"
            # Calendar channel is now included automatically with email
            if channel == "calendar":
                return (
                    "ℹ️ Calendar events are now processed automatically with emails.\n\n"
                    f"Use `/agent {domain} {action} email` instead."
                )
            if channel not in valid_channels:
                return f"❌ Unknown channel: `{channel}`\n\nValid channels: `email`, `all`"

        # Verify a transport is available before doing any agent work.
        from zylch.llm import try_make_llm_client

        if try_make_llm_client() is None:
            return (
                "❌ No LLM configured. Set ANTHROPIC_API_KEY in the "
                "profile .env, or sign in with Firebase to use MrCall credits."
            )

        user_email = get_email(owner_id)

        # Build agent_type for DB storage (e.g., 'memory_email', 'task_calendar')
        def get_agent_type(domain: str, channel: str) -> str:
            return f"{domain}_{channel}"

        # =====================
        # MEMORY DOMAIN
        # =====================
        if domain == "memory":
            if action == "train":
                # Run as background job
                job = storage.create_background_job(
                    owner_id=owner_id,
                    job_type="memory_train",
                    channel=channel,
                    params={"user_email": user_email or "", "channel": channel},
                )
                if job["status"] in ("pending", "running"):
                    if job["status"] == "pending":
                        import asyncio
                        from zylch.services.job_executor import JobExecutor

                        executor = JobExecutor(storage)
                        asyncio.create_task(
                            executor.execute_job(job["id"], owner_id, user_email)
                        )
                        logger.info(
                            f"[/agent memory train] Scheduled background job {job['id']} for channel={channel}"
                        )
                    return f"🚀 **Memory training started** ({channel})\n\nYou'll be notified when complete."
                return "❌ Failed to create training job."

            elif action == "run":
                return await _handle_memory_run(storage, owner_id, channel)

            elif action == "show":
                return await _handle_agent_show(storage, owner_id, domain, channel)

            elif action == "reset":
                return await _handle_agent_reset(storage, owner_id, domain, channel)

        # =====================
        # TASK DOMAIN
        # =====================
        elif domain == "task":
            if action == "train":
                return await _handle_task_train(
                    storage, owner_id, channel, user_email
                )

            elif action == "run":
                return await _handle_task_run(
                    storage, owner_id, channel, user_email
                )

            elif action == "show":
                return await _handle_agent_show(storage, owner_id, domain, channel)

            elif action == "reset":
                return await _handle_task_reset(storage, owner_id, channel)

        # =====================
        # EMAIL DOMAIN (Multi-tool Agent)
        # =====================
        elif domain == "email":
            if action == "train":
                # Run as background job
                job = storage.create_background_job(
                    owner_id=owner_id,
                    job_type="email_train",
                    channel="email",
                    params={"user_email": user_email or ""},
                )
                if job["status"] in ("pending", "running"):
                    if job["status"] == "pending":
                        import asyncio
                        from zylch.services.job_executor import JobExecutor

                        executor = JobExecutor(storage)
                        asyncio.create_task(
                            executor.execute_job(job["id"], owner_id, user_email)
                        )
                        logger.info(f"[/agent email train] Scheduled background job {job['id']}")
                    return "🚀 **Email training started**\n\nAnalyzing your writing style in the background. You'll be notified when complete."
                return "❌ Failed to create training job."

            elif action == "run":
                instructions = " ".join(args[2:]) if len(args) > 2 else ""
                return await _handle_emailer_run(storage, owner_id, instructions)

            elif action == "show":
                return await _handle_emailer_show(storage, owner_id)

            elif action == "reset":
                return await _handle_emailer_reset(storage, owner_id)

        # =====================
        # MRCALL DOMAIN (Unified MrCall Agent)
        # =====================
        elif domain == "mrcall":
            if action == "train":
                # Training the MrCall configurator was a platform-side
                # responsibility that never landed in the desktop. Point
                # the user at the dashboard.
                return (
                    "**Train your MrCall assistant from the dashboard:**\n\n"
                    "https://dashboard.mrcall.ai\n\n"
                    "Local training was removed — the desktop is a "
                    "consumer of MrCall via StarChat."
                )

            elif action == "run":
                instructions = " ".join(args[2:]) if len(args) > 2 else ""
                return await _handle_mrcall_agent_run(
                    storage, owner_id, instructions, context
                )

            elif action == "show":
                return await _handle_mrcall_agent_show(storage, owner_id, context)

            elif action == "reset":
                return await _handle_mrcall_agent_reset(storage, owner_id, context)

        return help_text

    except Exception as e:
        logger.error(f"Error in /agent: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}\n\n{help_text}"


# =====================
# MEMORY AGENT HELPERS
# =====================


async def _handle_memory_train(
    storage, owner_id: str, channel: str, user_email: str
) -> str:
    """Train memory extraction agent for specified channel."""
    from zylch.agents.trainers import EmailMemoryAgentTrainer
    from zylch.llm import try_make_llm_client

    if try_make_llm_client() is None:
        return """❌ **No LLM configured**

Set `ANTHROPIC_API_KEY` in the profile `.env`, or sign in with Firebase
to use MrCall credits."""

    if not user_email:
        return """❌ **User email not found**

Your email address is required to identify sent vs received emails.
Please ensure your account is properly connected via `/connect`."""

    channels_to_train = [channel] if channel != "all" else ["email", "calendar", "mrcall"]
    results = []

    for ch in channels_to_train:
        if ch == "email":
            emails = storage.get_emails(owner_id, limit=1)
            if not emails:
                results.append("📧 **Email:** No emails found - skipped")
                continue

            builder = EmailMemoryAgentTrainer(storage, owner_id, user_email)
            agent_prompt, metadata = await builder.build_memory_email_prompt()
            storage.store_agent_prompt(owner_id, "memory_email", agent_prompt, metadata)
            results.append(
                f"📧 **Email:** Agent created ({metadata.get('threads_analyzed', 0)} threads analyzed)"
            )

        elif ch == "calendar":
            # Calendar memory training - placeholder for future implementation
            results.append("📅 **Calendar:** Not yet implemented")

        elif ch == "mrcall":
            # MrCall memory training
            from zylch.agents.trainers import MrCallMemoryTrainer

            calls = storage.get_mrcall_conversations(owner_id, limit=1)
            if not calls:
                results.append(
                    "📞 **MrCall:** No phone calls found - skipped (run `/sync mrcall` first)"
                )
                continue

            try:
                trainer = MrCallMemoryTrainer(storage, owner_id, user_email)
                agent_prompt, metadata = await trainer.build_prompt()
                storage.store_agent_prompt(owner_id, "memory_mrcall", agent_prompt, metadata)
                results.append(
                    f"📞 **MrCall:** Agent created ({metadata.get('calls_analyzed', 0)} calls analyzed)"
                )
            except ValueError as e:
                results.append(f"📞 **MrCall:** {str(e)}")

    return f"""✅ **Memory Agent Training Complete**

{chr(10).join(results)}

**Next steps:**
- `/agent memory show {channel}` to review
- `/agent memory process {channel}` to extract facts"""


async def _handle_memory_run(storage, owner_id: str, channel: str) -> str:
    """Start memory processing as a background job.

    Creates a background job that runs in a thread pool, returning immediately.
    The user is notified via user_notifications when the job completes.
    """
    import asyncio
    from zylch.services.job_executor import JobExecutor
    from zylch.llm import try_make_llm_client

    if try_make_llm_client() is None:
        return """❌ **No LLM configured**

Set `ANTHROPIC_API_KEY` in the profile `.env`, or sign in with Firebase
to use MrCall credits."""

    # Check for custom agent before starting job
    if channel in ["email", "all"]:
        if not storage.get_agent_prompt(owner_id, "memory_email"):
            return """⚠️ **No memory agent found for email**

Train your memory agent first:
`/agent memory train email`"""

    if channel in ["mrcall", "all"]:
        if not storage.get_agent_prompt(owner_id, "memory_mrcall"):
            return """⚠️ **No memory agent found for MrCall**

Train your memory agent first:
`/agent memory train mrcall`"""

    # Create background job (returns existing if duplicate)
    job = storage.create_background_job(
        owner_id=owner_id, job_type="memory_process", channel=channel
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
        asyncio.create_task(
            executor.execute_job(
                job["id"],
                owner_id,
                "",  # user_email not needed for memory processing
            )
        )

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


async def _handle_task_train(
    storage, owner_id: str, channel: str, user_email: str
) -> str:
    """Force-regenerate task detection prompt (manual override).

    Normally the task prompt is auto-generated after each sync.
    This command forces a full regeneration as a background job.
    """
    import asyncio
    from zylch.services.job_executor import JobExecutor
    from zylch.llm import try_make_llm_client

    if try_make_llm_client() is None:
        return """❌ **No LLM configured**

Set `ANTHROPIC_API_KEY` in the profile `.env`, or sign in with Firebase
to use MrCall credits."""

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
    job = storage.create_background_job(owner_id=owner_id, job_type="task_train", channel=channel)

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
        asyncio.create_task(
            executor.execute_job(job["id"], owner_id, user_email or "")
        )

        return f"""🚀 **Task agent training started**

Training on {channel} data in the background.
You'll receive a notification when complete.

Job ID: `{job['id']}`

**Note:** You can continue working while this runs."""

    # Job exists but completed/failed - should create new one
    return f"Previous job status: {job['status']}. Run the command again to start a new job."


async def _handle_task_run(
    storage, owner_id: str, channel: str, user_email: str
) -> str:
    """Start task detection as a background job.

    Creates a background job that runs in a thread pool, returning immediately.
    The user is notified via user_notifications when the job completes.
    """
    import asyncio
    from zylch.services.job_executor import JobExecutor
    from zylch.llm import try_make_llm_client

    if try_make_llm_client() is None:
        return """❌ **No LLM configured**

Set `ANTHROPIC_API_KEY` in the profile `.env`, or sign in with Firebase
to use MrCall credits."""

    # Log if no task prompt exists (auto-generated after sync)
    if channel in ["email", "all"]:
        if not storage.get_agent_prompt(owner_id, "task_email"):
            logger.debug(
                f"[/agent task run] No task prompt for" f" {owner_id}, will use default detection"
            )

    # Create background job (returns existing if duplicate)
    job = storage.create_background_job(owner_id=owner_id, job_type="task_process", channel=channel)

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
        asyncio.create_task(
            executor.execute_job(job["id"], owner_id, user_email or "")
        )

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

The prompt will be auto-regenerated on next sync, or run \
`/agent task train {channel}` to force it.

💡 To reset the actual task items, run `/tasks reset`"""
    else:
        return f"❌ No agent found for `task {channel}`"


# =====================
# EMAILER AGENT HELPERS
# =====================


async def _handle_emailer_train(
    storage, owner_id: str, user_email: str
) -> str:
    """Train emailer agent to learn user's writing style."""
    from zylch.agents.trainers import EmailerAgentTrainer
    from zylch.llm import try_make_llm_client

    if try_make_llm_client() is None:
        return """❌ **No LLM configured**

Set `ANTHROPIC_API_KEY` in the profile `.env`, or sign in with Firebase
to use MrCall credits."""

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
        trainer = EmailerAgentTrainer(storage, owner_id, user_email)
        agent_prompt, metadata = await trainer.build_emailer_prompt()
        storage.store_agent_prompt(owner_id, "emailer", agent_prompt, metadata)

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
    agent_prompt = storage.get_agent_prompt(owner_id, "emailer")
    if not agent_prompt:
        return """❌ **No emailer agent found**

Train your emailer agent to learn your writing style:
`/agent email train`"""

    meta = storage.get_agent_prompt_metadata(owner_id, "emailer")
    meta_info = ""
    if meta:
        metadata = meta.get("metadata", {})
        created = meta.get("created_at", "") if meta.get("created_at") else "unknown"
        sent_analyzed = metadata.get("sent_emails_analyzed", "unknown")
        user_domain = metadata.get("user_domain", "unknown")
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
    deleted = storage.delete_agent_prompt(owner_id, "emailer")
    if deleted:
        return """✅ **Emailer agent deleted**

Your emailer agent has been deleted.
Emails will be composed with generic style.

Retrain with: `/agent email train`"""
    else:
        return "❌ No emailer agent found"


async def _handle_emailer_run(
    storage, owner_id: str, instructions: str
) -> str:
    """Execute the email agent with given instructions.

    This is the multi-tool email agent that can:
    - Compose emails (write_email)
    - Search memory (search_memory)
    - Fetch emails (get_email)
    - Answer questions (respond_text)

    The agent decides which tool to use based on the instructions.
    """
    from zylch.agents.emailer_agent import EmailerAgent
    from zylch.llm import try_make_llm_client

    if not instructions.strip():
        return """❌ **Missing instructions**

Usage: `/agent email run "your instructions"`

Examples:
• `/agent email run "scrivi a Mario un'offerta"`
• `/agent email run "What can I answer to this guy?"`
• `/agent email run "cerca info su Acme Corp"`"""

    if try_make_llm_client() is None:
        return """❌ **No LLM configured**

Set `ANTHROPIC_API_KEY` in the profile `.env`, or sign in with Firebase
to use MrCall credits."""

    try:
        # Initialize the email agent
        agent = EmailerAgent(storage=storage, owner_id=owner_id)

        # Run the agent
        result = await agent.run(instructions=instructions)

        tool_used = result.get("tool_used")
        tool_result = result.get("result", {})

        # Format response based on tool used
        if tool_used == "write_email":
            subject = tool_result.get("subject", "(no subject)")
            body = tool_result.get("body", "")
            recipient = tool_result.get("recipient_email", "(not specified)")

            # Auto-save draft
            to_addresses = [recipient] if recipient and recipient != "(not specified)" else []
            draft = storage.create_draft(
                owner_id=owner_id,
                to=to_addresses,
                subject=subject,
                body=body,
                in_reply_to=tool_result.get("in_reply_to"),
                references=tool_result.get("references"),
                thread_id=tool_result.get("thread_id"),
            )
            draft_id = draft.get("id", "") if draft else ""

            return f"""**📝 Draft Created** (ID: `{draft_id}`)

**To:** {recipient}
**Subject:** {subject}

{body}

---
Say "send it" or use `/email send {draft_id}` to send."""

        elif tool_used == "search_memory":
            results = tool_result.get("results", [])
            message = tool_result.get("message", "")
            if not results:
                return f"🔍 {message}\n\nNo results found."

            formatted = []
            for r in results:
                content = r.get("content", "")
                formatted.append(f"```\n{content}\n```")

            return f"""🔍 **{message}**

{chr(10).join(formatted)}"""

        elif tool_used == "get_email":
            if "error" in tool_result:
                return f"❌ {tool_result['error']}"

            return f"""📧 **Email Retrieved**

**From:** {tool_result.get('from_email', 'unknown')}
**Subject:** {tool_result.get('subject', '(no subject)')}
**Date:** {tool_result.get('date', 'unknown')}

{tool_result.get('body', '')}"""

        elif tool_used == "respond_text":
            response = tool_result.get("response", "")
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


async def _handle_mrcall_agent_train(
    storage,
    owner_id: str,
    api_key: str,
    llm_provider: str,
    user_email: str,
    feature: str = None,
    context: dict = None,
    force: bool = False,
    job_id: str = None,
) -> str:
    """Stub — MrCall training was a platform-side responsibility that
    never landed in the desktop. Point users at the dashboard.

    The signature is preserved because `services/job_executor.py:
    _execute_mrcall_train` still calls this function as a coroutine.
    """
    logger.info(
        f"[mrcall_train] Stubbed call: owner={owner_id}, feature={feature}, "
        f"force={force}, job_id={job_id}"
    )
    return (
        "**Train your MrCall assistant from the dashboard:**\n\n"
        "https://dashboard.mrcall.ai\n\n"
        "Local training was removed — the desktop is a consumer of "
        "MrCall via StarChat."
    )


async def _handle_mrcall_agent_run(
    storage, owner_id: str, instructions: str, context: dict = None
) -> str:
    """Execute the MrCall agent with given instructions.

    Args:
        storage: Supabase storage instance
        owner_id: User's Owner ID
        instructions: User instructions for the agent
        context: Request context (for dashboard detection)
    """
    from zylch.agents.mrcall_agent import MrCallAgent
    from zylch.llm import try_make_llm_client
    from zylch.tools.starchat import StarChatClient, create_starchat_client

    if not instructions.strip():
        return """❌ **Missing instructions**

Usage: `/agent mrcall run "your instructions"`

Examples:
• `/agent mrcall run "enable booking"`
• `/agent mrcall run "set 30-minute appointments"`
• `/agent mrcall run "change the welcome message"`
• `/agent mrcall run "what are my current settings?"`"""

    if try_make_llm_client() is None:
        return """❌ **No LLM configured**

Set `ANTHROPIC_API_KEY` in the profile `.env`, or sign in with Firebase
to use MrCall credits."""

    try:
        # Create StarChat client (dashboard vs CLI)
        is_dashboard = context and context.get("source") in ("dashboard", "mrcall_dashboard")
        firebase_token = context.get("firebase_token") if context else None

        if is_dashboard and firebase_token:
            from zylch.config import settings

            starchat = StarChatClient(
                base_url=settings.mrcall_base_url.rstrip("/"),
                auth_type="firebase",
                jwt_token=firebase_token,
                realm=settings.mrcall_realm,
                owner_id=owner_id,
                verify_ssl=settings.starchat_verify_ssl,
            )
            logger.info("[/agent mrcall run] Created StarChatClient with firebase_token")
        else:
            starchat = await create_starchat_client(owner_id)

        # Initialize the MrCall agent
        agent = MrCallAgent(
            storage=storage,
            owner_id=owner_id,
            starchat_client=starchat,
        )

        # Detect dashboard source for dry_run
        is_dashboard = context and context.get("source") in ("dashboard", "mrcall_dashboard")
        dry_run = is_dashboard

        # Extract conversation history for multi-turn context
        conversation_history = context.get("_conversation_history") if context else None

        # Extract attachments (file uploads from dashboard)
        attachments = context.get("attachments") if context else None

        # Run the agent with live values + conversation history
        result = await agent.run(
            instructions=instructions,
            dry_run=dry_run,
            conversation_history=conversation_history,
            attachments=attachments,
        )

        # Check for errors
        if result.get("error"):
            return f"❌ {result['error']}"

        tool_used = result.get("tool_used")
        tool_result = result.get("result", {})

        # Store pending_changes in context for chat_service to pick up
        if tool_result and tool_result.get("pending_changes") and context is not None:
            context["_pending_changes"] = tool_result["pending_changes"]

        # Format response based on tool used
        if tool_used and tool_used.startswith("configure_"):
            if tool_result.get("success"):
                # Use human-friendly summary if available
                response_text = tool_result.get("response_text")
                if response_text:
                    return f"✅ {response_text}"
                # Fallback
                feature = tool_result.get("feature", "unknown")
                return f"✅ **{feature.replace('_', ' ').title()}** updated successfully."
            else:
                errors = tool_result.get("errors", ["Unknown error"])
                return f"""❌ **Configuration Failed**

{chr(10).join(f'• {e}' for e in errors)}"""

        elif tool_used == "respond_text":
            response = tool_result.get("response", "")
            return f"""💬 **Response**

{response}"""

        else:
            return f"⚠️ Agent returned unexpected result: {result}"

    except Exception as e:
        logger.error(f"MrCall agent run error: {e}", exc_info=True)
        error_str = str(e).lower()
        if (
            "405" in error_str
            or "401" in error_str
            or "403" in error_str
            or "unauthorized" in error_str
        ):
            return """❌ **MrCall authentication error**

Please connect your MrCall account:
`/connect mrcall`"""
        return f"❌ **Error:** {str(e)}"


async def _handle_mrcall_agent_show(storage, owner_id: str, context: dict = None) -> str:
    """Show MrCall agent prompt.

    Args:
        context: Request context (for dashboard detection)
    """
    # Dashboard detection - skip OAuth check for dashboard users
    is_dashboard = context and context.get("source") in ("dashboard", "mrcall_dashboard")

    if not is_dashboard:
        from zylch.api.token_storage import get_mrcall_credentials

        mrcall_creds = get_mrcall_credentials(owner_id)
        if not mrcall_creds or not mrcall_creds.get("access_token"):
            return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first."

    business_id = storage.get_mrcall_link(owner_id)
    if not business_id:
        return "❌ **No assistant linked**\n\nRun `/mrcall list` to see available assistants, then `/mrcall link <ID>` to link one."

    agent_prompt = storage.get_agent_prompt(owner_id, f"mrcall_{business_id}")
    if not agent_prompt:
        return """❌ **No MrCall agent found**

Train the agent first:
`/agent mrcall train`"""

    meta = storage.get_agent_prompt_metadata(owner_id, f"mrcall_{business_id}")
    meta_info = ""
    if meta:
        metadata = meta.get("metadata", {})
        created = meta.get("created_at", "")[:10] if meta.get("created_at") else "unknown"
        features = metadata.get("features_included", [])
        meta_info = f"\n_Created: {created} | Features: {', '.join(features)}_\n"

    return f"""**🤖 Your MrCall Agent**
{meta_info}
---
{agent_prompt}
---

_Use `/agent mrcall reset` to delete._"""


async def _handle_mrcall_agent_reset(storage, owner_id: str, context: dict = None) -> str:
    """Delete MrCall agent prompt.

    Args:
        context: Request context (for dashboard detection)
    """
    # Dashboard detection - skip OAuth check for dashboard users
    is_dashboard = context and context.get("source") in ("dashboard", "mrcall_dashboard")

    if not is_dashboard:
        from zylch.api.token_storage import get_mrcall_credentials

        mrcall_creds = get_mrcall_credentials(owner_id)
        if not mrcall_creds or not mrcall_creds.get("access_token"):
            return "❌ **Not connected to MrCall**\n\nRun `/connect mrcall` first."

    business_id = storage.get_mrcall_link(owner_id)
    if not business_id:
        return "❌ **No assistant linked**\n\nRun `/mrcall list` to see available assistants, then `/mrcall link <ID>` to link one."

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
        created = meta.get("created_at", "") if meta.get("created_at") else "unknown"
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

    if "--help" in args:
        return help_text

    if "--hard" not in args:
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
        from zylch.storage.database import get_session
        from zylch.storage.models import (
            BlobSentence,
            Blob,
            TaskItem,
            Draft,
            Email,
            CalendarEvent,
            BackgroundJob,
            UserNotification,
            AgentPrompt,
        )

        counts = {}
        # Map table display names to ORM models
        # Delete order matters: sentences before blobs (FK)
        table_models = [
            ("blob_sentences", BlobSentence),
            ("blobs", Blob),
            ("task_items", TaskItem),
            ("drafts", Draft),
            ("emails", Email),
            ("calendar_events", CalendarEvent),
            ("background_jobs", BackgroundJob),
            ("user_notifications", UserNotification),
            ("agent_prompts", AgentPrompt),
        ]
        with get_session() as session:
            for table_name, model_cls in table_models:
                try:
                    deleted = (
                        session.query(model_cls).filter(model_cls.owner_id == owner_id).delete()
                    )
                    counts[table_name] = deleted
                except Exception as e:
                    counts[table_name] = f"error: {e}"
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
    dev_mode = "--dev" in args
    args = [a for a in args if a != "--dev"]

    topic = args[0].lower() if args else None

    if topic == "mrcall":
        if dev_mode:
            return _tutorial_mrcall_dev()
        return _tutorial_mrcall_user()

    if topic == "tasks":
        return _tutorial_tasks()

    return f"Unknown tutorial topic: `{topic}`\n\nAvailable: `/tutorial mrcall` | `/tutorial tasks`"


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
│  4️⃣  TRAIN MEMORY AGENT                                    │
│      /agent memory train email    (learns your style)       │
│                                                             │
│  5️⃣  PROCESS YOUR DATA (email auto-includes calendar)      │
│      /agent memory run email      (extracts facts)          │
│      /tasks                       (view detected tasks)     │
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

**More tutorials:** `/tutorial mrcall` | `/tutorial tasks`

**Next:** Run `/connect anthropic YOUR_KEY` to begin!"""


def _tutorial_mrcall_user() -> str:
    """Tutorial for new MrCall users."""
    return """**MrCall Tutorial - User Guide**

MrCall lets you configure your AI phone assistant and sync call transcriptions.

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

## Step 4: Sync Phone Transcriptions

```
/sync mrcall
```
Downloads phone call transcriptions from your MrCall assistant.
Use `--days 60` to sync more history.

---

## Step 5: Train Memory Agent (Optional)

Build a knowledge base from your phone calls:

```
/agent memory train mrcall
```
Then extract entities:
```
/agent memory process mrcall
```

---

## Step 6: Configure Your Assistant (Multi-turn)

Enter configuration mode for interactive setup:

```
/mrcall open
```

The assistant will guide you through configurations, asking clarifying questions when needed.

**Example conversation:**
```
> /mrcall open
MrCall Configuration Mode
Configuring: Mario's Restaurant

> enable booking
I can enable booking. A few questions:
1. Appointment duration? (15, 30, or 60 minutes)
2. Available days and hours?

> 30 minutes, weekdays 9 to 5
Booking updated successfully.

> /mrcall exit
Exited MrCall configuration mode.
```

---

## Step 7: Quick Commands (Single-turn Alternative)

For quick changes without dialogue, use single-turn mode:

```
/agent mrcall run "enable booking with 30-min appointments, Mon-Fri 9-17"
/agent mrcall run "is booking enabled?"
/agent mrcall run "make the greeting more casual"
```

**Tip:** Use `/mrcall open` for complex configurations, `/agent mrcall run` for quick one-liners.

---

## Command Reference

| Command | Description |
|---------|-------------|
| `/mrcall open` | **Enter config mode (multi-turn)** |
| `/mrcall exit` | **Exit config mode** |
| `/mrcall status` | Check connection status |
| `/mrcall list` | List your assistants |
| `/mrcall link <id>` | Link to assistant |
| `/mrcall unlink` | Disconnect from assistant |
| `/mrcall variables` | List all configuration variables |
| `/sync mrcall --days 30` | Sync call transcriptions |
| `/agent mrcall train` | Train MrCall configuration agent |
| `/agent mrcall run "..."` | Single-turn config (alternative) |
| `/agent mrcall show` | Show current agent prompt |
| `/agent mrcall reset` | Delete config agent |
| `/agent memory train mrcall` | Train call memory extraction |
| `/agent memory process mrcall` | Extract entities from calls |

---

**Tip:** Use `/memory search <query>` to search across all extracted information (emails, calendar, and phone calls).
"""


def _tutorial_mrcall_dev() -> str:
    """Pointer to the dashboard for MrCall configuration."""
    return (
        "**MrCall configuration**\n\n"
        "MrCall assistants are configured from the dashboard at "
        "https://dashboard.mrcall.ai. The desktop is a *consumer* of "
        "MrCall via StarChat (see `/mrcall list`, `/mrcall link`, and "
        "the `mrcall.list_my_businesses` JSON-RPC method)."
    )


def _tutorial_tasks() -> str:
    """Tutorial for task management and task mode."""
    return """# 📋 Task Management Tutorial

Zylch helps you track actionable items from your emails and calendar.

## 1. Detecting Tasks

Task detection runs automatically after each sync. You can also
trigger it manually:

```
/agent task process email  (Analyze recent emails)
```

## 2. Viewing Tasks

List your tasks to see what needs attention:

```
/tasks
```

Each task will show a **Task ID** (e.g., `123e4567-e89b...`).

## 3. Task Mode (Virtualenv) 🎯

To work on a specific task without distraction, enter **Task Mode**:

```
/tasks open <TASK_ID>
```
*Tip: You can also say "work on task <TASK_ID>"*

**In Task Mode:**
- You are focused ONLY on that task.
- The AI has full context (emails, files, history) about that task.
- You can give multi-step instructions (e.g., "Draft a reply, then check my calendar").

**Example Workflow:**
1. You: "work on task 9ea6..."
2. AI: Shows task details.
3. You: "Reply apologizing for the delay."
4. AI: Drafts email.
5. You: "Looks good, send it."
6. AI: Sends email.

## 4. Finishing Up

When you are done with the task:

```
/tasks exit
```
*Tip: You can also say "exit", "done", or "close task".*

This returns you to normal chat mode.
"""


# Export all handlers
COMMAND_HANDLERS = {
    "/echo": handle_echo,
    "/help": handle_help,
    "/tutorial": handle_tutorial,
    "/sync": handle_sync,
    "/update": None,  # lazy-loaded from process_pipeline
    "/memory": handle_memory,
    "/email": handle_email,
    "/mrcall": handle_mrcall,
    # NOTE: /connect is partially handled client-side by CLI for OAuth. Only --help, reset, status reach backend.
    "/connect": handle_connect,
    "/share": handle_share,
    "/revoke": handle_revoke,
    # Phase 1: High-impact commands (replacing tools)
    "/stats": handle_stats,
    "/calendar": handle_calendar,
    "/tasks": handle_tasks,
    "/jobs": handle_jobs,
    "/agent": handle_agent,
    "/reset": handle_reset,
}


# Lazy-load /update to avoid circular imports
def _load_update_handler():
    from zylch.services.process_pipeline import handle_process

    COMMAND_HANDLERS["/update"] = handle_process


_load_update_handler()


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
#   model    - AI model names (e.g., "opus")
#
# The semantic matcher:
# 1. Strips placeholders from templates for embedding comparison
# 2. Finds best semantic match using embeddings
# 3. Extracts typed values from the original user input
#
COMMAND_PATTERNS = {
    # --- Sync & Data ---
    "/sync": [
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
    "/memory reset": [
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
    "/help": [
        "help",
        "commands",
        "update everything",
        "synchronize",
    ],
    # --- Memory ---
    "/memory": [
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
    "/connect": [
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
    "/share": [
        "share my data",
        "give someone access",
        "share with {email:email}",
        "grant access to {email:email}",
        "share with {name:text}",
    ],
    "/revoke": [
        "revoke access",
        "remove access",
        "stop sharing",
        "revoke sharing",
        "revoke access from {email:email}",
        "stop sharing with {email:email}",
    ],
    # --- MrCall/Phone ---
    "/mrcall": [
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
    "/email": [
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
        # NOTE: "send it" is intentionally NOT listed here. It's a
        # confirmation phrase that must be interpreted by the LLM via
        # the send_draft tool (see command_matcher.py and
        # chat_service.py semantic-match guard). Listing it caused
        # "send it" to semantically match and get rewritten to
        # /email list --draft (the _format_email fallback), which
        # defeats the draft-preview flow.
        "send draft",
        "send draft {draft_id:text}",
        "send the email",
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
    "/calendar": [
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
    "/reminder": [
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
    "/stats": [
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
    "/tasks": [
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
    "/jobs": [
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
    "/agent": [
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
    "/reset": [
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
    "/tutorial": [
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
