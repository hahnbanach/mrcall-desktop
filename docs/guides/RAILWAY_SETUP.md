# Railway Deployment Setup

This document explains how to deploy Zylch on Railway.

## Architecture

Zylch uses Railway's multi-service deployment with:

1. **API Service** (`web`) - FastAPI HTTP server
2. **Background Workers** - Scheduled jobs for email sync, task detection, trigger processing

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
4. Select the `main` branch

### 2. Configure Services

Railway will auto-detect the Procfile and create services.

#### API Service

- **Process Type**: `web`
- **Start Command**: `uvicorn zylch.api.main:app --host 0.0.0.0 --port $PORT`
- **Port**: Railway auto-assigns (use `$PORT` variable)
- **Health Check**: `/health` endpoint

### 3. Configure Environment Variables

In Railway dashboard:

1. Go to project settings
2. Click "Variables" tab
3. Add all required environment variables (see above)
4. Deploy changes

### 4. Run Migrations

Before first deployment, run SQL migrations:

1. Connect to Supabase SQL Editor
2. Run all migrations from `zylch/storage/migrations/` in order
3. Verify tables created: `emails`, `task_items`, `blobs`, `triggers`, `oauth_tokens`, etc.

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

## Monitoring

### Application Logs

Check execution in Railway dashboard:

1. Go to your service
2. Check logs tab
3. Look for startup messages and request logs

### Database Status

Check task status in Supabase:

```sql
-- Recent tasks
SELECT contact_name, suggested_action, urgency, analyzed_at
FROM task_items
ORDER BY analyzed_at DESC
LIMIT 20;

-- Email archive stats
SELECT COUNT(*) as total_emails,
       MAX(date_timestamp) as latest_email
FROM emails;
```

## Troubleshooting

### No Tasks Being Created

1. Check `emails` table - are emails being archived?
2. Check logs for task_agent.py errors
3. Verify Anthropic API key is valid (users must `/connect anthropic`)
4. Check the flow: `/sync` → emails archived → task_agent extracts tasks → `task_items` table

### Database Connection Errors

1. Verify `SUPABASE_SERVICE_ROLE_KEY` is correct
2. Check `SUPABASE_URL` format
3. Test connection manually with psycopg2
4. Verify Supabase project is not paused

## Scaling

### Increase Resources

For high-volume deployments:
- Increase Railway plan tier
- Monitor database connections (Supabase limit: 60)

## Cost Considerations

### Anthropic API Costs

- Task detection uses Claude to analyze emails
- Cost depends on email volume and complexity
- Users provide their own API keys (BYOK)

### Railway Costs

- **Hobby plan** ($5/month): 500 hours, 512MB RAM, 1GB disk
- **Pro plan** ($20/month): Unlimited hours, more resources

## Support

- Railway docs: https://docs.railway.app
- Supabase docs: https://supabase.com/docs
- Zylch issues: File on GitHub
