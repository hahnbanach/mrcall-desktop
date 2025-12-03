"""Overview tutorial step - Welcome and introduction."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tutorial_manager import TutorialManager


class OverviewStep:
    """Welcome and overview step for the tutorial."""

    def __init__(self, manager: "TutorialManager"):
        self.manager = manager

    async def run(self):
        """Run the overview step."""
        self.manager._print()
        self.manager._print_box("👋 WELCOME TO ZYLCH AI", [
            "",
            "Hi! I'm Zylch AI, your personal intelligence assistant.",
            "",
            "I help you:",
            "  • Know everyone you know (across all channels)",
            "  • Write emails faster (in your style)",
            "  • Stay on top of your calendar",
            "  • Never miss an important follow-up",
            "  • Remember your preferences automatically",
            "",
            "The best part? Just talk naturally.",
            "No special commands needed for most things.",
            "",
        ])

        self.manager._print()
        self.manager._print("💡 Quick examples of what you can ask:")
        self.manager._print()
        self.manager._print('  "What\'s happening with Marco?"')
        self.manager._print('  "Write a follow-up to Sofia about the project"')
        self.manager._print('  "Schedule a call with Elena for tomorrow"')
        self.manager._print('  "What emails need my attention?"')
        self.manager._print()

        self.manager._print("📌 Useful commands:")
        self.manager._print()
        self.manager._print("  /sync    - Get your daily briefing")
        self.manager._print("  /gaps    - See who needs attention")
        self.manager._print("  /help    - See all commands")
        self.manager._print()
