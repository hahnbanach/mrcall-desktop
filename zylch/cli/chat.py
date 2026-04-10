"""Interactive chat mode for Zylch standalone.

REPL with readline (history, line editing) and rich (markdown output).
Routes slash commands to command_handlers, natural language to ChatService.
"""

import asyncio
import logging
import os
import readline
import shlex
import sys

from rich.console import Console
from rich.markdown import Markdown

from zylch.cli.utils import get_owner_id, load_env
from zylch.tools.config import ToolConfig

logger = logging.getLogger(__name__)

console = Console()

# Commands that need ToolConfig with BYOK credentials
_BYOK_COMMANDS = {
    "/memory", "/email", "/agent", "/calendar",
}
# Commands that need only (args, owner_id)
_SIMPLE_COMMANDS = {
    "/tasks", "/stats", "/jobs", "/reset", "/tutorial",
}


def _setup_readline(profile_dir: str):
    """Configure readline: history file, tab completion, bindings."""
    history_file = os.path.join(profile_dir, ".zylch_history")

    # Load existing history (may fail on macOS sandbox)
    try:
        readline.read_history_file(history_file)
    except (FileNotFoundError, PermissionError, OSError):
        pass

    try:
        readline.set_history_length(1000)
        import atexit
        atexit.register(readline.write_history_file, history_file)
    except (PermissionError, OSError):
        pass  # Read-only or sandboxed — no history

    # Slash command completion
    commands = [
        "/help", "/quit", "/update", "/sync",
        "/tasks", "/stats",
        "/email", "/memory", "/agent", "/calendar",
        "/connect", "/mrcall", "/jobs", "/clear",
        "/model",
    ]

    def completer(text, state):
        if text.startswith("/"):
            matches = [c for c in commands if c.startswith(text)]
        else:
            matches = []
        return matches[state] if state < len(matches) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")


def _print_dashboard(profile: str, owner_id: str):
    """Show startup dashboard: profile, sync state, pending work."""
    from datetime import datetime, timezone
    from zylch.storage.storage import Storage

    store = Storage.get_instance()

    # --- Email stats ---
    email_stats = store.get_email_stats(owner_id)
    total_emails = email_stats.get("total_emails", 0)

    # Last sync = newest email date in DB
    last_sync_str = "never"
    sync_age_hours = None
    latest = email_stats.get("latest_date")
    if latest:
        try:
            ls = datetime.fromisoformat(latest)
            if ls.tzinfo is None:
                ls = ls.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - ls
            sync_age_hours = delta.total_seconds() / 3600
            if delta.days > 0:
                last_sync_str = f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                last_sync_str = (
                    f"{delta.seconds // 3600}h ago"
                )
            elif delta.seconds >= 60:
                last_sync_str = (
                    f"{delta.seconds // 60}m ago"
                )
            else:
                last_sync_str = "just now"
        except Exception:
            last_sync_str = "unknown"

    # --- Pending processing ---
    try:
        pending_memory = len(
            store.get_unprocessed_emails(owner_id)
        )
    except Exception:
        pending_memory = 0
    try:
        pending_tasks = len(
            store.get_unprocessed_emails_for_task(owner_id)
        )
    except Exception:
        pending_tasks = 0

    # --- Active tasks ---
    task_stats = store.get_task_items_stats(owner_id)
    if task_stats:
        active = (
            task_stats["action_required"]
            - task_stats["completed"]
        )
        if active < 0:
            active = 0
    else:
        active = 0

    # --- Task urgency breakdown ---
    urgency_line = ""
    if active > 0:
        try:
            items = store.get_task_items(
                owner_id, action_required=True, limit=200,
            )
            by_urgency = {}
            for t in items:
                u = (t.get("urgency") or "unknown").lower()
                by_urgency[u] = by_urgency.get(u, 0) + 1
            parts = []
            for u in ["critical", "high", "medium", "low"]:
                if by_urgency.get(u):
                    parts.append(f"{by_urgency[u]} {u}")
            if parts:
                urgency_line = f" ({', '.join(parts)})"
        except Exception:
            pass

    # --- Memory ---
    try:
        from zylch.memory.blob_storage import BlobStorage

        mem_stats = BlobStorage().get_stats(owner_id)
        entities = mem_stats.get("total_blobs", 0)
    except Exception:
        entities = 0

    # --- Print ---
    console.print(f"[bold cyan]Zylch AI[/bold cyan] — {profile}")
    console.print(
        f"  [dim]Email:[/dim] {total_emails} synced,"
        f" last sync {last_sync_str}"
    )

    pending_parts = []
    if pending_memory:
        pending_parts.append(
            f"{pending_memory} for memory"
        )
    if pending_tasks:
        pending_parts.append(
            f"{pending_tasks} for tasks"
        )
    if pending_parts:
        console.print(
            f"  [yellow]Pending:[/yellow]"
            f" {', '.join(pending_parts)}"
        )

    if active > 0:
        console.print(
            f"  [dim]Tasks:[/dim] {active}"
            f" active{urgency_line}"
        )

    if entities > 0:
        console.print(
            f"  [dim]Memory:[/dim] {entities} entities"
        )

    # --- Suggestions: tell the user what to do ---
    suggestions = []

    needs_sync = (
        (total_emails == 0 and sync_age_hours is None)
        or (sync_age_hours is not None and sync_age_hours > 1)
    )
    needs_processing = pending_memory or pending_tasks

    if needs_sync or needs_processing:
        suggestions.append(
            "/update — sync + analyze + detect tasks"
        )

    if active > 0:
        suggestions.append(
            "/tasks — review your action items"
        )

    if suggestions:
        console.print()
        console.print("[bold]Next:[/bold]")
        for s in suggestions:
            console.print(f"  [green]>{s}[/green]")

    console.print()


def _print_response(text: str):
    """Render response as rich markdown."""
    if not text:
        return
    try:
        console.print(Markdown(text))
    except Exception:
        # Fallback to plain text if rich fails
        print(text)


def interactive_chat():
    """REPL-style chat loop with Zylch AI.

    - Selects profile (if multiple exist)
    - Acquires exclusive lock on profile
    - readline for history + line editing
    - rich for markdown output
    - Lines starting with / are dispatched as slash commands.
    - Everything else goes to ChatService.process_message().
    - Ctrl-C or /quit exits.
    """
    from zylch.cli.profiles import (
        get_active_profile,
        get_active_profile_dir,
    )

    # Profile already selected and activated by main.py _setup_profile()
    load_env()
    owner_id = get_owner_id()

    # Setup readline with profile-specific history
    profile_dir = get_active_profile_dir()
    if profile_dir:
        _setup_readline(profile_dir)

    # Reap zombie jobs from dead sessions
    from zylch.storage.storage import Storage
    zombies = Storage.get_instance().reap_zombie_jobs()
    if zombies:
        console.print(
            f"[yellow]Cleaned {zombies} failed job(s)"
            f" from previous session.[/yellow]\n"
        )

    profile = get_active_profile()
    logger.info(
        f"[chat] Starting interactive chat,"
        f" profile={profile}, owner_id={owner_id}"
    )

    _print_dashboard(profile, owner_id)
    console.print(
        "[dim]Type /help for commands."
        " Ctrl+C interrupts, Ctrl+D twice to exit."
        " Tab completes.[/dim]\n"
    )

    conversation_history: list = []
    _last_eof = False  # For double Ctrl+D exit

    while True:
        try:
            user_input = input("you> ").strip()
            _last_eof = False
        except EOFError:
            if _last_eof:
                console.print("\n[dim]Bye![/dim]")
                sys.exit(0)
            _last_eof = True
            console.print(
                "\n[dim]Press Ctrl+D again to exit.[/dim]"
            )
            continue
        except KeyboardInterrupt:
            _last_eof = False
            console.print()  # Clean line after ^C
            continue

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "/q"):
            console.print("[dim]Bye![/dim]")
            sys.exit(0)

        try:
            if user_input.startswith("/"):
                _handle_slash_command(
                    user_input, owner_id,
                    conversation_history,
                )
            else:
                _handle_chat_message(
                    user_input, owner_id,
                    conversation_history,
                )
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Interrupted.[/yellow]"
            )


def _handle_slash_command(
    raw_input: str,
    owner_id: str,
    conversation_history: list,
):
    """Dispatch a slash command to the appropriate handler."""
    try:
        parts = shlex.split(raw_input)
    except ValueError as e:
        console.print(f"[red]Error: malformed command — {e}[/red]")
        return

    cmd = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []
    logger.debug(f"[chat] slash cmd={cmd}, args={args}")

    from zylch.services.command_handlers import (
        COMMAND_HANDLERS,
    )

    if cmd == "/clear":
        conversation_history.clear()
        console.print("[dim]Conversation cleared.[/dim]")
        return

    if cmd not in COMMAND_HANDLERS:
        console.print(
            f"[yellow]Unknown command: {cmd}. Type /help.[/yellow]"
        )
        return

    handler = COMMAND_HANDLERS[cmd]

    try:
        if cmd in ("/sync", "/update"):
            config = ToolConfig.from_settings()
            result = asyncio.run(
                handler(args, config, owner_id)
            )
        elif cmd in _BYOK_COMMANDS:
            config = ToolConfig.from_settings_with_owner(
                owner_id
            )
            if cmd == "/agent":
                ctx = {
                    "_conversation_history": (
                        conversation_history
                    ),
                }
                result = asyncio.run(
                    handler(args, config, owner_id, ctx)
                )
            else:
                result = asyncio.run(
                    handler(args, config, owner_id)
                )
        elif cmd in _SIMPLE_COMMANDS:
            result = asyncio.run(handler(args, owner_id))
        elif cmd in ("/help", "/echo"):
            if args:
                result = asyncio.run(handler(args))
            else:
                result = asyncio.run(handler())
        elif cmd in ("/share", "/revoke", "/connect"):
            result = asyncio.run(
                handler(args, owner_id, None)
            )
        elif cmd == "/mrcall":
            result = asyncio.run(
                handler(args, owner_id, None, None)
            )
        else:
            result = asyncio.run(handler(args, owner_id))

        if result:
            _print_response(result)

    except Exception as e:
        logger.error(
            f"[chat] Command {cmd} failed: {e}",
            exc_info=True,
        )
        console.print(f"[red]Error running {cmd}: {e}[/red]")


def _handle_chat_message(
    user_input: str,
    owner_id: str,
    conversation_history: list,
):
    """Send a natural-language message to ChatService."""
    from zylch.services.chat_service import ChatService

    logger.debug(
        f"[chat] Sending to ChatService: "
        f"{repr(user_input[:80])}"
    )

    try:
        service = _get_chat_service()
        result = asyncio.run(
            service.process_message(
                user_message=user_input,
                user_id=owner_id,
                conversation_history=conversation_history,
                context={"user_id": owner_id},
            )
        )

        response = result.get("response", "")
        if response:
            console.print()
            _print_response(response)
            console.print()

        # Update history for next turn
        conversation_history.append(
            {"role": "user", "content": user_input}
        )
        conversation_history.append(
            {"role": "assistant", "content": response}
        )

    except Exception as e:
        logger.error(
            f"[chat] ChatService error: {e}", exc_info=True
        )
        console.print(f"[red]Error: {e}[/red]")


# Lazy singleton for ChatService
_chat_service_instance = None


def _get_chat_service():
    """Get or create the ChatService singleton."""
    global _chat_service_instance
    if _chat_service_instance is None:
        from zylch.services.chat_service import ChatService

        _chat_service_instance = ChatService()
    return _chat_service_instance
