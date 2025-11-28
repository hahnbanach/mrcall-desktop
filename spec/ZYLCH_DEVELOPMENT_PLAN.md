# Zylch AI Development Plan
## Implementation Roadmap & Status

**Last Updated:** November 23, 2024
**Based on:** ANALYSIS_ZYLCH_SKILLS.md, SERVICE_LAYER_ARCHITECTURE.md
**Scope:** 0-100 Customer Horizon (18-24 months)
**Approach:** Incremental, additive, non-breaking

---

## Current Status (November 2024)

### MrCall Dashboard Integration ✅

**Status:** Completed (November 24, 2024)
**Integration:** Firebase-authenticated chat interface in Vue.js dashboard

Zylch AI is now accessible via web dashboard with full authentication:

**What Was Built:**
- Firebase Admin SDK integration for JWT authentication
- Multi-user chat session management with persistence
- RESTful API endpoints (`/api/chat/*`)
- Vue.js chat component with real-time UI
- Multi-language support (English + Italian)
- Session persistence across page reloads

**Backend (Zylch):**
```
zylch/api/
├── firebase_auth.py         # Firebase token validation
├── routes/chat.py           # Chat API endpoints
└── main.py                  # Server initialization

zylch/services/
└── chat_session.py          # Session management

cache/chat_sessions/         # Persistent chat history
```

**Frontend (Dashboard):**
```
src/utils/Zylch.js           # API wrapper
src/components/ZylchChat.vue # Chat interface
src/views/Zylch.vue          # Page wrapper
src/router/index.js          # /zylch route
src/components/Navbar.vue    # Navigation integration
```

**Access:** `https://dashboard.mrcall.ai/zylch` (production)

**Documentation:** See SERVICE_LAYER_ARCHITECTURE.md Section 6

---

### Email Archive System ✅

**Status:** Production Ready (477 messages archived)

Zylch maintains a permanent local archive of emails in SQLite:

**Storage:**
```
cache/emails/
├── archive.db (5.2 MB) - Permanent email storage
└── threads.json (2.2 MB) - AI-analyzed intelligence cache
```

**Checking Archive Status:**
```bash
# Via SQLite
sqlite3 cache/emails/archive.db "SELECT COUNT(*) FROM messages"
sqlite3 cache/emails/archive.db "SELECT MIN(date), MAX(date) FROM messages"

# Via CLI
/archive          # Show statistics
/archive --sync   # Incremental sync

# Via HTTP API
GET /api/archive/stats
```

**Documentation:** EMAIL_ARCHIVE_SYSTEM.md, CLI_ARCHIVE_COMMANDS.md

---

### Recently Completed: ToolFactory Refactoring ✅

**Date:** November 23, 2024
**Status:** COMPLETED AND VALIDATED (A+ Grade)

#### What Was Done

Successfully completed a major architectural refactoring to eliminate the dependency violation where the Service layer was depending on the CLI layer. This was achieved through the Factory Pattern:

1. **Created ToolFactory Infrastructure** (`zylch/tools/`)
   - `config.py` - ToolConfig dataclass for centralized configuration (135 lines)
   - `factory.py` - ToolFactory with centralized tool creation (~1800 lines)
   - Updated `__init__.py` to export ToolFactory and ToolConfig

2. **Refactored Service Layer** (`zylch/services/chat_service.py`)
   - Removed dependency on ZylchAICLI (CLI layer)
   - Now uses ToolFactory directly for agent initialization
   - Added comprehensive exception handling (AuthenticationError, RateLimitError, APIConnectionError)

3. **Refactored CLI** (`zylch/cli/main.py`)
   - Reduced from 2,694 lines to 1,069 lines (60% reduction!)
   - Removed 1,600+ lines of inline tool definitions
   - Now uses ToolFactory for tool creation

4. **Documentation** (`SERVICE_LAYER_ARCHITECTURE.md`)
   - Added comprehensive Section 5 documenting ToolFactory Pattern
   - Architecture diagrams, usage examples, benefits

5. **Testing** (`tests/test_tool_factory.py`)
   - Created 11 comprehensive unit tests
   - All tests passing (100% success rate)
   - Tests cover: tool creation, memory system, model selector, error handling, configuration

#### Results

- **Code Reduction:** 60% reduction in CLI code (2,694 → 1,069 lines)
- **Architecture:** Clean separation between Service and CLI layers
- **Maintainability:** Single source of truth for all 25 tools
- **Validation:** A+ grade from refactor-architecture-validator agent
- **Test Coverage:** 11 comprehensive unit tests with 100% pass rate

#### Files Modified

- `zylch/tools/config.py` (created)
- `zylch/tools/factory.py` (created)
- `zylch/tools/__init__.py` (updated)
- `zylch/services/chat_service.py` (refactored)
- `zylch/cli/main.py` (refactored)
- `SERVICE_LAYER_ARCHITECTURE.md` (documented)
- `tests/test_tool_factory.py` (created)

---

## Pending Improvements

### High Priority

All high-priority improvements from the recent refactoring have been completed:
- ✅ SERVICE_LAYER_ARCHITECTURE.md updated with ToolFactory documentation
- ✅ Unit tests created for ToolFactory (11 tests, all passing)
- ✅ Exception handling added to Chat API

### Medium Priority

Recommended improvements for the ToolFactory pattern:

#### 1. Tool Registry Pattern for Scalability
**Motivation:** As the tool count grows, a registry pattern would improve discoverability and management.

**Implementation:**
```python
# zylch/tools/registry.py
class ToolRegistry:
    """Registry for tool discovery and management."""

    def __init__(self):
        self._tools: Dict[str, Type[Tool]] = {}

    def register(self, tool_class: Type[Tool], category: str):
        """Register a tool class."""
        self._tools[tool_class.name] = {
            "class": tool_class,
            "category": category
        }

    def list_by_category(self, category: str) -> List[Type[Tool]]:
        """List all tools in a category."""
        return [
            info["class"]
            for info in self._tools.values()
            if info["category"] == category
        ]
```

**Benefits:**
- Better tool organization by category (Gmail, Calendar, Contacts, etc.)
- Easier to add/remove tools without modifying factory
- Foundation for future dynamic tool loading

**Effort:** 2-3 days

#### 2. Retry Mechanisms for Service Initialization
**Motivation:** External services (StarChat, Gmail) can fail temporarily during initialization.

**Implementation:**
```python
# In ToolFactory.create_all_tools()
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def _init_starchat_with_retry(config):
    """Initialize StarChat with exponential backoff."""
    return StarChatClient(
        api_url=config.starchat_api_url,
        api_key=config.starchat_api_key,
        username=config.starchat_username,
        password=config.starchat_password,
        auth_method=config.starchat_auth_method
    )
```

**Benefits:**
- More resilient to transient failures
- Better user experience (automatic recovery)
- Reduced initialization failures in production

**Effort:** 1-2 days

#### 3. Configuration Validation
**Motivation:** Invalid configuration can cause cryptic errors during tool creation.

**Implementation:**
```python
# In ToolConfig class
def validate(self) -> List[str]:
    """Validate configuration and return list of errors."""
    errors = []

    if not self.anthropic_api_key:
        errors.append("ANTHROPIC_API_KEY is required")

    if not Path(self.google_credentials_path).exists():
        errors.append(f"Google credentials not found: {self.google_credentials_path}")

    if self.pipedrive_enabled and not self.pipedrive_api_token:
        errors.append("Pipedrive enabled but PIPEDRIVE_API_TOKEN not set")

    return errors
```

**Benefits:**
- Early detection of configuration issues
- Clear error messages for users
- Prevents runtime failures

**Effort:** 1 day

### Low Priority

Nice-to-have improvements for future consideration:

#### 1. Performance Monitoring and Metrics
**Motivation:** Track tool initialization time and resource usage.

**Implementation:**
```python
# Add metrics collection to ToolFactory
import time
from dataclasses import dataclass

@dataclass
class FactoryMetrics:
    total_tools_created: int
    initialization_time_ms: float
    service_init_times: Dict[str, float]

class ToolFactory:
    _metrics: Optional[FactoryMetrics] = None

    @staticmethod
    async def create_all_tools(config: ToolConfig) -> List[Tool]:
        start_time = time.time()
        service_times = {}

        # Track each service initialization time
        starchat_start = time.time()
        starchat = StarChatClient(...)
        service_times["starchat"] = (time.time() - starchat_start) * 1000

        # ... create tools ...

        ToolFactory._metrics = FactoryMetrics(
            total_tools_created=len(tools),
            initialization_time_ms=(time.time() - start_time) * 1000,
            service_init_times=service_times
        )

        return tools

    @staticmethod
    def get_metrics() -> Optional[FactoryMetrics]:
        return ToolFactory._metrics
```

**Benefits:**
- Identify slow initialization steps
- Monitor production performance
- Data-driven optimization decisions

**Effort:** 2-3 days

#### 2. Tool Versioning
**Motivation:** Support multiple versions of tools for A/B testing and gradual rollouts.

**Implementation:**
```python
# Version-aware tool creation
class ToolFactory:
    @staticmethod
    async def create_all_tools(
        config: ToolConfig,
        tool_versions: Optional[Dict[str, str]] = None
    ) -> List[Tool]:
        """Create tools with optional version specification.

        Args:
            tool_versions: {"gmail": "v2", "calendar": "v1"}
        """
        versions = tool_versions or {}

        # Use versioned tool if specified
        gmail_version = versions.get("gmail", "v1")
        if gmail_version == "v2":
            tools.extend(ToolFactory._create_gmail_tools_v2(gmail))
        else:
            tools.extend(ToolFactory._create_gmail_tools(gmail))
```

**Benefits:**
- Safe A/B testing of tool improvements
- Gradual rollout of breaking changes
- Easier deprecation of old tool versions

**Effort:** 3-4 days

#### 3. Tool Health Checks
**Motivation:** Verify external services are healthy before creating tools.

**Implementation:**
```python
@dataclass
class ServiceHealth:
    service_name: str
    healthy: bool
    latency_ms: float
    error: Optional[str] = None

class ToolFactory:
    @staticmethod
    async def check_service_health(config: ToolConfig) -> List[ServiceHealth]:
        """Check health of all external services."""
        health_checks = []

        # Check StarChat
        start = time.time()
        try:
            starchat = StarChatClient(...)
            await starchat.health_check()
            health_checks.append(ServiceHealth(
                service_name="starchat",
                healthy=True,
                latency_ms=(time.time() - start) * 1000
            ))
        except Exception as e:
            health_checks.append(ServiceHealth(
                service_name="starchat",
                healthy=False,
                latency_ms=(time.time() - start) * 1000,
                error=str(e)
            ))

        return health_checks
```

**Benefits:**
- Better operational visibility
- Easier debugging of initialization failures
- Foundation for health dashboard

**Effort:** 2-3 days

---

## Skill-Based Architecture Evolution

### Executive Summary

This section provides a concrete implementation plan for evolving Zylch from command-based CLI to skill-based natural language interface, following the strategic analysis in ANALYSIS_ZYLCH_SKILLS.md.

**Key Principles:**
1. ✅ **Don't rewrite existing code** - Wrap it in skills
2. ✅ **Start minimal** - 3 skills prove the concept
3. ✅ **Incremental migration** - New architecture alongside existing
4. ✅ **Battle-tested tools** - SQLite, Redis, standard patterns
5. ✅ **Configurable models** - All LLM choices in .env, not hard-coded
6. ✅ **Measure everything** - A/B test, metrics, user feedback

---

## Configuration Strategy: Model Selection

**Philosophy:** All LLM model choices should be configurable via environment variables, not hard-coded. This enables:
- Easy model upgrades without code changes
- Cost/performance tuning per deployment
- A/B testing different models
- Self-hosted model options for enterprise

### New Environment Variables

Add to `.env.example`:

```bash
# Skill System Models
SKILL_ROUTER_MODEL=claude-3-5-haiku-20241022  # Intent classification (fast, cheap)
SKILL_EXECUTION_MODEL=claude-sonnet-4-20250514  # Skill execution (accurate)
SKILL_PATTERN_MODEL=claude-3-5-haiku-20241022  # Pattern matching (fast)

# Performance Optimization
ENABLE_PROMPT_CACHING=true
ENABLE_BATCH_PROCESSING=false  # Requires Anthropic Batches API access
CLAUDE_QUEUE_ENABLED=false  # Enable API request queue

# Pattern Learning
PATTERN_STORE_ENABLED=true
PATTERN_STORE_PATH=.swarm/patterns.db  # SQLite database for patterns
PATTERN_CONFIDENCE_THRESHOLD=0.5
PATTERN_MAX_RESULTS=3

# Storage Backend
STORAGE_BACKEND=json  # Options: json, sqlite, hybrid
SQLITE_DB_PATH=.swarm/threads.db
```

### Updated Config Class

Extend `zylch/config.py`:

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # Skill System Models
    skill_router_model: str = Field(
        default="claude-3-5-haiku-20241022",
        description="Model for intent classification (router)"
    )
    skill_execution_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Model for skill execution"
    )
    skill_pattern_model: str = Field(
        default="claude-3-5-haiku-20241022",
        description="Model for pattern matching"
    )

    # Performance
    enable_prompt_caching: bool = Field(default=True)
    enable_batch_processing: bool = Field(default=False)
    claude_queue_enabled: bool = Field(default=False)

    # Pattern Learning
    pattern_store_enabled: bool = Field(default=True)
    pattern_store_path: str = Field(default=".swarm/patterns.db")
    pattern_confidence_threshold: float = Field(default=0.5)
    pattern_max_results: int = Field(default=3)

    # Storage
    storage_backend: str = Field(default="json")  # json, sqlite, hybrid
    sqlite_db_path: str = Field(default=".swarm/threads.db")
```

**Usage in code:**
```python
from zylch.config import settings

# Intent classification uses configured model
router_response = await anthropic_client.messages.create(
    model=settings.skill_router_model,  # NOT hard-coded!
    messages=[...]
)

# Skill execution uses configured model
skill_response = await anthropic_client.messages.create(
    model=settings.skill_execution_model,
    messages=[...]
)
```

---

## Phase A: Foundation (Week 1-2) - Skill Architecture Core

### 1. Create Base Skill System

**File:** `zylch/skills/base.py`

```python
"""Base skill system for Zylch AI skill-based architecture."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
from zylch.config import settings


@dataclass
class SkillResult:
    """Result from skill execution."""
    success: bool
    data: Any
    message: str
    skill_name: str
    execution_time_ms: float
    tokens_used: Optional[int] = None
    model_used: Optional[str] = None


@dataclass
class SkillContext:
    """Context provided to skill execution."""
    user_id: str
    intent: str
    params: Dict[str, Any]
    conversation_history: List[Dict[str, Any]]
    memory_rules: List[Dict[str, Any]]
    patterns: List[Dict[str, Any]]


class BaseSkill(ABC):
    """Abstract base class that all skills inherit from."""

    def __init__(self, skill_name: str, description: str):
        self.skill_name = skill_name
        self.description = description
        self.execution_model = settings.skill_execution_model  # From config!

    async def activate(self, context: SkillContext) -> SkillResult:
        """Main entry point for skill activation."""
        start_time = datetime.now()

        try:
            # Pre-execution: Load context, validate
            await self.pre_execute(context)

            # Core logic
            result = await self.execute(context)

            # Post-execution: Store patterns, update memory
            await self.post_execute(context, result)

            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            return SkillResult(
                success=True,
                data=result,
                message=f"{self.skill_name} completed successfully",
                skill_name=self.skill_name,
                execution_time_ms=execution_time,
                model_used=self.execution_model
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            return SkillResult(
                success=False,
                data=None,
                message=f"{self.skill_name} failed: {str(e)}",
                skill_name=self.skill_name,
                execution_time_ms=execution_time
            )

    async def pre_execute(self, context: SkillContext):
        """Pre-execution hook: Load context, validate parameters."""
        pass

    @abstractmethod
    async def execute(self, context: SkillContext) -> Any:
        """Core skill logic - must be implemented by concrete skills."""
        pass

    async def post_execute(self, context: SkillContext, result: Any):
        """Post-execution hook: Store patterns, update memory."""
        pass

    def get_skill_info(self) -> Dict[str, Any]:
        """Returns skill metadata for router."""
        return {
            "name": self.skill_name,
            "description": self.description,
            "model": self.execution_model
        }
```

### 2. Intent Router

**File:** `zylch/router/intent_classifier.py`

```python
"""Lightweight Haiku-based intent classification."""

import json
from typing import Dict, Any, List
from anthropic import Anthropic
from zylch.config import settings


class IntentRouter:
    """Routes user input to appropriate skill(s)."""

    def __init__(self, skill_registry):
        self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.skill_registry = skill_registry
        self.router_model = settings.skill_router_model  # From config!

    async def classify_intent(self, user_input: str, conversation_history: List = None) -> Dict[str, Any]:
        """
        Classify user intent using configured model (typically Haiku for speed/cost).

        Returns:
            {
                "primary_skill": "draft_composer",
                "context_skills": ["email_triage"],
                "params": {"contact": "luisa", "type": "reminder"},
                "confidence": 0.95
            }
        """

        # Get available skills from registry
        available_skills = self.skill_registry.list_skills()

        classification_prompt = f"""You are an intent classification system for Zylch AI.

User said: "{user_input}"

Available skills:
{json.dumps(available_skills, indent=2)}

Analyze the user's intent and determine:
1. Which PRIMARY skill should handle this request
2. Which CONTEXT skills need to run first (for gathering info)
3. Extract relevant parameters

Respond with JSON only (use JSON mode):
{{
  "primary_skill": "skill_name",
  "context_skills": ["skill1", "skill2"],
  "params": {{"key": "value"}},
  "confidence": 0.0-1.0
}}

Rules:
- primary_skill: The main skill that fulfills the request
- context_skills: Skills that gather context before primary (empty if none needed)
- params: Extracted entities (contact names, dates, types, etc.)
- confidence: How confident you are in this classification
"""

        response = self.client.messages.create(
            model=self.router_model,  # Configurable!
            max_tokens=500,
            temperature=0,
            messages=[{
                "role": "user",
                "content": classification_prompt
            }]
        )

        # Parse JSON response (use structured outputs in production)
        result = json.loads(response.content[0].text)

        return result
```

### 3. Skill Registry

**File:** `zylch/skills/registry.py`

```python
"""Central registry of available skills."""

from typing import Dict, Type, List
from zylch.skills.base import BaseSkill


class SkillRegistry:
    """Manages skill registration and discovery."""

    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register_skill(self, skill_instance: BaseSkill):
        """Register a skill instance."""
        self._skills[skill_instance.skill_name] = skill_instance

    def get_skill(self, skill_name: str) -> BaseSkill:
        """Get skill by name."""
        if skill_name not in self._skills:
            raise ValueError(f"Skill '{skill_name}' not found in registry")
        return self._skills[skill_name]

    def list_skills(self) -> List[Dict[str, Any]]:
        """List all available skills with metadata (for router)."""
        return [skill.get_skill_info() for skill in self._skills.values()]

    def has_skill(self, skill_name: str) -> bool:
        """Check if skill is registered."""
        return skill_name in self._skills


# Global registry instance
registry = SkillRegistry()
```

---

## Phase A: Core Skills (Week 3-4)

### 4. EmailTriageSkill

**File:** `zylch/skills/email_triage.py`

```python
"""Email triage skill - wraps existing email_sync + relationship_analyzer."""

from typing import Any, List, Dict
from zylch.skills.base import BaseSkill, SkillContext
from zylch.tools.email_sync import EmailSyncManager
from zylch.tools.relationship_analyzer import RelationshipAnalyzer
from zylch.config import settings


class EmailTriageSkill(BaseSkill):
    """Find and analyze relevant email threads."""

    def __init__(self):
        super().__init__(
            skill_name="email_triage",
            description="Find and prioritize email threads by contact, subject, or content"
        )
        self.email_sync = EmailSyncManager()
        self.analyzer = RelationshipAnalyzer()

    async def execute(self, context: SkillContext) -> Any:
        """
        Execute email search and triage.

        Params:
            contact: Contact name or email
            subject: Email subject to search
            priority: Filter by priority (high, medium, low)
            days_back: How many days to look back
        """
        params = context.params

        # Extract search criteria
        contact = params.get("contact")
        subject = params.get("subject")
        priority = params.get("priority")
        days_back = params.get("days_back", 30)

        # Use existing email search functionality
        threads = self.email_sync.search_threads(
            participant=contact,
            subject=subject,
            days_back=days_back
        )

        # If priority filter requested, use analyzer
        if priority:
            threads = [
                t for t in threads
                if self._match_priority(t, priority)
            ]

        # Return structured results
        return {
            "threads": threads,
            "count": len(threads),
            "search_criteria": {
                "contact": contact,
                "subject": subject,
                "priority": priority,
                "days_back": days_back
            }
        }

    def _match_priority(self, thread: Dict, priority: str) -> bool:
        """Match thread priority (high/medium/low)."""
        score = thread.get("priority_score", 5)

        if priority == "high":
            return score >= 8
        elif priority == "medium":
            return 5 <= score < 8
        else:  # low
            return score < 5
```

### 5. DraftComposerSkill

**File:** `zylch/skills/draft_composer.py`

```python
"""Draft composition skill with memory and pattern integration."""

from typing import Any, Dict
from anthropic import Anthropic
from zylch.skills.base import BaseSkill, SkillContext
from zylch.memory.reasoning_bank import ReasoningBankMemory
from zylch.memory.pattern_store import PatternStore  # New!
from zylch.config import settings


class DraftComposerSkill(BaseSkill):
    """Compose email drafts with personalized style and patterns."""

    def __init__(self):
        super().__init__(
            skill_name="draft_composer",
            description="Compose email drafts using memory rules and learned patterns"
        )
        self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.pattern_store = PatternStore() if settings.pattern_store_enabled else None

    async def pre_execute(self, context: SkillContext):
        """Load context: thread, memory rules, patterns."""
        # Memory rules already in context.memory_rules

        # Retrieve similar successful patterns
        if self.pattern_store and settings.pattern_store_enabled:
            patterns = self.pattern_store.retrieve_similar(
                intent=context.intent,
                limit=settings.pattern_max_results
            )
            context.patterns = patterns

    async def execute(self, context: SkillContext) -> Any:
        """Generate draft using Sonnet with memory + patterns."""
        params = context.params

        # Build prompt with memory rules
        memory_section = self._build_memory_section(context.memory_rules)
        pattern_section = self._build_pattern_section(context.patterns)

        prompt = f"""You are composing an email draft for the user.

{memory_section}

{pattern_section}

Task: {params.get('task', 'Compose email')}
Contact: {params.get('contact', 'Unknown')}
Context: {params.get('thread_context', 'No previous context')}

Instructions:
{params.get('instructions', 'Write a professional email')}

Generate the email draft following the memory rules and successful patterns above.
Return JSON: {{"draft": "email body", "subject": "email subject"}}
"""

        # Use configured execution model
        response = self.client.messages.create(
            model=self.execution_model,  # From config!
            max_tokens=2000,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse result (use structured outputs in production)
        import json
        result = json.loads(response.content[0].text)

        return result

    async def post_execute(self, context: SkillContext, result: Any):
        """Store successful pattern if user approves."""
        # This will be called after user approval
        # Pattern storage happens in CLI when user confirms draft
        pass

    def _build_memory_section(self, memory_rules: List[Dict]) -> str:
        """Build memory rules section for prompt."""
        if not memory_rules:
            return ""

        rules_text = "MEMORY RULES (PRIORITY - ALWAYS FOLLOW):\n"
        for rule in memory_rules:
            rules_text += f"- {rule['correct_behavior']}\n"

        return rules_text

    def _build_pattern_section(self, patterns: List[Dict]) -> str:
        """Build successful patterns section for prompt."""
        if not patterns:
            return ""

        pattern_text = "SUCCESSFUL PATTERNS (learn from these):\n"
        for pattern in patterns:
            pattern_text += f"- {pattern['summary']} (confidence: {pattern['confidence']:.0%})\n"

        return pattern_text
```

### 6. CrossChannelOrchestratorSkill

**File:** `zylch/skills/cross_channel.py`

```python
"""Cross-channel orchestration skill."""

from typing import Any, List, Dict
from zylch.skills.base import BaseSkill, SkillContext
from zylch.intelligence.context_graph import ContextGraph  # New!
from zylch.config import settings


class CrossChannelOrchestratorSkill(BaseSkill):
    """Orchestrate multiple skills across channels (email + phone + calendar)."""

    def __init__(self, skill_registry):
        super().__init__(
            skill_name="cross_channel_orchestrator",
            description="Coordinate actions across email, phone, and calendar"
        )
        self.registry = skill_registry
        self.context_graph = ContextGraph()

    async def execute(self, context: SkillContext) -> Any:
        """
        Orchestrate multi-channel workflow.

        Example: "Marco called about proposal, draft follow-up with meeting times"

        Workflow:
        1. PhoneHandlerSkill: Get call transcript
        2. EmailTriageSkill: Find proposal email thread
        3. MeetingSchedulerSkill: Check calendar availability
        4. DraftComposerSkill: Generate email with all context
        """
        params = context.params

        # Build context graph for this contact
        contact = params.get("contact")
        graph_context = self.context_graph.get_context(contact)

        # Determine skill sequence based on intent
        skill_sequence = self._plan_skill_sequence(context.intent, params, graph_context)

        # Execute skills in sequence, passing context forward
        results = []
        accumulated_context = {}

        for skill_name in skill_sequence:
            skill = self.registry.get_skill(skill_name)

            # Enrich context with accumulated data
            skill_context = SkillContext(
                user_id=context.user_id,
                intent=context.intent,
                params={**params, **accumulated_context},
                conversation_history=context.conversation_history,
                memory_rules=context.memory_rules,
                patterns=context.patterns
            )

            # Execute skill
            result = await skill.activate(skill_context)
            results.append(result)

            # Accumulate context for next skill
            accumulated_context.update(result.data)

        return {
            "orchestration": {
                "skills_executed": skill_sequence,
                "results": results,
                "final_context": accumulated_context
            }
        }

    def _plan_skill_sequence(self, intent: str, params: Dict, graph_context: Dict) -> List[str]:
        """
        Determine which skills to run and in what order.

        This is a simple heuristic version. Could be made smarter with LLM planning.
        """
        sequence = []

        # Check what data we need
        needs_phone = "call" in intent.lower() or "phone" in intent.lower()
        needs_email = "email" in intent.lower() or "proposal" in intent.lower()
        needs_calendar = "meeting" in intent.lower() or "schedule" in intent.lower()
        needs_draft = "draft" in intent.lower() or "write" in intent.lower()

        # Build sequence
        if needs_phone:
            sequence.append("phone_handler")

        if needs_email:
            sequence.append("email_triage")

        if needs_calendar:
            sequence.append("meeting_scheduler")

        if needs_draft:
            sequence.append("draft_composer")

        return sequence
```

---

## Phase B: Pattern Learning (Week 5-7)

### 7. Pattern Store

**File:** `zylch/memory/pattern_store.py`

```python
"""SQLite-based pattern storage for learned interaction patterns."""

import sqlite3
import json
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from zylch.config import settings


class PatternStore:
    """Store and retrieve successful interaction patterns."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.pattern_store_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database with schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Patterns table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id TEXT PRIMARY KEY,
                skill TEXT NOT NULL,
                intent_hash TEXT NOT NULL,
                context TEXT NOT NULL,
                action TEXT NOT NULL,
                outcome TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                usage_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_used TEXT,
                user_id TEXT NOT NULL
            )
        """)

        # Embeddings table (hash-based initially, can add vector embeddings later)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pattern_embeddings (
                pattern_id TEXT PRIMARY KEY,
                embedding_hash TEXT NOT NULL,
                FOREIGN KEY (pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
            )
        """)

        # Trajectories table (skill execution sequences)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trajectories (
                id TEXT PRIMARY KEY,
                pattern_id TEXT NOT NULL,
                skill_sequence TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                success BOOLEAN NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_intent_hash ON patterns(intent_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill ON patterns(skill)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_confidence ON patterns(confidence)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_embedding_hash ON pattern_embeddings(embedding_hash)")

        conn.commit()
        conn.close()

    def store_pattern(
        self,
        skill: str,
        intent: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: str,
        user_id: str
    ) -> str:
        """Store a successful pattern."""

        # Generate intent hash for similarity matching
        intent_hash = self._hash_intent(intent)

        # Generate pattern ID
        pattern_id = hashlib.sha256(
            f"{skill}:{intent_hash}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO patterns (
                id, skill, intent_hash, context, action, outcome,
                confidence, usage_count, success_count, created_at, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pattern_id,
            skill,
            intent_hash,
            json.dumps(context),
            json.dumps(action),
            outcome,
            0.5,  # Initial confidence
            1,
            1,
            datetime.now().isoformat(),
            user_id
        ))

        # Store embedding hash
        cursor.execute("""
            INSERT INTO pattern_embeddings (pattern_id, embedding_hash)
            VALUES (?, ?)
        """, (pattern_id, intent_hash))

        conn.commit()
        conn.close()

        return pattern_id

    def retrieve_similar(
        self,
        intent: str,
        skill: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Retrieve similar successful patterns."""

        intent_hash = self._hash_intent(intent)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT p.*, pe.embedding_hash
            FROM patterns p
            JOIN pattern_embeddings pe ON p.id = pe.pattern_id
            WHERE p.confidence >= ?
        """
        params = [settings.pattern_confidence_threshold]

        if skill:
            query += " AND p.skill = ?"
            params.append(skill)

        # Simple hash matching (can be enhanced with vector similarity)
        query += " AND pe.embedding_hash = ?"
        params.append(intent_hash)

        query += " ORDER BY p.confidence DESC, p.usage_count DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        patterns = []
        for row in rows:
            patterns.append({
                "id": row["id"],
                "skill": row["skill"],
                "context": json.loads(row["context"]),
                "action": json.loads(row["action"]),
                "outcome": row["outcome"],
                "confidence": row["confidence"],
                "usage_count": row["usage_count"],
                "summary": self._summarize_pattern(row)
            })

        conn.close()
        return patterns

    def update_confidence(self, pattern_id: str, success: bool):
        """Update pattern confidence based on outcome (Bayesian update)."""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get current confidence
        cursor.execute("SELECT confidence, usage_count, success_count FROM patterns WHERE id = ?", (pattern_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return

        confidence, usage_count, success_count = row

        # Bayesian update (same as ReasoningBank)
        if success:
            new_confidence = confidence + 0.15 * (1 - confidence)
            new_success = success_count + 1
        else:
            new_confidence = confidence - 0.10 * confidence
            new_success = success_count

        new_usage = usage_count + 1

        cursor.execute("""
            UPDATE patterns
            SET confidence = ?, usage_count = ?, success_count = ?, last_used = ?
            WHERE id = ?
        """, (new_confidence, new_usage, new_success, datetime.now().isoformat(), pattern_id))

        conn.commit()
        conn.close()

    def _hash_intent(self, intent: str) -> str:
        """Generate hash for intent similarity matching."""
        # Normalize: lowercase, remove punctuation, sort words
        words = sorted(intent.lower().replace("?", "").replace("!", "").split())
        normalized = " ".join(words)
        return hashlib.md5(normalized.encode()).hexdigest()[:8]

    def _summarize_pattern(self, row) -> str:
        """Create human-readable pattern summary."""
        return f"{row['skill']}: {row['outcome']} (used {row['usage_count']}x)"
```

---

## Phase B: Performance Optimizations (Week 8-9)

### 8. SQLite Thread Storage (Optional, for scale)

**File:** `zylch/storage/sqlite_backend.py`

```python
"""SQLite backend for thread storage (migration from threads.json)."""

import sqlite3
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from zylch.config import settings


class SQLiteThreadStore:
    """SQLite-based thread storage with indexing."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.sqlite_db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                participants TEXT NOT NULL,
                date TEXT NOT NULL,
                body_preview TEXT,
                summary TEXT,
                open BOOLEAN NOT NULL,
                expected_action TEXT,
                priority_score INTEGER,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                raw_data TEXT NOT NULL
            )
        """)

        # Indexes for fast search
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_participants ON threads(participants)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subject ON threads(subject)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON threads(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_priority ON threads(priority_score)")

        # Full-text search (optional, SQLite FTS5)
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS threads_fts USING fts5(
                thread_id,
                subject,
                body_preview,
                summary
            )
        """)

        conn.commit()
        conn.close()

    def search(
        self,
        participant: Optional[str] = None,
        subject: Optional[str] = None,
        date_range: Optional[tuple] = None,
        full_text: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Search threads with multiple criteria."""

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM threads WHERE 1=1"
        params = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        if participant:
            query += " AND participants LIKE ?"
            params.append(f"%{participant}%")

        if subject:
            query += " AND subject LIKE ?"
            params.append(f"%{subject}%")

        if date_range:
            query += " AND date BETWEEN ? AND ?"
            params.extend(date_range)

        if full_text:
            # Use FTS5 for full-text search
            cursor.execute("""
                SELECT thread_id FROM threads_fts WHERE threads_fts MATCH ?
            """, (full_text,))
            thread_ids = [row[0] for row in cursor.fetchall()]

            if thread_ids:
                placeholders = ",".join("?" * len(thread_ids))
                query += f" AND id IN ({placeholders})"
                params.extend(thread_ids)
            else:
                # No FTS matches
                conn.close()
                return []

        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        threads = []
        for row in rows:
            thread = json.loads(row["raw_data"])
            threads.append(thread)

        conn.close()
        return threads

    def upsert_thread(self, thread_id: str, thread_data: Dict[str, Any], user_id: str):
        """Insert or update thread."""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO threads (
                id, subject, participants, date, body_preview, summary,
                open, expected_action, priority_score, user_id,
                created_at, updated_at, raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                subject = excluded.subject,
                participants = excluded.participants,
                date = excluded.date,
                body_preview = excluded.body_preview,
                summary = excluded.summary,
                open = excluded.open,
                expected_action = excluded.expected_action,
                priority_score = excluded.priority_score,
                updated_at = excluded.updated_at,
                raw_data = excluded.raw_data
        """, (
            thread_id,
            thread_data.get("subject", ""),
            ",".join(thread_data.get("participants", [])),
            thread_data.get("date", ""),
            thread_data.get("body_preview", ""),
            thread_data.get("summary", ""),
            thread_data.get("open", False),
            thread_data.get("expected_action"),
            thread_data.get("priority_score", 5),
            user_id,
            now,
            now,
            json.dumps(thread_data)
        ))

        # Update FTS index
        cursor.execute("""
            INSERT INTO threads_fts (thread_id, subject, body_preview, summary)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                subject = excluded.subject,
                body_preview = excluded.body_preview,
                summary = excluded.summary
        """, (
            thread_id,
            thread_data.get("subject", ""),
            thread_data.get("body_preview", ""),
            thread_data.get("summary", "")
        ))

        conn.commit()
        conn.close()


# Migration script (run once)
def migrate_json_to_sqlite(json_path: str, sqlite_store: SQLiteThreadStore, user_id: str):
    """Migrate existing threads.json to SQLite."""

    with open(json_path, 'r') as f:
        threads_data = json.load(f)

    for thread_id, thread_data in threads_data.get("threads", {}).items():
        sqlite_store.upsert_thread(thread_id, thread_data, user_id)

    print(f"Migrated {len(threads_data.get('threads', {}))} threads to SQLite")
```

### 9. Claude API Queue

**File:** `zylch/api/claude_queue.py`

```python
"""Request queue for Claude API with priority handling."""

import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid
from zylch.config import settings


class Priority(Enum):
    """Request priority levels."""
    HIGH = 1    # User interactions - immediate
    NORMAL = 2  # Regular tasks
    LOW = 3     # Background sync


@dataclass
class QueuedRequest:
    """Queued Claude API request."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    model: str = ""
    messages: list = field(default_factory=list)
    priority: Priority = Priority.NORMAL
    created_at: datetime = field(default_factory=datetime.now)
    result: Optional[Any] = None
    error: Optional[str] = None
    completed: bool = False


class ClaudeQueue:
    """
    Request queue with priority and rate limiting.

    Prevents API rate limit blocks and provides graceful degradation.
    """

    def __init__(self):
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.results: Dict[str, QueuedRequest] = {}
        self.processing = False
        self.rate_limit_per_minute = 50  # Anthropic tier 1
        self.last_request_time = None

    async def enqueue(
        self,
        model: str,
        messages: list,
        priority: Priority = Priority.NORMAL,
        **kwargs
    ) -> str:
        """
        Enqueue a Claude API request.

        Returns request_id for later retrieval.
        """

        request = QueuedRequest(
            model=model,
            messages=messages,
            priority=priority
        )

        # Store in results dict
        self.results[request.id] = request

        # Add to priority queue (lower priority value = higher priority)
        await self.queue.put((priority.value, request.id))

        # Start processing if not already
        if not self.processing:
            asyncio.create_task(self._process_queue())

        return request.id

    async def get_result(self, request_id: str, timeout: float = 30.0) -> Any:
        """
        Get result for a queued request (blocking until available).

        Raises TimeoutError if not completed within timeout.
        """

        start_time = datetime.now()

        while True:
            if request_id not in self.results:
                raise ValueError(f"Request {request_id} not found")

            request = self.results[request_id]

            if request.completed:
                if request.error:
                    raise Exception(request.error)
                return request.result

            # Check timeout
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                raise TimeoutError(f"Request {request_id} timed out after {timeout}s")

            # Wait a bit before checking again
            await asyncio.sleep(0.1)

    async def _process_queue(self):
        """Process queue with rate limiting."""

        self.processing = True

        try:
            while not self.queue.empty():
                # Rate limiting: ensure we don't exceed API limits
                await self._wait_for_rate_limit()

                # Get next request
                priority_value, request_id = await self.queue.get()
                request = self.results[request_id]

                try:
                    # Make API call
                    from anthropic import Anthropic
                    client = Anthropic(api_key=settings.anthropic_api_key)

                    response = client.messages.create(
                        model=request.model,
                        messages=request.messages
                    )

                    request.result = response
                    request.completed = True

                except Exception as e:
                    request.error = str(e)
                    request.completed = True

                self.last_request_time = datetime.now()

        finally:
            self.processing = False

    async def _wait_for_rate_limit(self):
        """Ensure we respect rate limits."""

        if self.last_request_time is None:
            return

        # Ensure at least (60 / rate_limit) seconds between requests
        min_interval = 60.0 / self.rate_limit_per_minute
        elapsed = (datetime.now() - self.last_request_time).total_seconds()

        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)


# Global queue instance
queue = ClaudeQueue() if settings.claude_queue_enabled else None
```

---

## Phase C: Cross-Channel Intelligence (Week 10-12)

### 10. Context Graph

**File:** `zylch/intelligence/context_graph.py`

```python
"""In-memory context graph connecting communication channels."""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class NodeType(Enum):
    """Types of nodes in context graph."""
    EMAIL_THREAD = "email_thread"
    PHONE_CALL = "phone_call"
    CALENDAR_EVENT = "calendar_event"
    CRM_DEAL = "crm_deal"
    CONTACT = "contact"


class EdgeType(Enum):
    """Types of relationships between nodes."""
    REFERENCES = "references"
    FOLLOWS_UP = "follows_up"
    SCHEDULED_FROM = "scheduled_from"
    RELATED_TO = "related_to"
    MENTIONS = "mentions"


@dataclass
class GraphNode:
    """Node in context graph."""
    id: str
    type: NodeType
    data: Dict[str, Any]
    created_at: datetime = datetime.now()


@dataclass
class GraphEdge:
    """Edge connecting nodes."""
    source_id: str
    target_id: str
    relation: EdgeType
    weight: float = 1.0
    created_at: datetime = datetime.now()


class ContextGraph:
    """
    In-memory graph connecting communication channels.

    Enables queries like "What's happening with Marco?"
    → Returns: emails + calls + meetings + deals
    """

    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self.contact_index: Dict[str, List[str]] = {}  # contact_id → [node_ids]

    def add_node(self, node_id: str, node_type: NodeType, data: Dict[str, Any]):
        """Add node to graph."""

        node = GraphNode(id=node_id, type=node_type, data=data)
        self.nodes[node_id] = node

        # Index by contact (if present in data)
        contact_id = data.get("contact_id") or data.get("contact_email")
        if contact_id:
            if contact_id not in self.contact_index:
                self.contact_index[contact_id] = []
            self.contact_index[contact_id].append(node_id)

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: EdgeType,
        weight: float = 1.0
    ):
        """Add edge between nodes."""

        edge = GraphEdge(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            weight=weight
        )
        self.edges.append(edge)

    def get_context(self, contact_identifier: str) -> Dict[str, Any]:
        """
        Get all context for a contact.

        Returns: {
            "emails": [...],
            "calls": [...],
            "meetings": [...],
            "deals": [...]
        }
        """

        # Get all nodes for this contact
        node_ids = self.contact_index.get(contact_identifier, [])

        context = {
            "emails": [],
            "calls": [],
            "meetings": [],
            "deals": []
        }

        for node_id in node_ids:
            node = self.nodes.get(node_id)
            if not node:
                continue

            if node.type == NodeType.EMAIL_THREAD:
                context["emails"].append(node.data)
            elif node.type == NodeType.PHONE_CALL:
                context["calls"].append(node.data)
            elif node.type == NodeType.CALENDAR_EVENT:
                context["meetings"].append(node.data)
            elif node.type == NodeType.CRM_DEAL:
                context["deals"].append(node.data)

        return context

    def build_from_recent(self, days_back: int = 7, user_id: str = "mario"):
        """
        Build graph from recent interactions.

        Queries threads.json, calendar events, MrCall logs, Pipedrive.
        """

        # This would integrate with existing data sources
        # For now, placeholder implementation
        pass

    def find_related(
        self,
        node_id: str,
        relation: Optional[EdgeType] = None,
        max_depth: int = 2
    ) -> List[GraphNode]:
        """Find related nodes (traverse edges)."""

        visited = set()
        related = []

        def traverse(current_id: str, depth: int):
            if depth > max_depth or current_id in visited:
                return

            visited.add(current_id)

            # Find edges from current node
            for edge in self.edges:
                if edge.source_id == current_id:
                    if relation is None or edge.relation == relation:
                        target_node = self.nodes.get(edge.target_id)
                        if target_node:
                            related.append(target_node)
                            traverse(edge.target_id, depth + 1)

        traverse(node_id, 0)
        return related
```

---

## Integration with Existing CLI

### Update CLI to Support Natural Language

**File:** `zylch/cli/main.py` (modifications)

```python
from zylch.skills.registry import registry
from zylch.skills.email_triage import EmailTriageSkill
from zylch.skills.draft_composer import DraftComposerSkill
from zylch.skills.cross_channel import CrossChannelOrchestratorSkill
from zylch.router.intent_classifier import IntentRouter
from zylch.memory.reasoning_bank import ReasoningBankMemory

class ZylchCLI:
    def __init__(self):
        # ... existing init ...

        # Initialize skill system (if enabled)
        self.skill_mode_enabled = True  # Feature flag
        if self.skill_mode_enabled:
            self._init_skills()

    def _init_skills(self):
        """Initialize skill-based architecture."""

        # Register skills
        registry.register_skill(EmailTriageSkill())
        registry.register_skill(DraftComposerSkill())
        registry.register_skill(CrossChannelOrchestratorSkill(registry))

        # Initialize router
        self.router = IntentRouter(registry)

        # Initialize memory (already exists, reuse)
        self.memory = ReasoningBankMemory(user_id="mario")

    async def process_input(self, user_input: str):
        """Process user input (command or natural language)."""

        # Check if it's a command (starts with /)
        if user_input.startswith("/"):
            return await self._process_command(user_input)

        # Natural language - use skill system
        if self.skill_mode_enabled:
            return await self._process_natural_language(user_input)
        else:
            print("❌ Natural language mode not enabled. Use commands like /help")

    async def _process_natural_language(self, user_input: str):
        """Process natural language input via skill router."""

        print(f"🤔 Processing: '{user_input}'...")

        # Classify intent
        routing = await self.router.classify_intent(user_input)

        print(f"🎯 Intent: {routing['primary_skill']} (confidence: {routing['confidence']:.0%})")

        # Get memory rules for context
        memory_rules = self.memory.get_relevant_memories(
            channel='email',  # Could be detected from intent
            min_confidence=0.5
        )

        # Build skill context
        from zylch.skills.base import SkillContext
        context = SkillContext(
            user_id="mario",
            intent=user_input,
            params=routing['params'],
            conversation_history=[],
            memory_rules=memory_rules,
            patterns=[]
        )

        # Execute context skills first (if any)
        accumulated_data = {}
        for skill_name in routing.get('context_skills', []):
            skill = registry.get_skill(skill_name)
            result = await skill.activate(context)
            accumulated_data.update(result.data)
            print(f"✅ {skill_name}: {result.message}")

        # Execute primary skill
        primary_skill = registry.get_skill(routing['primary_skill'])

        # Enrich context with accumulated data
        context.params.update(accumulated_data)

        result = await primary_skill.activate(context)

        if result.success:
            print(f"✅ {result.message}")
            return result.data
        else:
            print(f"❌ {result.message}")
            return None
```

---

## Quick Wins (Parallel Implementation)

### Prompt Caching (3 days)

**Update existing prompts to use caching:**

```python
# In DraftComposerSkill.execute() and other skills
response = self.client.messages.create(
    model=self.execution_model,
    max_tokens=2000,
    messages=[{
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": memory_section,  # Cached prefix
                "cache_control": {"type": "ephemeral"}
            },
            {
                "type": "text",
                "text": pattern_section,  # Cached prefix
                "cache_control": {"type": "ephemeral"}
            },
            {
                "type": "text",
                "text": task_prompt  # Variable suffix (not cached)
            }
        ]
    }]
)
```

**Result:** 50% cost savings on repeated prompts with same memory/patterns.

### Batch Processing (1 week)

```python
# In TaskManager when rebuilding all tasks
from anthropic import Anthropic

client = Anthropic(api_key=settings.anthropic_api_key)

# Create batch requests
requests = []
for contact_email, threads in contact_threads.items():
    requests.append({
        "custom_id": contact_email,
        "params": {
            "model": settings.skill_execution_model,
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": build_task_prompt(threads)}]
        }
    })

# Submit batch (50% cost reduction, 4.5x faster)
batch = client.messages.batches.create(requests=requests)

# Poll for results
while batch.processing_status != "ended":
    await asyncio.sleep(5)
    batch = client.messages.batches.retrieve(batch.id)

# Extract results
results = client.messages.batches.results(batch.id)
```

---

## Testing & Rollout Strategy

### A/B Testing

```python
# Feature flag in config
SKILL_MODE_ENABLED=true  # Enable for 50% of users

# In CLI
class ZylchCLI:
    def __init__(self):
        # Randomly assign users to skill mode (A/B test)
        import random
        self.skill_mode_enabled = (
            settings.skill_mode_enabled and
            random.random() < 0.5
        )
```

### Metrics to Track

```python
# Add telemetry to skills
class BaseSkill:
    async def activate(self, context: SkillContext) -> SkillResult:
        # ... existing code ...

        # Track metrics
        metrics.record({
            "skill": self.skill_name,
            "execution_time_ms": execution_time,
            "tokens_used": result.tokens_used,
            "success": result.success,
            "user_id": context.user_id,
            "model": self.execution_model
        })
```

**Key metrics:**
- Approval rate (draft composer)
- Time to action (triage → draft → send)
- User satisfaction (explicit feedback)
- Cost per interaction
- Skill usage distribution

### Rollout Phases

**Week 1-2:** Internal testing (team only)
**Week 3-4:** Alpha users (5-10 friendly customers)
**Week 5-6:** Beta (50% of users via A/B test)
**Week 7+:** General availability (100%)

---

## Success Criteria

### Product Metrics
- ✅ 80%+ approval rate on skill-generated drafts
- ✅ 30%+ reduction in time-to-action
- ✅ 90%+ natural language intent classification accuracy
- ✅ 50%+ cost reduction via caching + batching

### Technical Metrics
- ✅ <200ms intent classification latency
- ✅ <3s total skill execution time
- ✅ 100 concurrent users supported
- ✅ Zero API rate limit blocks

### Business Metrics
- ✅ User retention +20% (vs command-based)
- ✅ Feature adoption >60% within 2 weeks
- ✅ NPS increase by 15+ points

---

## Risk Mitigation

### Risk 1: Skill Over-Engineering
**Mitigation:** Start with 3 skills only. Add more only after proven adoption.

### Risk 2: Pattern Learning Doesn't Improve Outcomes
**Mitigation:** A/B test pattern-based vs non-pattern drafts. Kill feature if no improvement after 1K interactions.

### Risk 3: SQLite Scalability
**Mitigation:** SQLite handles 100K reads/sec. Sufficient for 100 users. PostgreSQL migration path exists if needed.

### Risk 4: Natural Language Misclassification
**Mitigation:** Allow users to switch to command mode. Log misclassifications for model fine-tuning.

---

## Timeline Summary

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| **Phase A** | 4 weeks | BaseSkill, Router, 3 core skills, Prompt caching |
| **Phase B** | 5 weeks | Pattern store, SQLite migration, API queue, Batch processing |
| **Phase C** | 3 weeks | Context graph, Additional skills, Cross-channel orchestration |
| **Testing** | 2 weeks | A/B testing, Metrics, Rollout |
| **Total** | **14 weeks** | Production-ready skill-based architecture |

---

## Conclusion

This implementation plan transforms Zylch from a command-based CLI to an intelligent, natural language skill-based system while:

✅ **Preserving existing code** - Skills wrap current functionality
✅ **Maintaining stability** - Incremental rollout with feature flags
✅ **Enabling scale** - SQLite + queue handles 100 users
✅ **Reducing costs** - Caching + batching = 50% savings
✅ **Creating moat** - Pattern learning + cross-channel intelligence

**All LLM model choices are configurable via .env** - no hard-coding, easy upgrades, enterprise-ready.

The architecture is ready to build. The decision is yours.

---

**Document End**

**Next Steps:**
1. Review and approve this plan
2. Set up development environment
3. Implement Phase A (Foundation + Core Skills)
4. Test with internal team
5. Iterate based on feedback
