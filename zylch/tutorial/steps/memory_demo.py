"""Memory & Learning tutorial step."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tutorial_manager import TutorialManager


class MemoryDemoStep:
    """Tutorial step demonstrating the memory and learning system."""

    def __init__(self, manager: "TutorialManager"):
        self.manager = manager

    async def run(self):
        """Run the memory demo."""
        self.manager._print()
        self.manager._print_box("🧠 MEMORY & LEARNING", [
            "",
            "The more you use Zylch, the better it gets.",
            "Corrections become automatic preferences.",
            "",
        ])

        self.manager._print()
        self.manager._print("Zylch learns:")
        self.manager._print("  • Your relationships (family, colleagues, clients)")
        self.manager._print("  • Your preferences (email style, meeting times)")
        self.manager._print("  • Your patterns (how you work, who matters)")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📋 DEMO: Learning from conversation...")
        self.manager._print()

        self.manager._print("  Example 1: Learning relationships")
        self.manager._print("  ─────────────────────────────────")
        self.manager._print('  You: "Write to my sister Francesca..."')
        self.manager._print("  → Zylch learns: Francesca is your sister")
        self.manager._print()
        self.manager._print("  Later...")
        self.manager._print('  You: "Message Francesca"')
        self.manager._print('  Zylch: "Writing to your sister Francesca?"')
        self.manager._print()

        self.manager._print("  Example 2: Learning style preferences")
        self.manager._print("  ─────────────────────────────────────")
        self.manager._print("  Zylch drafts a long, formal email")
        self.manager._print('  You: "Too long, I write short emails"')
        self.manager._print("  → Zylch remembers: You prefer short emails")
        self.manager._print()
        self.manager._print("  Next time...")
        self.manager._print("  Zylch automatically drafts shorter emails")
        self.manager._print()

        self.manager._print("  Example 3: Learning priorities")
        self.manager._print("  ──────────────────────────────")
        self.manager._print('  You: "Elena is VIP, always prioritize her"')
        self.manager._print("  → Zylch remembers: Elena is high priority")
        self.manager._print()
        self.manager._print("  In your briefings...")
        self.manager._print("  Elena's emails always appear first")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📝 DEMO: Managing memories...")
        self.manager._print()
        self.manager._print("  /memory --list           Show what Zylch remembers")
        self.manager._print("  /memory --channel email  Show email preferences only")
        self.manager._print("  /memory --delete <id>    Remove a specific memory")
        self.manager._print()

        self.manager._print("  Example output of /memory --list:")
        self.manager._print("  ┌────────────────────────────────────────────────────┐")
        self.manager._print("  │ Your Preferences (3 items)                         │")
        self.manager._print("  │ ────────────────────────────────────────────────── │")
        self.manager._print("  │ 1. [email] Prefer short, direct emails             │")
        self.manager._print("  │ 2. [email] Elena Verdi is VIP - prioritize         │")
        self.manager._print("  │ 3. [calendar] No meetings before 9am               │")
        self.manager._print("  └────────────────────────────────────────────────────┘")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("💡 TIP: Just be yourself! Zylch learns from normal conversation.")
        self.manager._print("       Say what you want naturally, and Zylch adapts to you.")
        self.manager._print()
