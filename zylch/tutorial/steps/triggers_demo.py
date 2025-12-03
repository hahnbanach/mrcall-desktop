"""Triggered Instructions tutorial step."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tutorial_manager import TutorialManager


class TriggersDemoStep:
    """Tutorial step demonstrating the triggered instructions system."""

    def __init__(self, manager: "TutorialManager"):
        self.manager = manager

    async def run(self):
        """Run the triggers demo."""
        self.manager._print()
        self.manager._print_box("🎯 TRIGGERED INSTRUCTIONS", [
            "",
            "Create event-driven automation that executes",
            "when specific triggers occur.",
            "",
        ])

        self.manager._print()
        self.manager._print("What are Triggered Instructions?")
        self.manager._print("  • Event-driven automation rules")
        self.manager._print("  • Execute when specific events happen")
        self.manager._print("  • Different from behavioral memory (which is always-on)")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📋 AVAILABLE TRIGGER TYPES")
        self.manager._print()

        self.manager._print("  session_start    - When a new CLI/API session starts")
        self.manager._print("                     Example: 'Greet me with today's date and time'")
        self.manager._print()

        self.manager._print("  email_received   - When a new email arrives")
        self.manager._print("                     Example: 'Create contact for unknown senders'")
        self.manager._print()

        self.manager._print("  sms_received     - When a new SMS arrives")
        self.manager._print("                     Example: 'Log all SMS in my calendar'")
        self.manager._print()

        self.manager._print("  call_received    - When a new call is received")
        self.manager._print("                     Example: 'Send follow-up email after calls'")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📝 EXAMPLE: Session Start Greeting")
        self.manager._print()

        self.manager._print("  Command:")
        self.manager._print("  /trigger --add")
        self.manager._print()
        self.manager._print("  Interactive prompts:")
        self.manager._print("  1. Select trigger type: session_start")
        self.manager._print("  2. Enter instruction: 'Greet me at the start of every session")
        self.manager._print("                         with Good morning, today is [date] and")
        self.manager._print("                         the time is [time]'")
        self.manager._print("  3. Enter name: Morning greeting")
        self.manager._print()
        self.manager._print("  Result:")
        self.manager._print("  → Every time you start a CLI session, Zylch greets you")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("📝 EXAMPLE: Email Auto-Contact Creation")
        self.manager._print()

        self.manager._print("  Instruction: 'When a new email arrives from someone I don't")
        self.manager._print("                know, automatically create a contact for them'")
        self.manager._print()
        self.manager._print("  Trigger type: email_received")
        self.manager._print()
        self.manager._print("  Result:")
        self.manager._print("  → New email from unknown sender → Contact auto-created")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("🛠️  MANAGING TRIGGERED INSTRUCTIONS")
        self.manager._print()

        self.manager._print("  /trigger --help          Show help")
        self.manager._print("  /trigger --list          List all triggered instructions")
        self.manager._print("  /trigger --types         Show available trigger types")
        self.manager._print("  /trigger --add           Add new triggered instruction (interactive)")
        self.manager._print("  /trigger --remove <id>   Remove a triggered instruction")
        self.manager._print()

        self.manager._print("  Example output of /trigger --list:")
        self.manager._print("  ┌────────────────────────────────────────────────────┐")
        self.manager._print("  │ Triggered Instructions (2)                         │")
        self.manager._print("  │ ────────────────────────────────────────────────── │")
        self.manager._print("  │ ID: trigger_abc123                                 │")
        self.manager._print("  │    Name: Morning greeting                          │")
        self.manager._print("  │    Trigger: session_start                          │")
        self.manager._print("  │    Instruction: Greet me at the start of every...  │")
        self.manager._print("  │                                                    │")
        self.manager._print("  │ ID: trigger_def456                                 │")
        self.manager._print("  │    Name: Auto-create contacts                      │")
        self.manager._print("  │    Trigger: email_received                         │")
        self.manager._print("  │    Instruction: When email from unknown sender...  │")
        self.manager._print("  └────────────────────────────────────────────────────┘")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("🔄 DIFFERENCE: Triggered Instructions vs Behavioral Memory")
        self.manager._print()

        self.manager._print("  Behavioral Memory (/memory):")
        self.manager._print("    • Always-on rules that guide Zylch's behavior")
        self.manager._print("    • Example: 'Always use formal tone in business emails'")
        self.manager._print("    • Example: 'Prefer concise communication'")
        self.manager._print()

        self.manager._print("  Triggered Instructions (/trigger):")
        self.manager._print("    • Event-driven automation")
        self.manager._print("    • Execute when specific events occur")
        self.manager._print("    • Example: 'Greet me at session start'")
        self.manager._print("    • Example: 'Auto-create contacts from new emails'")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("💡 TIP: Use triggered instructions to automate repetitive tasks")
        self.manager._print("       that should happen when specific events occur!")
        self.manager._print()
