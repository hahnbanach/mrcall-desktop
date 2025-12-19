# Plan: `/prompt build email` Command

## Overview

Create a command that **learns from the user's email history** to generate a personalized prompt for memory extraction. Instead of hardcoded rules, the system analyzes:
- Who the user actually replies to
- What topics they engage with
- What they ignore (cold outreach patterns unique to them)
- Their role, business context, and priorities

The generated prompt is stored in the DB and used by `memory_worker.py` when processing emails.

---

## Implementation Steps

### 1. Create DB Table for User Prompts

**File:** `zylch/storage/migrations/006_user_prompts.sql`

```sql
CREATE TABLE user_prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    prompt_type TEXT NOT NULL,  -- 'memory_email', 'memory_calendar', 'triage', etc.
    prompt_content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,  -- generation stats, sample count, etc.
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(owner_id, prompt_type)
);

CREATE INDEX idx_user_prompts_owner ON user_prompts(owner_id);
```

### 2. Add Supabase Storage Methods

**File:** `zylch/storage/supabase_client.py`

Add methods:
- `get_user_prompt(owner_id, prompt_type) -> Optional[str]`
- `store_user_prompt(owner_id, prompt_type, content, metadata) -> Dict`
- `delete_user_prompt(owner_id, prompt_type) -> bool`

### 3. Create Prompt Builder Service

**File:** `zylch/services/prompt_builder.py`

This is the core logic:

```python
class PromptBuilder:
    """Builds personalized prompts by analyzing user's email patterns."""

    async def build_memory_email_prompt(self, owner_id: str) -> str:
        """Analyze user's emails and generate personalized extraction prompt.

        Steps:
        1. Check sync status (fail if no emails synced)
        2. Sample emails intelligently:
           - Emails user REPLIED to (high signal)
           - Emails user IGNORED (what to filter)
           - Recent threads with multiple exchanges
        3. Analyze patterns:
           - User's role/business (from signatures, domain)
           - VIP contacts (frequent correspondence)
           - Topics they engage with
           - Cold outreach patterns they ignore
        4. Generate comprehensive prompt with all context
        5. Return the prompt content
        """
```

**Key Analysis Functions:**

```python
def _sample_replied_emails(self, owner_id: str, limit: int = 50) -> List[Dict]:
    """Get emails where user sent a reply (high-value relationships)."""

def _sample_ignored_emails(self, owner_id: str, limit: int = 50) -> List[Dict]:
    """Get emails user received but never replied to (noise patterns)."""

def _analyze_user_profile(self, emails: List[Dict]) -> Dict:
    """Extract user context: role, company, domain, signature patterns."""

def _identify_vip_contacts(self, replied_emails: List[Dict]) -> List[str]:
    """Contacts with high reply rate = VIPs."""

def _identify_noise_patterns(self, ignored_emails: List[Dict]) -> List[str]:
    """Common patterns in emails user ignores."""
```

### 4. Meta-Prompt for Analysis

The `PromptBuilder` will use a meta-prompt to analyze the sampled emails and generate the final prompt. This meta-prompt explains:
- The goal: create a prompt for memory extraction
- What to learn: who matters, what to capture, what to ignore
- Output format: a complete, self-contained prompt

```python
META_PROMPT = """You are analyzing a user's email history to create a personalized prompt for their AI assistant.

Your task: Generate a prompt that will be used to extract relevant information from emails and store it in memory blobs.

USER'S EMAILS THEY REPLIED TO (high priority contacts):
{replied_emails}

USER'S EMAILS THEY IGNORED (noise/cold outreach):
{ignored_emails}

USER'S PROFILE (inferred):
{user_profile}

Based on this analysis, generate a complete prompt that:

1. DESCRIBES THE USER
   - Their role (founder, engineer, investor, etc.)
   - Their company/domain
   - What they care about professionally

2. DEFINES WHAT TO EXTRACT
   - For contacts they engage with: detailed facts, context, relationship history
   - VIP contacts (list specific domains/people with high engagement)
   - Topics they care about

3. DEFINES WHAT TO SKIP OR MINIMIZE
   - Cold outreach patterns specific to this user
   - Newsletter/marketing patterns
   - Types of requests they ignore (e.g., fundraising if not an investor)

4. OUTPUT FORMAT
   - How to structure extracted facts
   - What makes something worth storing vs. "No significant facts"

The prompt should be self-contained (no external references) and directly usable.
Output ONLY the prompt text, nothing else."""
```

### 5. Add Command Handler

**File:** `zylch/services/command_handlers.py`

Add `/prompt` command with subcommands:
- `/prompt build email` - Generate personalized email memory prompt
- `/prompt show email` - Display current prompt
- `/prompt reset email` - Delete and return to default

```python
async def handle_prompt(args: List[str], config: ToolConfig, owner_id: str) -> str:
    """Handle /prompt command - manage user-specific prompts."""

    if not args or args[0] == '--help':
        return """**📝 Prompt Management**

**Usage:**
• `/prompt build email` - Analyze your emails and create personalized extraction prompt
• `/prompt show email` - Show your current email memory prompt
• `/prompt reset email` - Reset to default prompt

**How it works:**
1. Run `/sync` first to ensure emails are available
2. `/prompt build email` analyzes your sent/received patterns
3. Creates a personalized prompt stored in your account
4. `/memory process email` uses this prompt for extraction"""

    cmd = args[0]
    prompt_type = args[1] if len(args) > 1 else None

    if cmd == 'build' and prompt_type == 'email':
        # Check sync status first
        sync_state = storage.get_sync_state(owner_id)
        if not sync_state or not sync_state.get('full_sync_completed'):
            return "❌ Please run `/sync` first to sync your emails."

        # Check email count
        email_count = storage.get_email_count(owner_id)
        if email_count < 50:
            return f"❌ Need at least 50 emails for analysis. Found: {email_count}\n\nRun `/sync --days 90` to sync more history."

        # Build the prompt
        builder = PromptBuilder(storage, owner_id, anthropic_client)
        prompt_content = await builder.build_memory_email_prompt()

        # Store in DB
        storage.store_user_prompt(owner_id, 'memory_email', prompt_content, {
            'email_count_analyzed': email_count,
            'generated_at': datetime.now().isoformat()
        })

        return f"""✅ **Email memory prompt created**

Analyzed {email_count} emails to learn your patterns.

**What was learned:**
- Your role and context
- VIP contacts (high reply rate)
- Topics you engage with
- Cold outreach patterns to ignore

Use `/prompt show email` to review.
Use `/memory process email` to extract memories using this prompt."""
```

### 6. Modify Memory Worker to Use User Prompt

**File:** `zylch/workers/memory_worker.py`

Change `_extract_facts()` to:
1. First check for user-specific prompt in DB
2. Fall back to default `EXTRACT_FACTS_PROMPT` if not found
3. Show warning on first `/memory process email` if no custom prompt exists

```python
def _get_extraction_prompt(self) -> str:
    """Get extraction prompt - user-specific or default."""
    user_prompt = self.storage.get_user_prompt(self.owner_id, 'memory_email')
    if user_prompt:
        return user_prompt
    return EXTRACT_FACTS_PROMPT  # Default fallback

def _extract_facts(self, email: Dict, contact_email: str) -> str:
    prompt_template = self._get_extraction_prompt()
    # ... rest of extraction logic
```

### 7. Add Gate to `/memory process email`

When user runs `/memory process email` without a custom prompt, show:

```
⚠️ **No personalized prompt found**

For better results, create a personalized extraction prompt first:
  `/prompt build email`

This analyzes your email patterns to understand:
- Who matters to you
- What to extract
- What to ignore (cold outreach, etc.)

Continue with default prompt? (less accurate for cold outreach detection)
```

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `zylch/storage/migrations/006_user_prompts.sql` | Create | New table for user prompts |
| `zylch/storage/supabase_client.py` | Modify | Add get/store/delete user prompt methods |
| `zylch/services/prompt_builder.py` | Create | Core prompt generation logic |
| `zylch/services/command_handlers.py` | Modify | Add `/prompt` command handler |
| `zylch/workers/memory_worker.py` | Modify | Load user prompt, add gate for first run |

---

## Testing Plan

1. **No emails synced:** `/prompt build email` → Error message
2. **Few emails:** `/prompt build email` → Error, suggest more sync
3. **Sufficient emails:** Generate prompt, store in DB, confirm success
4. **Show prompt:** `/prompt show email` → Display stored prompt
5. **Memory process without prompt:** Show warning/gate
6. **Memory process with prompt:** Use personalized prompt for extraction
7. **Reset:** `/prompt reset email` → Delete, confirm

---

## Edge Cases

- **New user with no email history:** Clear error, guide to sync first
- **User with only sent emails:** Still works (can infer role/context)
- **User with only received emails:** Works but less signal on priorities
- **Prompt regeneration:** `/prompt build` overwrites existing (with confirmation?)
- **Very large email history:** Sample intelligently (last 6 months, focus on replied)
