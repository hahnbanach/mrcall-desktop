<!-- mrcall-ai-kit:delivery:start -->
## Documentation lifecycle (harness v9)
This repository's managed protocol lives here in AGENTS.md; no CLAUDE.md read is
required. Use this v9 entry instead of any older kit instruction to load CLAUDE.md.
When repository `.agents/skills/` provides doc-start/doc-end/doc-critic, load those
copies; do not select same-named older global workflows.

The lead, before source reads, searches, diagnosis, edits, or delegation for ANY repository
request (including questions, fast-path fixes, briefs, and reviews), invoke
`doc-start`: load its current workflow and execute it. The lead personally reads
AGENTS.md, docs/README.md, docs/active-context.md, and relevant durable docs in full.
Reuse exact documents already present in context. Bounded installation/profile
checks may precede orientation; source exploration may not. Reload affected
orientation after repository/worktree/instruction changes or context loss, not
ordinary source edits. Never substitute a worker summary for these lead reads.
Workers use the lead's scoped handoff; reload only required context they lack.

Act as the senior engineer and project manager reporting to the human CTO.
Resolve routine reversible decisions from evidence; deliver verified outcomes.
Ask only for unresolved intent, authority, material risk, or irreversible/external
action. Match effort to risk; fix in-scope problems. Delegate bounded substantive
work only when its parallelism, expertise, or isolation exceeds coordination cost.

Classify the request and preserve its scope:
- Explanation/read-only diagnosis: orient, investigate, answer with uncertainty;
  no required edits, trace, consolidation, baseline advancement, or release.
- Brief-only/review-only: orient and deliver only the requested artifact/verdict;
  no automatic plan, implementation, migration, baseline advancement, or release.
- Fast path requires ALL: local, obvious, reversible; no public contract, behavior
  boundary, persistent data, security, dependency graph, or migration change;
  no decomposition/delegation; one focused real check proves it. Implement and
  check; state documentation impact. If none, justify it. If docs are affected,
  invoke `doc-end` for proportionate reconciliation and verification.
- Documentation-only: invoke `doc-end` before completion, including lead-owned
  reconciliation, mechanical gate, `doc-critic`, and living-context shape check.
- Substantial development: follow the ordered reviews below, then `doc-end`
  before final approval. Generic code review never substitutes for `doc-critic`.

Substantial work starts with docs/briefs/YYYY-MM-DD-<slug>.md (intent, scope,
constraints, acceptance, assumptions) and then docs/execution-plans/YYYY-MM-DD-<slug>.md
(status frontmatter, dependencies, ownership, verification, relevant rollback).
Order: brief → fresh reviewer APPROVED → plan → fresh reviewer APPROVED →
implementation → milestone integration review before dependent work → separate
final review through the final-user path. Review the brief's framing first.
Repair REVISE with the same reviewer; use a fresh reviewer for each new gate.
Verdicts: APPROVED, REVISE, FAST_PATH (prove every criterion), BLOCKED (unresolved
intent/risk/authority). Reviews are internal gates, not human approval prompts.
Relay each verdict and its evidence in your own words; never paste the report.
Without fresh-review capability, perform a separate pass and report the limitation.

Closure: the lead identifies affected docs, including unchanged docs and missing
coverage; reconciles current knowledge; preserves historical narrative verbatim
in docs/active-context-archive.md; runs the mechanical gate and explicitly invokes
`doc-critic` over affected docs plus active-context shape even when untouched.
Repair STALE, preserve UNVERIFIABLE, and recheck affected changes. Final review
must REVISE missing/stale required evidence. For applicable closure, use
`doc-check.py --completion check`, then `--completion finalize` for baseline.
Fast-path no-impact closure stays proportionate; release needs authorization.
Keep actual result references and pending obligations across delegation/resumption;
attestations and mechanical success alone do not prove semantic or runtime enforcement.
<!-- mrcall-ai-kit:delivery:end -->

# AGENTS.md

**Stack**: Electron + React (app), Python 3.11+ (engine), SQLite
**Entry point**: `engine/` (Python sidecar) and `app/` (Electron + React) — each has its own CLAUDE.md
**Do not break**: The Firebase ID token is never persisted to disk; profiles are keyed by the immutable Firebase UID (`~/.zylch/profiles/<firebase_uid>/`), never by email; the company memory key (`MEMORY_KEY`) is a capability — never logged, never in git, written only by `memory.join`

<!-- orientation ends -->

<!-- doc-scope:start -->
Scope: the thin index of this monorepo — what each of the three trees owns, and
the cross-cutting facts a session needs before it routes anywhere (identity,
LLM billing modes, the naming rename in flight). Engine detail is
[`engine/CLAUDE.md`](engine/CLAUDE.md), app detail
[`app/CLAUDE.md`](app/CLAUDE.md), cross-cutting volatile state
[`docs/active-context.md`](docs/active-context.md).
<!-- doc-scope:end -->

**MrCall Desktop** — local AI assistant for business communication. This is a **monorepo**: a Python sidecar (the engine) and an Electron + React frontend (the app), shipped together as a single desktop application for macOS and Windows.

## Operator versus engine AI

Claude Code headless (`claude -p "/cs-operator"`) runs in a cs-kernel clone,
not in this engine. Desktop Settings selects **engine API** models and billing;
its daily budget does not cover Claude Code reasoning or kernel direct API
classifiers. Engine preparation pause and clone `CS_PAUSE` are different.
See [execution, billing and pause boundaries](docs/operator-setup.md#ai-execution-and-controls).

## Layout

| Path | What | Owns |
|------|------|------|
| `engine/` | Python 3.11+ sidecar — IMAP / SMTP, WhatsApp (neonize), MrCall phone, company memory (one SQLite store per memory key), hybrid search, local SQLite profile store. | The `zylch` CLI binary, the on-disk profile directory, all business logic. |
| `app/` | Electron + React frontend that embeds the engine via JSON-RPC over stdio. Three views: chat, tasks, emails. | The desktop UI, packaging via `electron-builder`, GitHub release pipeline. |
| `docs/` | Monorepo-wide docs: things that span engine ↔ app or describe the repo as a whole. | Cross-cutting decisions, release process, IPC contracts. |

Each subdir has its own `CLAUDE.md` and `docs/` (mirroring the three-tree
structure). Read those for details:

- [`engine/CLAUDE.md`](engine/CLAUDE.md) + [`engine/docs/`](engine/docs/) — engine doc index, install, channel matrix, critical rules.
- [`engine/docs/active-context.md`](engine/docs/active-context.md) — **freshest source** for what's working / in-flight on the engine side.
- [`app/CLAUDE.md`](app/CLAUDE.md) + [`app/docs/`](app/docs/) — Electron layout, dev workflow, packaging.
- [`docs/`](docs/) — cross-cutting docs: IPC contract, release pipeline, brand/rename rollout.

## Cross-cutting runtime contracts

[Identity, company memory, hosted isolation and LLM billing](docs/cross-cutting-contracts.md)
carry the detailed contracts and historical migration notes. Read the relevant
section before changing these boundaries. Firebase tokens stay in memory;
profile identity is the immutable UID; company memory access requires its
capability key. Provider selection never falls back, and paid requests reserve
their maximum cost against the saved daily budget before dispatch.

## Naming and identifiers — the rename in flight

This monorepo was assembled by subtree-merging two predecessor repos
(`example-owner/zylch` and `example-owner/zylch-desktop`, now private/archived). Until
the planned rename completes, the engine still uses **`zylch`** as its
internal identifier in many places:

- Python package: `zylch.*`
- CLI binary: `zylch`
- Data directory: `~/.zylch/profiles/<firebase_uid>/`
- Env var prefix: `ZYLCH_*`

Treat these as synonyms for `mrcall` until the rename PR lands. Don't
re-introduce `zylch` strings in **new** code or docs; mention `mrcall`
where natural and leave existing `zylch` references for the dedicated
sweep.

## Memory discipline

Claude Code keeps a per-user, per-machine memory at
`~/.claude/projects/<encoded-path>/memory/`. **It is not in git, not
shared with the team, not portable.** The project's source of truth is
this `AGENTS.md`, the per-subdir `CLAUDE.md` files, and the docs under
`docs/` and `engine/docs/`.

Rules for any agent working in this repo:

- **Project knowledge → in git.** Architecture, decisions, current
  state, rules: write or edit a doc under `docs/` (cross-cutting) or
  `engine/docs/` (engine-specific). Propose the change to the user; do
  not silently auto-save it to your local CC memory under a `project`
  or `reference` type.
- **`engine/docs/active-context.md` is the freshest source** for
  engine-side state. It overrides anything in older strategy /
  business-model files when they disagree.
- **Personal notes → CC memory.** User preferences, working-style
  feedback, your own session-local recall — these are appropriate for
  `~/.claude/.../memory/` because they're per-developer.
- **Before quoting CC memory**, verify against the current state of the
  repo. Memory can be stale; the repo cannot.

## Quick reference

```bash
# Engine — see engine/CLAUDE.md for the full set
cd engine
pip install -e .                  # dev install
zylch -p user@example.com update  # sync + analyze + detect tasks
zylch -p user@example.com         # interactive REPL

# App — see app/CLAUDE.md for full dev / packaging
cd app
npm ci
npm run dev                       # hot-reload, expects engine sidecar at ZYLCH_BINARY
npm run dist:mac                  # produce .dmg
```

## License

MIT. See [`LICENSE`](LICENSE).
