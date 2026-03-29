# Zylch — Indice Documentazione

Indice completo della documentazione Zylch. Se cerchi qualcosa, parti da qui.

## Architettura e Convenzioni

| File | Contenuto |
|------|-----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architettura sistema, moduli, DB, infrastruttura |
| [CONVENTIONS.md](CONVENTIONS.md) | Code style, pattern, logging, sicurezza |
| [system-rules.md](system-rules.md) | Tech stack, regole imperative |
| [active-context.md](active-context.md) | Stato corrente, lavoro recente, issue noti |
| [quality-grades.md](quality-grades.md) | Criteri di qualità codice |
| [architecture/credentials-management.md](architecture/credentials-management.md) | Gestione credenziali, BYOK, encryption |

## Guide

| File | Contenuto |
|------|-----------|
| [guides/environments.md](guides/environments.md) | **Ambienti, file .env.*, Firebase apps, deploy (Docker/Railway/Scaleway)** |
| [guides/quick-start.md](guides/quick-start.md) | Quick start locale |
| [guides/DEPLOYMENT.md](guides/DEPLOYMENT.md) | Deploy Scaleway K8s con GitLab CI |
| [guides/gmail-oauth.md](guides/gmail-oauth.md) | Configurazione Google OAuth per Gmail |
| [guides/oauth-flows-comparison.md](guides/oauth-flows-comparison.md) | Confronto flussi OAuth |
| [guides/integrations.md](guides/integrations.md) | Guida integrazioni (Pipedrive, SendGrid, Vonage) |
| [guides/email-sending-setup.md](guides/email-sending-setup.md) | Setup invio email |
| [guides/cli-commands.md](guides/cli-commands.md) | Riferimento comandi CLI |
| [guides/SHARING.md](guides/SHARING.md) | Sistema di condivisione |
| [guides/qa_testing.md](guides/qa_testing.md) | QA e testing |

## Agenti

| File | Contenuto |
|------|-----------|
| [agents/README.md](agents/README.md) | Overview sistema agenti |
| [agents/mrcall-configurator.md](agents/mrcall-configurator.md) | Configuratore MrCall: two-tier, 11 tools, dry_run, training |
| [agents/emailer-agent.md](agents/emailer-agent.md) | Agente composizione email |
| [agents/task-agent.md](agents/task-agent.md) | Agente gestione task |
| [agents/memory-agent.md](agents/memory-agent.md) | Agente memoria |

## Features

| File | Contenuto |
|------|-----------|
| [features/entity-memory-system.md](features/entity-memory-system.md) | Memory entity-centric con hybrid search e reconsolidation |
| [features/multi-tenant-architecture.md](features/multi-tenant-architecture.md) | Architettura multi-tenant |
| [features/mrcall-integration.md](features/mrcall-integration.md) | Integrazione MrCall/StarChat |
| [features/email-archive.md](features/email-archive.md) | Archivio email permanente |
| [features/email-triage.md](features/email-triage.md) | Triage email con AI |
| [features/email-read-tracking.md](features/email-read-tracking.md) | Tracking apertura email |
| [features/email-read-tracking-implementation.md](features/email-read-tracking-implementation.md) | Implementazione tracking email |
| [features/calendar-integration.md](features/calendar-integration.md) | Integrazione Google Calendar |
| [features/cache-management.md](features/cache-management.md) | Gestione cache |
| [features/relationship-intelligence.md](features/relationship-intelligence.md) | Intelligenza relazionale, gap detection |
| [features/task-management.md](features/task-management.md) | Task management |
| [features/triggers-automation.md](features/triggers-automation.md) | Trigger e automazione |
| [features/sharing-system.md](features/sharing-system.md) | Sistema condivisione |
| [features/user-persona-learning.md](features/user-persona-learning.md) | Apprendimento persona utente |

## Piani futuri (TODO)

| File | Priorita |
|------|----------|
| [features/BILLING_SYSTEM_TODO.md](features/BILLING_SYSTEM_TODO.md) | Critica — Stripe |
| [features/WHATSAPP_INTEGRATION_TODO.md](features/WHATSAPP_INTEGRATION_TODO.md) | Alta — WhatsApp |
| [features/MICROSOFT_CALENDAR_TODO.md](features/MICROSOFT_CALENDAR_TODO.md) | Media — Outlook Calendar |
| [features/DESKTOP_APP_TODO.md](features/DESKTOP_APP_TODO.md) | Media — Tauri desktop |
| [features/MOBILE_APP_TODO.md](features/MOBILE_APP_TODO.md) | Media — React Native |
| [features/REAL_TIME_PUSH_TODO.md](features/REAL_TIME_PUSH_TODO.md) | Media — Gmail Pub/Sub |
| [features/REDIS_SCALING_TODO.md](features/REDIS_SCALING_TODO.md) | Bassa — Redis caching |

## Strategia e Piani

| File | Contenuto |
|------|-----------|
| [strategy/zylchai-vs-googlecc.md](strategy/zylchai-vs-googlecc.md) | Analisi competitiva vs Google CC |
| [plans/tasks-refactor-plan.md](plans/tasks-refactor-plan.md) | Piano refactoring task system |
| [harness-backlog.md](harness-backlog.md) | Backlog harness Claude Code |
