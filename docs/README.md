# Zylch — Documentation Index

Complete documentation for Zylch standalone (local CLI sales intelligence tool).

## Architecture and Rules (Static)

| File | Content |
|------|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System map, data flow, modules, dependencies |
| [system-rules.md](system-rules.md) | Tech stack, coding standards, imperatives |
| [CONVENTIONS.md](CONVENTIONS.md) | Code style, patterns, logging, security |
| [architecture/credentials-management.md](architecture/credentials-management.md) | Credential storage, BYOK, Fernet encryption |

## Current State (Dynamic)

| File | Content |
|------|---------|
| [active-context.md](active-context.md) | What works, what's next, known issues |
| [quality-grades.md](quality-grades.md) | Module quality, oversized files, stale code |
| [execution-plans/cleanup-and-split.md](execution-plans/cleanup-and-split.md) | Active: dead code removal, file splitting, lint |
| [execution-plans/claude-code-patterns.md](execution-plans/claude-code-patterns.md) | Active: prompt caching, parallel LLM, dream, digest |
| [execution-plans/next-features.md](execution-plans/next-features.md) | Backlog: agentic solve, CalDAV, dedup, cleanup, tests |

## Guides

| File | Content |
|------|---------|
| [guides/quick-start.md](guides/quick-start.md) | Install, setup, first use |
| [guides/cli-commands.md](guides/cli-commands.md) | CLI and slash command reference |

## Agents

| File | Content |
|------|---------|
| [agents/README.md](agents/README.md) | Agent system overview |
| [agents/memory-agent.md](agents/memory-agent.md) | Memory extraction agent |
| [agents/task-agent.md](agents/task-agent.md) | Task detection agent |
| [agents/emailer-agent.md](agents/emailer-agent.md) | Email composition agent |

## Features

| File | Content |
|------|---------|
| [features/entity-memory-system.md](features/entity-memory-system.md) | Entity-centric memory with hybrid search |
| [features/email-archive.md](features/email-archive.md) | Email archive with IMAP sync |
| [features/email-triage.md](features/email-triage.md) | Email triage and auto-reply detection |
| [features/task-management.md](features/task-management.md) | Task system (4-level urgency) |
| [features/relationship-intelligence.md](features/relationship-intelligence.md) | Relationship intelligence and gap detection |
| [features/calendar-integration.md](features/calendar-integration.md) | Calendar integration (planned: CalDAV) |
| [features/MICROSOFT_CALENDAR_TODO.md](features/MICROSOFT_CALENDAR_TODO.md) | Outlook Calendar via CalDAV (TODO) |

## Reference

| File | Content |
|------|---------|
| [plans/standalone-transformation.md](plans/standalone-transformation.md) | Transformation plan (completed, reference) |
| [harness-backlog.md](harness-backlog.md) | Claude Code harness gaps |
