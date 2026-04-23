---
description: |
  Background system that analyzes user conversations to extract persistent persona facts (e.g.,
  "has a sister named Francesca"). Runs asynchronously, uses LLM for extraction, stores in user's
  memory namespace with reconsolidation (merges similar facts, no duplicates). Zylch references
  learned facts proactively in future interactions when relevant.
---

# User Persona Learning

**Background AI system that learns about the user from conversations**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [What It Learns](#what-it-learns)
4. [How It Works](#how-it-works)
5. [Memory Storage](#memory-storage)
6. [Prompt Injection](#prompt-injection)
7. [Configuration](#configuration)
8. [Technical Implementation](#technical-implementation)

---

## Overview

User Persona Learning is a background system that analyzes conversations between the user and Zylch AI to extract persistent information about the user. This creates a "persona" that Zylch uses proactively in future interactions.

### Key Features

- **Background Processing**: Analysis runs asynchronously without blocking conversations
- **Economical**: Uses LLM for fast extraction
- **Reconsolidation**: Similar facts are merged, not duplicated
- **Proactive Usage**: Zylch references learned facts naturally when relevant
- **Privacy-Focused**: All data stays in user's own namespace

### Example

**Conversation:**
```
User: "Scrivi una mail a mia sorella Francesca per ricordarle della cena"
Zylch: "Certo! Mi serve l'email di Francesca..."
User: "francesca.rossi@gmail.com"
```

**What Zylch Learns:**
- User has a sister named Francesca
- Francesca's email is francesca.rossi@gmail.com

**Future Interaction:**
```
User: "Manda un messaggio a Francesca"
Zylch: "Scrivo a tua sorella Francesca (francesca.rossi@gmail.com)?"
```

---

## Architecture

```
User <--> Zylch Agent (main conversation)
              │
              │ every N messages
              ▼
      [asyncio.create_task]
              │
              ▼
  ┌─────────────────────────┐
  │    PersonaAnalyzer      │
  │   (background, LLM)     │
  └─────────────────────────┘
              │
              ▼
  ┌─────────────────────────┐
  │      zylch_memory       │
  │   namespace: persona    │
  │   user:{owner_id}       │
  └─────────────────────────┘
              │
              ▼
  Injected into prompt at next session
```

### Key Design Decisions

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Timing | Background async | Doesn't block conversation |
| Model | LLM (configured via env var) | One model per provider |
| Trigger | Every N messages | Configurable, default: 5 |
| Storage | zylch_memory | Semantic search, reconsolidation |
| Usage | Proactive | AI references facts naturally |

---

## What It Learns

### Categories

| Category | What It Captures | Example |
|----------|------------------|---------|
| **relationships** | Family, colleagues, partners | "Ha una sorella Francesca (francesca@email.com)" |
| **preferences** | Communication style, habits | "Preferisce email brevi e dirette" |
| **work_context** | Role, company, clients | "Sales Manager presso TechCorp" |
| **patterns** | Behavioral patterns | "Fa /sync ogni mattina alle 8" |

### What It Does NOT Learn

- Information about contacts (stored separately in contact memory)
- Sensitive data (passwords, financial info)
- Temporary context (current task details)

---

## How It Works

### 1. Trigger Analysis

After every N user messages (default: 5), the system triggers background analysis:

```python
# In agent/core.py process_message()
self.message_count += 1
if self.persona_analyzer:
    self.persona_analyzer.analyze_conversation(
        self.conversation_history,
        self.message_count
    )
```

### 2. Extract Facts

PersonaAnalyzer calls the LLM with the extraction prompt:

```python
# Simplified
async def _do_analysis(self, history):
    conversation_text = self._format_conversation(history)
    extracted = await self._extract_facts(conversation_text)
    await self._store_facts(extracted)
```

### 3. Store with Reconsolidation

Facts are stored using `force_new=False` to enable reconsolidation:

```python
memory.store_memory(
    namespace="user:mario:persona",
    category="relationships",
    context="Family relationship",
    pattern="Ha una sorella Francesca (email: francesca@email.com)",
    confidence=0.7,
    force_new=False  # Reconsolidation enabled
)
```

If a similar fact already exists (cosine similarity > threshold), it's updated instead of creating a duplicate.

### 4. Inject into Prompt

At session start, persona facts are injected into the system prompt:

```python
# In agent/core.py
if self.persona_analyzer:
    persona_prompt = self.persona_analyzer.get_persona_prompt()
    if persona_prompt:
        system_prompt += f"\n\n**ABOUT THE USER:**\n{persona_prompt}"
```

---

## Memory Storage

### Namespace Structure

```
user:{owner_id}:persona
  ├── category: "relationships"
  │   └── "Ha una sorella Francesca (tel: 333..., email: ...)"
  │   └── "Il suo socio è Marco Bianchi"
  │
  ├── category: "preferences"
  │   └── "Preferisce email brevi e dirette"
  │   └── "Usa tono informale con i colleghi"
  │
  ├── category: "work_context"
  │   └── "Lavora come sales manager"
  │   └── "I suoi top client: Azienda X, Azienda Y"
  │
  └── category: "patterns"
      └── "Chiede sempre conferma prima di inviare email importanti"
      └── "Usa spesso /sync la mattina"
```

### Reconsolidation Example

**First mention:**
```
"Ha una sorella Francesca (email: francesca@email.com)"
confidence: 0.7
```

**Second mention (adds phone):**
```
User: "Chiama Francesca al 333-1234567"
```

**After reconsolidation (similarity > 0.85):**
```
"Ha una sorella Francesca (email: francesca@email.com, tel: 333-1234567)"
confidence: 0.8  # Boosted
```

---

## Prompt Injection

### Format

The persona is injected into the system prompt in this format:

```
**ABOUT THE USER:**

**Personal And Professional Relationships:**
- Ha una sorella Francesca (francesca@email.com, 333-1234567)
- Il suo socio è Marco Bianchi (CTO di TechCorp)

**Communication And Work Preferences:**
- Preferisce email brevi e dirette
- Usa tono informale con colleghi, formale con clienti nuovi

**Professional Context And Role:**
- Sales Manager presso TechCorp (settore B2B)
- Top clients: Azienda Alfa, Beta Srl

**Behavioral Patterns And Habits:**
- Fa /sync ogni mattina alle 8
- Chiede sempre conferma prima di inviare email a C-level
```

### Usage Instructions

The system prompt includes instructions for proactive usage:

```
**USER PERSONA:**
You may have access to learned information about the user.
Use this information PROACTIVELY when relevant:
- Reference known relationships naturally ("Since Francesca is your sister...")
- Apply known preferences without asking ("I'll keep this email brief as you prefer...")
- Acknowledge context ("Given your role as sales manager...")

Do NOT repeat persona facts unnecessarily - use them naturally when contextually relevant.
Never mention that you "learned" something - just use the information as if you always knew it.
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PERSONA_ANALYSIS_ENABLED` | `true` | Enable/disable persona learning |
| `PERSONA_ANALYSIS_INTERVAL` | `5` | Analyze every N messages |
| `PERSONA_ANALYSIS_MODEL` | Uses `ANTHROPIC_MODEL` env var | Model for extraction |

### In Code

```python
persona_analyzer = PersonaAnalyzer(
    zylch_memory=zylch_memory,
    owner_id=config.owner_id,
    anthropic_api_key=config.anthropic_api_key,
    model=config.anthropic_model,  # from ANTHROPIC_MODEL env var
    analysis_interval=5,
    enabled=True
)
```

---

## Technical Implementation

### Files

| File | Purpose |
|------|---------|
| `zylch/services/persona_analyzer.py` | Main PersonaAnalyzer class |
| `zylch/services/persona_prompts.py` | Extraction prompt and categories |
| `zylch/agent/core.py` | Integration hooks (lines 122-127, 176-182) |
| `zylch/agent/prompts.py` | USER PERSONA instructions (lines 67-76) |
| `zylch/tools/factory.py` | Initialization (lines 231-247) |
| `zylch/cli/main.py` | CLI integration (lines 87, 110) |

### Tests

```bash
# Run persona analyzer tests (17 tests)
python -m pytest tests/test_persona_analyzer.py -v
```

### Key Methods

```python
class PersonaAnalyzer:
    def analyze_conversation(history, message_count)
        """Trigger background analysis if at interval."""

    async def _do_analysis(history)
        """Extract and store persona facts."""

    async def _extract_facts(conversation_text) -> Dict[str, List[str]]
        """Call LLM to extract facts."""

    async def _store_facts(extracted)
        """Store facts with reconsolidation."""

    def get_persona_prompt() -> str
        """Get formatted persona for prompt injection."""
```

---

## Best Practices

### For Users

1. **Be specific**: "Mia sorella Francesca" teaches relationship + name
2. **Include details**: Email, phone, role when mentioning contacts
3. **Express preferences**: "Preferisco email brevi" will be remembered

### For Developers

1. **Fire and forget**: Background tasks don't block conversation
2. **Reconsolidation**: Always use `force_new=False` for persona facts
3. **Category separation**: Keep facts in appropriate categories
4. **Natural usage**: AI should use facts naturally, not announce them

---

**Last Updated:** November 2025
**Version:** 1.0.0
