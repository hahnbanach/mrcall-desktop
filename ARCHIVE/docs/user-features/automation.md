# Automation & Reminders

**Zylch works for you even when you're not here.**

---

## What It Does

Set persistent instructions, schedule reminders, send SMS, and trigger AI phone calls - all through natural conversation.

---

## Standing Instructions

### What Are They?

Rules that Zylch follows in every conversation. Set them once, they apply forever (until you remove them).

### Examples

- "Rispondi sempre in italiano"
- "Quando scrivo a clienti, usa tono formale"
- "Marco Rossi e' VIP, prioritizza sempre"
- "Non schedulare mai meeting prima delle 10"
- "Firma le email come Dott. Mario Bianchi"

### How to Use

**Add an instruction:**
> "Aggiungi istruzione: rispondi sempre in italiano"

**See your instructions:**
> "Mostra le mie istruzioni"

**Remove an instruction:**
> "Rimuovi l'istruzione sul italiano"

### When to Use

- Language preferences
- Tone and style rules
- VIP contacts
- Schedule constraints
- Email signatures
- Any rule you want applied consistently

---

## Reminders & Scheduling

### Simple Reminders

Ask Zylch to remind you of things:

> "Ricordami tra 30 minuti di chiamare Luigi"
> "Ricordami domani alle 9 di inviare il preventivo"
> "Ricordami tra 2 ore di controllare la mail"

### Conditional Reminders

Set reminders that trigger only if something doesn't happen:

> "Se Mario non risponde entro 24 ore, ricordamelo"
> "Se non ricevo conferma entro domani, avvisami"

### Managing Reminders

**See all reminders:**
> "Mostra i miei reminder"

**Cancel a reminder:**
> "Cancella il reminder per Luigi"

---

## SMS

### Sending SMS

Send text messages directly through Zylch:

> "Manda un SMS a +39 333 1234567: Arrivo tra 10 minuti"
> "Scrivi un SMS a Marco: Confermato per domani alle 15"

### Verification Codes

Send one-time codes for verification:

> "Invia codice di verifica a +39 333 1234567"

### Requirements

SMS requires Vonage configuration. Ask your administrator if this feature is available.

---

## Outbound Calls

### AI Phone Calls

Let your MrCall AI assistant make calls on your behalf:

> "Chiama +39 333 1234567 per confermare l'appuntamento"
> "Fai chiamare Marco per ricordargli la riunione di domani"

### What Happens

1. Zylch triggers the call
2. Your AI assistant calls the number
3. Delivers your message
4. Reports back what happened

### Use Cases

- Appointment confirmations
- Meeting reminders
- Follow-up calls
- Quick notifications when email isn't enough

### Requirements

Requires MrCall/StarChat integration with outbound calling enabled.

---

## Combining Features

The real power is combining these features:

### Example Workflow

> "Se il cliente non risponde alla mail entro 2 giorni, mandagli un SMS di promemoria"

This sets up:
1. A conditional trigger (2 days)
2. An automatic SMS action

### Another Example

> "Aggiungi istruzione: quando un lead non risponde per 3 giorni, ricordami di chiamarlo"

Now Zylch will automatically track response times and remind you.

---

## Tips

- **Be specific** - "tra 30 minuti" is better than "dopo"
- **Use natural language** - Just say what you want
- **Combine with standing instructions** - Set rules that trigger reminders
- **Check your reminders** - Review with "mostra i miei reminder"

---

## Commands Quick Reference

| What You Say | What Happens |
|--------------|--------------|
| "Aggiungi istruzione: ..." | Creates persistent rule |
| "Mostra le mie istruzioni" | Lists all instructions |
| "Rimuovi l'istruzione su ..." | Deletes an instruction |
| "Ricordami tra X di ..." | Schedules a reminder |
| "Se X non succede, ricordamelo" | Conditional reminder |
| "Mostra i miei reminder" | Lists pending reminders |
| "Manda un SMS a ..." | Sends SMS |
| "Chiama +39... per ..." | Triggers AI phone call |

---

## Related Features

- [Memory & Learning](./memory-learning.md) - How Zylch remembers
- [Email Management](./email-management.md) - Email automation
- [MrCall Integration](./mrcall-integration.md) - Phone features

---

[<- Back to Overview](./README.md)
