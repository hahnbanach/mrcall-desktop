---
description: |
  Scaleway Kubernetes deployment with GitLab CI/CD. ARM64 nodes (COPARM1/BASIC2),
  self-hosted GitLab Runner on Scaleway for native builds, auto-shutdown after 4h idle.
  Two environments: test (starchat-test, in-cluster postgres) and production
  (starchat-production, Scaleway Managed PostgreSQL). HTTPS via nginx ingress + cert-manager.
---

# Zylch Deployment - Scaleway Kubernetes

## Overview

Zylch runs on **Scaleway Kubernetes** with **ARM64 nodes**, built via **GitLab CI/CD** using a self-hosted ARM runner on Scaleway.

| Component | Technology |
|-----------|-----------|
| **Orchestration** | Scaleway Kapsule (Kubernetes) |
| **Nodes** | ARM64 — BASIC2-A2C-4G (2 vCPU, 4GB) |
| **CI/CD** | GitLab CI with self-hosted ARM runner |
| **Registry** | GitLab Container Registry (`registry.gitlab.com/hahnbanach/zylch`) |
| **Database (test)** | In-cluster PostgreSQL 16 + pgvector (container) |
| **Database (prod)** | Scaleway Managed PostgreSQL 16 (`zylch-db`, db-dev-s, pgvector 0.8) |
| **Network** | ClusterIP + nginx Ingress (HTTPS via cert-manager/Let's Encrypt) |
| **CORS** | nginx ingress annotations + FastAPI CORSMiddleware (defense-in-depth) |

## Architecture

```
git push (dev/production)
       │
       ├─ pre-push hook auto-starts runner if stopped
       │
       ▼
┌─────────────────────────────────────────────┐
│  GitLab CI (.gitlab-ci.yml)                 │
│                                             │
│  Stage 1: BUILD                             │
│    Self-hosted ARM64 runner (Scaleway)      │
│    docker build → push to GitLab Registry   │
│                                             │
│  Stage 2: DEPLOY                            │
│    kubectl set image → rollout status       │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  Scaleway Kubernetes                        │
│                                             │
│  ┌──────────────────┐  ┌──────────────────┐ │
│  │  starchat-test    │  │ starchat-prod    │ │
│  │  (dev branch)     │  │ (prod branch)    │ │
│  │                   │  │                  │ │
│  │  zylch (API)      │  │  zylch (API)     │ │
│  │  postgres (DB)    │  │  Service :8000   │ │
│  │  Service :8000    │  │                  │ │
│  └──────────────────┘  └────────┬─────────┘ │
│                                 │            │
│  Pool: zylch-pool (ARM64)       │            │
└─────────────────────────────────┼────────────┘
                                  │
                     ┌────────────▼────────────┐
                     │  Scaleway Managed        │
                     │  PostgreSQL (zylch-db)   │
                     └─────────────────────────┘
```

## Environments

| Branch | K8s Namespace | Database | Description |
|--------|--------------|----------|-------------|
| `dev` | `starchat-test` | In-cluster postgres container | Test/staging environment |
| `production` | `starchat-production` | Scaleway Managed PostgreSQL | Production environment |

Both branches trigger build + deploy on push.

## Infrastructure

### GitLab Runner (self-hosted ARM64)

A dedicated Scaleway instance builds Docker images **natively on ARM64** — no QEMU emulation, fast builds.

| Property | Value |
|----------|-------|
| **Name** | `gitlab-runner-arm64` |
| **Instance ID** | `fa2201aa-d1d6-4915-9c07-ea0bd93ae734` |
| **Type** | COPARM1-2C-8G (2 ARM cores, 8GB RAM) |
| **IP** | `51.15.139.29` |
| **Zone** | `fr-par-1` |
| **OS** | Ubuntu 24.04 (Noble) |
| **Executor** | `shell` (Docker installed locally) |
| **GitLab Runner tag** | `arm64` |
| **Cost** | ~€0.043/h (on-demand, auto-shuts down after 4h idle) |

**Installed software:**
- Docker 29.3.0
- GitLab Runner 18.9.0
- kubectl v1.35.2
- git 2.43.0

**Config file:** `/etc/gitlab-runner/config.toml`

### Auto-Shutdown (cost savings)

The runner auto-shuts down after **4 hours of inactivity** to minimize costs.

- **Mechanism**: Cron job every 10 minutes checks for active GitLab jobs or Docker containers
- **Script**: `/usr/local/bin/idle-shutdown.sh` on the runner
- **Idle threshold**: 14400 seconds (4 hours)
- **Activity file**: `/tmp/runner-last-activity`

### Auto-Start (pre-push hook)

A local git hook (`pre-push`) auto-starts the runner before every push to GitLab.

- **Hook location**: `.git/hooks/pre-push` (local, not committed)
- **Only triggers for**: GitLab remote (`origin`)
- **Uses**: `scw instance server start` with `--wait`
- **If already running**: No-op

**Manual start/stop:**

```bash
# Start the runner
scw instance server start fa2201aa-d1d6-4915-9c07-ea0bd93ae734 zone=fr-par-1

# Stop the runner
scw instance server stop fa2201aa-d1d6-4915-9c07-ea0bd93ae734 zone=fr-par-1

# Check status
scw instance server get fa2201aa-d1d6-4915-9c07-ea0bd93ae734 zone=fr-par-1 -o json | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])"

# SSH into runner
ssh root@51.15.139.29
```

### Kubernetes Clusters

Two separate Scaleway Kapsule clusters:

| Cluster | Auth method | Namespace |
|---------|------------|-----------|
| **Test** | Static token in kubeconfig | `starchat-test` |
| **Production** | `scw` CLI exec-based kubeconfig | `starchat-production` |

**Node pool**: `zylch-pool` — BASIC2-A2C-4G (2 ARM vCPU, 4GB RAM), 1 node per cluster.

### Kubernetes Manifests

Manifests live in two locations:

- **`~/hb/zylch-deploy/`** — operational manifests + secrets (not in git)
- **`k8s/`** in the zylch repo — postgres manifests applied by CI

```
zylch-deploy/
├── test/
│   ├── kubeconfig.yaml
│   ├── secrets.env                  ← DATABASE_URL + all app secrets
│   ├── namespace.yaml
│   ├── deployment-zylch.yaml        ← env vars from zylch-secrets
│   ├── deployment-postgres.yaml     ← in-cluster postgres + pgvector
│   ├── ingress-zylch.yaml            ← nginx ingress + CORS + TLS
│   ├── service-zylch.yaml           ← ClusterIP :8000
│   ├── service-postgres.yaml        ← ClusterIP :5432
│   ├── configmap-postgres-init.yaml ← uuid-ossp + vector extensions
│   ├── create-secrets.sh
│   ├── deploy.sh
│   └── check-status.sh
└── production/
    └── (same structure, no postgres — uses Managed DB)

zylch/k8s/test/                      ← in repo, applied by CI
├── configmap-postgres-init.yaml
├── deployment-postgres.yaml
└── service-postgres.yaml
```

## GitLab CI/CD

### Pipeline

Defined in `.gitlab-ci.yml`:

```
Stage 1: build    → docker build + push (ARM64 native)
Stage 2: deploy   → kubectl apply (postgres for test) + set image + rollout status
```

Both stages use the `arm64` tag to run on the self-hosted runner.

### Required CI/CD Variables

Set in **GitLab > Settings > CI/CD > Variables**:

| Variable | Description | How to get |
|----------|-------------|-----------|
| `KUBECONFIG_TEST` | Base64-encoded kubeconfig for test cluster | `base64 < test/kubeconfig.yaml` |
| `KUBECONFIG_PRODUCTION` | Base64-encoded kubeconfig for production cluster | `base64 < production/kubeconfig.yaml` |

`CI_REGISTRY`, `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD` are auto-set by GitLab.

### Image Tags

| Branch | Image tag |
|--------|-----------|
| `dev` | `dev-<short_sha>` + `dev` (latest) |
| `production` | `prod-<short_sha>` + `production` (latest) |

## Secrets (Kubernetes)

Each environment has a `zylch-secrets` K8s secret:

| Category | Variables |
|----------|-----------|
| **Registry** | `REGISTRY_SERVER`, `REGISTRY_USERNAME`, `REGISTRY_TOKEN`, `REGISTRY_EMAIL` |
| **Database** | `DATABASE_URL`, `DB_PASSWORD` (test only, for postgres container) |
| **Firebase** | `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_SERVICE_ACCOUNT_BASE64` |
| **Google OAuth** | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| **Encryption** | `ENCRYPTION_KEY` |
| **CORS** | `CORS_ALLOWED_ORIGINS` |
| **MrCall** | `MRCALL_BASE_URL`, `MRCALL_CLIENT_ID`, `MRCALL_CLIENT_SECRET`, `MRCALL_REALM`, `MRCALL_OAUTH_AUTHORIZE_URL` |
| **AI** | `ANTHROPIC_API_KEY` |
| **App** | `LOG_LEVEL` |

`DATABASE_URL` format:
- **Test**: `postgresql://zylch:<pass>@postgres:5432/zylch` (in-cluster service)
- **Production**: `postgresql://zylch:<pass>@62.210.39.141:4433/zylch?sslmode=require` (Managed DB)

Setup:
```bash
cd ~/hb/zylch-deploy/test/   # or production/
cp secrets.env.template secrets.env
# Edit secrets.env with real values
./create-secrets.sh
```

## Ingress & CORS

Each environment has an nginx ingress (`ingress-zylch.yaml`) that terminates TLS and handles CORS.

| Environment | Host | Ingress file |
|-------------|------|-------------|
| **Test** | `zylch-test.mrcall.ai` | `~/hb/zylch-deploy/test/ingress-zylch.yaml` |
| **Production** | `zylch.mrcall.ai` | `~/hb/zylch-deploy/production/ingress-zylch.yaml` |

CORS is configured at **two layers** (defense-in-depth):

1. **nginx ingress annotations** — handles CORS headers on ALL responses, including nginx-generated error responses (502/503/504). This is critical because when the pod is slow/unresponsive, nginx returns errors that bypass FastAPI middleware.
2. **FastAPI CORSMiddleware** (`zylch/api/main.py`) — handles CORS on application responses. Origins read from `CORS_ALLOWED_ORIGINS` env var (K8s secret).

Key ingress annotations:
```yaml
nginx.ingress.kubernetes.io/enable-cors: "true"
nginx.ingress.kubernetes.io/cors-allow-origin: "https://dashboard-test.mrcall.ai,..."
nginx.ingress.kubernetes.io/cors-allow-credentials: "true"
nginx.ingress.kubernetes.io/proxy-read-timeout: "300"    # 5min for LLM calls
nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
```

**When updating allowed origins**, update BOTH:
- The ingress YAML (`cors-allow-origin` annotation) → `kubectl apply`
- The K8s secret (`CORS_ALLOWED_ORIGINS`) → `./create-secrets.sh`

## Database

### Test: In-Cluster PostgreSQL

A `pgvector/pgvector:pg16` container runs in the `starchat-test` namespace alongside zylch. Extensions `uuid-ossp` and `vector` are initialized via ConfigMap (`/docker-entrypoint-initdb.d/`). Data is ephemeral (`emptyDir` volume).

### Production: Scaleway Managed PostgreSQL

Instance `zylch-db`:

| Property | Value |
|----------|-------|
| **Instance ID** | `7964a6db-25a2-4e98-b5ae-cf1c255a47d0` |
| **Type** | db-dev-s |
| **Engine** | PostgreSQL 16 |
| **Extensions** | pgvector 0.8, uuid-ossp |
| **Host** | `62.210.39.141` |
| **Port** | `4433` |
| **Database** | `zylch` |
| **User** | `zylch` (admin) |
| **Volume** | 5 GB lssd |
| **Region** | fr-par |
| **Backups** | Daily, 7-day retention |

### Data Layer

SQLAlchemy ORM (29 models in `zylch/storage/models.py`). Schema managed by Alembic migrations (`alembic/versions/`). On container start, `alembic upgrade head` runs automatically.

## Local Development

```bash
# Option 1: Docker Compose (zylch + postgres containers)
docker compose up --build

# Option 2: Just the DB container, run zylch locally
docker compose up postgres
uvicorn zylch.api.main:app --reload --port 8000
# DATABASE_URL=postgresql://zylch:zylch_dev@localhost:5432/zylch

# .env symlink points to your development config
ls -la .env  # → .env.development or .env.mrcall
```

## Operations

### Deploy manually

```bash
cd ~/hb/zylch-deploy/test/
export KUBECONFIG=$(pwd)/kubeconfig.yaml
./deploy.sh              # Apply current manifests
./deploy.sh 1.2.0        # Update image tag and apply
```

### Check status

```bash
cd ~/hb/zylch-deploy/test/
./check-status.sh        # Pods, services, ingress, events, logs
```

### kubectl direct

```bash
export KUBECONFIG=~/hb/zylch-deploy/test/kubeconfig.yaml
kubectl get pods -n starchat-test -l app=zylch
kubectl logs -f deployment/zylch -n starchat-test
```

### Runner maintenance

```bash
# Check runner config
ssh root@51.15.139.29 'cat /etc/gitlab-runner/config.toml'

# Check runner status
ssh root@51.15.139.29 'gitlab-runner verify && gitlab-runner status'

# View idle-shutdown cron
ssh root@51.15.139.29 'crontab -l'

# Check Docker disk usage
ssh root@51.15.139.29 'docker system df'

# Prune old images
ssh root@51.15.139.29 'docker image prune -af --filter "until=168h"'
```

## Costs

| Component | Cost | Notes |
|-----------|------|-------|
| **K8s nodes** (2x BASIC2-A2C-4G) | ~€33/mo total | 1 test + 1 prod |
| **GitLab Runner** (COPARM1-2C-8G) | ~€0.043/h on-demand | Auto-shutdown after 4h, ~€2-5/mo typical |
| **K8s control plane** | Free | Scaleway Kapsule control plane is free |
| **Managed PostgreSQL** (db-dev-s) | ~€7/mo | Production only, 5GB lssd, daily backups |

## Troubleshooting

### Runner not picking up jobs

1. Check runner is running: `scw instance server get fa2201aa... zone=fr-par-1`
2. If stopped, start it: `scw instance server start fa2201aa... zone=fr-par-1`
3. SSH and verify: `ssh root@51.15.139.29 'gitlab-runner verify'`
4. Check `.gitlab-ci.yml` has `tags: [arm64]`

### Build fails

1. SSH into runner: `ssh root@51.15.139.29`
2. Check Docker: `docker info`
3. Check disk space: `df -h`
4. Prune if needed: `docker system prune -af`

### Deploy fails

1. Check kubeconfig CI variable is correct (base64-encoded)
2. Verify namespace exists: `kubectl get ns starchat-test`
3. Check deployment exists: `kubectl get deployment zylch -n starchat-test`
4. Check pod events: `kubectl describe pod -n starchat-test -l app=zylch`

### Pod CrashLoopBackOff

1. Check logs: `kubectl logs -n starchat-test -l app=zylch --previous`
2. Verify secrets are created: `kubectl get secrets -n starchat-test`
3. Check env vars: `kubectl describe deployment zylch -n starchat-test`

---

*Last updated: March 2026*
