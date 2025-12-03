"""Calendar Integration tutorial step."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tutorial_manager import TutorialManager

from ..sandbox.mock_data import MOCK_EVENTS


class CalendarDemoStep:
    """Tutorial step demonstrating calendar integration features."""

    def __init__(self, manager: "TutorialManager"):
        self.manager = manager

    async def run(self):
        """Run the calendar demo."""
        self.manager._print()
        self.manager._print_box("📅 CALENDAR INTEGRATION", [
            "",
            "Schedule meetings with context - Zylch knows who and why.",
            "",
            "  • Create meetings naturally",
            "  • Auto-add Google Meet links",
            "  • See meeting context at a glance",
            "",
        ])

        self.manager._print()
        self.manager._print("Try asking things like:")
        self.manager._print('  • "Schedule a call with Marco for Tuesday at 10"')
        self.manager._print('  • "Add a Meet link to my meeting tomorrow"')
        self.manager._print('  • "What meetings do I have this week?"')
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📋 DEMO: Your upcoming meetings...")
        self.manager._print()

        for event in MOCK_EVENTS[:3]:
            meet_icon = "📹" if event.get("has_meet_link") else "📍"
            self.manager._print(f"  {meet_icon} {event['title']}")
            self.manager._print(f"     📅 {event['date']} - {event.get('end_time', '').split()[-1] if event.get('end_time') else ''}")
            if event.get("attendees"):
                attendee_names = [a.split("@")[0].replace(".", " ").title() for a in event["attendees"]]
                self.manager._print(f"     👥 {', '.join(attendee_names)}")
            if event.get("has_meet_link"):
                self.manager._print(f"     🔗 {event.get('meet_link', 'Meet link attached')}")
            self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📝 DEMO: Creating a meeting from email...")
        self.manager._print()
        self.manager._print('  You say: "Set up the meeting Sofia proposed in her email"')
        self.manager._print()
        self.manager._print("  Zylch:")
        self.manager._print("  1. Finds Sofia's email mentioning a meeting")
        self.manager._print("  2. Extracts proposed time (Thursday 11:00)")
        self.manager._print("  3. Creates calendar event with Sofia as attendee")
        self.manager._print("  4. Adds Google Meet link automatically")
        self.manager._print()
        self.manager._print("  ✅ Created: 'Campaign Review with Sofia'")
        self.manager._print("     Thursday 11:00 - 12:00")
        self.manager._print("     Meet link: meet.google.com/xxx-yyyy-zzz")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("💡 TIP: Zylch adds context to meetings, so you know")
        self.manager._print("       why you're meeting and what you've discussed before.")
        self.manager._print()
