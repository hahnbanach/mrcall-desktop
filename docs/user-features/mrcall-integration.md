# MrCall Integration

**Your AI phone assistant - configured your way.**

---

## What It Does

MrCall is your AI phone assistant that answers calls, takes messages, and handles inquiries when you're not available. Zylch helps you configure and manage MrCall.

---

## Getting Started

### Select Your Assistant

If you have multiple MrCall assistants (for different businesses or numbers):

```bash
/mrcall
```

Shows your available assistants. Select one to work with.

### Switch Assistants

```bash
/mrcall --id your_assistant_id
```

---

## What You Can Configure

### Welcome Message
How MrCall greets callers:
- "Hello, you've reached [Your Name]..."
- Custom greetings for different scenarios

### Call Handling
- What information to collect
- When to offer callback
- How to handle urgent calls

### Business Hours
- When MrCall answers
- Different behavior during/after hours

### Contact Integration
When someone calls, MrCall can:
- Recognize known contacts
- Provide context about the caller
- Handle VIPs differently

---

## Managing Contacts

### Add Phone Contacts

Tell Zylch to save contacts for MrCall:

> "Save Marco's number for MrCall"

This adds Marco to your MrCall contact book, so:
- MrCall recognizes when Marco calls
- You can initiate calls to Marco through MrCall

### View Your Contacts

> "Show my MrCall contacts"

### Call History

> "Who called today?"
> "Show calls from this week"

---

## Outbound Calls

### Initiate a Call

> "Call Marco through MrCall"

MrCall initiates the call, and you're connected.

### Campaign Calls

For multiple calls:
> "Call everyone on my follow-up list"

MrCall handles the calls and reports back.

---

## Examples

### Check Messages

**You:** "Any messages from MrCall today?"
**Zylch:** Shows voicemails and messages from callers

### Update Greeting

**You:** "Change my MrCall greeting to mention I'm on vacation until Monday"
**Zylch:** Updates the welcome message

### Handle VIPs

**You:** "If Elena calls, always notify me immediately"
**Zylch:** Configures priority handling for Elena

---

## Multiple Assistants

If you run multiple businesses:

```bash
/mrcall --list
```

Shows all your assistants:
```
1. Personal - +39 333 xxx xxxx
2. Business - +39 02 xxx xxxx  (current)
3. Support Line - +39 02 xxx xxxx
```

Each assistant has:
- Separate contact list
- Different greeting
- Independent settings

---

## Integration with Zylch

### Caller Context

When someone calls, MrCall knows:
- Your relationship with them
- Recent email/meeting context
- Priority level

### After Calls

MrCall reports back to Zylch:
- Who called
- What they needed
- Suggested follow-up

### In Your Briefing

Calls appear in `/sync`:
```
CALLS TODAY:
- Marco Ferrari (10:32) - Left message about proposal
- Unknown +39 02 xxx - Inquiry about services
```

---

## Tips

- **Keep greetings short** - Callers want to leave messages, not listen
- **Set expectations** - "I'll return your call within 24 hours"
- **Use context** - Let MrCall mention if you have a meeting scheduled
- **Review regularly** - Check messages and call logs

---

## Commands Reference

| Command | What It Does |
|---------|--------------|
| `/mrcall` | Show assistants, select one |
| `/mrcall --list` | List all assistants |
| `/mrcall --id <id>` | Switch to specific assistant |

---

## Related Features

- [Contact Intelligence](./contact-intelligence.md) - Caller context
- [Daily Briefing](./daily-briefing.md) - Calls in your briefing

---

[← Back to Overview](./README.md)
