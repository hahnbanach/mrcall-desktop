"""Email Management tutorial step."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tutorial_manager import TutorialManager

from ..sandbox.mock_data import MOCK_EMAILS


class EmailDemoStep:
    """Tutorial step demonstrating email management features."""

    def __init__(self, manager: "TutorialManager"):
        self.manager = manager

    async def run(self):
        """Run the email management demo."""
        self.manager._print()
        self.manager._print_box("📧 EMAIL MANAGEMENT", [
            "",
            "Zylch helps you write better emails faster.",
            "",
            "  • Draft emails in your style",
            "  • Find any conversation instantly",
            "  • Reply with full context",
            "",
        ])

        self.manager._print()
        self.manager._print("Try asking things like:")
        self.manager._print('  • "Write a follow-up to Marco about the proposal"')
        self.manager._print('  • "Find emails about the Q4 budget"')
        self.manager._print('  • "Reply to Sofia saying yes to Thursday"')
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📋 DEMO: Emails needing your attention...")
        self.manager._print()

        priority_count = 1
        for email in MOCK_EMAILS:
            if email.get("needs_reply"):
                self.manager._print(f"  {priority_count}. From: {email['from_name']}")
                self.manager._print(f"     Subject: {email['subject']}")
                self.manager._print(f"     {email['snippet'][:50]}...")
                self.manager._print(f"     📅 {email['date']} | Priority: {email['priority']}")
                self.manager._print()
                priority_count += 1

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📝 DEMO: Drafting a reply...")
        self.manager._print()
        self.manager._print('  You say: "Reply to Marco with some questions about timeline"')
        self.manager._print()
        self.manager._print("  Zylch drafts:")
        self.manager._print("  ┌────────────────────────────────────────────────────┐")
        self.manager._print("  │ To: marco.ferrari@techcorp.example.com             │")
        self.manager._print("  │ Subject: Re: Q4 Proposal - Ready for Review        │")
        self.manager._print("  │ ────────────────────────────────────────────────── │")
        self.manager._print("  │ Hi Marco,                                          │")
        self.manager._print("  │                                                    │")
        self.manager._print("  │ Thanks for the proposal review. A few questions:   │")
        self.manager._print("  │                                                    │")
        self.manager._print("  │ 1. What's your target go-live date?                │")
        self.manager._print("  │ 2. Any flexibility on the Q1 milestones?           │")
        self.manager._print("  │                                                    │")
        self.manager._print("  │ Let's discuss tomorrow during our call.            │")
        self.manager._print("  │                                                    │")
        self.manager._print("  │ Best,                                              │")
        self.manager._print("  └────────────────────────────────────────────────────┘")
        self.manager._print()
        self.manager._print('  You can say: "Save it" → saved to Gmail drafts')
        self.manager._print('              "Send it" → sends immediately')
        self.manager._print('              "Make it shorter" → Zylch revises')
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("💡 TIP: The more you use Zylch, the better it matches your style.")
        self.manager._print("       Correct drafts and Zylch remembers for next time.")
        self.manager._print()
