"""Tutorial Manager - Orchestrates the interactive tutorial experience."""

import asyncio
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..cli.main import ZylchCLI

from .steps import (
    OverviewStep,
    ContactIntelStep,
    EmailDemoStep,
    CalendarDemoStep,
    SyncDemoStep,
    MemoryDemoStep,
    TriggersDemoStep,
    AutomationDemoStep,
)


class TutorialManager:
    """Manages the interactive tutorial flow."""

    TOPICS = {
        "1": ("contact", "Contact Intelligence", ContactIntelStep),
        "2": ("email", "Email Management", EmailDemoStep),
        "3": ("calendar", "Calendar & Meetings", CalendarDemoStep),
        "4": ("sync", "Daily Briefing", SyncDemoStep),
        "5": ("memory", "Memory & Learning", MemoryDemoStep),
        "6": ("triggers", "Triggered Instructions", TriggersDemoStep),
        "7": ("automation", "Automation & Reminders", AutomationDemoStep),
    }

    def __init__(self, cli: "ZylchCLI"):
        """Initialize tutorial manager.

        Args:
            cli: Reference to the ZylchCLI instance for output
        """
        self.cli = cli
        self.current_step = None
        self._running = False

    def _print(self, text: str = ""):
        """Print text to CLI."""
        print(text)

    def _print_box(self, title: str, content: list[str], width: int = 65):
        """Print a formatted box with title and content."""
        border = "─" * (width - 2)
        self._print(f"┌{border}┐")
        self._print(f"│ {title:<{width-4}} │")
        self._print(f"├{border}┤")
        for line in content:
            # Handle lines that are too long
            while len(line) > width - 4:
                self._print(f"│ {line[:width-4]} │")
                line = line[width - 4 :]
            self._print(f"│ {line:<{width-4}} │")
        self._print(f"└{border}┘")

    def _print_divider(self, char: str = "─", width: int = 65):
        """Print a divider line."""
        self._print(char * width)

    async def start(self, topic: Optional[str] = None):
        """Start the tutorial.

        Args:
            topic: Optional specific topic to jump to
        """
        self._running = True

        # If specific topic requested, go directly there
        if topic:
            await self._run_topic(topic)
            return

        # Show welcome and overview first
        await self._show_welcome()

        # Then show menu
        while self._running:
            choice = await self._show_menu()
            if choice == "0":
                self._running = False
                self._print("\n👋 Tutorial ended. Type /help to see all commands.\n")
                break
            elif choice == "8":
                # Full tour
                await self._run_full_tour()
            elif choice in self.TOPICS:
                _, _, step_class = self.TOPICS[choice]
                await self._run_step(step_class)
            else:
                self._print("Invalid choice. Please try again.")

    async def _show_welcome(self):
        """Show welcome screen."""
        overview = OverviewStep(self)
        await overview.run()

    async def _show_menu(self) -> str:
        """Show interactive menu and get user choice."""
        self._print()
        self._print_box("📚 TUTORIAL MENU", [
            "",
            "Choose a topic to explore:",
            "",
            "  1. 👤 Contact Intelligence",
            "  2. 📧 Email Management",
            "  3. 📅 Calendar & Meetings",
            "  4. 🌅 Daily Briefing",
            "  5. 🧠 Memory & Learning",
            "  6. 🎯 Triggered Instructions",
            "  7. ⚡ Automation & Reminders",
            "",
            "  8. 🚀 Full Tour (all topics)",
            "  0. Exit tutorial",
            "",
        ])

        try:
            choice = input("\nYour choice [0-8]: ").strip()
            return choice
        except (EOFError, KeyboardInterrupt):
            return "0"

    async def _run_step(self, step_class):
        """Run a single tutorial step."""
        step = step_class(self)
        await step.run()
        self._wait_for_continue()

    async def _run_topic(self, topic: str):
        """Run a specific topic by name."""
        topic_lower = topic.lower()
        for key, (name, _, step_class) in self.TOPICS.items():
            if topic_lower in name.lower() or topic_lower == name:
                await self._run_step(step_class)
                return

        self._print(f"Topic '{topic}' not found. Available topics:")
        for key, (name, title, _) in self.TOPICS.items():
            self._print(f"  {key}. {title}")

    async def _run_full_tour(self):
        """Run the complete tutorial tour."""
        self._print("\n🚀 Starting full tour...\n")

        for key in sorted(self.TOPICS.keys()):
            _, title, step_class = self.TOPICS[key]
            self._print(f"\n{'='*65}")
            self._print(f"  {title}")
            self._print(f"{'='*65}\n")

            step = step_class(self)
            await step.run()

            if not self._running:
                break

            self._print("\n" + "─" * 65)
            try:
                response = input("Press Enter to continue, or 'q' to quit tour: ").strip()
                if response.lower() == 'q':
                    break
            except (EOFError, KeyboardInterrupt):
                break

        self._print("\n✅ Tour complete! You now know the essentials of Zylch AI.")
        self._print("Type /help to see all commands, or just start asking questions.\n")

    def _wait_for_continue(self):
        """Wait for user to press Enter."""
        try:
            input("\n[Press Enter to return to menu]")
        except (EOFError, KeyboardInterrupt):
            pass
