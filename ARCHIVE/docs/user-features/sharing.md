# Sharing Intelligence

**Share what you know with your team.**

---

## What It Does

When you learn something valuable about a contact, share it with colleagues who need to know. Team intelligence means everyone stays informed.

---

## How It Works

### Share Information

When you want to share something:

> "Share with Luigi that Marco signed the contract"

Zylch will:
1. Find Luigi in your authorized contacts
2. Send the intel about Marco
3. Luigi sees it when he asks about Marco

### Receive Shared Intel

When someone shares with you:

> You: "Tell me about Marco Ferrari"
> Zylch: Shows your data + "Luigi shared: Marco signed the contract (Nov 25)"

---

## Setting Up Sharing

### Authorize a Colleague

Before sharing, both parties must connect:

```bash
/share luigi@company.com
```

Luigi receives an invitation. Once accepted, you can share with each other.

### Check Your Connections

```bash
/share --list
```

Shows who you can share with.

---

## What You Can Share

### Contact Updates
- "Share that Marco is now at NewCompany"
- "Tell Sara that Elena changed her number"

### Deal Information
- "Share with Luigi that the deal closed"
- "Let the team know Marco is interested"

### Meeting Outcomes
- "Share with Sara what we discussed with TechCorp"

### Warnings and Notes
- "Tell Luigi that Marco prefers email over calls"
- "Share that the client is difficult about pricing"

---

## Examples

### After Closing a Deal

**You:** "Share with the sales team that Marco Ferrari signed the Q4 contract"

**Result:** When any sales team member asks about Marco, they see:
> "Your colleague shared: Marco Ferrari signed the Q4 contract (Nov 25)"

### Important Contact Update

**You:** "Let Sara know that Elena's new email is elena@newcompany.com"

**Sara later asks:** "Contact info for Elena?"
**Sara sees:** Your shared update about the new email

### Meeting Intelligence

**You:** "Share with Luigi that TechCorp wants to discuss expansion in Q1"

**Luigi is prepared** for his call with TechCorp

---

## Privacy and Control

### What Gets Shared
- Only specific intel you explicitly share
- Your full contact database is NOT shared
- Each share is a deliberate action

### Who Can See
- Only authorized colleagues
- You control who you connect with
- Remove connections anytime with `/share --remove`

### Your Data
- Shared intel is attributed to you
- Recipients know who shared what
- You can share anonymously if preferred

---

## Tips

- **Be specific** - Share actionable information
- **Share proactively** - After important meetings or decisions
- **Keep it relevant** - Share with people who need to know
- **Trust your network** - Only authorize trusted colleagues

---

## Commands Reference

| Command | What It Does |
|---------|--------------|
| `/share email@company.com` | Invite colleague |
| `/share --list` | See connections |
| `/share --pending` | See pending invitations |
| `/share --remove email` | Remove connection |

---

## Related Features

- [Contact Intelligence](./contact-intelligence.md) - What you can share
- [Daily Briefing](./daily-briefing.md) - See shared intel in briefings

---

[← Back to Overview](./README.md)
