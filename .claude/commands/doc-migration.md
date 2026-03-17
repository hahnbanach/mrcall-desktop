---
description: Migrate Documentation to Harness Structure
---
1. **Inventory existing knowledge.** Read any existing `./docs/*.md`, `./CLAUDE.md`, `./AGENTS.md`, `README.md`, and inline code comments that describe architecture or conventions.
2. **Ground truth from code.** Scan source directories (`src/`, `lib/`, `app/`, etc.) and configuration files (`package.json`, `build.sbt`, `docker-compose.yml`, `Makefile`, etc.) to understand the *actual* implementation — modules, dependencies, layering, data shapes, infrastructure.
3. **Resolve conflicts.** Where documentation contradicts the code, the code wins. Flag discrepancies in the output.
4. **Generate the harness documentation structure:**

   - **`./CLAUDE.md`** (or `./AGENTS.md`): The table of contents. Max ~100 lines. Contains:
     - One-sentence project description
     - Pointers to every doc in `./docs/` with a one-line summary of each
     - Quick-reference: how to build, test, lint, run
     - Do NOT put rules or architecture details here — only pointers

   - **`./docs/system-rules.md`**: Extract and codify:
     - Tech stack, language version, key libraries
     - Coding standards observed in the actual codebase (naming, patterns, error handling)
     - Formatting and style rules (what a linter would enforce)
     - Dependency rules: which modules/layers can import from which (if detectable)
     - Rules the agent must never violate, stated as imperatives

   - **`./docs/architecture.md`**: Document based on how the code *is*, not how it was imagined:
     - High-level system map: modules/packages, their responsibilities, their boundaries
     - Dependency direction (e.g., Types → Config → Repo → Service → Runtime → UI)
     - Data flow: how requests/data move through the system
     - Infrastructure: databases, queues, external services, deployment topology
     - Cross-cutting concerns: auth, telemetry, feature flags — where they enter the system

   - **`./docs/active-context.md`**: Current project state:
     - What is built and working
     - What is in progress
     - Immediate next steps
     - Known issues or tech debt

   - **`./docs/quality-grades.md`**: For each major module/domain, assess:
     - Test coverage (high/medium/low/none)
     - Documentation completeness
     - Architectural conformance
     - Known gaps

   - **`./docs/execution-plans/`**: Create the directory. If there is active work in progress, create one plan file per workstream using the template:
     ```
     # [Plan Name]
     status: active | completed | paused
     ## Goal
     ## Steps
     - [ ] Step 1
     - [ ] Step 2
     ## Decisions Made
     ## Open Questions
     ```

5. **Tone and format.** All docs are declarative, present-tense, living documents. No changelogs, no past tense, no "we decided to." State what *is*.
6. Output:
   `Harness migration complete. Generated: CLAUDE.md, system-rules.md, architecture.md, active-context.md, quality-grades.md, execution-plans/. [N discrepancies found between old docs and code — see flagged items.]`