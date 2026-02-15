# Email Triage System

**See [ARCHITECTURE.md](../ARCHITECTURE.md) for system overview**

## Overview

The Email Triage System solves a critical bug where support emails were incorrectly marked as "resolved" when an auto-reply (e.g., "Ciao MrCaller! Grazie mille...") was sent. The system now:

1. **Detects auto-replies** via RFC 3834 headers (saves Claude API costs)
2. **Asks the human triage question**: "Should someone take care of this?"
3. **Applies configurable importance rules** based on contact metadata
4. **Collects anonymized training data** for future small model fine-tuning

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        EMAIL TRIAGE PIPELINE                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Gmail API (headers)                                                    │
│       │                                                                 │
│       ▼                                                                 │
│  ┌─────────────────────────────────────┐                                │
│  │ gmail.py:_parse_message()           │ Extract RFC 3834 headers       │
│  │ - Auto-Submitted, X-Autoreply       │                                │
│  │ - Precedence, X-Auto-Response-Suppress                               │
│  └──────────────┬──────────────────────┘                                │
│                 │                                                       │
│                 ▼                                                       │
│  ┌─────────────────────────────────────┐                                │
│  │ auto_reply_detector.py              │ Detect auto-reply patterns     │
│  │ - detect_auto_reply(headers, from)  │                                │
│  │ - get_auto_reply_reason()           │ 35 test cases                  │
│  └──────────────┬──────────────────────┘                                │
│                 │                                                       │
│                 ▼                                                       │
│  ┌─────────────────────────────────────┐                                │
│  │ email_sync.py:_analyze_thread()     │                                │
│  │                                      │                               │
│  │  if is_auto_reply:                   │                               │
│  │    → early-exit (NO Claude call)     │ ← Saves API costs             │
│  │    → _build_auto_reply_thread_data() │                               │
│  │  else:                               │                               │
│  │    → proceed to Claude analysis      │                               │
│  └──────────────┬──────────────────────┘                                │
│                 │                                                       │
│                 ▼                                                       │
│  ┌──────────────────────────────────────┐                               │
│  │ Email Task Agent                     │                               │
│  │                                      │                               │
│  │ 1. Get contact importance            │ Evaluate importance rules     │
│  │    → Loads rules from Supabase       │                               │
│  │    → evaluate_rules(rules, contact)  │                               │
│  │                                      │                               │
│  │ 2. Analyze for tasks                 │ Ask Claude with context       │
│  │    → Injects importance context      │                               │
│  │    → Claude returns verdict          │                               │
│  │                                      │                               │
│  │ 3. Collect training sample           │ Collect anonymized data       │
│  │    → Anonymize with TriageAnonymizer │                               │
│  │    → Store to triage_training_samples│                               │
│  └──────────────────────────────────────┘                               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Components

| Component | File | Purpose | Tests |
|-----------|------|---------|-------|
| Auto-Reply Detector | `zylch/utils/auto_reply_detector.py` | RFC 3834 header-based detection | 35 tests |
| Importance Rules | `zylch/models/importance_rules.py` | User-configurable contact importance | 32 tests |
| Rules API | `zylch/api/routes/settings.py` | CRUD endpoints for rules | — |
| ML Anonymizer | `zylch/ml/anonymizer.py` | PII anonymization for training data | — |
| Training Collector | Email task agent | Collects samples after Claude analysis | — |

## Auto-Reply Detection (RFC 3834)

**Headers checked** (extracted in `gmail.py:_parse_message()`):

| Header | Auto-Reply Values | Pattern |
|--------|-------------------|---------|
| `Auto-Submitted` | `auto-replied`, `auto-generated`, `auto-notified` | Starts with `auto-` |
| `X-Autoreply` | `yes`, `true`, `1` | Case-insensitive |
| `Precedence` | `bulk`, `auto_reply`, `list`, `junk` | Exact match |
| `X-Auto-Response-Suppress` | Any non-empty value | Presence check |
| From address patterns | `noreply@`, `no-reply@`, `no_reply@`, `mailer-daemon@`, `postmaster@`, `bounce@`, `donotreply@`, `do-not-reply@` | Case-insensitive prefix |
| Reply-To patterns | Same as From patterns | Fallback check |

**Implementation** (`zylch/utils/auto_reply_detector.py`):

```python
def detect_auto_reply(headers: Dict[str, str], from_email: str = None) -> bool:
    """
    Detect if an email is an automated reply using RFC 3834 headers.

    Args:
        headers: Dict of email headers (case-insensitive keys)
        from_email: Optional from address for pattern matching

    Returns:
        True if email is detected as auto-reply
    """
```

**Key behaviors**:
- Auto-reply threads are NOT analyzed by Claude (saves API costs)
- Auto-reply threads remain "open" (require human follow-up)
- `is_auto_reply` flag stored in database for filtering

## Importance Rules Engine

User-configurable rules to determine contact priority based on CRM/address book metadata.

**Rule Structure** (`zylch/models/importance_rules.py:17`):

```python
@dataclass
class ImportanceRule:
    name: str           # Unique identifier (e.g., "professional_customers")
    condition: str      # Safe expression (e.g., "contact.template == 'professional'")
    importance: str     # "high", "normal", or "low"
    reason: str         # Human-readable explanation
    priority: int = 0   # Higher = evaluated first
    enabled: bool = True
```

**Example rules for MrCall**:

```python
rules = [
    ImportanceRule(
        name="enterprise_customers",
        condition="contact.template == 'enterprise'",
        importance="high",
        reason="Enterprise tier customer - top priority",
        priority=100
    ),
    ImportanceRule(
        name="professional_customers",
        condition="contact.template == 'professional'",
        importance="high",
        reason="Professional tier paying customer",
        priority=50
    ),
    ImportanceRule(
        name="free_tier",
        condition="contact.template == 'free'",
        importance="low",
        reason="Free tier user",
        priority=10
    ),
]
```

**Safe Evaluation** (`safe_eval_condition()` at line 128):

Uses regex-based parsing instead of Python `eval()` for security. Supported expressions:

| Expression | Example | Description |
|------------|---------|-------------|
| Equality | `contact.field == 'value'` | String/number comparison |
| Inequality | `contact.field != 'value'` | Not equal |
| In list | `contact.status in ['active', 'trial']` | Membership test |
| Not in list | `contact.role not in ['guest', 'viewer']` | Non-membership |
| None check | `contact.phone is None` | Null check |
| Not None | `contact.email is not None` | Non-null check |
| Greater/Less | `contact.score >= 80` | Numeric comparison |
| Boolean | `contact.active == True` | Boolean comparison |
| Truthy | `contact.has_subscription` | Truthy check |

**Security**: Rejects arbitrary code, SQL injection attempts, and nested field access. Invalid conditions raise `ValueError`.

**API Endpoints** (`/api/settings/importance-rules`):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | List all rules (ordered by priority descending) |
| `POST` | `/` | Create rule (validates condition syntax) |
| `PUT` | `/{rule_id}` | Update rule |
| `DELETE` | `/{rule_id}` | Delete rule |

## Training Data Collection

The system automatically collects anonymized training samples after each Claude analysis for future small model fine-tuning.

**Collection Point** (email task agent):

```python
result = json.loads(result_text)  # Claude's verdict

# Collect training sample (for both positive and negative verdicts)
self._collect_training_sample(person_data, result, importance)
```

**Collection Method** (`_collect_training_sample()` at line 232):

```python
def _collect_training_sample(
    self,
    person_data: Dict[str, Any],
    claude_response: Dict[str, Any],
    importance: Dict[str, Any]
) -> None:
    """
    Collect anonymized training sample for future model fine-tuning.

    Stores:
    - Anonymized email content (PII removed)
    - Claude's verdict (has_task, reason, is_ai_generated)
    - Importance rule result
    - Feedback type: 'auto_collected'
    """
```

**Data Flow**:

```
Claude analysis complete
       │
       ▼
_collect_training_sample()
       │
       ├─→ Build email_data from thread
       │   {subject, messages, thread_id, message_count}
       │
       ├─→ TriageAnonymizer.anonymize_email_thread()
       │   - Detects PII: EMAIL, PHONE, PERSON, DATE, URL, etc.
       │   - Replaces with: <EMAIL_1>, <PERSON_1>, etc.
       │   - Returns anonymized_data + entity_map
       │
       ├─→ create_sample_hash(anonymized_data)
       │   - SHA256 for deduplication
       │
       └─→ supabase.store_training_sample({
               owner_id, thread_id, email_data,
               predicted_verdict, feedback_type: 'auto_collected'
           })
```

**Anonymization** (`zylch/ml/anonymizer.py`):

```python
class TriageAnonymizer:
    """
    Anonymize email content for training data collection.

    Uses Presidio + spaCy when available, falls back to regex patterns.
    """

    def anonymize(self, text: str) -> Tuple[str, Dict[str, List[str]]]:
        """Returns (anonymized_text, entity_map)."""

    def anonymize_email_thread(self, thread: dict) -> dict:
        """Anonymize entire thread for training."""
```

**PII Categories Detected**:

| Category | Placeholder | Example |
|----------|-------------|---------|
| EMAIL_ADDRESS | `<EMAIL_1>` | `john@example.com` → `<EMAIL_1>` |
| PHONE_NUMBER | `<PHONE_1>` | `+1-555-1234` → `<PHONE_1>` |
| PERSON | `<PERSON_1>` | `John Smith` → `<PERSON_1>` |
| LOCATION | `<LOCATION_1>` | `New York` → `<LOCATION_1>` |
| DATE_TIME | `<DATE_1>` | `12/25/2025` → `<DATE_1>` |
| ORGANIZATION | `<ORG_1>` | `Acme Corp` → `<ORG_1>` |
| CREDIT_CARD | `<FINANCIAL_1>` | Card numbers |
| IP_ADDRESS | `<URL_1>` | IP addresses |
| URL | `<URL_1>` | Web URLs |

## Database Tables

**Core Tables** (created by `migrations/add_triage_tables.sql`):

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `email_triage` | AI triage verdicts | `thread_id`, `needs_human_attention`, `triage_category`, `reason` |
| `importance_rules` | User-defined rules | `name`, `condition`, `importance`, `priority`, `enabled` |
| `triage_training_samples` | Training data | `email_data`, `predicted_verdict`, `actual_verdict`, `feedback_type` |

**`email_triage` Table Schema**:

```sql
CREATE TABLE email_triage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,

    -- Verdict
    needs_human_attention BOOLEAN NOT NULL,
    triage_category TEXT,  -- 'urgent', 'normal', 'low', 'noise'
    reason TEXT,

    -- Classification breakdown
    is_real_customer BOOLEAN,
    is_actionable BOOLEAN,
    is_time_sensitive BOOLEAN,
    is_resolved BOOLEAN,
    is_cold_outreach BOOLEAN,
    is_automated BOOLEAN,

    -- Action
    suggested_action TEXT,
    deadline_detected DATE,

    -- Metadata
    model_used TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(owner_id, thread_id)
);
```

**`importance_rules` Table Schema**:

```sql
CREATE TABLE importance_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    account_id UUID REFERENCES email_accounts(id),
    name TEXT NOT NULL,
    condition TEXT NOT NULL,
    importance TEXT NOT NULL CHECK (importance IN ('high', 'normal', 'low')),
    reason TEXT,
    priority INTEGER DEFAULT 0,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(owner_id, name)
);
```

**`triage_training_samples` Table Schema**:

```sql
CREATE TABLE triage_training_samples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    thread_id TEXT,

    -- Training data (anonymized)
    email_data JSONB NOT NULL,           -- Anonymized email content
    predicted_verdict JSONB NOT NULL,    -- Claude's decision
    actual_verdict JSONB,                -- User correction (if any)
    feedback_type TEXT DEFAULT 'auto_collected',

    -- Pipeline tracking
    used_for_training BOOLEAN DEFAULT FALSE,
    training_batch_id TEXT,

    created_at TIMESTAMPTZ DEFAULT now()
);
```

**Modified Tables**:

| Table | Column Added | Type | Purpose |
|-------|--------------|------|---------|
| `emails` / `email_archive` | `is_auto_reply` | BOOLEAN | Auto-reply flag |

## Key Files Reference

| File | Line | Function/Class | Purpose |
|------|------|----------------|---------|
| `utils/auto_reply_detector.py` | 1-89 | `detect_auto_reply()` | RFC 3834 header detection |
| `utils/auto_reply_detector.py` | 91-137 | `get_auto_reply_reason()` | Human-readable reason |
| `models/importance_rules.py` | 17-91 | `ImportanceRule` | Rule dataclass with evaluate/serialize |
| `models/importance_rules.py` | 94-125 | `evaluate_rules()` | Priority-ordered rule evaluation |
| `models/importance_rules.py` | 128-305 | `safe_eval_condition()` | Secure regex-based evaluation |
| `services/email_task_agent_trainer.py` | — | Email task agent | Task detection with importance rules |
| `tools/email_sync.py` | varies | `_analyze_thread()` | Early-exit for auto-replies |
| `tools/email_sync.py` | varies | `_build_auto_reply_thread_data()` | Thread data without Claude |
| `ml/anonymizer.py` | 17-255 | `TriageAnonymizer` | PII detection and replacement |
| `ml/anonymizer.py` | 258-275 | `create_sample_hash()` | SHA256 deduplication hash |
| `storage/supabase_client.py` | 2197-2229 | `store_training_sample()` | Save training sample |
| `storage/supabase_client.py` | 2256-2280 | `get_importance_rules()` | Load rules for user |
| `api/routes/settings.py` | varies | `importance_rules_*` | CRUD API endpoints |

## Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/test_auto_reply_detector.py` | 35 | RFC 3834 headers, email patterns, edge cases |
| `zylch/tests/test_importance_rules.py` | 32 | Rule creation, safe_eval, evaluate_rules, real-world scenarios |

**Test Categories**:

**Auto-Reply Detector** (35 tests):
- RFC 3834 `Auto-Submitted` header variants
- `X-Autoreply` header detection
- `Precedence` header values
- `X-Auto-Response-Suppress` presence
- From/Reply-To email pattern matching
- Case-insensitive handling
- Edge cases (empty headers, whitespace, etc.)

**Importance Rules** (32 tests):
- Rule creation and serialization
- All safe_eval patterns (==, !=, in, not in, is None, >=, etc.)
- Boolean comparisons
- Missing field handling
- Code injection rejection
- Priority-based evaluation
- Real-world MrCall scenarios

## ML Training Pipeline

**Current Status**: Infrastructure implemented, data collection active

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1-3 | ✅ Complete | Auto-reply detection, AI triage, importance rules |
| Phase 4 | ✅ Active | Data collection (anonymizer + storage wired up) |
| Phase 5 | 📋 Planned | Fine-tuning pipeline (QLoRA on Qwen2.5) |
| Phase 6 | 📋 Planned | Desktop deployment (MLX, llama.cpp) |
| Phase 7 | 📋 Planned | Mobile deployment (CoreML, ONNX) |

**Target Models**:

| Model | Size | Use Case | Format |
|-------|------|----------|--------|
| Qwen2.5-1.5B | 1.5B | Desktop/Server | GGUF Q4_K_M (~900MB) |
| Qwen2.5-0.5B | 0.5B | Mobile | CoreML/ONNX (~500MB) |

**Future Hybrid Inference** (planned):

```python
class HybridTriageClassifier:
    """
    Try local model first, fall back to Claude if:
    - Local model unavailable
    - Confidence below threshold (0.85)
    - Complex edge case detected
    """
```

## Performance Impact

| Operation | Before | After |
|-----------|--------|-------|
| Auto-reply thread analysis | ~3-5s (Claude) | <100ms (early-exit) |
| Training sample collection | N/A | <50ms (async, non-blocking) |
| Importance rule evaluation | N/A | <10ms |

**API Cost Savings**: Auto-reply threads skip LLM entirely, saving API costs per thread.

## Architecture Decisions

1. **No template content matching** - Rely only on headers and email patterns (privacy-safe)
2. **Regex-based rule evaluation** - No Python `eval()` for security
3. **Early-exit for auto-replies** - Skip Claude analysis to save API costs
4. **Automatic training data collection** - Anonymize and store every Claude verdict

## Recent Changes (December 2025)

**Problem Solved**: Support emails incorrectly marked "resolved" when auto-reply sent.

**Features Added**:

| Feature | Status | Tests |
|---------|--------|-------|
| RFC 3834 Auto-Reply Detection | ✅ Complete | 35 tests |
| Configurable Importance Rules | ✅ Complete | 32 tests |
| Training Data Collection | ✅ Active | — |
| Small Model Fine-Tuning | 📋 Planned | — |

**Key Files Created**:

```
zylch/
├── utils/
│   └── auto_reply_detector.py       # RFC 3834 header detection
├── models/
│   └── importance_rules.py          # Rule engine with safe_eval
├── ml/
│   └── anonymizer.py                # PII anonymization for training
├── api/routes/
│   └── settings.py                  # Importance rules CRUD API
└── migrations/
    └── add_triage_tables.sql        # Database schema

tests/
├── test_auto_reply_detector.py      # 35 tests
└── zylch/tests/
    └── test_importance_rules.py     # 32 tests
```

**Key Files Modified**:

| File | Changes |
|------|---------|
| `services/email_task_agent_trainer.py` | Task detection with importance rules and auto-reply filtering |
| `tools/email_sync.py` | Added early-exit for auto-replies, `_build_auto_reply_thread_data()` |
| `tools/gmail.py` | Extract RFC 3834 headers in `_parse_message()` |
| `storage/supabase_client.py` | Added `store_training_sample()`, `get_importance_rules()`, `get_contact_by_email()` |
