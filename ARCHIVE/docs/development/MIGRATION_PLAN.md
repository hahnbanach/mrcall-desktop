# Zylch Avatar Architecture Migration Plan

**From:** task_manager.py (person-centric JSON caching)
**To:** Avatar-based architecture (ZylchMemory + Supabase pg_vector)
**Risk Level:** Medium (production system, gradual rollout possible)
**Estimated Timeline:** 3-4 weeks (development) + 2 weeks (testing/validation)

---

## Executive Summary

This migration moves Zylch from task_manager.py's JSON-cached person analysis to a proper avatar architecture where **every contact has a persistent, evolving representation** stored in ZylchMemory with semantic search capabilities.

### Key Changes

| Component | Before | After |
|-----------|--------|-------|
| **Storage** | `cache/tasks.json` (local filesystem) | Supabase `avatars` table + pg_vector |
| **Analysis** | Claude API per `/tasks` call | Avatar aggregation + memory reconsolidation |
| **Contact identity** | Email-based grouping | Multi-identifier avatars (email, phone, name) |
| **Update pattern** | Full rebuild on demand | Incremental updates on events |
| **Search** | O(n) JSON scan | O(log n) vector similarity |

### Why This Matters

1. **Eliminates redundant API calls**: Task analysis is expensive (Sonnet 1500 tokens/contact). Avatars cache intelligence.
2. **Enables cross-channel insights**: Email + WhatsApp + calls = unified contact understanding
3. **Supports relational memory**: "Luigi's communication style" persists across sessions
4. **Foundation for future features**: Response time prediction, relationship health scoring

---

## Phase 0: Pre-Migration (Schema + Data Preparation)

### 0.1 Database Schema Changes

**New Tables** (Supabase):

```sql
-- Avatars table (aggregated contact profiles)
CREATE TABLE avatars (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,  -- MD5 hash of primary identifier

    -- Identity
    display_name TEXT,
    primary_email TEXT,
    identifiers JSONB DEFAULT '[]'::jsonb,  -- [{type: "email", value: "luigi@x.com"}, ...]

    -- Communication profile
    preferred_channel TEXT,
    preferred_tone TEXT,
    preferred_language TEXT DEFAULT 'it',
    response_latency JSONB,  -- {median_hours, p90_hours, by_channel, ...}

    -- Behavioral aggregation
    aggregated_preferences JSONB,  -- {formality, pronoun, ...}

    -- Relationship metadata
    first_interaction TIMESTAMPTZ,
    last_interaction TIMESTAMPTZ,
    interaction_count INTEGER DEFAULT 0,
    relationship_strength REAL DEFAULT 0.5,

    -- Confidence
    profile_confidence REAL DEFAULT 0.5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, contact_id)
);

CREATE INDEX idx_avatars_owner ON avatars(owner_id);
CREATE INDEX idx_avatars_contact ON avatars(contact_id);
CREATE INDEX idx_avatars_email ON avatars(primary_email);
CREATE INDEX idx_avatars_updated ON avatars(updated_at);

-- Identifier map for O(1) lookups
CREATE TABLE contact_identifiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,  -- References avatars.contact_id
    identifier_type TEXT NOT NULL,  -- "email", "phone", "name"
    identifier_value TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, identifier_type, identifier_value)
);

CREATE INDEX idx_identifiers_owner ON contact_identifiers(owner_id);
CREATE INDEX idx_identifiers_contact ON contact_identifiers(contact_id);
CREATE INDEX idx_identifiers_value ON contact_identifiers(identifier_value);
```

**Modified Tables**:

```sql
-- Add avatar_id to existing thread_analysis table
ALTER TABLE thread_analysis ADD COLUMN avatar_id UUID REFERENCES avatars(id);
CREATE INDEX idx_thread_analysis_avatar ON thread_analysis(avatar_id);

-- Add avatar_id to relationship_gaps table
ALTER TABLE relationship_gaps ADD COLUMN avatar_id UUID REFERENCES avatars(id);
CREATE INDEX idx_gaps_avatar ON relationship_gaps(avatar_id);
```

### 0.2 Data Backfill Strategy

**Goal**: Convert existing task_manager.py JSON cache into avatars WITHOUT N API calls.

**Challenge**: task_manager.py already did the expensive Sonnet analysis. We need to preserve that work.

**Solution**: Multi-source backfill pipeline

```python
# tools/avatar_backfill.py

class AvatarBackfillService:
    """One-time migration service to build initial avatars"""

    async def backfill_avatars_from_existing_data(self, owner_id: str):
        """Strategy: Aggregate from existing sources, avoid new API calls"""

        # Source 1: task_manager.py JSON cache (if exists)
        tasks_cache = self._load_legacy_tasks_cache()

        # Source 2: Supabase thread_analysis table (30-day window)
        thread_analyses = await self._get_thread_analyses(owner_id)

        # Source 3: Supabase emails table (contact extraction)
        contact_threads = await self._group_threads_by_contact(owner_id)

        # Build avatars
        avatars_created = 0
        for contact_email, data in self._merge_sources(
            tasks_cache, thread_analyses, contact_threads
        ):
            avatar = await self._create_avatar_from_legacy_data(
                owner_id=owner_id,
                contact_email=contact_email,
                legacy_task=data.get('task'),
                thread_summaries=data.get('threads'),
                email_metadata=data.get('emails')
            )
            avatars_created += 1

        return {
            'avatars_created': avatars_created,
            'source': 'backfill',
            'date': datetime.utcnow()
        }

    def _create_avatar_from_legacy_data(
        self,
        owner_id: str,
        contact_email: str,
        legacy_task: Optional[Dict],
        thread_summaries: List[Dict],
        email_metadata: List[Dict]
    ) -> Avatar:
        """Build avatar WITHOUT new Claude API calls"""

        # Generate stable contact_id
        contact_id = self._generate_contact_id(contact_email)

        # Extract communication profile from thread patterns
        profile = self._infer_communication_profile(thread_summaries)

        # Calculate response latency from email timestamps
        latency = self._compute_response_latency(email_metadata)

        # Aggregate preferences from legacy task (if available)
        preferences = {}
        if legacy_task and legacy_task.get('view'):
            # Legacy task contains narrative summary
            # Store as initial pattern in ZylchMemory
            self.memory.store_memory(
                namespace=f"{owner_id}:contact:{contact_id}",
                category="person",
                context=f"Email relationship with {contact_email}",
                pattern=legacy_task['view'],  # Italian narrative
                confidence=0.7
            )

            # Infer preferences from narrative
            preferences = self._extract_preferences_from_narrative(
                legacy_task['view']
            )

        # Build avatar
        avatar = {
            'owner_id': owner_id,
            'contact_id': contact_id,
            'display_name': legacy_task.get('contact_name') if legacy_task else contact_email,
            'primary_email': contact_email,
            'identifiers': self._collect_identifiers(contact_email, legacy_task),
            'preferred_channel': 'email',  # Default for backfill
            'preferred_tone': preferences.get('tone', 'professional'),
            'preferred_language': 'it',
            'response_latency': latency,
            'aggregated_preferences': preferences,
            'first_interaction': self._get_first_interaction(email_metadata),
            'last_interaction': self._get_last_interaction(email_metadata),
            'interaction_count': len(email_metadata),
            'relationship_strength': self._compute_relationship_strength(email_metadata),
            'profile_confidence': 0.6  # Lower than fresh analysis
        }

        # Store in Supabase
        supabase.table('avatars').insert(avatar).execute()

        # Store identifiers
        for identifier in avatar['identifiers']:
            supabase.table('contact_identifiers').insert({
                'owner_id': owner_id,
                'contact_id': contact_id,
                'identifier_type': identifier['type'],
                'identifier_value': identifier['value'],
                'is_primary': identifier.get('is_primary', False)
            }).execute()

        return avatar

    def _compute_response_latency(self, emails: List[Dict]) -> Dict:
        """Calculate response patterns from email thread history"""

        response_times = []
        for i in range(1, len(emails)):
            prev = emails[i-1]
            curr = emails[i]

            # Only count their responses to our emails
            if self._is_my_email(prev['from_email']) and not self._is_my_email(curr['from_email']):
                delta_hours = (curr['date_timestamp'] - prev['date_timestamp']) / 3600
                response_times.append(delta_hours)

        if not response_times:
            return None

        import numpy as np
        return {
            'median_hours': float(np.median(response_times)),
            'p90_hours': float(np.percentile(response_times, 90)),
            'sample_size': len(response_times),
            'by_channel': {'email': float(np.median(response_times))}
        }
```

**Backfill Execution Plan**:

```bash
# Step 1: Run backfill for one test user
python -m zylch.tools.avatar_backfill --owner-id test_user --dry-run

# Step 2: Validate avatar quality
python -m zylch.tools.avatar_backfill --owner-id test_user --validate

# Step 3: Backfill all users (production)
python -m zylch.tools.avatar_backfill --all-users --batch-size 10
```

**Priority Strategy**:

```python
def prioritize_backfill(owner_id: str) -> List[str]:
    """Which contacts to backfill first?"""

    # Priority 1: Active contacts (last 7 days)
    active = get_contacts_with_recent_activity(owner_id, days=7)

    # Priority 2: High-value relationships (>10 email exchanges)
    high_value = get_contacts_by_interaction_count(owner_id, min_count=10)

    # Priority 3: Open tasks (from legacy task_manager)
    open_tasks = get_contacts_with_open_tasks(owner_id)

    # Priority 4: Everything else
    all_contacts = get_all_contacts(owner_id)

    return deduplicate([*active, *high_value, *open_tasks, *all_contacts])
```

### 0.3 Migration Validation Criteria

Before proceeding to Phase 1, verify:

- [ ] All tables created successfully
- [ ] Indexes created and performant (query plan analysis)
- [ ] Backfill script tested on 3+ test users
- [ ] Avatar quality spot-check: 10 random avatars match legacy task data
- [ ] No data loss: `COUNT(avatars) >= COUNT(distinct contact_email from tasks.json)`
- [ ] ZylchMemory integration tested: store/retrieve person patterns

---

## Phase 1: Parallel Run (Dual System)

**Goal**: Run old and new systems side-by-side. Feature flag controls which is active.

### 1.1 Feature Flag Implementation

```python
# config.py
class Settings(BaseSettings):
    # Migration control
    AVATAR_MIGRATION_ENABLED: bool = False  # Default: keep old system
    AVATAR_MIGRATION_USERS: str = ""  # Comma-separated owner_ids for early access

    def is_avatar_enabled(self, owner_id: str) -> bool:
        """Check if user should use avatar system"""
        if self.AVATAR_MIGRATION_ENABLED:
            return True
        return owner_id in self.AVATAR_MIGRATION_USERS.split(',')
```

### 1.2 Service Layer Abstraction

Create a unified interface that works with both systems:

```python
# services/contact_intelligence_service.py

class ContactIntelligenceService:
    """Facade for contact intelligence - works with both old and new systems"""

    def __init__(self, owner_id: str, settings: Settings):
        self.owner_id = owner_id
        self.use_avatars = settings.is_avatar_enabled(owner_id)

        # Old system
        self.task_manager = TaskManager(...) if not self.use_avatars else None

        # New system
        self.avatar_engine = AvatarEngine(...) if self.use_avatars else None

    async def get_contact_intelligence(
        self,
        contact_email: str
    ) -> ContactIntelligence:
        """Unified API - delegates to old or new system"""

        if self.use_avatars:
            return await self._get_from_avatar(contact_email)
        else:
            return await self._get_from_task_manager(contact_email)

    async def _get_from_avatar(self, contact_email: str) -> ContactIntelligence:
        """New system: Avatar-based"""
        contact_id = generate_contact_id(email=contact_email)
        avatar = await self.avatar_engine.get_avatar(self.owner_id, contact_id)

        if not avatar:
            # Avatar doesn't exist yet - trigger creation
            avatar = await self.avatar_engine.create_avatar_from_threads(
                owner_id=self.owner_id,
                contact_email=contact_email
            )

        # Convert avatar to ContactIntelligence format
        return ContactIntelligence(
            contact_id=avatar.contact_id,
            contact_name=avatar.display_name,
            contact_email=contact_email,
            view=self._get_avatar_narrative(avatar),
            status=self._infer_status(avatar),
            score=self._compute_priority_score(avatar),
            action=self._get_recommended_action(avatar),
            preferred_tone=avatar.preferred_tone,
            response_latency=avatar.response_latency
        )

    async def _get_from_task_manager(self, contact_email: str) -> ContactIntelligence:
        """Old system: task_manager.py"""
        task = self.task_manager.get_task_by_contact_email(contact_email)

        if not task:
            return None

        # Convert task to ContactIntelligence format
        return ContactIntelligence(
            contact_id=task['task_id'],
            contact_name=task['contact_name'],
            contact_email=contact_email,
            view=task['view'],
            status=task['status'],
            score=task['score'],
            action=task['action'],
            preferred_tone=None,  # Not available in old system
            response_latency=None  # Not available in old system
        )

    def _get_avatar_narrative(self, avatar: Avatar) -> str:
        """Generate Italian narrative from avatar (like old task view)"""

        # Retrieve stored narratives from ZylchMemory
        memories = self.memory.retrieve_memories(
            namespace=f"{avatar.owner_id}:contact:{avatar.contact_id}",
            category="person",
            limit=5
        )

        if memories:
            # Use most recent/confident narrative
            return max(memories, key=lambda m: m['confidence'])['pattern']

        # Fallback: generate from avatar data
        return self._generate_narrative_from_avatar(avatar)
```

### 1.3 API Route Updates

Update all `/tasks` endpoints to use the facade:

```python
# api/routes/tasks.py

@router.get("/tasks")
async def list_tasks(
    owner_id: str = Depends(get_owner_id),
    status: Optional[str] = None,
    min_score: Optional[int] = None
):
    """List tasks (works with both old and new systems)"""

    service = ContactIntelligenceService(owner_id, settings)

    # Get all contacts
    contacts = await service.get_all_contacts()

    # Apply filters
    if status:
        contacts = [c for c in contacts if c.status == status]
    if min_score:
        contacts = [c for c in contacts if c.score >= min_score]

    return {
        'tasks': contacts,
        'source': 'avatars' if service.use_avatars else 'task_manager',
        'total': len(contacts)
    }
```

### 1.4 Testing Strategy

**A/B Comparison**:

```python
# tests/test_migration_parity.py

async def test_avatar_task_manager_parity():
    """Ensure both systems return similar results"""

    owner_id = "test_user"
    contact_email = "luigi@example.com"

    # Old system
    task_manager = TaskManager(...)
    old_result = task_manager.get_task_by_contact_email(contact_email)

    # New system
    avatar_engine = AvatarEngine(...)
    contact_id = generate_contact_id(email=contact_email)
    avatar = await avatar_engine.get_avatar(owner_id, contact_id)

    # Compare
    assert old_result['contact_name'] == avatar.display_name
    assert old_result['status'] in ['open', 'waiting', 'closed']
    # Avatar system should have richer data
    assert avatar.response_latency is not None
    assert avatar.preferred_tone is not None
```

**Metrics to Track**:

| Metric | Old System | New System | Goal |
|--------|-----------|------------|------|
| Response time (ms) | ~2000 | <500 | 4x improvement |
| API calls per `/tasks` | N contacts | 0 (cached) | Zero API cost |
| Data completeness | 60% | 90% | Richer profiles |
| Error rate | <1% | <1% | No regression |

### 1.5 Rollout Plan

**Week 1**: Internal testing
- Enable for 1-2 internal users
- Monitor logs, performance
- Fix bugs

**Week 2**: Early access
- Enable for 10 beta users
- Collect feedback
- Validate parity

**Week 3**: Gradual rollout
- 25% of users
- 50% of users
- Monitor metrics

**Week 4**: Full rollout
- 100% of users
- `AVATAR_MIGRATION_ENABLED=true`

---

## Phase 2: Cutover Strategy

### 2.1 Cutover Checklist

Before fully deprecating task_manager.py:

- [ ] Avatar system in production for >2 weeks
- [ ] Zero critical bugs reported
- [ ] Performance metrics meet goals (response time, accuracy)
- [ ] 100% of active users have avatars backfilled
- [ ] Backup of legacy tasks.json files created
- [ ] Rollback plan tested

### 2.2 Event-Driven Avatar Updates

Replace task_manager.py's "rebuild on demand" with incremental updates:

```python
# services/avatar_event_processor.py

class AvatarEventProcessor:
    """Process events to keep avatars up-to-date"""

    async def on_email_received(self, owner_id: str, email: Dict):
        """Update avatar when new email arrives"""

        contact_email = self._extract_contact_email(email)
        contact_id = generate_contact_id(email=contact_email)

        # Update interaction metadata
        await self._update_interaction_timestamp(owner_id, contact_id)

        # Check if email contains new behavioral signals
        if self._has_behavioral_signals(email):
            await self._update_avatar_from_email(owner_id, contact_id, email)

    async def on_email_sent(self, owner_id: str, email: Dict):
        """Update avatar when user sends email"""

        contact_email = self._extract_recipient_email(email)
        contact_id = generate_contact_id(email=contact_email)

        # Update interaction count
        await self._increment_interaction_count(owner_id, contact_id)

        # If we used avatar preferences to draft, boost confidence
        if email.get('used_avatar_preferences'):
            await self._boost_avatar_confidence(owner_id, contact_id)

    async def on_user_corrects_draft(self, owner_id: str, contact_id: str, corrections: Dict):
        """Learn from user corrections"""

        # User changed tone from "casual" to "formal"
        if 'tone' in corrections:
            await self.avatar_engine.update_preference(
                owner_id,
                contact_id,
                'preferred_tone',
                corrections['tone']
            )

        # User changed language
        if 'language' in corrections:
            await self.avatar_engine.update_preference(
                owner_id,
                contact_id,
                'preferred_language',
                corrections['language']
            )
```

**Integration Points**:

```python
# tools/gmail.py - SendDraftTool

async def execute(self, draft_id: str, **kwargs):
    # Send email
    result = await gmail_client.send_draft(draft_id)

    # NEW: Trigger avatar update
    await avatar_event_processor.on_email_sent(
        owner_id=self.owner_id,
        email=result
    )

    return result
```

### 2.3 Deprecation Timeline

**Day 0 (Cutover)**:
- Set `AVATAR_MIGRATION_ENABLED=true` globally
- task_manager.py disabled by default

**Week 1**:
- Monitor for issues
- Keep task_manager.py code but unused

**Week 2**:
- Archive legacy tasks.json files
- Remove task_manager.py imports from production code

**Month 1**:
- Delete task_manager.py and related tools
- Update documentation

---

## Phase 3: Cleanup and Optimization

### 3.1 Code Cleanup

**Files to Delete**:
```
zylch/tools/task_manager.py
cache/tasks.json (archived)
```

**Files to Update**:
```python
# zylch/tools/factory.py
- Remove task_manager imports
- Remove _BuildTasksTool, _GetContactTaskTool, etc.
+ Add _GetAvatarTool, _UpdateAvatarTool
```

### 3.2 Performance Optimization

**Avatar Cache Strategy**:

```python
# Cache hot avatars in Redis for <100ms response
class AvatarCache:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.ttl = 3600  # 1 hour

    async def get_avatar(self, owner_id: str, contact_id: str) -> Optional[Avatar]:
        key = f"avatar:{owner_id}:{contact_id}"
        cached = await self.redis.get(key)

        if cached:
            return Avatar.from_json(cached)

        # Cache miss - load from Supabase
        avatar = await supabase.get_avatar(owner_id, contact_id)

        if avatar:
            await self.redis.setex(key, self.ttl, avatar.to_json())

        return avatar
```

**Batch Avatar Retrieval**:

```python
async def get_avatars_batch(owner_id: str, contact_ids: List[str]) -> List[Avatar]:
    """Retrieve multiple avatars in one query"""

    result = await supabase.table('avatars')\
        .select('*')\
        .eq('owner_id', owner_id)\
        .in_('contact_id', contact_ids)\
        .execute()

    return [Avatar.from_dict(row) for row in result.data]
```

### 3.3 Monitoring and Alerts

**Metrics to Track**:

```python
# Prometheus metrics
avatar_retrieval_latency_seconds = Histogram('avatar_retrieval_latency_seconds')
avatar_cache_hit_rate = Gauge('avatar_cache_hit_rate')
avatar_update_events_total = Counter('avatar_update_events_total', ['event_type'])
avatar_creation_errors_total = Counter('avatar_creation_errors_total')
```

**Alerts**:
- Avatar retrieval latency >500ms (95th percentile)
- Cache hit rate <80%
- Avatar creation errors >5% of attempts
- Missing avatar for active contact

---

## Risk Assessment and Mitigation

### Risk 1: Data Loss During Backfill

**Impact**: High
**Probability**: Low
**Mitigation**:
- Dry-run mode in backfill script
- Archive tasks.json before migration
- Validation checks: avatar count >= task count
- Rollback script: regenerate tasks.json from avatars

**Rollback Plan**:
```bash
# Restore from backup
cp cache/tasks.json.backup cache/tasks.json

# Disable avatar system
export AVATAR_MIGRATION_ENABLED=false

# Restart services
systemctl restart zylch-api
```

### Risk 2: Performance Regression

**Impact**: Medium
**Probability**: Medium (first few weeks)
**Mitigation**:
- Redis caching for hot avatars
- Connection pooling for Supabase
- Load testing before rollout
- Gradual rollout (10% → 50% → 100%)

**Monitoring**:
```python
# Alert if p95 latency > 500ms
if avatar_retrieval_latency_seconds.p95 > 0.5:
    alert("Avatar system slow - check Supabase connection pool")
```

### Risk 3: Avatar Quality Lower Than Task Analysis

**Impact**: High (user trust)
**Probability**: Medium (backfill avatars less accurate)
**Mitigation**:
- Clearly mark backfilled avatars (`backfill_source: true`)
- Lower initial confidence (0.6 vs 0.8)
- Trigger re-analysis for high-value contacts
- User feedback loop: "Is this information correct?"

**Quality Assurance**:
```python
async def validate_avatar_quality(avatar: Avatar):
    """Quality checks before surfacing to user"""

    checks = []

    # Check 1: Has minimum data
    checks.append(avatar.display_name is not None)
    checks.append(len(avatar.identifiers) > 0)

    # Check 2: Confidence above threshold
    checks.append(avatar.profile_confidence >= 0.5)

    # Check 3: Recent data (not stale)
    days_since_update = (datetime.utcnow() - avatar.updated_at).days
    checks.append(days_since_update < 30)

    if not all(checks):
        # Trigger refresh
        await avatar_engine.refresh_avatar(avatar.owner_id, avatar.contact_id)
```

### Risk 4: Breaking Changes to /tasks API

**Impact**: High (frontend depends on it)
**Probability**: Low (facade pattern maintains interface)
**Mitigation**:
- Keep `/tasks` API signature identical
- Return same JSON structure
- Add optional new fields (backward compatible)
- Version API if breaking changes needed (`/v2/tasks`)

**API Contract Test**:
```python
def test_tasks_api_backward_compatibility():
    """Ensure /tasks returns same structure as before"""

    response = client.get("/api/tasks")

    # Old fields must exist
    assert 'tasks' in response.json()
    assert 'task_id' in response.json()['tasks'][0]
    assert 'contact_name' in response.json()['tasks'][0]
    assert 'view' in response.json()['tasks'][0]
    assert 'status' in response.json()['tasks'][0]
    assert 'score' in response.json()['tasks'][0]

    # New fields optional
    if 'preferred_tone' in response.json()['tasks'][0]:
        assert isinstance(response.json()['tasks'][0]['preferred_tone'], str)
```

### Risk 5: Increased Supabase Costs

**Impact**: Low (budget)
**Probability**: Medium
**Mitigation**:
- Monitor query patterns
- Optimize indexes
- Use connection pooling
- Cache frequently accessed avatars
- Set Supabase budget alerts

**Cost Monitoring**:
```python
# Track Supabase API calls
supabase_queries_total = Counter('supabase_queries_total', ['table', 'operation'])

async def get_avatar(owner_id, contact_id):
    supabase_queries_total.labels(table='avatars', operation='select').inc()
    # ...
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_avatar_engine.py

async def test_create_avatar_from_threads():
    """Test avatar creation from email threads"""

    owner_id = "test_user"
    contact_email = "luigi@example.com"

    # Setup: Create mock email threads
    threads = [
        create_mock_thread(from_email=contact_email, subject="Re: Progetto X"),
        create_mock_thread(from_email=contact_email, subject="Fattura novembre")
    ]

    # Execute
    avatar = await avatar_engine.create_avatar_from_threads(
        owner_id=owner_id,
        contact_email=contact_email,
        threads=threads
    )

    # Assert
    assert avatar.contact_id == generate_contact_id(email=contact_email)
    assert avatar.display_name == "Luigi"
    assert avatar.primary_email == contact_email
    assert avatar.interaction_count == 2
    assert avatar.profile_confidence > 0.5

async def test_avatar_update_incremental():
    """Test incremental avatar update on new email"""

    # Create initial avatar
    avatar = await create_test_avatar(interaction_count=5)

    # Process new email event
    await avatar_event_processor.on_email_received(
        owner_id=avatar.owner_id,
        email=create_mock_email(from_email=avatar.primary_email)
    )

    # Reload avatar
    updated = await avatar_engine.get_avatar(avatar.owner_id, avatar.contact_id)

    # Assert interaction count incremented
    assert updated.interaction_count == 6
    assert updated.last_interaction > avatar.last_interaction
```

### Integration Tests

```python
# tests/test_migration_integration.py

async def test_parallel_run_consistency():
    """Test that both systems return consistent results during parallel run"""

    owner_id = "test_user"

    # Enable avatar system for this user
    settings.AVATAR_MIGRATION_USERS = owner_id

    # Get results from old system
    old_service = ContactIntelligenceService(owner_id, use_avatars=False)
    old_tasks = await old_service.get_all_contacts()

    # Get results from new system
    new_service = ContactIntelligenceService(owner_id, use_avatars=True)
    new_tasks = await new_service.get_all_contacts()

    # Compare
    assert len(old_tasks) == len(new_tasks)

    for old, new in zip(old_tasks, new_tasks):
        assert old.contact_email == new.contact_email
        assert old.status == new.status
        # New system should have richer data
        assert new.preferred_tone is not None
```

### Load Tests

```python
# tests/test_avatar_performance.py

async def test_avatar_retrieval_performance():
    """Ensure avatar retrieval meets SLA (<500ms)"""

    owner_id = "test_user"
    contact_id = "test_contact"

    # Warm up cache
    await avatar_cache.get_avatar(owner_id, contact_id)

    # Benchmark
    times = []
    for _ in range(100):
        start = time.time()
        await avatar_cache.get_avatar(owner_id, contact_id)
        times.append(time.time() - start)

    # Assert p95 < 500ms
    p95 = np.percentile(times, 95)
    assert p95 < 0.5, f"P95 latency {p95*1000}ms exceeds 500ms SLA"
```

---

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| **Phase 0: Pre-Migration** | 1.5 weeks | - |
| 0.1 Database schema | 2 days | Supabase access |
| 0.2 Backfill script | 5 days | Schema complete |
| 0.3 Validation | 2 days | Backfill complete |
| **Phase 1: Parallel Run** | 2 weeks | Phase 0 complete |
| 1.1 Feature flags | 1 day | - |
| 1.2 Service abstraction | 3 days | - |
| 1.3 API updates | 2 days | Service layer ready |
| 1.4 Testing | 3 days | - |
| 1.5 Gradual rollout | 5 days | Tests passing |
| **Phase 2: Cutover** | 1 week | Phase 1 stable |
| 2.1 Cutover execution | 1 day | >2 weeks in production |
| 2.2 Event-driven updates | 3 days | - |
| 2.3 Deprecation | 3 days | Cutover stable |
| **Phase 3: Cleanup** | 1 week | Phase 2 complete |
| 3.1 Code cleanup | 2 days | - |
| 3.2 Optimization | 3 days | - |
| 3.3 Monitoring | 2 days | - |
| **Total** | **5.5 weeks** | + 2 weeks buffer |

**Critical Path**:
Schema → Backfill → Service Abstraction → Testing → Rollout → Cutover

---

## Success Criteria

### Technical Metrics

- [ ] Avatar retrieval latency p95 < 500ms
- [ ] Cache hit rate > 80%
- [ ] Zero data loss (all contacts migrated)
- [ ] API backward compatibility (existing integrations work)
- [ ] Error rate < 1%

### Business Metrics

- [ ] No user complaints about missing data
- [ ] Reduced Claude API costs (fewer Sonnet calls)
- [ ] Richer contact intelligence (response latency, preferences)
- [ ] Foundation for future features (relationship scoring)

### Migration Metrics

- [ ] 100% of active users migrated
- [ ] Backfill success rate > 99%
- [ ] Rollback tested and working
- [ ] Documentation updated

---

## Appendix: Command Reference

### Backfill Commands

```bash
# Dry run (no DB writes)
python -m zylch.tools.avatar_backfill \
  --owner-id abc123 \
  --dry-run \
  --verbose

# Backfill single user
python -m zylch.tools.avatar_backfill \
  --owner-id abc123

# Backfill all users (batch)
python -m zylch.tools.avatar_backfill \
  --all-users \
  --batch-size 10 \
  --priority active  # active, high-value, all

# Validate backfill quality
python -m zylch.tools.avatar_backfill \
  --owner-id abc123 \
  --validate
```

### Feature Flag Commands

```bash
# Enable for specific user
export AVATAR_MIGRATION_USERS="user1,user2,user3"

# Enable globally
export AVATAR_MIGRATION_ENABLED=true

# Rollback
export AVATAR_MIGRATION_ENABLED=false
```

### Monitoring Commands

```bash
# Check avatar count
psql -c "SELECT owner_id, COUNT(*) FROM avatars GROUP BY owner_id;"

# Check cache performance
redis-cli INFO stats | grep keyspace_hits

# Check API latency
curl https://api.zylchai.com/metrics | grep avatar_retrieval_latency
```

---

**End of Migration Plan**

*Next Steps*: Review with team → Get approval → Begin Phase 0 implementation*
