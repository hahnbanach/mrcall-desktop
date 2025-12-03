"""Daily Briefing (Sync) tutorial step."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tutorial_manager import TutorialManager

from ..sandbox.mock_data import get_mock_briefing


class SyncDemoStep:
    """Tutorial step demonstrating the daily briefing feature."""

    def __init__(self, manager: "TutorialManager"):
        self.manager = manager

    async def run(self):
        """Run the sync/briefing demo."""
        self.manager._print()
        self.manager._print_box("🌅 DAILY BRIEFING", [
            "",
            "Start each day knowing what needs your attention.",
            "",
            "Commands:",
            "  /sync  - Full morning briefing",
            "  /gaps  - Relationship gaps only",
            "",
        ])

        self.manager._print()
        self.manager._print("Zylch identifies:")
        self.manager._print("  • Priority emails needing response")
        self.manager._print("  • Follow-ups you should send")
        self.manager._print("  • Contacts going silent")
        self.manager._print("  • Meetings without follow-up")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📋 DEMO: Your morning briefing (/sync)...")
        self.manager._print()

        briefing = get_mock_briefing()

        self.manager._print(f"  Good morning! Here's your briefing for {briefing['date']}:")
        self.manager._print()

        # Meetings
        self.manager._print(f"  📅 TODAY'S CALENDAR ({len(briefing['meetings_today'])} meetings):")
        for event in briefing["meetings_today"]:
            time = event["date"].split()[-1] if event["date"] else ""
            self.manager._print(f"     • {time} - {event['title']}")
        self.manager._print()

        # Priority emails
        self.manager._print(f"  📧 NEEDS YOUR ATTENTION:")
        for i, email in enumerate(briefing["priority_emails"], 1):
            self.manager._print(f"     {i}. {email['from_name']} - {email['subject'][:30]}...")
        self.manager._print()

        # Tasks
        self.manager._print(f"  ✅ PENDING TASKS:")
        for task in briefing["pending_tasks"]:
            self.manager._print(f"     • {task['description']} ({task['due']})")
        self.manager._print()

        # Relationship gaps
        if briefing["relationship_gaps"]:
            self.manager._print(f"  ⚠️  RELATIONSHIP GAPS:")
            for gap in briefing["relationship_gaps"]:
                self.manager._print(f"     • {gap['contact']}: Last contact {gap['last_contact']}")
                self.manager._print(f"       Usually: {gap['usual_frequency']}")
                self.manager._print(f"       Suggestion: {gap['suggestion']}")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("💡 TIP: Run /sync every morning to stay on top of things.")
        self.manager._print("       Check /gaps weekly to catch relationship drift early.")
        self.manager._print()
