# Railway Deployment Setup for Avatar System

This document explains how to deploy Zylch with the Von Neumann Memory Architecture on Railway.

## Architecture

Zylch uses Railway's multi-service deployment with:

1. **API Service** (`web`) - FastAPI HTTP server
2. **Memory Worker** (`memory-worker`) - Background cron job for identifier extraction and memory storage
3. **CRM Worker** (`crm-worker`) - Background cron job for avatar computation from memory

## Prerequisites

- Railway account ([railway.app](https://railway.app))
- GitHub repository connected to Railway
- Supabase project with migrations applied

## Environment Variables

Configure these in Railway dashboard:

### Required for All Services

```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
SUPABASE_DB_PASSWORD=your_db_password

# Anthropic - BYOK (users provide via /connect anthropic)
# NOTE: ANTHROPIC_API_KEY is NOT in system .env
# Each user provides their own key, stored in Supabase

# Firebase (for auth)
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}

# App Config
ENVIRONMENT=production
LOG_LEVEL=INFO
CORS_ALLOWED_ORIGINS=https://your-frontend.com,http://localhost:5173
```

### Optional

```bash
# Skill Mode (if using)
SKILL_MODE_ENABLED=true

# Pattern Store (if using)
PATTERN_STORE_ENABLED=true
```

## Deployment Steps

### 1. Connect Repository

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Create new project
3. Connect your GitHub repository
4. Select the `main` branch (or `avatar` branch for testing)

### 2. Configure Services

Railway will auto-detect the Procfile and create services.

#### API Service

- **Process Type**: `web`
- **Start Command**: `uvicorn zylch.api.main:app --host 0.0.0.0 --port $PORT`
- **Port**: Railway auto-assigns (use `$PORT` variable)
- **Health Check**: `/health` endpoint

#### Memory Worker Service

Railway supports cron jobs in two ways:

**Option A: Railway Cron (Recommended)**

1. In Railway dashboard, create new service called "memory-worker"
2. Select "Cron Job" type
3. Configure:
   - **Schedule**: `*/5 * * * *` (every 5 minutes)
   - **Command**: `python -m zylch.workers.memory_worker`
   - **Timeout**: 300 seconds (5 minutes)

**Option B: Continuous Loop (Alternative)**

If Railway doesn't support cron in your plan:

1. Use the `memory-scheduler` process from Procfile
2. Command: `while true; do python -m zylch.workers.memory_worker; sleep 300; done`
3. This runs the worker every 5 minutes in a loop

#### CRM Worker Service

**Option A: Railway Cron (Recommended)**

1. In Railway dashboard, create new service called "crm-worker"
2. Select "Cron Job" type
3. Configure:
   - **Schedule**: `*/10 * * * *` (every 10 minutes, runs after memory worker)
   - **Command**: `python -m zylch.workers.crm_worker`
   - **Timeout**: 600 seconds (10 minutes)

**Option B: Continuous Loop (Alternative)**

1. Use the `crm-scheduler` process from Procfile
2. Command: `while true; do python -m zylch.workers.crm_worker; sleep 600; done`
3. This runs the worker every 10 minutes in a loop

### 3. Configure Environment Variables

In Railway dashboard:

1. Go to project settings
2. Click "Variables" tab
3. Add all required environment variables (see above)
4. Deploy changes

### 4. Run Migrations

Before first deployment, run SQL migration:

1. Connect to Supabase SQL Editor
2. Run contents of `docs/migration/001_add_avatar_fields_v3.sql`
3. Verify tables created: `avatars`, `identifier_map`, `memory` (replaces avatar_compute_queue)

### 5. Deploy

Railway auto-deploys on git push:

```bash
git push origin main
```

Or manually trigger deployment in Railway dashboard.

### 6. Verify Deployment

#### Check API Health

```bash
curl https://your-app.railway.app/health
# Should return: {"status": "healthy", ...}
```

#### Check Worker Logs

In Railway dashboard:

**Memory Worker:**
1. Go to "memory-worker" service
2. Check logs tab
3. Look for: "Memory Worker Starting"
4. Verify it runs every 5 minutes

**CRM Worker:**
1. Go to "crm-worker" service
2. Check logs tab
3. Look for: "CRM Worker Starting"
4. Verify it runs every 10 minutes

#### Test Avatar API

```bash
# Get avatars (requires Firebase auth token)
curl https://your-app.railway.app/api/avatars \
  -H "auth: your_firebase_id_token"
```

## Monitoring

### Worker Logs

Check worker execution:

```bash
# Railway CLI - Memory Worker
railway logs --service memory-worker --tail

# Railway CLI - CRM Worker
railway logs --service crm-worker --tail
```

**Memory Worker logs** - Look for:
- "Memory worker starting..." (every 5 min)
- "Processing {n} emails..." (when new emails exist)
- "Extracted identifiers: {n}" (on success)
- Error messages (if any failures)

**CRM Worker logs** - Look for:
- "CRM worker starting..." (every 10 min)
- "Computing avatars for {n} contacts..." (when memory has updates)
- "Batch complete: {n} avatars updated" (on success)
- Error messages (if any failures)

### Database Queue

Check memory and avatar status in Supabase:

```sql
-- Check memory entries by contact
SELECT contact_id, COUNT(*) as memory_count,
       MAX(created_at) as latest_memory
FROM memory
GROUP BY contact_id
ORDER BY latest_memory DESC
LIMIT 20;

-- Recent avatar updates
SELECT contact_id, display_name, last_computed, compute_trigger
FROM avatars
ORDER BY last_computed DESC
LIMIT 20;

-- Memory to Avatar flow status
SELECT
  m.contact_id,
  COUNT(DISTINCT m.id) as memory_entries,
  a.last_computed,
  a.compute_trigger
FROM memory m
LEFT JOIN avatars a ON m.contact_id = a.contact_id
GROUP BY m.contact_id, a.last_computed, a.compute_trigger
ORDER BY MAX(m.created_at) DESC
LIMIT 20;
```

### Performance Metrics

Monitor in Railway dashboard:

**Memory Worker:**
- **CPU usage**: Should spike every 5 minutes during execution
- **Memory usage**: Should stay under 256MB (very lightweight)
- **Execution time**: ~5-30 seconds per batch (depends on new emails)

**CRM Worker:**
- **CPU usage**: Should spike every 10 minutes during execution
- **Memory usage**: Should stay under 512MB (LLM processing)
- **Execution time**: ~10-60 seconds per batch (depends on contacts with updated memory)

## Backfilling Existing Contacts

After deployment, backfill avatars for existing contacts:

```bash
# SSH into Railway container (if available) or run locally
python scripts/backfill_avatars.py --owner-id <firebase_uid>
```

Or trigger via API (create endpoint if needed).

## Troubleshooting

### Worker Not Running

1. Check Railway logs for errors
2. Verify environment variables are set
3. Check Supabase connection
4. Verify cron schedule is correct

### No Avatars Being Created

1. Check `memory` table - are identifiers being extracted?
2. Check memory worker logs - is it processing emails?
3. Check CRM worker logs - is it computing avatars from memory?
4. Verify Anthropic API key is valid
5. Check the flow: Emails → Memory Worker → Memory table → CRM Worker → Avatars

### Slow Avatar Computation

1. Increase worker timeout (if hitting limits)
2. Reduce batch size in worker code
3. Check Anthropic API rate limits
4. Consider multiple worker instances (if supported)

### Database Connection Errors

1. Verify `SUPABASE_SERVICE_ROLE_KEY` is correct
2. Check `SUPABASE_URL` format
3. Test connection manually with psycopg2
4. Verify Supabase project is not paused

## Scaling

### Increase Worker Frequency

**Memory Worker** (identifier extraction):
- Every 2 minutes: `*/2 * * * *`
- Every minute: `* * * * *`
- Every 10 minutes: `*/10 * * * *`

**CRM Worker** (avatar computation):
- Every 5 minutes: `*/5 * * * *`
- Every 15 minutes: `*/15 * * * *`
- Every 30 minutes: `*/30 * * * *`

### Multiple Workers

For high-volume deployments:
1. Create multiple worker services
2. Use different priorities or partitioning logic
3. Monitor for conflicts (Postgres row locking handles this)

### Optimize Batch Size

**Memory Worker** (in `memory_worker.py`):
```python
# Default: Process all new emails per run
# Adjust email fetch limit in sync_service.py if needed
```

**CRM Worker** (in `crm_worker.py`):
```python
# Default: 10 avatars per batch
worker = CRMWorker(storage, anthropic_client, batch_size=20)
```

Balance between:
- **Smaller batches** (10): More frequent updates, less risk
- **Larger batches** (50): Fewer LLM calls, more efficient

## Cost Considerations

### Anthropic API Costs

With 1000 contacts:
- 1 avatar computation = ~1500 tokens (~$0.003)
- Full backfill = 1000 × $0.003 = **~$3**
- Weekly refresh = 1000 × $0.003 = **~$3/week**
- Per-email triggers = depends on email volume

### Railway Costs

- **Hobby plan** ($5/month): 500 hours, 512MB RAM, 1GB disk
- **Pro plan** ($20/month): Unlimited hours, more resources
- Worker uses ~10-60s per run, ~300 runs/day = **~5 hours/day**

### Optimization Tips

1. **Skip recent avatars**: Worker checks `last_computed`, skips if <7 days
2. **Prioritize important contacts**: Use priority queue effectively
3. **Batch operations**: Process multiple avatars per LLM call (future optimization)
4. **Cache embeddings**: Reuse sentence-transformers embeddings

## Support

- Railway docs: https://docs.railway.app
- Supabase docs: https://supabase.com/docs
- Zylch issues: File on GitHub
