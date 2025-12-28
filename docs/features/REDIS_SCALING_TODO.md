# Redis Caching & Scaling - Future Development

## Status
🟢 **LOW PRIORITY** - Phase J (Scaling)

## Business Impact

**When Needed**:
- **User Growth**: 1,000+ concurrent users
- **Performance Issues**: API response times >500ms
- **Database Load**: Supabase queries become bottleneck
- **Cost Optimization**: Reduce database read operations

**Why Important**:
- **Faster responses**: Cache frequently accessed data
- **Lower costs**: Fewer database queries = lower Supabase costs
- **Better UX**: Sub-100ms API response times
- **Scalability**: Handle 10,000+ users without performance degradation

**Use Cases**:
- Cache email threads for instant task building
- Cache relationship gaps for fast `/gaps` command
- Cache tasks for quick lookups
- Session storage for multi-request workflows
- Rate limiting per user

## Current State

### What Works Well
- ✅ **Supabase performance**: Currently fast enough (<500ms responses)
- ✅ **Local file cache**: `cache/` directory for development
- ✅ **Reasonable load**: <100 users, no scaling issues
- ✅ **Simple architecture**: Direct Supabase queries, easy to maintain

### What's Missing
- ❌ **Redis caching**: No distributed cache layer
- ❌ **Rate limiting**: No per-user API rate limits
- ❌ **Session management**: JWT-only, no session cache
- ❌ **Webhook retry**: No retry queue for failed webhooks
- ❌ **Background jobs**: No task queue (Celery/Bull)

### Current Performance (Low Load)
```
API Response Times (P95):
- GET /api/gaps: 300-500ms
- POST /api/chat/message: 1-2s (LLM call)
- GET /api/tasks: 200-400ms
- POST /api/sync/full: 10-30s (Gmail API)

Database Queries:
- ~50 queries/minute (very low)
- No caching needed yet
```

### Target Performance (High Load)
```
API Response Times (P95):
- GET /api/gaps: <100ms (cached)
- POST /api/chat/message: <1s
- GET /api/tasks: <100ms (cached)
- POST /api/sync/full: 5-10s (optimized)

Database Queries:
- Cache hit rate: >80%
- Reduced database load by 5x
```

## Planned Features

### 1. Upstash Redis Integration

**Why Upstash**:
- **Serverless**: No server management
- **Global**: Low latency worldwide
- **Generous free tier**: 10,000 requests/day free
- **Redis-compatible**: Standard Redis commands

**Setup**:
```bash
# Install Upstash Redis client
pip install upstash-redis>=0.15.0
```

**Configuration**:
```python
from upstash_redis import Redis

redis = Redis(
    url=os.getenv('UPSTASH_REDIS_REST_URL'),
    token=os.getenv('UPSTASH_REDIS_REST_TOKEN')
)

# Test connection
await redis.ping()  # Returns PONG
```

### 2. Cache Strategy

**What to Cache**:
```python
# 1. Relationship Gaps (5 minute TTL)
cache_key = f"gaps:{user_id}:{days_back}"
cached_gaps = await redis.get(cache_key)

if cached_gaps:
    return json.loads(cached_gaps)
else:
    gaps = await gap_service.analyze_gaps(days_back)
    await redis.setex(cache_key, 300, json.dumps(gaps))  # 5 min TTL
    return gaps


# 2. Tasks (10 minute TTL)
cache_key = f"tasks:{user_id}"
cached_tasks = await redis.get(cache_key)

if cached_tasks:
    return json.loads(cached_tasks)
else:
    tasks = await task_manager.list_tasks_fast()
    await redis.setex(cache_key, 600, json.dumps(tasks))  # 10 min TTL
    return tasks


# 3. Contact Memory (1 hour TTL)
cache_key = f"contact_memory:{contact_email}"
cached_memory = await redis.get(cache_key)

if cached_memory:
    return json.loads(cached_memory)
else:
    memory = await blob_service.get_contact_blobs(contact_email)
    await redis.setex(cache_key, 3600, json.dumps(memory))  # 1 hour TTL
    return memory
```

**Cache Invalidation**:
```python
# Invalidate when data changes
async def invalidate_user_caches(user_id: str):
    """Clear all caches for a user after sync or manual changes"""

    await redis.delete(
        f"gaps:{user_id}:7",
        f"gaps:{user_id}:30",
        f"tasks:{user_id}",
        f"chat_history:{user_id}"
    )
```

### 3. Rate Limiting

**Per-User API Rate Limits**:
```python
from fastapi import Request, HTTPException

async def rate_limit_check(request: Request, user_id: str):
    """Check if user has exceeded rate limit"""

    # Sliding window rate limit
    window_key = f"ratelimit:{user_id}:{int(time.time() / 60)}"  # Per minute

    # Increment request count
    count = await redis.incr(window_key)

    # Set expiration on first request
    if count == 1:
        await redis.expire(window_key, 60)  # 1 minute window

    # Check limit
    RATE_LIMIT = 60  # 60 requests per minute
    if count > RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return count


# Middleware to apply rate limiting
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    user_id = request.state.user.get('id')

    if user_id:
        await rate_limit_check(request, user_id)

    return await call_next(request)
```

**Tier-Based Rate Limits**:
```python
RATE_LIMITS = {
    'free': 60,      # 60 requests/min
    'pro': 300,      # 300 requests/min
    'team': 1000     # 1000 requests/min
}

tier = request.state.user.get('subscription_tier', 'free')
limit = RATE_LIMITS[tier]

if count > limit:
    raise HTTPException(status_code=429)
```

### 4. Session Management

**Cache Chat Sessions**:
```python
# Store conversation history in Redis (not Supabase)
async def save_chat_session(session_id: str, messages: list):
    """Save chat history to Redis"""

    session_key = f"chat_session:{session_id}"

    await redis.setex(
        session_key,
        3600,  # 1 hour TTL
        json.dumps(messages)
    )


async def get_chat_session(session_id: str) -> list:
    """Retrieve chat history from Redis"""

    session_key = f"chat_session:{session_id}"
    cached = await redis.get(session_key)

    return json.loads(cached) if cached else []
```

**User Session State**:
```python
# Store temporary user state (current task, active filters, etc.)
async def save_user_state(user_id: str, state: dict):
    """Save user's UI state for continuity"""

    state_key = f"user_state:{user_id}"

    await redis.setex(
        state_key,
        86400,  # 24 hours
        json.dumps(state)
    )
```

### 5. Webhook Retry Queue

**Failed Webhook Retry**:
```python
import asyncio

# Store failed webhooks for retry
async def queue_webhook_retry(webhook_url: str, payload: dict, attempt: int = 1):
    """Queue webhook for retry with exponential backoff"""

    retry_key = f"webhook_retry:{webhook_url}:{attempt}"

    await redis.setex(
        retry_key,
        60 * (2 ** attempt),  # Exponential backoff: 2min, 4min, 8min
        json.dumps({'url': webhook_url, 'payload': payload, 'attempt': attempt})
    )


# Background worker to process retries
async def process_webhook_retries():
    """Process queued webhook retries"""

    while True:
        # Scan for retry keys
        retry_keys = await redis.scan(match='webhook_retry:*')

        for key in retry_keys:
            retry_data = json.loads(await redis.get(key))

            try:
                # Retry webhook
                response = await httpx.post(
                    retry_data['url'],
                    json=retry_data['payload'],
                    timeout=10
                )

                if response.status_code == 200:
                    # Success - remove from queue
                    await redis.delete(key)
                else:
                    # Failed - requeue with higher attempt
                    if retry_data['attempt'] < 5:  # Max 5 retries
                        await queue_webhook_retry(
                            retry_data['url'],
                            retry_data['payload'],
                            retry_data['attempt'] + 1
                        )
                    await redis.delete(key)

            except Exception as e:
                print(f"Webhook retry failed: {e}")

        await asyncio.sleep(60)  # Check every minute
```

### 6. Background Job Queue

**Task Queue with Bull (Node.js) or Celery (Python)**:
```python
# Use Redis as task queue backend

# Celery configuration
from celery import Celery

app = Celery('zylch', broker='redis://localhost:6379/0')

# Define background tasks
@app.task
def send_email_async(user_id: str, email_data: dict):
    """Send email asynchronously"""
    gmail_client = GmailClient()
    gmail_client.send_message(**email_data)


@app.task
def run_gap_analysis_async(user_id: str):
    """Run gap analysis in background"""
    gap_service = GapService(user_id)
    gaps = gap_service.analyze_gaps(days_back=7)
    return gaps


# Queue tasks
send_email_async.delay(user_id='123', email_data={...})
run_gap_analysis_async.delay(user_id='123')
```

## Technical Requirements

### Backend Dependencies
```bash
# Upstash Redis
pip install upstash-redis>=0.15.0

# Or standard Redis client (if self-hosting)
pip install redis>=5.0.0

# Celery for background jobs
pip install celery>=5.3.0
```

### Environment Variables
```bash
# Upstash Redis
UPSTASH_REDIS_REST_URL=https://...upstash.io
UPSTASH_REDIS_REST_TOKEN=...

# Or standard Redis
REDIS_URL=redis://localhost:6379/0

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### Monitoring
```bash
# Redis monitoring tools
pip install redis-py-cluster
pip install prometheus-client  # For metrics export

# Monitor cache hit rate
cache_hits = await redis.info('stats')['keyspace_hits']
cache_misses = await redis.info('stats')['keyspace_misses']
hit_rate = cache_hits / (cache_hits + cache_misses)
```

## Implementation Phases

### Phase 1: Upstash Setup (Week 1)
**Duration**: 1-2 days
**Tasks**:
1. Create Upstash account and Redis instance
2. Configure connection in backend
3. Test basic Redis operations (get, set, expire)
4. Set up monitoring dashboard

### Phase 2: Basic Caching (Week 1)
**Duration**: 2-3 days
**Tasks**:
1. Implement caching for `/api/gaps` endpoint
2. Implement caching for `/api/tasks` endpoint
3. Add cache invalidation on sync
4. Measure cache hit rate

### Phase 3: Rate Limiting (Week 2)
**Duration**: 2 days
**Tasks**:
1. Implement sliding window rate limiter
2. Add tier-based limits (Free/Pro/Team)
3. Return rate limit headers (X-RateLimit-Remaining)
4. Test with load testing tool (Locust)

### Phase 4: Session Management (Week 2)
**Duration**: 2 days
**Tasks**:
1. Move chat history to Redis
2. Cache user state (filters, preferences)
3. Test session expiration

### Phase 5: Webhook Retry Queue (Week 3)
**Duration**: 2 days
**Tasks**:
1. Implement webhook retry logic
2. Add exponential backoff
3. Create background worker for retries
4. Monitor retry success rate

### Phase 6: Background Jobs (Week 3)
**Duration**: 3 days
**Tasks**:
1. Set up Celery with Redis broker
2. Move long-running tasks to background (email sync, gap analysis)
3. Monitor job queue length
4. Test job failures and retries

## Success Metrics

### Technical Metrics
- **Cache Hit Rate**: >80% for frequently accessed data
- **API Response Time**: <100ms for cached endpoints (vs 300-500ms uncached)
- **Database Load**: 5x reduction in read queries
- **Rate Limit Accuracy**: 100% enforcement (no over-limit requests)

### Business Metrics
- **Cost Savings**: 50% reduction in Supabase costs (fewer queries)
- **User Experience**: 3x faster perceived performance
- **Scalability**: Support 10,000+ concurrent users

### Operational Metrics
- **Cache Uptime**: >99.9% Redis availability
- **Webhook Retry Success**: >95% of retries succeed
- **Background Job Success**: >99% of jobs complete successfully

## Related Documentation

- **Architecture**: `docs/architecture/overview.md` - Caching layer
- **Performance**: Monitoring and alerting setup
- **Development Plan**: `.claude/DEVELOPMENT_PLAN.md` - Phase J details

## Open Questions

1. **Self-Hosted vs Upstash**: Should we self-host Redis or use Upstash?
   - **Recommendation**: Start with Upstash (serverless), migrate to self-hosted if costs grow

2. **Cache Eviction Policy**: LRU (Least Recently Used) or LFU (Least Frequently Used)?
   - **Recommendation**: LRU for most data, manual TTL for time-sensitive data

3. **Redis Cluster**: When to use Redis Cluster (sharding)?
   - **Answer**: When single Redis instance can't handle load (>100,000 operations/sec)

4. **Data Consistency**: What if cache and database diverge?
   - **Solution**: TTL-based expiration + manual invalidation on writes

5. **Cost**: What's the monthly cost for Redis at scale?
   - **Upstash**: ~$10/month for 10,000 users, ~$100/month for 100,000 users
   - **Self-hosted**: ~$50/month for t3.medium EC2 instance

---

**Priority**: 🟢 **LOW - Scaling for Growth (Phase J)**

**Owner**: Backend Team (Mario) + DevOps

**Dependencies**:
- User growth (1,000+ users)
- Performance issues detected
- Billing system (to monetize scale)

**Next Steps**:
1. Monitor current performance metrics
2. Set up alerts for slow API endpoints
3. Research Upstash vs self-hosted Redis
4. Wait until scaling is actually needed (not premature optimization)

**Estimated Timeline**: 3 weeks (when needed)

**Trigger**: When API response times exceed 500ms P95 OR database costs exceed $200/month

**Last Updated**: December 2025
