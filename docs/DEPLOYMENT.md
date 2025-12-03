# Zylch AI - Railway Deployment Guide

## Overview

This guide covers deploying Zylch AI backend to Railway for production hosting.

## Prerequisites

- Railway account (https://railway.app)
- GitHub repository connected to Railway
- Firebase project with service account
- All required API keys (Anthropic, Google OAuth, etc.)

## Deployment Files

| File | Purpose |
|------|---------|
| `railway.json` | Railway configuration (build, deploy, health checks) |
| `Procfile` | Process definition for web server |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |

## Quick Start

### 1. Create Railway Project

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login to Railway
railway login

# Initialize project in zylch directory
cd /path/to/zylch
railway init
```

### 2. Link GitHub Repository

1. Go to Railway Dashboard → Project Settings
2. Connect GitHub repository
3. Select `main` branch for auto-deploy

### 3. Configure Environment Variables

In Railway Dashboard → Variables, add:

**Required:**
```
ANTHROPIC_API_KEY=sk-ant-xxx
FIREBASE_PROJECT_ID=zylch-xxx
FIREBASE_API_KEY=xxx
FIREBASE_AUTH_DOMAIN=zylch-xxx.firebaseapp.com
CORS_ALLOWED_ORIGINS=https://app.zylch.com,https://zylch.com
```

**Google OAuth (for Gmail/Calendar):**
```
GOOGLE_CREDENTIALS_PATH=credentials/google_oauth.json
GOOGLE_TOKEN_PATH=/app/.zylch/credentials/google
```

**StarChat/MrCall:**
```
STARCHAT_API_URL=https://api.starchat.com
STARCHAT_USERNAME=xxx
STARCHAT_PASSWORD=xxx
STARCHAT_BUSINESS_ID=xxx
```

**SendGrid:**
```
SENDGRID_API_KEY=SG.xxx
```

**Vonage SMS:**
```
VONAGE_API_KEY=xxx
VONAGE_API_SECRET=xxx
VONAGE_FROM_NUMBER=+1xxx
```

See `.env.example` for the complete list.

### 4. Configure Persistent Storage

Railway provides ephemeral storage by default. For SQLite persistence:

**Option A: Railway Volume (Recommended)**
1. Add a Volume in Railway Dashboard
2. Mount path: `/app/data`
3. Update `CACHE_DIR` and `DATA_DIR` env vars to use `/app/data`

**Option B: Migrate to Supabase (Future)**
- See Phase I in DEVELOPMENT_PLAN.md

### 5. Deploy

**Automatic (recommended):**
- Push to `main` branch triggers deploy

**Manual:**
```bash
railway up
```

### 6. Verify Deployment

```bash
# Check health endpoint
curl https://your-app.railway.app/health

# Expected response:
# {"status":"healthy","skill_mode":true,"pattern_store":true}
```

## Custom Domain Setup

1. Railway Dashboard → Settings → Domains
2. Add custom domain: `api.zylch.com`
3. Configure DNS:
   - CNAME record pointing to Railway domain
   - Or use Railway's DNS settings

## CI/CD Pipeline

Railway automatically:
- Builds on push to connected branch
- Runs health checks before routing traffic
- Rolls back on failed deployments

### GitHub Actions (Optional)

For additional CI steps, create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Railway

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pip install pytest pytest-asyncio
      - run: python -m pytest tests/ -v

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: railwayapp/railway-deploy@v1
        with:
          railway_token: ${{ secrets.RAILWAY_TOKEN }}
```

## Monitoring

### Health Check
- Endpoint: `GET /health`
- Timeout: 30 seconds
- Checked every 30 seconds

### Logs
```bash
# View logs via CLI
railway logs

# Or in Railway Dashboard → Deployments → Logs
```

### Metrics
Railway provides:
- CPU usage
- Memory usage
- Network I/O
- Request latency

## Troubleshooting

### Build Fails
1. Check `requirements.txt` syntax
2. Verify Python 3.11+ is being used
3. Check build logs for missing dependencies

### Health Check Fails
1. Verify `/health` endpoint works locally
2. Check Firebase initialization (may fail without proper credentials)
3. Review startup logs for errors

### SQLite Permission Errors
1. Ensure cache directories exist and are writable
2. Use Railway Volume for persistence
3. Consider migrating to Supabase (Phase I)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Railway                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                 Zylch API Server                     │    │
│  │  uvicorn zylch.api.main:app --port $PORT            │    │
│  │                                                       │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐           │    │
│  │  │ /api/*   │  │/webhooks │  │ /health  │           │    │
│  │  │ FastAPI  │  │ StarChat │  │ Monitor  │           │    │
│  │  │ Routes   │  │ SendGrid │  │          │           │    │
│  │  └──────────┘  └──────────┘  └──────────┘           │    │
│  └─────────────────────────────────────────────────────┘    │
│                            │                                  │
│  ┌─────────────────────────┴───────────────────────────┐    │
│  │              Railway Volume (/app/data)              │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │    │
│  │  │ archive.db │  │ memory.db  │  │ sharing.db │     │    │
│  │  └────────────┘  └────────────┘  └────────────┘     │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │           External Services              │
        │  ┌────────┐ ┌────────┐ ┌────────┐       │
        │  │Firebase│ │Anthropic│ │StarChat│       │
        │  │  Auth  │ │  Claude │ │ MrCall │       │
        │  └────────┘ └────────┘ └────────┘       │
        └─────────────────────────────────────────┘
```

## Cost Estimation

Railway pricing (as of 2024):
- **Hobby Plan**: $5/month (512MB RAM, shared CPU)
- **Pro Plan**: Usage-based (~$20-50/month typical)

Recommended for Zylch:
- Start with Hobby for testing
- Upgrade to Pro for production load

## Next Steps

After Railway deployment:
1. **Phase G**: Deploy dashboard to Vercel
2. **Phase H**: Integrate Stripe billing
3. **Phase I**: Migrate to Supabase for database

---

*Last updated: 2025-12-03*
