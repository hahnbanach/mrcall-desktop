"""Automation & Reminders tutorial step."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tutorial_manager import TutorialManager


class AutomationDemoStep:
    """Tutorial step demonstrating automation features."""

    def __init__(self, manager: "TutorialManager"):
        self.manager = manager

    async def run(self):
        """Run the automation demo."""
        self.manager._print()
        self.manager._print_box("⚡ AUTOMATION & REMINDERS", [
            "",
            "Zylch can work for you even when you're not here.",
            "Set instructions, schedule reminders, send messages.",
            "",
        ])

        # Standing Instructions
        self.manager._print()
        self.manager._print("━━━ STANDING INSTRUCTIONS ━━━")
        self.manager._print()
        self.manager._print("  Give Zylch persistent rules that apply to every conversation.")
        self.manager._print()
        self.manager._print("  Examples:")
        self.manager._print('  • "Rispondi sempre in italiano"')
        self.manager._print('  • "Quando scrivo a clienti, usa tono formale"')
        self.manager._print('  • "Marco Rossi e\' VIP, prioritizza sempre"')
        self.manager._print('  • "Non schedulare mai meeting prima delle 10"')
        self.manager._print()
        self.manager._print("  Commands:")
        self.manager._print('  You: "Aggiungi istruzione: firma le email come Dott. Bianchi"')
        self.manager._print('  You: "Mostra le mie istruzioni"')
        self.manager._print('  You: "Rimuovi l\'istruzione sulla firma"')
        self.manager._print()

        self.manager._print_divider()

        # Reminders
        self.manager._print()
        self.manager._print("━━━ REMINDERS & SCHEDULING ━━━")
        self.manager._print()
        self.manager._print("  Zylch can remind you of things at specific times.")
        self.manager._print()
        self.manager._print("  Examples:")
        self.manager._print('  • "Ricordami tra 30 minuti di chiamare Luigi"')
        self.manager._print('  • "Ricordami domani alle 9 di inviare il preventivo"')
        self.manager._print('  • "Se Mario non risponde entro 24 ore, ricordamelo"')
        self.manager._print()
        self.manager._print("  Commands:")
        self.manager._print('  You: "Mostra i miei reminder"')
        self.manager._print('  You: "Cancella il reminder per Luigi"')
        self.manager._print()

        self.manager._print_divider()

        # SMS
        self.manager._print()
        self.manager._print("━━━ SMS ━━━")
        self.manager._print()
        self.manager._print("  Send SMS directly from Zylch (requires Vonage config).")
        self.manager._print()
        self.manager._print("  Examples:")
        self.manager._print('  • "Manda un SMS a +39 333 1234567: Arrivo tra 10 minuti"')
        self.manager._print('  • "Invia codice di verifica a questo numero"')
        self.manager._print()

        self.manager._print_divider()

        # Outbound Calls
        self.manager._print()
        self.manager._print("━━━ OUTBOUND CALLS ━━━")
        self.manager._print()
        self.manager._print("  Let your MrCall AI assistant make calls for you.")
        self.manager._print()
        self.manager._print("  Examples:")
        self.manager._print('  • "Chiama +39 333 1234567 per confermare appuntamento"')
        self.manager._print('  • "Fai chiamare Marco per ricordargli la riunione"')
        self.manager._print()
        self.manager._print("  The AI assistant will:")
        self.manager._print("  1. Call the number")
        self.manager._print("  2. Deliver your message")
        self.manager._print("  3. Report back what happened")
        self.manager._print()

        self.manager._print_divider()
        self.manager._print()
        self.manager._print("💡 TIP: Combine these features for powerful workflows!")
        self.manager._print('   "Se il cliente non risponde alla mail entro 2 giorni,')
        self.manager._print('    mandagli un SMS di promemoria"')
        self.manager._print()
