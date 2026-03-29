---
description: |
  All Zylch deployment environments: local Docker (MrCall + Standalone), Railway, Scaleway.
  How to start, configure, and deploy to each.
---

# Environments & Deployment

## Overview

| Environment | Mode | Firebase | Database | URL | Deploy method |
|---|---|---|---|---|---|
| **Local MrCall** | Configurator | talkmeapp-e696c | Local Docker postgres | localhost:8000 | `docker compose` |
| **Local Standalone** | Sales agent | zylch-test-9a895 | Railway remote postgres | localhost:8000 | `docker compose` |
| **Railway** | Sales agent | zylch-test-9a895 | Railway Postgres-FmCF | api.zylchai.com | Auto-deploy from GitHub `main` |
| **Scaleway Test** | Configurator | talkmeapp-e696c | Scaleway Managed PG | test-env-0.scw.hbsrv.net | GitLab CI, `dev` branch |
| **Scaleway Prod** | Configurator | talkmeapp-e696c | Scaleway Managed PG | (production URL) | GitLab CI, `production` branch |

## Local Development (Docker)

### Starting

```bash
# MrCall Configurator (default)
docker compose up -d --build zylch-api

# Standalone Sales Agent
ZYLCH_MODE=standalone docker compose up -d --build zylch-api
```

Health check: `curl http://localhost:8000/health`

### Rebuilding after code changes

Code is baked into the image (no volume mount):

```bash
ZYLCH_MODE=standalone docker compose up -d --build zylch-api  # ~30s
```

### Logs

```bash
docker logs -f zylch-api
```

### Environment files

| File | Loaded by | Purpose |
|------|-----------|---------|
| `.env.shared` | Both modes | LLM keys, models, encryption, logging |
| `.env.mrcall` | `ZYLCH_MODE=mrcall` | Firebase talkmeapp, local DB, StarChat/MrCall config, MrCall dashboard CORS |
| `.env.standalone` | `ZYLCH_MODE=standalone` | Firebase zylch-test, Railway DB, Zylch app CORS |
| `.env.docker` | postgres service | Docker postgres password |

`docker-compose.yml` loads `.env.shared` + `.env.${ZYLCH_MODE:-mrcall}` automatically.

### Connecting the CLI

```bash
cd ~/hb/zylch-cli
zylch --host localhost              # local Docker
zylch --host api.zylchai.com        # Railway production
```

## Railway (Standalone Production)

### URL

`https://api.zylchai.com`

### How it deploys

Auto-deploy from GitHub repo `malemi/zylch`, branch `main`. Every push triggers a build + deploy (~6 min).

```bash
git push github main    # triggers Railway deploy
```

### Configuration

Environment variables are set via Railway CLI or dashboard — NOT from `.env` files:

```bash
railway variables -s zylch                    # list vars
railway variables -s zylch --set 'KEY=value'  # set a var
railway open                                  # open dashboard
```

Key variables: `DATABASE_URL` (auto from Postgres-FmCF), `FIREBASE_SERVICE_ACCOUNT_BASE64`, `ANTHROPIC_API_KEY`, `SYSTEM_LLM_PROVIDER`, `API_SERVER_URL`.

### Database

Railway managed PostgreSQL (`Postgres-FmCF`). Connect:

```bash
railway connect Postgres-FmCF             # psql shell
echo "SELECT count(*) FROM emails;" | railway connect Postgres-FmCF
```

### Logs

```bash
railway logs -s zylch
```

### Manual redeploy

```bash
railway redeploy -s zylch --yes
```

## Scaleway (MrCall Production)

### URLs

- **Test**: `https://test-env-0.scw.hbsrv.net` (namespace `starchat-test`)
- **Production**: (namespace `starchat-production`)

### How it deploys

GitLab CI from `git@gitlab.com:hahnbanach/zylch.git`:
- Push to `dev` → deploys to `starchat-test`
- Push to `production` → deploys to `starchat-production`

```bash
git push origin dev          # deploy to test
git push origin production   # deploy to production
```

### Configuration

Kubernetes secrets managed via deploy scripts:

```bash
cd ~/hb/zylch-deploy/test/       # or production/
vi secrets.env                    # edit env vars
./create-secrets.sh               # update K8s secrets
./deploy.sh                       # roll out new pod
```

### Database

Scaleway Managed PostgreSQL 16 with pgvector + uuid-ossp. Connection via `DATABASE_URL` in `secrets.env`.

### CLI tools

```bash
scw instance server list          # Scaleway instances
kubectl get pods -n starchat-test # K8s pods
kubectl logs -f deploy/zylch -n starchat-test
```

### GitLab Runner

Self-hosted ARM64 runner on Scaleway (`gitlab-runner-arm64`, IP `51.15.139.29`). Auto-shutdown after 4h idle, auto-start via local `.git/hooks/pre-push` hook.

If disk full on runner:
```bash
ssh ubuntu@51.15.139.29
sudo docker system prune -af && sudo docker builder prune -af
```

## Git Topology

| Remote | URL | Branches |
|--------|-----|----------|
| `origin` | `git@gitlab.com:hahnbanach/zylch.git` | `main`, `dev`, `production` |
| `github` | `https://malemi:TOKEN@github.com/malemi/zylch.git` | `main` |

- `main` → shared between GitLab and GitHub
- `dev` → GitLab only, triggers Scaleway test deploy
- `production` → GitLab only, triggers Scaleway prod deploy
- GitHub `main` → triggers Railway auto-deploy
