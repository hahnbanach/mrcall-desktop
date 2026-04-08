---
description: Migrate Documentation to Harness Structure
---
Build the documentation harness from scratch. Two layers: **static** (stable knowledge, cacheable) and **dynamic** (volatile state, changes every session).

## Phase 1 — Inventory
1. Read any existing `./docs/*.md`, `./CLAUDE.md`, `./AGENTS.md`, `README.md`.
2. Scan source directories and config files to understand the *actual* implementation.
3. Where documentation contradicts the code, **the code wins**. Flag discrepancies.

## Phase 2 — Generate Static Layer
These docs change rarely. They form the cacheable foundation.

- **`./CLAUDE.md`** — The index. Max ~100 lines. Contains:
  - One-sentence project description
  - Pointers to every doc in `./docs/` with a one-line summary
  - Quick-reference: how to build, test, lint, run
  - NO rules or architecture details — only pointers

- **`./docs/system-rules.md`** — Absolute constraints:
  - Tech stack, language version, key libraries
  - Coding standards observed in the actual codebase
  - Dependency rules: which layers can import which
  - Rules stated as imperatives ("Never", "Always", "Must")

- **`./docs/ARCHITECTURE.md`** — System map from code reality:
  - Modules/packages, responsibilities, boundaries
  - Dependency direction diagram
  - Data flow: how requests/data move through the system
  - Infrastructure: databases, external services, deployment
  - Cross-cutting concerns: where they enter the system

- **`./docs/CONVENTIONS.md`** — Code style, patterns, file organization

## Phase 3 — Generate Dynamic Layer
These docs change every session.

- **`./docs/active-context.md`** — Current execution state:
  - What is built and working
  - What is in progress
  - Immediate next steps
  - Known issues or tech debt

- **`./docs/quality-grades.md`** — Per-module assessment:
  - Test coverage (high/medium/low/none)
  - Documentation completeness
  - Architectural conformance
  - Known gaps

- **`./docs/execution-plans/`** — One file per active workstream:
  ```
  # [Plan Name]
  status: active | completed | paused
  ## Goal
  ## Steps
  - [ ] Step 1
  ## Decisions Made
  ## Open Questions
  ```

## Principles
- All docs are declarative, present-tense, living documents.
- No changelogs, no past tense, no "we decided to." State what *is*.
- Reconsolidate, don't accumulate — when updating, merge knowledge, don't append.
- The index (`CLAUDE.md`) is the boundary marker between static and dynamic.

## Output
`Harness migration complete. Generated: CLAUDE.md, system-rules.md, ARCHITECTURE.md, CONVENTIONS.md, active-context.md, quality-grades.md, execution-plans/. [N discrepancies found between old docs and code — see flagged items.]`