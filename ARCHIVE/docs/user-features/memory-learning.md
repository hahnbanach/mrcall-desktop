# Memory & Learning

**Zylch learns your style - corrections become automatic.**

---

## What It Does

The more you use Zylch, the better it gets. When you correct something, Zylch remembers - and applies that preference automatically in the future.

---

## How It Works

### Automatic Learning

Zylch learns from your conversations:

- **You mention:** "My sister Francesca..."
- **Next time:** Zylch knows Francesca is your sister

- **You correct:** "Make it shorter"
- **Next time:** Zylch writes shorter emails by default

- **You prefer:** Morning meetings
- **Next time:** Zylch suggests morning slots first

### What Zylch Learns

**About You:**
- Relationships (family, colleagues, partners)
- Work context (role, company, industry)
- Communication preferences (formal/casual, long/short)
- Patterns (when you work, how you schedule)

**Your Preferences:**
- Email style (greetings, sign-offs, length)
- Calendar habits (preferred times, meeting duration)
- Contact priorities (who's important, who's not)

---

## Teaching Zylch

### Through Conversation

Just talk naturally:
- "Marco is my most important client"
- "I prefer short emails"
- "Always CC my assistant on client emails"

### Through Corrections

When Zylch gets something wrong:
- "Too formal, make it casual"
- "That's not important, ignore it"
- "I never meet before 9am"

### Explicit Memory Commands

Use `/memory` to manage what Zylch knows:

```bash
/memory --list          # See what Zylch remembers
/memory --channel email # See email-specific preferences
```

---

## Examples

### Learning Relationships

**Conversation:**
> You: "Write to my sister Francesca..."

**Later:**
> You: "Message Francesca"
> Zylch: "Writing to your sister Francesca?"

### Learning Style

**Correction:**
> You: "Too long, I write short emails"

**Next time:**
> Zylch automatically drafts shorter emails

### Learning Priorities

**Teaching:**
> You: "Elena is VIP, always prioritize her"

**In briefings:**
> Elena's emails appear first, marked as important

---

## Types of Memory

### Personal Preferences
Things specific to you:
- Your writing style
- Your schedule preferences
- Your relationship definitions

### Contact Knowledge
What Zylch learns about your contacts:
- Who they are to you
- How to communicate with them
- What's important about them

### Pattern Recognition
Behaviors Zylch notices:
- When you usually respond
- How you handle different types of emails
- Your meeting patterns

---

## Privacy

- All learning is private to you
- Zylch doesn't share what it learns
- You can view and delete memories anytime
- Use `/memory --delete` to remove specific memories

---

## Tips

- **Be explicit** - "Remember: I prefer..." makes it stick
- **Correct naturally** - Just say what's wrong
- **Check periodically** - Review with `/memory --list`
- **Remove outdated** - Delete memories that no longer apply

---

## Commands Reference

| Command | What It Does |
|---------|--------------|
| `/memory --list` | Show all memories |
| `/memory --channel email` | Show email preferences |
| `/memory --delete <id>` | Remove a memory |

---

## Related Features

- [Email Management](./email-management.md) - See learning in action
- [Daily Briefing](./daily-briefing.md) - Personalized prioritization
- [Contact Intelligence](./contact-intelligence.md) - Contact-specific knowledge

---

[← Back to Overview](./README.md)
