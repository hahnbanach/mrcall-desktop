# Zylch — Documentation Index

Complete documentation for Zylch standalone (local CLI sales intelligence tool).

## Architecture and Rules

| File | Content |
|------|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System map, data flow, modules, dependencies |
| [CONVENTIONS.md](CONVENTIONS.md) | Code style, patterns, logging, security |
| [system-rules.md](system-rules.md) | Tech stack, coding standards, imperatives |
| [active-context.md](active-context.md) | Current state, recent work, known issues |
| [quality-grades.md](quality-grades.md) | Module quality assessment |
| [architecture/credentials-management.md](architecture/credentials-management.md) | Credential storage, BYOK, Fernet encryption |

## Guides

| File | Content |
|------|---------|
| [guides/quick-start.md](guides/quick-start.md) | Install, setup, first use |
| [guides/cli-commands.md](guides/cli-commands.md) | CLI and slash command reference |

## Agents

| File | Content |
|------|---------|
| [agents/README.md](agents/README.md) | Agent system overview |
| [agents/emailer-agent.md](agents/emailer-agent.md) | Email composition agent |
| [agents/task-agent.md](agents/task-agent.md) | Task detection agent |
| [agents/memory-agent.md](agents/memory-agent.md) | Memory extraction agent |

## Features

| File | Content |
|------|---------|
| [features/entity-memory-system.md](features/entity-memory-system.md) | Entity-centric memory with hybrid search |
| [features/email-archive.md](features/email-archive.md) | Email archive with IMAP sync |
| [features/email-triage.md](features/email-triage.md) | Email triage and auto-reply detection |
| [features/task-management.md](features/task-management.md) | Task system (4-level urgency) |
| [features/relationship-intelligence.md](features/relationship-intelligence.md) | Relationship intelligence and gap detection |
| [features/user-persona-learning.md](features/user-persona-learning.md) | User persona learning |
| [features/calendar-integration.md](features/calendar-integration.md) | Calendar integration (planned: CalDAV) |

## Future Plans (TODO)

| File | Priority |
|------|----------|
| [features/WHATSAPP_INTEGRATION_TODO.md](features/WHATSAPP_INTEGRATION_TODO.md) | High — WhatsApp via GOWA |
| [features/MICROSOFT_CALENDAR_TODO.md](features/MICROSOFT_CALENDAR_TODO.md) | Medium — Outlook Calendar via CalDAV |

## Plans and QA

| File | Content |
|------|---------|
| [plans/standalone-transformation.md](plans/standalone-transformation.md) | Transformation plan (completed, reference only) |
| [qa/standalone-qa-report.md](qa/standalone-qa-report.md) | QA report from standalone transformation |
| [strategy/zylchai-vs-googlecc.md](strategy/zylchai-vs-googlecc.md) | Competitive analysis vs Google CC |
| [harness-backlog.md](harness-backlog.md) | Claude Code harness gaps and backlog |
