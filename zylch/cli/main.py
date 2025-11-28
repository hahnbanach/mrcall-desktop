"""Main CLI interface for Zylch AI using prompt_toolkit."""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from ..agent import ZylchAIAgent
from ..config import settings
from ..tools import ToolFactory, ToolConfig
from ..tools.email_archive import EmailArchiveManager
from ..tools.gmail import GmailClient

# Get logger (configuration is done by launcher script or defaults to INFO)
logger = logging.getLogger(__name__)

# Only configure if not already configured (allows launcher to set level)
if not logging.root.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

# CLI style
cli_style = Style.from_dict({
    'prompt': 'ansicyan bold',
    'assistant': 'ansigreen',
    'error': 'ansired',
    'info': 'ansiyellow',
})


class ZylchAICLI:
    """Interactive CLI for Zylch AI agent."""

    def __init__(self):
        """Initialize CLI."""
        self.agent = None
        self.session = None
        self.running = False
        self.current_business_id = None  # Track selected MrCall assistant
        self.starchat = None  # Store StarChat client reference
        self.memory = None  # ZylchMemory system
        self.email_archive = None  # Email archive manager
        self.owner_id = settings.owner_id  # Multi-tenant owner ID
        self.zylch_assistant_id = settings.zylch_assistant_id  # Multi-tenant assistant ID
        self.forced_model = None  # Override model selection (None = auto)

        # Initialize AssistantManager
        from zylch.services.assistant_manager import AssistantManager
        self.assistant_manager = AssistantManager()

        # Initialize history file
        history_file = Path.home() / ".zylch_history"
        self.history = FileHistory(str(history_file))

    async def initialize(self):
        """Initialize agent and all components."""
        print("🏗️  Initializing Zylch AI...")

        # Validate configuration
        if not settings.anthropic_api_key:
            print("❌ Error: ANTHROPIC_API_KEY not set in .env file")
            sys.exit(1)

        if not settings.starchat_password:
            print("❌ Error: STARCHAT_PASSWORD not set in .env file")
            sys.exit(1)

        # Initialize components
        try:
            # Create ToolConfig from settings
            config = ToolConfig.from_settings()

            # Set default business_id from config if available
            if settings.starchat_business_id:
                self.current_business_id = settings.starchat_business_id

            # Create all tools using factory (passing current_business_id for contact tools)
            tools, self.session_state, persona_analyzer = await ToolFactory.create_all_tools(config, current_business_id=self.current_business_id)
            print(f"✅ {len(tools)} tools initialized")

            # Create memory system
            self.memory = await ToolFactory.create_memory_system(config)
            print(f"✅ ZylchMemory system initialized (semantic search enabled)")

            # Create model selector
            model_selector = ToolFactory.create_model_selector(config)

            # Get references to key components for CLI commands
            # (ToolFactory stores these internally during create_all_tools)
            self.starchat = ToolFactory._starchat_client
            self.email_archive = ToolFactory._email_archive
            self.task_manager = ToolFactory._task_manager

            # Initialize agent
            self.agent = ZylchAIAgent(
                api_key=settings.anthropic_api_key,
                tools=tools,
                model_selector=model_selector,
                email_style_prompt=settings.email_style_prompt,
                memory_system=self.memory,
                persona_analyzer=persona_analyzer,
            )

            print(f"\n✅ Zylch AI initialized successfully!")
            print(f"   • {len(tools)} tools available")
            print(f"   • Memory system: enabled")
            print(f"   • Persona learning: enabled")
            print(f"   • Model: {settings.default_model}\n")

            # Auto-create default assistant if none exists (single-assistant mode)
            assistants = self.assistant_manager.list_assistants(self.owner_id)
            if not assistants:
                try:
                    self.assistant_manager.create_assistant(
                        owner_id=self.owner_id,
                        zylch_assistant_id=self.zylch_assistant_id,
                        name=f"Default Assistant ({self.owner_id})",
                        business_type=None
                    )
                    logger.info(f"✅ Auto-created default assistant: {self.zylch_assistant_id}")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to auto-create assistant: {e}")

        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def print_welcome(self):
        """Print welcome message."""
        print("=" * 60)
        print("🌟  Zylch AI - Email Intelligence Assistant")
        print("=" * 60)
        print()
        print(f"📌 Owner: {self.owner_id}")
        print(f"📌 Current Zylch assistant: {self.zylch_assistant_id}")
        if self.current_business_id:
            print(f"📌 Linked MrCall assistant: {self.current_business_id}")
        else:
            print("⚠️  No MrCall assistant linked - use /mrcall <id> to link one")
        print()
        print("Commands:")
        print("  Type your message to interact with Zylch AI")
        print("  /help          - Show help")
        print("  /assistant     - Manage Zylch assistants (use /assistant --help for details)")
        print("  /mrcall        - Manage MrCall assistant link (use /mrcall --help for details)")
        print("  /clear         - Clear conversation history")
        print("  /history       - Show conversation history")
        print("  /memory        - Manage behavioral memory (use /memory --help for details)")
        print("  /sync [days]   - Run morning sync (emails + calendar + gap analysis)")
        print("                   Examples: /sync (default 30 days), /sync 3 (last 3 days)")
        print("  /gaps          - Show relationship gaps briefing")
        print("  /archive       - Email archive management (use /archive --help for details)")
        print("  /cache         - Inspect and manage cache (use /cache --help for details)")
        print("  /model         - Change AI model (use /model --help for details)")
        print("  /quit          - Exit Zylch AI")
        print()

    async def run(self):
        """Run interactive CLI loop."""
        await self.initialize()
        self.print_welcome()

        # Create prompt session
        self.session = PromptSession(history=self.history)
        self.running = True

        while self.running:
            try:
                # Get user input
                user_input = await self.session.prompt_async(
                    "You: ",
                    style=cli_style,
                )

                # Handle commands
                if user_input.startswith("/"):
                    await self.handle_command(user_input)
                    continue

                # Process with agent
                if user_input.strip():
                    print()
                    print("Zylch AI: ", end="", flush=True)

                    try:
                        # Build context with current session state
                        context = {
                            "current_business_id": self.current_business_id,
                            "force_model": self.forced_model
                        }
                        response = await self.agent.process_message(user_input, context=context)
                        print(response)
                    except Exception as e:
                        print(f"❌ Error: {e}")
                        logger.exception("Agent processing failed")

                    print()

            except KeyboardInterrupt:
                print("\n\nUse /quit to exit")
                continue
            except EOFError:
                break

        print("\n👋 Goodbye!")

    def _handle_memory_command(self, command: str):
        """Handle Unix-style /memory subcommands.

        Supported commands:
        - /memory --help           - Show help
        - /memory --list           - List personal memories (default)
        - /memory --list --global  - List global memories
        - /memory --list --all     - List all memories (global + personal)
        - /memory --add            - Add a new memory (interactive or with args)
        - /memory --remove <id>    - Remove a memory by ID
        - /memory --remove <id> --global  - Remove from global memory
        - /memory --stats          - Show statistics
        - /memory --stats --global - Show global statistics
        - /memory --stats --all    - Show all statistics
        """
        import shlex

        # Parse command into parts
        parts = command.split(None, 1)
        if len(parts) == 1:
            # Just "/memory" with no args - show help
            self._print_memory_help()
            return

        # Parse arguments
        args_str = parts[1]
        try:
            args = shlex.split(args_str)
        except ValueError as e:
            print(f"❌ Error parsing arguments: {e}")
            return

        # Extract flags and positional arguments
        flags = {arg for arg in args if arg.startswith('--')}
        positional = [arg for arg in args if not arg.startswith('--')]

        # Handle --help
        if '--help' in flags or '-h' in flags:
            self._print_memory_help()
            return

        # Determine scope
        scope = 'personal'  # default
        if '--global' in flags:
            scope = 'global'
        elif '--all' in flags:
            scope = 'all'

        # Handle subcommands
        if '--list' in flags or (not flags and not positional):
            # List memories (default action)
            self._memory_list(scope)

        elif '--add' in flags:
            # Add memory
            is_global = (scope == 'global')
            if positional:
                # Parse from positional args: "what_went_wrong" "correct_behavior" channel
                if len(positional) < 3:
                    print("❌ Usage: /memory --add \"what went wrong\" \"correct behavior\" channel")
                    print("\nChannels: email, calendar, whatsapp, mrcall, task")
                    print("\nExamples:")
                    print('  /memory --add "Used tu instead of lei" "Always use lei" email')
                    print('  /memory --add --global "Didn\'t check style" "Check past communication style" email')
                    print('  /memory --add "Too formal" "Use casual tone" whatsapp')
                    return

                what_went_wrong = positional[0]
                correct_behavior = positional[1]
                channel = positional[2]

                try:
                    namespace = "global:system" if is_global else "user:mario"
                    correction_id = self.memory.store_memory(
                        namespace=namespace,
                        category=channel,
                        context=what_went_wrong,
                        pattern=correct_behavior,
                        examples=[],
                        user_id=None if is_global else "mario",
                        confidence=0.5
                    )
                    scope_label = "🌍 global" if is_global else "👤 personal"
                    print(f"✅ Memory #{correction_id} added ({scope_label})!")
                    print(f"   Channel: {channel}")
                    print(f"   Starting confidence: 50%")
                except ValueError as e:
                    print(f"❌ {e}")
            else:
                # Interactive mode would go here (future enhancement)
                print("❌ Please provide arguments: /memory --add \"what went wrong\" \"correct behavior\" channel")

        elif '--remove' in flags:
            # Remove memory
            if '--all' in flags:
                # Remove all memories - requires confirmation
                print("⚠️  WARNING: This will delete ALL behavioral corrections from the memory database!")
                print("   This action cannot be undone.")
                confirm = input("\n   Type 'yes' to confirm: ").strip().lower()

                if confirm == 'yes':
                    self._memory_remove_all()
                else:
                    print("❌ Operation cancelled")
                return

            if not positional:
                print("❌ Usage: /memory --remove <id> [--global]")
                print("   Or: /memory --remove --all  (clear all memories)")
                print("   Get IDs with: /memory --list")
                return

            try:
                memory_id = int(positional[0])
                is_global = (scope == 'global')
                # TODO: Implement delete_memory() in ZylchMemory
                print(f"⚠️  Memory deletion not yet implemented in ZylchMemory")
                print(f"   Memory #{memory_id} will remain but can be overridden with low confidence")
            except ValueError:
                print("❌ Invalid memory ID. Must be a number.")

        elif '--stats' in flags:
            # Show statistics
            self._memory_stats(scope)

        elif '--build' in flags:
            # Build person memories from historical archive
            days = 30  # default
            contact_email = None
            force = '--force' in flags

            # Parse --days X
            for i, arg in enumerate(positional):
                if i > 0 and positional[i-1] == '--days':
                    try:
                        days = int(arg)
                    except ValueError:
                        print(f"❌ Invalid days value: {arg}")
                        return

            # Parse --contact email
            if '--contact' in args:
                contact_idx = args.index('--contact')
                if contact_idx + 1 < len(args):
                    contact_email = args[contact_idx + 1]
                else:
                    print("❌ --contact requires an email address")
                    return

            # Extract days from positional if format is: /memory --build --days 90
            days_idx = None
            for i, arg in enumerate(args):
                if arg == '--days' and i + 1 < len(args):
                    try:
                        days = int(args[i + 1])
                        days_idx = i
                    except ValueError:
                        print(f"❌ Invalid days value: {args[i + 1]}")
                        return

            self._memory_build(days=days, contact_email=contact_email, force=force)

        else:
            print("❌ Unknown subcommand")
            print("Use /memory --help to see available commands")

    def _print_memory_help(self):
        """Print help for /memory command."""
        print("\n=== 🧠 Memory Command Help ===\n")
        print("Manage behavioral corrections and person-centric knowledge base")
        print()
        print("Usage:")
        print("  /memory --help              Show this help")
        print("  /memory --list              List personal memories (default)")
        print("  /memory --list --global     List global memories (shared)")
        print("  /memory --list --all        List all memories")
        print()
        print("  /memory --add \"what went wrong\" \"correct behavior\" channel")
        print("                              Add a personal correction")
        print("  /memory --add --global \"wrong\" \"correct\" channel")
        print("                              Add a global correction (admin)")
        print()
        print("  /memory --build --days X    Build person memories from email archive")
        print("                              (Analyzes last X days of emails)")
        print("  /memory --build --days X --contact email@example.com")
        print("                              Build memory for specific contact only")
        print("  /memory --build --days X --force")
        print("                              Overwrite existing person memories")
        print()
        print("  /memory --remove <id>       Remove a personal memory")
        print("  /memory --remove <id> --global")
        print("                              Remove a global memory")
        print("  /memory --remove --all      Clear ALL memories (requires confirmation)")
        print()
        print("  /memory --stats             Show personal memory stats")
        print("  /memory --stats --global    Show global memory stats")
        print("  /memory --stats --all       Show all memory stats")
        print()
        print("Channels (for behavioral corrections):")
        print("  email      - Email drafting and replies")
        print("  calendar   - Calendar events and scheduling")
        print("  whatsapp   - WhatsApp messaging")
        print("  mrcall     - Phone call scripts and notes")
        print("  task       - Zylch AI task management")
        print()
        print("Examples:")
        print('  /memory --add "Used tu instead of lei" "Always use lei" email')
        print('  /memory --add --global "Didn\'t check style" "Check past emails" email')
        print('  /memory --build --days 30   # Analyze last month (default)')
        print('  /memory --build --days 90   # Analyze last 3 months')
        print('  /memory --build --days 90 --contact luisa@example.com')
        print('  /memory --list --all')
        print('  /memory --remove 5')
        print()

    def _memory_list(self, scope: str):
        """List memories with given scope using ZylchMemory."""
        import sqlite3

        conn = sqlite3.connect(str(self.memory.config.db_path))
        cursor = conn.cursor()

        # Build query based on scope
        if scope == 'personal':
            cursor.execute("SELECT * FROM memories WHERE namespace = 'user:mario' ORDER BY id")
        elif scope == 'global':
            cursor.execute("SELECT * FROM memories WHERE namespace = 'global:system' ORDER BY id")
        else:  # all
            cursor.execute("SELECT * FROM memories ORDER BY namespace, id")

        memories = cursor.fetchall()
        conn.close()

        if not memories:
            scope_label = {
                'personal': '👤 personal',
                'global': '🌍 global',
                'all': 'any'
            }[scope]
            print(f"📭 No {scope_label} memories learned yet")
            print("\nAdd your first correction with:")
            print('  /memory --add "what went wrong" "correct behavior" email')
        else:
            scope_label = {
                'personal': '👤 Personal',
                'global': '🌍 Global',
                'all': '🌍/👤 All'
            }[scope]
            print(f"\n=== 🧠 {scope_label} Memory Bank ({len(memories)} corrections) ===\n")
            for mem in memories:
                mem_id, namespace, category, context, pattern, examples, confidence, created_at, updated_at, embedding_id = mem
                conf_emoji = "🟢" if confidence > 0.7 else "🟡" if confidence > 0.4 else "🔴"
                scope_icon = "🌍" if namespace.startswith('global:') else "👤"
                channel = category.upper()
                print(f"{scope_icon} {mem_id}. {conf_emoji} [{channel}]")
                print(f"   ❌ {context}")
                print(f"   ✅ {pattern}")
                print(f"   📊 Confidence: {confidence:.0%}")
                print()

    def _memory_stats(self, scope: str):
        """Show memory statistics for given scope using ZylchMemory."""
        import sqlite3

        conn = sqlite3.connect(str(self.memory.config.db_path))
        cursor = conn.cursor()

        # Build query based on scope
        if scope == 'personal':
            cursor.execute("SELECT COUNT(*), AVG(confidence) FROM memories WHERE namespace = 'user:mario'")
            total, avg_conf = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM memories WHERE namespace = 'user:mario' AND confidence > 0.7")
            high_conf = cursor.fetchone()[0]
            cursor.execute("SELECT category, COUNT(*) FROM memories WHERE namespace = 'user:mario' GROUP BY category")
            by_channel = dict(cursor.fetchall())
        elif scope == 'global':
            cursor.execute("SELECT COUNT(*), AVG(confidence) FROM memories WHERE namespace = 'global:system'")
            total, avg_conf = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM memories WHERE namespace = 'global:system' AND confidence > 0.7")
            high_conf = cursor.fetchone()[0]
            cursor.execute("SELECT category, COUNT(*) FROM memories WHERE namespace = 'global:system' GROUP BY category")
            by_channel = dict(cursor.fetchall())
        else:  # all
            cursor.execute("SELECT COUNT(*), AVG(confidence) FROM memories")
            total, avg_conf = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM memories WHERE confidence > 0.7")
            high_conf = cursor.fetchone()[0]
            cursor.execute("SELECT category, COUNT(*) FROM memories GROUP BY category")
            by_channel = dict(cursor.fetchall())

        conn.close()

        scope_label = {
            'personal': '👤 Personal',
            'global': '🌍 Global',
            'all': '🌍/👤 All'
        }[scope]
        print(f"\n=== 🧠 {scope_label} Memory Statistics (ZylchMemory) ===\n")
        print(f"Total corrections: {total or 0}")
        print(f"Average confidence: {(avg_conf or 0):.0%}")
        print(f"High-confidence rules (>70%): {high_conf or 0}")
        if by_channel:
            print("\nBy channel:")
            for channel, count in by_channel.items():
                print(f"  - {channel}: {count}")
        print()

    def _memory_remove_all(self):
        """Remove all memories from the database."""
        import os

        try:
            db_path = str(self.memory.config.db_path)

            if os.path.exists(db_path):
                os.remove(db_path)
                print("✅ All behavioral corrections removed from memory database")
                print(f"   Deleted: {db_path}")

                # Also remove indices directory if it exists
                index_dir = self.memory.config.index_dir
                if os.path.exists(index_dir):
                    import shutil
                    shutil.rmtree(index_dir)
                    print(f"   Deleted indices: {index_dir}")
            else:
                print("⚠️  Memory database not found (already empty)")

        except Exception as e:
            print(f"❌ Error removing memories: {e}")

    def _memory_build(self, days: int, contact_email: str = None, force: bool = False):
        """Build person memories from historical email archive.

        Args:
            days: Number of days back to analyze
            contact_email: Optional specific contact to analyze (None = all contacts)
            force: If True, overwrite existing memories
        """
        import sqlite3
        from collections import defaultdict
        from datetime import datetime, timedelta

        print(f"\n🧠 Building person memories from email archive...")
        print(f"📅 Time window: Last {days} days")
        if contact_email:
            print(f"👤 Target contact: {contact_email}")
        print(f"🔄 Force overwrite: {'Yes' if force else 'No (skip existing)'}")
        print()

        try:
            # Get all threads from archive in the specified window
            cutoff_date = datetime.now() - timedelta(days=days)
            cutoff_timestamp = int(cutoff_date.timestamp())

            conn = sqlite3.connect(str(self.email_archive.db_path))
            cursor = conn.cursor()

            # Get all messages in window
            cursor.execute("""
                SELECT thread_id, from_email, from_name, subject, date, date_timestamp
                FROM messages
                WHERE date_timestamp >= ?
                ORDER BY date_timestamp ASC
            """, (cutoff_timestamp,))

            messages = cursor.fetchall()
            conn.close()

            if not messages:
                print(f"📭 No messages found in last {days} days")
                return

            print(f"📧 Found {len(messages)} messages")

            # Group by thread_id
            threads_by_id = defaultdict(list)
            for thread_id, from_email, from_name, subject, date, timestamp in messages:
                threads_by_id[thread_id].append({
                    'thread_id': thread_id,
                    'from_email': from_email,
                    'from_name': from_name,
                    'subject': subject,
                    'date': date,
                    'timestamp': timestamp
                })

            print(f"🧵 Grouped into {len(threads_by_id)} threads")

            # Group threads by contact email (deduplicate my own emails)
            contact_threads = defaultdict(list)
            my_emails = set(self.task_manager.my_emails)

            for thread_id, thread_messages in threads_by_id.items():
                # Find the contact email (not my own)
                contact = None
                for msg in thread_messages:
                    if msg['from_email'] not in my_emails:
                        contact = msg['from_email']
                        break

                if contact:
                    # If specific contact filter, skip others
                    if contact_email and contact != contact_email:
                        continue

                    contact_threads[contact].append({
                        'thread_id': thread_id,
                        'messages': thread_messages
                    })

            if not contact_threads:
                if contact_email:
                    print(f"❌ No threads found for contact: {contact_email}")
                else:
                    print(f"❌ No contact threads found (only messages from/to yourself)")
                return

            print(f"👥 Found {len(contact_threads)} unique contacts\n")

            # Estimate cost and time
            total_contacts = len(contact_threads)
            est_time_minutes = (total_contacts * 5) / 60  # ~5 sec per contact
            est_cost = total_contacts * 0.015  # ~$0.015 per contact

            print(f"⏳ Estimated time: ~{est_time_minutes:.1f} minutes")
            print(f"💰 Estimated cost: ~${est_cost:.2f} (Sonnet API calls)\n")

            # Confirm if large batch
            if total_contacts > 20 and not force:
                confirm = input(f"Process {total_contacts} contacts? (yes/no): ").strip().lower()
                if confirm != 'yes':
                    print("❌ Operation cancelled")
                    return

            # Process each contact
            processed = 0
            skipped = 0
            failed = 0

            for idx, (contact, threads) in enumerate(contact_threads.items(), 1):
                progress = int((idx / total_contacts) * 100)
                bar_length = 40
                filled = int((progress / 100) * bar_length)
                bar = '█' * filled + '░' * (bar_length - filled)

                print(f"\rProcessing: [{bar}] {progress}% ({idx}/{total_contacts})", end='', flush=True)

                try:
                    # Get contact_id from StarChat (multi-tenant namespace, use sync version)
                    contact_record = None
                    try:
                        contact_record = self.starchat.get_contact_by_email_sync(contact)
                    except Exception:
                        pass  # Contact not in StarChat, use email fallback

                    contact_id = contact_record.get('id') if contact_record else f"email_{contact.replace('@', '_at_')}"

                    # Multi-tenant namespace: {owner}:{zylch_assistant_id}:{contact_id}
                    namespace = f"{self.owner_id}:{self.zylch_assistant_id}:{contact_id}"

                    if not force:
                        conn = sqlite3.connect(str(self.memory.config.db_path))
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT COUNT(*) FROM memories WHERE namespace = ? AND category = 'person'",
                            (namespace,)
                        )
                        exists = cursor.fetchone()[0] > 0
                        conn.close()

                        if exists:
                            skipped += 1
                            continue

                    # Analyze contact using TaskManager
                    # Prepare threads in expected format
                    thread_list = []
                    for thread in threads:
                        thread_list.append({
                            'thread_id': thread['thread_id'],
                            'subject': thread['messages'][0]['subject'],
                            'from_email': contact,
                            'from_name': thread['messages'][0].get('from_name', contact),
                            'date': thread['messages'][-1]['date'],
                            'message_count': len(thread['messages'])
                        })

                    # Call TaskManager to analyze and store
                    result = self.task_manager._analyze_contact_task(contact, thread_list)

                    if result:
                        processed += 1
                    else:
                        failed += 1

                except Exception as e:
                    failed += 1
                    # Don't print error inline, will summarize at end

            print()  # Newline after progress bar
            print()

            # Summary
            print("="*70)
            print("✅ Build completed!\n")
            print(f"📊 Results:")
            print(f"   ✅ Processed: {processed} contacts")
            print(f"   ⏭️  Skipped: {skipped} (already in memory)")
            print(f"   ❌ Failed: {failed}")
            print()
            print(f"💾 Person memories stored in: person:{{email}} namespace")
            print(f"🔍 Test retrieval with: draft_email_from_memory tool")
            print("="*70)

        except Exception as e:
            print(f"\n❌ Error building memories: {e}")
            import traceback
            traceback.print_exc()

    def _handle_cache_command(self, command: str):
        """Handle /cache command.

        Supported commands:
        - /cache --help    - Show help
        - /cache --clear   - Clear entire cache directory
        """
        import shlex

        # Parse command into parts
        parts = command.split(None, 1)
        if len(parts) == 1:
            # Just "/cache" with no args - show help
            print("\n=== 🗄️  Cache Command Help ===\n")
            print("Manage Zylch cache directory")
            print()
            print("Usage:")
            print("  /cache --help    Show this help")
            print("  /cache --clear   Clear entire cache directory")
            print()
            print("Cache contains:")
            print("  - Contact caches (JSON)")
            print("  - Email archive")
            print("  - Calendar cache")
            print("  - Relationship data")
            print("  - Memory database (zylch_memory.db)")
            print()
            return

        # Parse arguments
        args_str = parts[1]
        try:
            args = shlex.split(args_str)
        except ValueError as e:
            print(f"❌ Error parsing arguments: {e}")
            return

        # Extract flags
        flags = {arg for arg in args if arg.startswith('--')}

        # Handle --help
        if '--help' in flags or '-h' in flags:
            print("\n=== 🗄️  Cache Command Help ===\n")
            print("Manage Zylch cache directory")
            print()
            print("Usage:")
            print("  /cache --help    Show this help")
            print("  /cache --clear   Clear entire cache directory")
            print()
            return

        # Handle --clear
        if '--clear' in flags:
            print("⚠️  WARNING: This will delete ALL cache data!")
            print("   This includes:")
            print("   - All contact caches")
            print("   - Email archive")
            print("   - Calendar cache")
            print("   - Memory database (behavioral corrections)")
            print("   - Relationship data")
            print()
            print("   This action cannot be undone.")
            confirm = input("\n   Type 'yes' to confirm: ").strip().lower()

            if confirm == 'yes':
                self._cache_clear()
            else:
                print("❌ Operation cancelled")
        else:
            print("❌ Unknown subcommand")
            print("Use /cache --help to see available commands")

    def _cache_clear(self):
        """Clear entire cache directory."""
        import shutil
        import os
        from pathlib import Path

        try:
            cache_path = Path(settings.cache_dir)

            if not cache_path.exists():
                print("⚠️  Cache directory not found (already empty)")
                return

            # Get directory size before clearing
            total_size = sum(f.stat().st_size for f in cache_path.rglob('*') if f.is_file())
            size_mb = total_size / (1024 * 1024)

            # Remove all contents
            for item in cache_path.iterdir():
                if item.name == '.gitkeep':
                    continue  # Keep .gitkeep
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)

            print(f"✅ Cache cleared successfully!")
            print(f"   Freed {size_mb:.2f} MB")
            print(f"   Location: {cache_path}")

        except Exception as e:
            print(f"❌ Error clearing cache: {e}")

    async def _handle_sync_command(self, days_back: Optional[int] = None):
        """Handle /sync command - run morning sync workflow.

        Args:
            days_back: Optional number of days to sync (default: 30 for emails, 7 for gaps)
        """
        from ..services.sync_service import SyncService

        if days_back:
            print(f"\n🌅 Starting sync workflow (last {days_back} days)...\n")
        else:
            print("\n🌅 Starting morning sync workflow...\n")

        # Use service layer for sync
        try:
            sync_service = SyncService()
            results = sync_service.run_full_sync(days_back=days_back or 30)

            # Display results
            if results['email_sync']['success']:
                email_data = results['email_sync']
                print(f"   ✅ Email sync complete: {email_data['new_threads']} new, "
                      f"{email_data['updated_threads']} updated\n")
            else:
                print(f"   ❌ Email sync failed: {results['email_sync'].get('error', 'Unknown error')}\n")

            if results['calendar_sync']['success']:
                cal_data = results['calendar_sync']
                print(f"   ✅ Calendar sync complete: {cal_data['new_events']} new, "
                      f"{cal_data['updated_events']} updated\n")
            else:
                print(f"   ❌ Calendar sync failed: {results['calendar_sync'].get('error', 'Unknown error')}\n")

            if results['gap_analysis']['success']:
                gap_data = results['gap_analysis']
                total_tasks = gap_data['total_tasks']
                print(f"   ✅ Task analysis complete: {total_tasks} TASKS found")
                print(f"      - Email tasks: {gap_data['email_tasks']}")
                print(f"      - Meeting follow-up tasks: {gap_data['meeting_tasks']}")
                print(f"      - Silent contacts: {gap_data['silent_contacts']}\n")
            else:
                print(f"   ❌ Gap analysis failed: {results['gap_analysis'].get('error', 'Unknown error')}\n")

            print("✅ Morning sync complete! Use /gaps to see your briefing.\n")

        except Exception as e:
            print(f"❌ Sync failed: {e}\n")
            logger.exception("Sync command failed")

    def _handle_gaps_command(self):
        """Handle /gaps command - show relationship gaps briefing."""
        from ..services.gap_service import GapService

        # Use service layer to get gaps
        gap_service = GapService()
        gaps = gap_service.get_cached_gaps()

        if not gaps:
            print("\n⚠️  No gap analysis found. Run /sync first to analyze your relationships.\n")
            return

        analyzed_at = gaps.get('analyzed_at', 'unknown')
        print(f"\n📋 RELATIONSHIP BRIEFING")
        print(f"   Analyzed: {analyzed_at}")
        print("=" * 60)

        # Show email tasks (person-level)
        email_tasks = gaps.get('email_tasks', [])
        if email_tasks:
            print("\n📧 EMAIL TASKS (by person):")
            for i, task in enumerate(email_tasks[:15], 1):
                name = task.get('contact_name', 'Unknown')
                email = task.get('contact_email', '')
                thread_count = task.get('thread_count', 1)
                task_desc = task.get('task_description', 'Follow up')
                reason = task.get('reason', '')

                print(f"\n{i}. {name} <{email}>")
                print(f"   💬 {thread_count} conversation{'s' if thread_count != 1 else ''}")
                print(f"   ✅ Task: {task_desc}")
                if reason:
                    print(f"   💡 Why: {reason}")

        # Show meeting follow-up tasks
        meeting_tasks = gaps.get('meeting_followup_tasks', [])
        if meeting_tasks:
            print("\n📅 MEETING FOLLOW-UP TASKS:")
            for i, task in enumerate(meeting_tasks[:5], 1):
                days = task['days_ago']
                time_ago = f"{days} day{'s' if days != 1 else ''} ago"
                print(f"\n{i}. Meeting with {task['contact_name']} ({time_ago})")
                print(f"   📅 {task['meeting_summary']}")
                print(f"   ✉️  No follow-up email sent yet")

        # Show silent contacts
        silent_contacts = gaps.get('silent_contacts', [])
        if silent_contacts:
            print("\n💤 SILENT CONTACTS:")
            for i, contact in enumerate(silent_contacts[:5], 1):
                print(f"\n{i}. {contact['contact_name']}")
                print(f"   📊 {contact['total_interactions']} past interactions ({contact['total_emails']} emails, {contact['total_meetings']} meetings)")
                print(f"   ⏰ {contact['days_silent']} days since last contact")

        # Summary
        total = len(email_tasks) + len(meeting_tasks) + len(silent_contacts)
        if total == 0:
            print("\n✅ All clear! No TASKS found.")
        else:
            print(f"\n📊 SUMMARY: {total} total TASKS")

        print("\n" + "=" * 60 + "\n")

    def _handle_assistant_command(self, command: str):
        """Handle /assistant command - manage Zylch assistants.

        Commands:
            /assistant                      - Show current assistant
            /assistant --list               - List all assistants for this owner
            /assistant --id <assistant_id>  - Switch to a different assistant
            /assistant --create <name>      - Create new assistant
            /assistant --help               - Show this help
        """
        parts = command.split()
        cmd = parts[0] if parts else ""

        if command == "/assistant" or cmd == "/assistant":
            # Show current assistant info
            assistant = self.assistant_manager.get_assistant(self.owner_id, self.zylch_assistant_id)
            print("\n📌 Current Zylch Assistant")
            print("=" * 60)
            print(f"Owner ID: {self.owner_id}")
            print(f"Assistant ID: {self.zylch_assistant_id}")
            if assistant:
                print(f"Name: {assistant.get('name', 'N/A')}")
                print(f"Business type: {assistant.get('business_type', 'N/A')}")
                print(f"MrCall link: {assistant.get('mrcall_assistant_id', 'Not linked')}")
                print(f"Created: {assistant.get('created_at', 'N/A')}")
            else:
                print("⚠️  Assistant not registered in AssistantManager")
            print()

        elif "--help" in command:
            print("\n📘 /assistant Command Help")
            print("=" * 60)
            print("Manage Zylch assistants (completely isolated workspaces)")
            print()
            print("⚠️  NOTE: Currently limited to ONE assistant per owner")
            print()
            print("Usage:")
            print("  /assistant                      - Show current assistant")
            print("  /assistant --list               - List your assistant")
            print("  /assistant --id <assistant_id>  - Switch to different assistant")
            print("  /assistant --create <name>      - Create assistant (blocked if exists)")
            print()
            print("Example:")
            print("  /assistant --create 'My Business'  # Only works if no assistant exists")
            print("  /assistant --id default_assistant")
            print()

        elif "--list" in command:
            assistants = self.assistant_manager.list_assistants(self.owner_id)
            print("\n📋 Your Zylch Assistant")
            print("=" * 60)
            print("⚠️  Single-assistant mode: Only 1 assistant per owner")
            print()
            if assistants:
                for i, asst in enumerate(assistants, 1):
                    active = "✅" if asst['id'] == self.zylch_assistant_id else "  "
                    print(f"{active} {i}. {asst['name']} ({asst['id']})")
                    print(f"      Business: {asst.get('business_type', 'N/A')}")
                    print(f"      MrCall: {asst.get('mrcall_assistant_id', 'Not linked')}")
                    print()
            else:
                print("⚠️  No assistant registered. One will be auto-created on next initialization.")
            print()

        elif "--create" in command:
            # Extract name from command
            name_start = command.find("--create") + 8
            name = command[name_start:].strip().strip('"').strip("'")
            if not name:
                print("❌ Error: Please provide a name")
                print("Usage: /assistant --create <name>")
                print("Example: /assistant --create 'MrCall Business'")
                return

            # Generate assistant ID from name
            asst_id = name.lower().replace(" ", "_").replace("-", "_")
            asst_id = "".join(c for c in asst_id if c.isalnum() or c == "_")

            try:
                assistant = self.assistant_manager.create_assistant(
                    owner_id=self.owner_id,
                    zylch_assistant_id=asst_id,
                    name=name
                )
                print(f"\n✅ Created assistant: {name}")
                print(f"   ID: {asst_id}")
                print(f"   Switch to it with: /assistant --id {asst_id}")
                print()
            except ValueError as e:
                print(f"❌ Error: {e}")

        elif "--id" in command:
            print("⚠️  Switching assistants requires restarting Zylch")
            print("   1. Update ZYLCH_ASSISTANT_ID in .env file")
            print("   2. Restart Zylch CLI")
            print()

        else:
            print("❌ Unknown command. Use /assistant --help for help")

    def _handle_mrcall_command(self, command: str):
        """Handle /mrcall command - manage MrCall assistant link.

        Commands:
            /mrcall                - Show current MrCall link
            /mrcall --list         - List available MrCall assistants from StarChat
            /mrcall --id <id>      - Link to a MrCall assistant
            /mrcall --help         - Show this help
        """
        parts = command.split()

        if "--help" in command:
            print("\n📘 /mrcall Command Help")
            print("=" * 60)
            print("Link your Zylch assistant to a MrCall/StarChat assistant")
            print()
            print("Usage:")
            print("  /mrcall                - Show current link")
            print("  /mrcall <id>           - Link to MrCall assistant (shortcut)")
            print("  /mrcall --id <id>      - Link to MrCall assistant")
            print("  /mrcall --list         - List available MrCall assistants")
            print()
            print("Example:")
            print("  /mrcall 3002475397")
            print("  /mrcall --id hahnbanach_personal")
            print()

        elif "--list" in command:
            # TODO: Call StarChat API to list available assistants
            print("\n📋 Available MrCall Assistants")
            print("=" * 60)
            print("⚠️  Feature coming soon - requires StarChat API integration")
            print("For now, use: /mrcall --id <assistant_id>")
            print()

        elif "--id" in command:
            # Extract ID
            id_start = command.find("--id") + 4
            mrcall_id = command[id_start:].strip()
            if not mrcall_id:
                print("❌ Error: Please provide an assistant ID")
                print("Usage: /mrcall --id <assistant_id>")
                return

            self.current_business_id = mrcall_id
            # Update session state so tools see the new value immediately
            if hasattr(self, 'session_state') and self.session_state:
                self.session_state.set_business_id(mrcall_id)

            # Update AssistantManager
            try:
                self.assistant_manager.link_mrcall_assistant(
                    self.owner_id,
                    self.zylch_assistant_id,
                    mrcall_id
                )
                print(f"\n✅ Linked to MrCall assistant: {mrcall_id}")
                print(f"   All enriched contacts will be saved to this assistant")
                print()
            except Exception as e:
                print(f"⚠️  Warning: Could not update AssistantManager: {e}")
                print(f"   But current session is now linked to: {mrcall_id}")
                print()

        elif len(parts) == 2 and not parts[1].startswith("-"):
            # Direct ID: /mrcall <id>
            mrcall_id = parts[1]
            self.current_business_id = mrcall_id
            # Update session state so tools see the new value immediately
            if hasattr(self, 'session_state') and self.session_state:
                self.session_state.set_business_id(mrcall_id)

            # Update AssistantManager
            try:
                self.assistant_manager.link_mrcall_assistant(
                    self.owner_id,
                    self.zylch_assistant_id,
                    mrcall_id
                )
                print(f"\n✅ Linked to MrCall assistant: {mrcall_id}")
                print(f"   All enriched contacts will be saved to this assistant")
                print()
            except Exception as e:
                print(f"⚠️  Warning: Could not update AssistantManager: {e}")
                print(f"   But current session is now linked to: {mrcall_id}")
                print()

        elif len(parts) == 1:
            # Just /mrcall - show current link
            print("\n📞 MrCall Assistant Link")
            print("=" * 60)
            if self.current_business_id:
                print(f"Linked to: {self.current_business_id}")
                print("All enriched contacts will be saved to this MrCall assistant")
            else:
                print("⚠️  Not linked to any MrCall assistant")
                print("Use: /mrcall --id <assistant_id>")
            print()

        else:
            print("❌ Unknown command. Use /mrcall --help for help")

    def _handle_model_command(self, command: str):
        """Handle /model command - change AI model at runtime.

        Commands:
            /model              - Show current model
            /model haiku        - Switch to Haiku (fast, cheap)
            /model sonnet       - Switch to Sonnet (balanced)
            /model opus         - Switch to Opus (premium)
            /model auto         - Reset to automatic selection
            /model --help       - Show this help
        """
        parts = command.split()

        # Model name mappings
        model_map = {
            "haiku": "claude-3-5-haiku-20241022",
            "sonnet": "claude-sonnet-4-20250514",
            "opus": "claude-opus-4-20250514",
        }

        if "--help" in command:
            print("\n📘 /model Command Help")
            print("=" * 60)
            print("Change the AI model used for responses")
            print()
            print("Usage:")
            print("  /model              - Show current model")
            print("  /model haiku        - Fast & cheap (good for bulk searches)")
            print("  /model sonnet       - Balanced (default)")
            print("  /model opus         - Premium quality")
            print("  /model auto         - Reset to automatic selection")
            print()
            print("💡 Tip: Use 'haiku' before expensive operations to save costs")
            print()

        elif len(parts) == 1:
            # Show current model
            print("\n🤖 Current Model")
            print("=" * 60)
            if self.forced_model:
                # Find friendly name
                friendly = next((k for k, v in model_map.items() if v == self.forced_model), self.forced_model)
                print(f"Mode: Manual override")
                print(f"Model: {friendly} ({self.forced_model})")
            else:
                print(f"Mode: Automatic selection")
                print(f"Default: sonnet ({model_map['sonnet']})")
            print()

        elif parts[1].lower() == "auto":
            self.forced_model = None
            print("\n✅ Switched to automatic model selection")
            print("   Model will be chosen based on task type")
            print()

        elif parts[1].lower() in model_map:
            model_name = parts[1].lower()
            self.forced_model = model_map[model_name]
            print(f"\n✅ Switched to {model_name}")
            print(f"   Model: {self.forced_model}")
            if model_name == "haiku":
                print("   💡 Good choice for bulk/expensive operations!")
            print()

        else:
            print(f"❌ Unknown model: {parts[1]}")
            print("Available: haiku, sonnet, opus, auto")

    def _handle_cache_command(self, command: str):
        """Handle /cache command - cache inspection and management.

        Subcommands:
            /cache            - Show cache overview
            /cache --help     - Show help
            /cache emails     - Show email cache details
            /cache calendar   - Show calendar cache details
            /cache gaps       - Show gaps cache details
            /cache --clear emails     - Clear email cache
            /cache --clear calendar   - Clear calendar cache
            /cache --clear gaps       - Clear gaps cache
            /cache --clear all        - Clear all caches
        """
        args = command.split()[1:] if len(command.split()) > 1 else []
        flags = [arg for arg in args if arg.startswith('--')]
        positional = [arg for arg in args if not arg.startswith('--')]

        # Handle --help
        if '--help' in flags or '-h' in flags:
            print("\n📦 CACHE MANAGEMENT")
            print("=" * 60)
            print("\nUsage:")
            print("  /cache              - Show cache overview (all channels)")
            print("  /cache emails       - Show email cache details")
            print("  /cache calendar     - Show calendar cache details")
            print("  /cache gaps         - Show gaps cache details")
            print("\nClear cache:")
            print("  /cache --clear emails     - Clear email cache")
            print("  /cache --clear calendar   - Clear calendar cache")
            print("  /cache --clear gaps       - Clear gaps cache")
            print("  /cache --clear all        - Clear ALL caches")
            print("\n" + "=" * 60 + "\n")
            return

        # Handle --clear
        if '--clear' in flags:
            if not positional:
                print("❌ Usage: /cache --clear <target>")
                print("   Targets: emails, calendar, gaps, all")
                return

            target = positional[0]
            self._clear_cache(target)
            return

        # Default: show cache overview or specific cache
        if positional:
            target = positional[0]
            if target == 'emails':
                self._show_email_cache()
            elif target == 'calendar':
                self._show_calendar_cache()
            elif target == 'gaps':
                self._show_gaps_cache()
            else:
                print(f"❌ Unknown cache: {target}")
                print("   Valid caches: emails, calendar, gaps")
        else:
            # Show overview of all caches
            self._show_cache_overview()

    def _show_cache_overview(self):
        """Show overview of all caches."""
        from ..cache import JSONCache
        cache = JSONCache(cache_dir=settings.cache_dir, ttl_days=settings.cache_ttl_days)

        print("\n📦 CACHE OVERVIEW")
        print("=" * 60)
        print(f"Cache directory: {settings.cache_dir}")
        print(f"TTL: {settings.cache_ttl_days} days")
        print()

        # Email cache
        email_cache_path = Path(settings.cache_dir) / "emails" / "email_threads.json"
        if email_cache_path.exists():
            with open(email_cache_path) as f:
                email_data = json.load(f)
                thread_count = len(email_data.get('threads', {}))
                last_sync = email_data.get('last_sync', 'Never')
                print(f"📧 Email cache: {thread_count} threads (last sync: {last_sync})")
        else:
            print(f"📧 Email cache: Empty")

        # Calendar cache
        cal_cache_path = Path(settings.cache_dir) / "calendar_events.json"
        if cal_cache_path.exists():
            with open(cal_cache_path) as f:
                cal_data = json.load(f)
                event_count = len(cal_data.get('events', []))
                last_sync = cal_data.get('last_sync', 'Never')
                print(f"📅 Calendar cache: {event_count} events (last sync: {last_sync})")
        else:
            print(f"📅 Calendar cache: Empty")

        # Gaps cache
        gaps_cache_path = Path(settings.cache_dir) / "relationship_gaps.json"
        if gaps_cache_path.exists():
            with open(gaps_cache_path) as f:
                gaps_data = json.load(f)
                email_tasks = len(gaps_data.get('email_tasks', []))
                meeting_tasks = len(gaps_data.get('meeting_followup_tasks', []))
                silent = len(gaps_data.get('silent_contacts', []))
                analyzed = gaps_data.get('analyzed_at', 'Never')
                print(f"💡 Gaps cache: {email_tasks + meeting_tasks + silent} tasks (analyzed: {analyzed})")
        else:
            print(f"💡 Gaps cache: Empty")

        print("\n" + "=" * 60 + "\n")

    def _show_email_cache(self):
        """Show email cache details."""
        email_cache_path = Path(settings.cache_dir) / "emails" / "email_threads.json"
        if not email_cache_path.exists():
            print("\n📧 Email cache is empty. Run /sync to populate.\n")
            return

        with open(email_cache_path) as f:
            data = json.load(f)

        threads = data.get('threads', {})
        last_sync = data.get('last_sync', 'Never')

        print("\n📧 EMAIL CACHE DETAILS")
        print("=" * 60)
        print(f"Last sync: {last_sync}")
        print(f"Total threads: {len(threads)}")
        print()

        # Show thread stats
        open_count = sum(1 for t in threads.values() if not t.get('closed', False))
        closed_count = len(threads) - open_count
        print(f"Open threads: {open_count}")
        print(f"Closed threads: {closed_count}")
        print()

        # Show recent threads (first 10)
        sorted_threads = sorted(threads.values(), key=lambda t: t.get('last_date', ''), reverse=True)
        if sorted_threads:
            print("Recent threads:")
            for i, thread in enumerate(sorted_threads[:10], 1):
                subject = thread.get('subject', 'No subject')
                participants = ', '.join(thread.get('participants', []))
                last_date = thread.get('last_date', 'Unknown')
                status = "🔒 Closed" if thread.get('closed') else "📬 Open"
                print(f"{i}. {status} [{last_date}] {subject}")
                print(f"   👥 {participants}")
                print()

        print("=" * 60 + "\n")

    def _show_calendar_cache(self):
        """Show calendar cache details."""
        cal_cache_path = Path(settings.cache_dir) / "calendar_events.json"
        if not cal_cache_path.exists():
            print("\n📅 Calendar cache is empty. Run /sync to populate.\n")
            return

        with open(cal_cache_path) as f:
            data = json.load(f)

        events = data.get('events', [])
        last_sync = data.get('last_sync', 'Never')

        print("\n📅 CALENDAR CACHE DETAILS")
        print("=" * 60)
        print(f"Last sync: {last_sync}")
        print(f"Total events: {len(events)}")
        print()

        # Show upcoming events (first 10)
        from datetime import datetime
        now = datetime.now()
        upcoming = [e for e in events if datetime.fromisoformat(e.get('start', {}).get('dateTime', '').replace('Z', '+00:00')) > now]
        past = [e for e in events if datetime.fromisoformat(e.get('start', {}).get('dateTime', '').replace('Z', '+00:00')) <= now]

        print(f"Upcoming: {len(upcoming)}")
        print(f"Past: {len(past)}")
        print()

        if upcoming:
            print("Next 10 events:")
            for i, event in enumerate(sorted(upcoming, key=lambda e: e.get('start', {}).get('dateTime', ''))[:10], 1):
                summary = event.get('summary', 'No title')
                start = event.get('start', {}).get('dateTime', 'Unknown')
                attendees = ', '.join([a.get('email', '') for a in event.get('attendees', [])])
                print(f"{i}. [{start}] {summary}")
                if attendees:
                    print(f"   👥 {attendees}")
                print()

        print("=" * 60 + "\n")

    def _show_gaps_cache(self):
        """Show gaps cache details."""
        gaps_cache_path = Path(settings.cache_dir) / "relationship_gaps.json"
        if not gaps_cache_path.exists():
            print("\n💡 Gaps cache is empty. Run /sync to populate.\n")
            return

        with open(gaps_cache_path) as f:
            data = json.load(f)

        email_tasks = data.get('email_tasks', [])
        meeting_tasks = data.get('meeting_followup_tasks', [])
        silent_contacts = data.get('silent_contacts', [])
        analyzed_at = data.get('analyzed_at', 'Never')

        print("\n💡 GAPS CACHE DETAILS")
        print("=" * 60)
        print(f"Last analysis: {analyzed_at}")
        print()
        print(f"Email tasks: {len(email_tasks)}")
        print(f"Meeting follow-up tasks: {len(meeting_tasks)}")
        print(f"Silent contacts: {len(silent_contacts)}")
        print(f"Total tasks: {len(email_tasks) + len(meeting_tasks) + len(silent_contacts)}")
        print()
        print("Use /gaps to see the full briefing.")
        print("=" * 60 + "\n")

    def _clear_cache(self, target: str):
        """Clear specified cache."""
        if target == 'emails':
            email_cache_path = Path(settings.cache_dir) / "emails" / "email_threads.json"
            if email_cache_path.exists():
                email_cache_path.unlink()
                print("✅ Email cache cleared")
            else:
                print("⚠️  Email cache already empty")

        elif target == 'calendar':
            cal_cache_path = Path(settings.cache_dir) / "calendar_events.json"
            if cal_cache_path.exists():
                cal_cache_path.unlink()
                print("✅ Calendar cache cleared")
            else:
                print("⚠️  Calendar cache already empty")

        elif target == 'gaps':
            gaps_cache_path = Path(settings.cache_dir) / "relationship_gaps.json"
            if gaps_cache_path.exists():
                gaps_cache_path.unlink()
                print("✅ Gaps cache cleared")
            else:
                print("⚠️  Gaps cache already empty")

        elif target == 'all':
            # Clear all caches
            cleared = []
            email_cache_path = Path(settings.cache_dir) / "emails" / "email_threads.json"
            if email_cache_path.exists():
                email_cache_path.unlink()
                cleared.append('emails')

            cal_cache_path = Path(settings.cache_dir) / "calendar_events.json"
            if cal_cache_path.exists():
                cal_cache_path.unlink()
                cleared.append('calendar')

            gaps_cache_path = Path(settings.cache_dir) / "relationship_gaps.json"
            if gaps_cache_path.exists():
                gaps_cache_path.unlink()
                cleared.append('gaps')

            if cleared:
                print(f"✅ Cleared caches: {', '.join(cleared)}")
            else:
                print("⚠️  All caches already empty")

        else:
            print(f"❌ Unknown cache target: {target}")
            print("   Valid targets: emails, calendar, gaps, all")

    async def _handle_archive_command(self, command: str):
        """Handle /archive command - email archive management.

        Usage:
            /archive                    - Show archive stats (default)
            /archive --help             - Show help
            /archive --stats            - Show archive statistics
            /archive --sync             - Run incremental sync
            /archive --init [months]    - Initialize archive (one-time)
            /archive --search <query> [--limit N]  - Search emails
        """
        parts = command.split()

        if not self.email_archive:
            print("❌ Email archive not initialized")
            return

        # Default: show stats
        if len(parts) == 1:
            parts.append("--stats")

        subcommand = parts[1] if len(parts) > 1 else "--stats"

        if subcommand == "--help":
            print("\n📦 EMAIL ARCHIVE MANAGEMENT")
            print("=" * 60)
            print("\nCommands:")
            print("  /archive                    Show archive statistics")
            print("  /archive --help             Show this help")
            print("  /archive --stats            Show archive statistics")
            print("  /archive --sync             Run incremental sync")
            print("  /archive --init [months]    Initialize archive (one-time)")
            print("  /archive --search <query> [--limit N]")
            print("                              Search archived emails")
            print("\nExamples:")
            print("  /archive")
            print("  /archive --sync")
            print("  /archive --search project --limit 10")
            print("  /archive --init 3")
            print("=" * 60 + "\n")

        elif subcommand == "--stats":
            try:
                stats = self.email_archive.get_stats()
                print("\n📊 ARCHIVE STATISTICS")
                print("=" * 60)
                print(f"Backend: {stats['backend'].upper()}")
                print(f"Location: {stats['db_path']}")
                print(f"\nMessages: {stats['total_messages']:,}")
                print(f"Threads: {stats['total_threads']:,}")
                print(f"\nDate Range:")
                if stats.get('earliest_message'):
                    print(f"  Earliest: {stats['earliest_message']}")
                if stats.get('latest_message'):
                    print(f"  Latest: {stats['latest_message']}")
                print("\n" + "=" * 60 + "\n")
            except Exception as e:
                print(f"❌ Failed to get stats: {e}")
                logger.exception("Archive stats failed")

        elif subcommand == "--sync":
            print("\n🔄 Running incremental archive sync...")
            try:
                result = await self.email_archive.sync_incremental()
                print(f"✅ Sync complete!")
                print(f"   New messages: {result['new_messages']}")
                print(f"   Updated messages: {result['updated_messages']}")
                print()
            except Exception as e:
                print(f"❌ Sync failed: {e}")
                logger.exception("Archive sync failed")

        elif subcommand == "--init":
            # Initialize archive with historical data
            months_back = 12  # default
            if len(parts) > 2:
                try:
                    months_back = int(parts[2])
                except ValueError:
                    print(f"❌ Invalid months value: {parts[2]}")
                    return

            print(f"\n🏗️  Initializing archive (last {months_back} months)...")
            print("⚠️  This is a one-time operation that may take several minutes.")
            confirm = input("Continue? (yes/no): ")
            if confirm.lower() != 'yes':
                print("Cancelled.")
                return

            try:
                result = await self.email_archive.initialize_archive(months_back=months_back)
                print(f"\n✅ Archive initialized!")
                print(f"   Messages archived: {result['messages_archived']}")
                print(f"   Threads created: {result['threads_created']}")
                print()
            except Exception as e:
                print(f"❌ Initialization failed: {e}")
                logger.exception("Archive init failed")

        elif subcommand == "--search":
            # Search archive
            if len(parts) < 3:
                print("❌ Usage: /archive --search <query> [--limit N]")
                return

            # Parse query and optional limit
            query_parts = []
            limit = 20  # default
            i = 2
            while i < len(parts):
                if parts[i] == "--limit":
                    if i + 1 < len(parts):
                        try:
                            limit = int(parts[i + 1])
                            i += 2
                        except ValueError:
                            print(f"❌ Invalid limit: {parts[i + 1]}")
                            return
                    else:
                        print("❌ --limit requires a value")
                        return
                else:
                    query_parts.append(parts[i])
                    i += 1

            query = ' '.join(query_parts)
            print(f"\n🔍 Searching archive for: '{query}'")
            print(f"   Limit: {limit} results\n")

            try:
                results = await self.email_archive.search_messages(query=query, limit=limit)
                if not results:
                    print("No results found.\n")
                    return

                print(f"Found {len(results)} message(s):\n")
                for i, msg in enumerate(results, 1):
                    print(f"{i}. From: {msg.get('from', 'Unknown')}")
                    print(f"   To: {msg.get('to', 'Unknown')}")
                    print(f"   Subject: {msg.get('subject', 'No subject')}")
                    print(f"   Date: {msg.get('date', 'Unknown')}")
                    print(f"   Snippet: {msg.get('snippet', '')[:150]}...")
                    print()

            except Exception as e:
                print(f"❌ Search failed: {e}")
                logger.exception("Archive search failed")

        else:
            print(f"❌ Unknown subcommand: {subcommand}")
            print("Use /archive --help for available commands")

    async def handle_command(self, command: str):
        """Handle CLI commands.

        Args:
            command: Command string
        """
        cmd = command.lower().strip()

        if cmd == "/help":
            self.print_welcome()

        elif cmd.startswith("/mrcall"):
            self._handle_mrcall_command(command)

        elif cmd.startswith("/assistant"):
            self._handle_assistant_command(command)

        elif cmd == "/clear":
            self.agent.clear_history()
            print("✅ Conversation history cleared")

        elif cmd == "/history":
            history = self.agent.get_history()
            if not history:
                print("No conversation history")
            else:
                print("\n=== Conversation History ===")
                for i, turn in enumerate(history, 1):
                    role = turn["role"].capitalize()
                    content = turn["content"]
                    if isinstance(content, str):
                        print(f"\n{i}. {role}: {content[:100]}...")
                    else:
                        print(f"\n{i}. {role}: [Tool use]")
                print()

        elif cmd == "/quit" or cmd == "/exit":
            self.running = False

        elif cmd.startswith("/memory"):
            # Unix-style memory subcommands: /memory --help, /memory --add, /memory --list, etc.
            self._handle_memory_command(command)

        elif cmd.startswith("/cache"):
            # Cache management command
            self._handle_cache_command(command)

        elif cmd.startswith("/model"):
            # Model selection command
            self._handle_model_command(command)

        elif cmd.startswith("/sync"):
            # Morning sync workflow
            # Parse optional days parameter: /sync 3 (last 3 days)
            parts = command.split()
            days = None
            if len(parts) > 1:
                try:
                    days = int(parts[1])
                except ValueError:
                    print(f"❌ Invalid days parameter: {parts[1]}")
                    print("Usage: /sync [days]")
                    print("Example: /sync 3  (sync last 3 days)")
                    return
            await self._handle_sync_command(days_back=days)

        elif cmd == "/gaps" or cmd == "/briefing":
            # Show relationship gaps
            self._handle_gaps_command()

        elif cmd.startswith("/cache"):
            # Cache management
            self._handle_cache_command(command)

        elif cmd.startswith("/archive"):
            # Email archive management
            await self._handle_archive_command(command)

        else:
            print(f"Unknown command: {cmd}")
            print("Type /help for available commands")


def main():
    """Entry point for Zylch AI CLI."""
    cli = ZylchAICLI()

    try:
        asyncio.run(cli.run())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
