# Zylch AI Memory System

**The relational memory layer that transforms stateless LLMs into assistants that know your network**

> **Technical Implementation**: See `zylch_memory/README.md` for API reference and `zylch_memory/ZYLCH_MEMORY_ARCHITECTURE.md` for architecture details.
> The CLI commands documented here use the ZylchMemory backend with semantic search and O(log n) HNSW indexing.

---

## Table of Contents

1. [Vision: The World Model for Relationships](#vision-the-world-model-for-relationships)
2. [Why LLMs Need Persistent Memory](#why-llms-need-persistent-memory)
3. [How It Works](#how-it-works)
4. [Channel-Based Learning](#channel-based-learning)
5. [From Channels to Avatars](#from-channels-to-avatars)
6. [Usage Guide](#usage-guide)
7. [Best Practices](#best-practices)

---

## Vision: The World Model for Relationships

This memory system is the foundation for **relational avatars**—personalized representations of each contact in your professional network that persist across conversations and accumulate understanding over time.

**The thesis**: LLMs are already perfect for relational intelligence because professional relationships are encoded in language. Every email, message, and call transcript contains the substrate of human connection. Where physical world models require learning object permanence and spatial reasoning from sensory data, the "world of relationships" is already made of text. The missing piece is persistent memory.

**What Zylch builds**: The relational memory layer that transforms stateless LLMs into assistants that know your network better than you do. Not a CRM, not a productivity tool—a living representation of people through their interactions with you.

**The moat**: Avatar architecture. Today this manifests as vector memory with small-world topology and per-person namespaces. Tomorrow: continuous training on interaction patterns. These avatars are shareable—when an employee leaves, the relational knowledge stays; when a new one joins, they inherit the context.

**The philosophical stance**: Professional communication has trapped us in a digital cage. Zylch doesn't want to deepen that cage—it wants to handle the digital burden so humans can have more embodied, in-person interactions. This is why Zylch focuses exclusively on professional relationships.

---

## Why LLMs Need Persistent Memory

Yann LeCun argues that LLMs are a "dead end" for human-level intelligence because they lack four fundamental capabilities: understanding of the physical world, persistent memory, true reasoning, and hierarchical planning. He's right about physical intelligence—LLMs can describe a rotating cube but can't actually model spatial reasoning the way humans intuitively grasp it.

But here's the insight that guides Zylch's architecture: **LeCun's critique doesn't apply to relational intelligence.**

Professional relationships exist entirely in language. The "world model" for understanding that your CFO prefers direct communication, that your client has a 3-week response latency, or that two contacts you're about to introduce have a shared history—all of this is encoded in text you've already generated. LLMs don't need to learn physics to model relationships; they need to remember.

**What we address**: The memory gap. LLMs are stateless by default—every conversation starts from zero. We provide the persistent memory layer that transforms episodic interactions into continuous relational understanding.

**What we don't build**: We're not building a world model for physical reasoning. We're building the specific world model for relationships, where the world is already made of text.

---

## How It Works

### The Problem

Traditional AI assistants are amnesiac. If you correct them today, they'll make the same mistake tomorrow. This isn't just frustrating—it's fundamentally incompatible with relationship building. Relationships accumulate. Every interaction adds context that shapes future interactions.

### The Solution

Zylch learns from your corrections and approvals. When you say "no, use 'lei' not 'tu' for formal contacts," the system stores this as a behavioral pattern. Next time you ask it to draft a formal email, it remembers.

The system doesn't just store exact phrases—it understands meaning. If you taught it about "formal emails," it will apply that learning when you ask to "compose a professional message" because it recognizes these are semantically similar.

### Two Types of Memory

**Skill Patterns**: What worked before in specific situations
- "When drafting emails to Luisa, use formal tone and 'lei' pronoun"
- "For calendar events with international attendees, always include timezone"
- Stored with your approval/rejection feedback, so the system learns what you prefer

**Behavioral Memory**: General preferences across channels
- "I prefer casual tone in WhatsApp messages"
- "Always check past communication history before drafting"
- Rules that apply broadly within a communication channel

### Confidence and Learning

Every pattern starts at 50% confidence. When the system applies a pattern and you approve the result, confidence increases. If you reject or modify the output, confidence decreases. Over time, reliable patterns become stronger while unreliable ones fade.

This mimics how human memory works: memories that are retrieved and reinforced become stronger; memories that fail verification weaken.

---

## Channel-Based Learning

Zylch organizes behavioral memory by communication channel. This prevents conflicts—you can be formal on email but casual on WhatsApp, and the system won't mix them up.

### Channels

| Channel | Purpose | Example Rules |
|---------|---------|---------------|
| `email` | Email drafting and responses | "Use 'lei' for formal contacts", "Keep emails under 3 paragraphs" |
| `calendar` | Calendar event management | "Always specify timezone for international meetings" |
| `whatsapp` | WhatsApp messaging | "Use casual tone", "Keep messages brief" |
| `mrcall` | Phone assistant behavior | "Speak slowly and clearly" |
| `task` | Task management | "Set reminders 1 day before deadlines" |

### Why Channel Isolation Matters

- **Clear boundaries**: Email rules ≠ Phone rules ≠ WhatsApp rules
- **No conflicts**: Be formal on email, casual on WhatsApp—no confusion
- **Scalable**: Works with 10 contacts or 10,000
- **Extensible**: Easy to add Slack, Teams, SMS later

### Two Tiers

1. **Personal Memory**: Your own learned behaviors per channel
2. **Global Memory**: System-wide improvements for all users (admin only)

---

## From Channels to Avatars

Channels organize behavioral rules, but the real goal is person-centric avatars that understand each contact across all channels.

### Current Architecture

**Namespace Isolation (Implemented)**
The system already supports per-person memory isolation via namespaces. Each user's patterns are stored separately (`user:mario`, `user:alice`), and retrieval cascades from user-specific to global patterns. This is the foundation for avatar architecture.

**Channel-Based Behavioral Memory (Implemented)**
Within each user namespace, behavioral rules are organized by communication channel. This prevents conflicts—you can be formal on email but casual on WhatsApp.

### The Evolution Path

**Phase 1: Per-Contact Namespaces (Current)**
Extend the namespace structure to isolate contact-specific patterns: `user:mario:contact:luisa`. This enables storing what you've learned about each person—their communication preferences, response patterns, relationship context.

**Phase 2: Avatar Aggregation (Next)**
Build the synthesis layer that combines per-contact patterns across channels into coherent avatars. The avatar for "Luisa" would know: formal tone preferred (from email patterns), responds within 24h (from response tracking), prefers morning meetings (from calendar patterns).

**Phase 3: Continuous Training (Future)**
Avatars that learn from every interaction without explicit correction. Predicting optimal communication timing, suggesting relationship maintenance actions, identifying network patterns.

### The Enterprise Moat

**Onboarding via avatar sharing**: New employees inherit relationship context immediately. They don't start from zero with key contacts—they inherit their predecessor's relational knowledge.

**Knowledge retention**: When employees leave, the relational knowledge stays. The institutional memory of how to work with key clients, partners, and vendors persists in the avatar layer.

---

## Usage Guide

### CLI Commands

All memory operations use Unix-style subcommands:

#### List Memories

```bash
# List personal memories (default)
/memory --list

# List global memories (admin)
/memory --list --global

# List all memories (personal + global)
/memory --list --all
```

#### Add Memory

```bash
# Add personal memory (channel-specific)
/memory --add "what went wrong" "correct behavior" channel

# Examples:
/memory --add "Used tu instead of lei" "Always use lei for formal business communication" email
/memory --add "Missing timezone" "Always specify timezone (e.g., CET, PST) in event description" calendar
/memory --add "Too formal tone" "Use casual, friendly language on WhatsApp" whatsapp
/memory --add "Script too brief" "Provide full context when explaining reason for phone call" mrcall

# Add global memory (admin only)
/memory --add --global "Didn't check past style" "Always check past communication history before drafting" email
```

#### Remove Memory

```bash
# Remove personal memory
/memory --remove <id>

# Remove global memory (admin)
/memory --remove <id> --global

# Example:
/memory --remove 5
```

#### Statistics

```bash
# Show personal memory stats
/memory --stats

# Show global memory stats (admin)
/memory --stats --global

# Show all memory stats (includes breakdown by channel)
/memory --stats --all
```

### Learning from Behavior

The system learns automatically when you interact with Zylch:

**Example 1: Email Drafting**
1. You ask Zylch to draft an email → It uses 'tu'
2. You correct: "No, use 'lei' - this is formal business"
3. You add the memory:
   ```bash
   /memory --add "Used tu instead of lei" "Always use lei for formal business communication" email
   ```
4. Next time: Zylch automatically uses 'lei' for formal emails

**Example 2: Gap Analysis**
1. You run `/gaps` → System flags reminder@superhuman.com as urgent
2. You're annoyed: "This is just an automated reminder!"
3. You teach it:
   ```bash
   /memory --add "Email from reminder@superhuman.com considered important" "Always ignore reminder@superhuman.com - automated reminders" email
   ```
4. Next `/gaps` run: Those reminders are automatically filtered out

**Example 3: Calendar Events**
1. You create a meeting with international attendees → No timezone included
2. You correct: "Add timezone - this is international!"
3. You add the memory:
   ```bash
   /memory --add "Missing timezone" "Always specify timezone (e.g., CET, PST) in event description" calendar
   ```
4. Next calendar event: Timezone automatically included

### Channel Isolation in Practice

```bash
# Add email rule - be friendly
/memory --add "Too formal" "Use friendly, conversational tone" email

# Add whatsapp rule - be more professional (opposite!)
/memory --add "Too casual" "Be more professional on WhatsApp" whatsapp

# Result: No conflict! Each channel has independent rules.
# Email drafts will be friendly, WhatsApp messages will be professional.
```

---

## Best Practices

### Writing Good Corrections

**✅ Good:**
```
what_went_wrong: "Used 'tu' instead of 'lei'"
correct_behavior: "Always use 'lei' for formal email communication"
```
- Clear and specific
- Generalizable to future situations
- Actionable

**❌ Bad:**
```
what_went_wrong: "Wrong"
correct_behavior: "Fix it"
```
- Too vague
- Not actionable
- Can't be applied automatically

### Channel Selection

Always choose the most specific channel:

- Email drafting/responses → `email`
- Calendar events → `calendar`
- WhatsApp messages → `whatsapp`
- Phone assistant behavior → `mrcall`
- Task management → `task`

### When to Use Global vs Personal Memory

**Use Personal Memory when:**
- Preference is user-specific ("I like casual tone")
- Rule applies to your workflow ("Set reminders 1 day before")

**Use Global Memory when (admin only):**
- Improvement benefits all users ("Always check past communication")
- Fixes a systematic problem ("Include video link for remote meetings")

### Understanding Confidence Levels

- **0.3-0.5**: Experimental rules, being tested
- **0.5-0.7**: Proven rules, reliable
- **0.7+**: Highly reliable, used many times successfully

Rules below 0.3 confidence are automatically filtered out—they've failed too often to be useful.

---

## Technical Reference

For implementation details, API reference, and architecture documentation:

- **API & Quick Start**: [`zylch_memory/README.md`](./zylch_memory/README.md)
- **Architecture**: [`zylch_memory/ZYLCH_MEMORY_ARCHITECTURE.md`](./zylch_memory/ZYLCH_MEMORY_ARCHITECTURE.md)
- **Relationship Intelligence**: [`relationship-intelligence.md`](./relationship-intelligence.md)

---

## Research Foundations

This system draws on:

**ReasoningBank** (Google Research): Strategy-level memory with success/failure learning and contrastive patterns ("Do this, not that").

**Memory Reconsolidation** (Neuroscience): Memories update rather than duplicate. Retrieval makes memories labile; reinforcement strengthens, failure weakens.

**JEPA** (LeCun, Meta AI): Representation-level prediction over pixel-level generation. Learning essential features, not raw reconstruction.

---

**End of Memory System Documentation**
