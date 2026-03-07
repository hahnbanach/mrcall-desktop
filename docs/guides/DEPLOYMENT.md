---
description: |
  Scaleway Kubernetes deployment with GitLab CI/CD. ARM64 nodes (COPARM1/BASIC2),
  self-hosted GitLab Runner on Scaleway for native builds, auto-shutdown after 4h idle.
  Two environments: test (starchat-test) and production (starchat-production).
  Database: Scaleway Managed PostgreSQL (Phase 2 migration from Supabase).
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
| **Ingress** | Nginx Ingress Controller + cert-manager (Let's Encrypt) |
| **Database** | Scaleway Managed PostgreSQL (Phase 2, currently Supabase) |

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
│  ┌─────────────────┐  ┌─────────────────┐  │
│  │  starchat-test   │  │ starchat-prod   │  │
│  │  (dev branch)    │  │ (prod branch)   │  │
│  │                  │  │                  │  │
│  │  Deployment      │  │  Deployment      │  │
│  │  Service :8000   │  │  Service :8000   │  │
│  │  Ingress (HTTPS) │  │  Ingress (HTTPS) │  │
│  └─────────────────┘  └─────────────────┘  │
│                                             │
│  Pool: zylch-pool (BASIC2-A2C-4G ARM64)    │
└─────────────────────────────────────────────┘
```

## Environments

| Branch | K8s Namespace | Domain | Description |
|--------|--------------|--------|-------------|
| `dev` | `starchat-test` | (TBD) | Test/staging environment |
| `production` | `starchat-production` | (TBD) | Production environment |

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

All manifests live in `~/hb/zylch-deploy/`:

```
zylch-deploy/
├── test/
│   ├── kubeconfig.yaml
│   ├── secrets.env.template
│   ├── namespace.yaml
│   ├── deployment-zylch.yaml    ← 21 env vars from zylch-secrets
│   ├── service-zylch.yaml       ← port 8000
│   ├── ingress-zylch.yaml       ← HTTPS via cert-manager
│   ├── create-secrets.sh
│   ├── deploy.sh
│   └── check-status.sh
└── production/
    └── (same structure, starchat-production namespace)
```

## GitLab CI/CD

### Pipeline

Defined in `.gitlab-ci.yml`:

```
Stage 1: build    → docker build + push (ARM64 native)
Stage 2: deploy   → kubectl set image + rollout status
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

Each environment has a `zylch-secrets` K8s secret with 21 env vars:

| Category | Variables |
|----------|-----------|
| **Registry** | `REGISTRY_SERVER`, `REGISTRY_USERNAME`, `REGISTRY_TOKEN`, `REGISTRY_EMAIL` |
| **Database** | `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SSLMODE` |
| **Firebase** | `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_SERVICE_ACCOUNT_BASE64` |
| **Google OAuth** | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| **Encryption** | `ENCRYPTION_KEY` |
| **CORS** | `CORS_ALLOWED_ORIGINS` |
| **MrCall** | `MRCALL_BASE_URL`, `MRCALL_CLIENT_ID`, `MRCALL_CLIENT_SECRET`, `MRCALL_REALM`, `MRCALL_BASIC_AUTH` |
| **AI** | `ANTHROPIC_API_KEY` |
| **App** | `LOG_LEVEL` |

Setup:
```bash
cd ~/hb/zylch-deploy/test/   # or production/
cp secrets.env.template secrets.env
# Edit secrets.env with real values
./create-secrets.sh
```

## Database (Phase 2 — pending)

Currently using **Supabase** (cloud). Migrating to **Scaleway Managed PostgreSQL** requires rewriting `supabase_client.py` (4028 lines, 139 methods, 25 tables) to SQLAlchemy.

See the data layer migration plan for details (Phase 2).

## Local Development

```bash
# Run locally (same as always)
uvicorn zylch.api.main:app --reload --port 8000

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
| **Ingress/LB** | ~€10/mo | Scaleway Load Balancer |
| **Managed PostgreSQL** | TBD | Phase 2 |

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
