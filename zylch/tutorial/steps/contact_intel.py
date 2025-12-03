"""Contact Intelligence tutorial step."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tutorial_manager import TutorialManager

from ..sandbox.mock_data import get_mock_contact, get_mock_email_thread, MOCK_EVENTS


class ContactIntelStep:
    """Tutorial step demonstrating contact intelligence features."""

    def __init__(self, manager: "TutorialManager"):
        self.manager = manager

    async def run(self):
        """Run the contact intelligence demo."""
        self.manager._print()
        self.manager._print_box("👤 CONTACT INTELLIGENCE", [
            "",
            "Zylch knows everyone you know - across all channels.",
            "",
            "Instead of searching emails, calendar, and phone separately,",
            "just ask about anyone and get the complete picture.",
            "",
        ])

        self.manager._print()
        self.manager._print("Try asking things like:")
        self.manager._print('  • "What\'s happening with Marco?"')
        self.manager._print('  • "Tell me about Sofia Bianchi"')
        self.manager._print('  • "Who haven\'t I talked to recently?"')
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📋 DEMO: Let me show you with Marco Ferrari...")
        self.manager._print()

        # Get mock data
        contact = get_mock_contact("Marco")
        emails = get_mock_email_thread("Marco")
        events = [e for e in MOCK_EVENTS if "Marco" in str(e.get("attendees", []))]

        if contact:
            self.manager._print(f"  👤 {contact['name']}")
            self.manager._print(f"     📧 {contact['email']}")
            self.manager._print(f"     📱 {contact['phone']}")
            self.manager._print(f"     🏢 {contact['role']} @ {contact['company']}")
            self.manager._print(f"     📅 Last contact: {contact['last_contact']}")
            self.manager._print(f"     📊 Relationship: {contact['relationship']}")
            self.manager._print()

            if emails:
                self.manager._print("  Recent activity:")
                for email in emails[:2]:
                    reply_flag = " (needs reply)" if email.get("needs_reply") else ""
                    self.manager._print(f"    • Email: \"{email['subject']}\"{reply_flag}")

            if events:
                for event in events[:1]:
                    meet = " (Meet link)" if event.get("has_meet_link") else ""
                    self.manager._print(f"    • Meeting: {event['title']} - {event['date']}{meet}")

            self.manager._print()
            if contact.get("notes"):
                self.manager._print(f"  💡 Note: {contact['notes']}")

        self.manager._print()
        self.manager._print_divider()
        self.manager._print()
        self.manager._print("💡 TIP: Just ask naturally! Zylch understands context.")
        self.manager._print('       "Marco from TechCorp" or just "Marco" both work.')
        self.manager._print()
