# Swarm Instructions: Von Neumann Memory Architecture Design

## Recommended Command

```bash
npx claude-flow@alpha swarm "$(cat <<'EOF'

## OBJECTIVE
Design the implementation plan for Zylch's Von Neumann Memory Architecture.
This is a DESIGN task - produce detailed specifications, NOT code.

## CONTEXT
Zylch is an AI email assistant. We are refactoring the data architecture to follow
the Von Neumann model:
- MEMORY (mass storage) = accumulated knowledge, the past
- WORKING MEMORY/CRM (registers) = computed state, the present

### New Architecture Flow
1. **Email arrives** → triggers Memory Agent (memory_worker.py)
2. **Memory Agent** → extracts facts/knowledge → writes to Memory table
3. **CRM Agent** (crm_worker.py) → reads Memory + email_archive → computes Avatar state
4. **Avatar state** → stored in avatars table (Working Memory/CRM)

This replaces the old direct Email → Avatar computation pattern.

## REFERENCE FILES (READ THESE FIRST)
1. Architecture overview: docs/architecture/VON_NEUMANN_MEMORY.md
2. Current architecture: .claude/ARCHITECTURE.md
3. Current memory system: zylch_memory/zylch_memory/core.py
4. Memory Agent worker: zylch/workers/memory_worker.py
5. CRM Agent worker: zylch/workers/crm_worker.py
6. Memory documentation: docs/features/entity-memory-system.md
7. Avatar documentation: docs/features/avatar-aggregation.md

## DELIVERABLES

### Agent 1 (Architect): Memory Agent Design
Design the Memory Agent that extracts knowledge from I/O and writes to Memory.
Produce:
- Input specification (what data sources)
- Output specification (what gets stored in Memory, schema)
- Extraction rules (what facts to extract from emails)
- Owner profile detection (how to learn owner's language, style)
- Trigger mechanism (when does it run)

### Agent 2 (Architect): CRM Agent Design
Design the CRM Agent that reads Memory and computes Working Memory state.
Produce:
- Input specification (Memory queries + email_archive timestamps)
- Output specification (avatars table schema updates)
- Status computation logic (open/waiting/closed rules)
- Priority computation logic (1-10 scoring algorithm)
- Action generation logic (suggested next steps)

### Agent 3 (Analyst): Migration Path
Analyze the current implementation and design migration path.
Produce:
- Current flow analysis (how data flows today)
- Breaking changes identification
- Migration steps (phase by phase)
- Backward compatibility considerations
- Testing strategy

### Agent 4 (Coordinator): Integration Design
Design how Memory Agent and CRM Agent coordinate.
Produce:
- Trigger sequence (which agent runs when)
- Error handling (what if Memory Agent fails)
- Performance considerations (batch vs real-time)
- Sync command integration (/sync flow)
- API integration (how HTTP endpoints use the new architecture)

## CONSTRAINTS
- Memory table schema exists (see memories table in Supabase)
- Avatars table schema exists (see avatars table in Supabase)
- Must maintain backward compatibility with existing /sync, /gaps commands
- LLM calls should be minimized (expensive)
- Owner uses Firebase Auth (owner_id is Firebase UID)

## OUTPUT FORMAT
Each agent produces a markdown document with:
1. Summary (3-5 sentences)
2. Detailed design (with diagrams if helpful)
3. Open questions
4. Dependencies on other agents' work

Final coordinator synthesizes into single implementation plan.

EOF
)" --strategy research --max-agents 4 --analysis --monitor
```

## Why These Options

| Option | Value | Rationale |
|--------|-------|-----------|
| `--strategy` | `research` | This is architectural design, not development |
| `--max-agents` | `4` | One per deliverable: Memory Agent, CRM Agent, Migration, Integration |
| `--analysis` | flag | Read-only mode - we're designing, not coding |
| `--monitor` | flag | Track progress in real-time |

## Alternative: Simpler 2-Agent Version

If 4 agents feels like overkill:

```bash
npx claude-flow@alpha swarm "$(cat <<'EOF'

## OBJECTIVE
Design Von Neumann Memory Architecture for Zylch.

## REFERENCE FILES
- docs/architecture/VON_NEUMANN_MEMORY.md (START HERE)
- .claude/ARCHITECTURE.md
- zylch_memory/zylch_memory/core.py
- zylch/workers/memory_worker.py (Memory Agent)
- zylch/workers/crm_worker.py (CRM Agent)

## DELIVERABLES

### Agent 1: Architecture Design
Design Memory Agent + CRM Agent specifications.
- What each agent extracts/computes
- Schemas and data flow
- LLM prompt templates

### Agent 2: Migration Plan
How to refactor current implementation.
- Current vs proposed flow
- Migration phases
- Testing approach

## CONSTRAINTS
- Backward compatible with /sync, /gaps
- Minimize LLM calls
- Use existing Memory and Avatar tables

EOF
)" --strategy research --max-agents 2 --analysis --monitor
```

## Expected Output

The swarm should produce:

1. **Memory Agent Specification** (memory_worker.py)
   - Extraction rules for emails
   - Memory namespace strategy per contact
   - Owner profile detection approach
   - What facts to store in Memory table

2. **CRM Agent Specification** (crm_worker.py)
   - Status/priority computation algorithms
   - Memory query patterns (how to read from Memory table)
   - Avatar update strategy (how to compute Working Memory state)
   - email_archive timestamp integration

3. **Migration Plan**
   - Phased approach to refactoring from old avatar_compute_worker.py
   - What code changes where (memory_worker.py + crm_worker.py)
   - Testing checkpoints
   - Backward compatibility with existing Avatar aggregation

4. **Integration Design**
   - `/sync` command new flow (Memory Agent → CRM Agent sequence)
   - API endpoint changes
   - Error handling
   - Trigger coordination between Memory Agent and CRM Agent

## Post-Swarm Steps

After the swarm completes:

1. Review the generated design documents
2. Clarify any open questions
3. Create implementation tasks (separate swarm with `--strategy development`)
4. Implement phase by phase

## Notes

- The `--analysis` flag ensures agents only read files, no modifications
- Strategy `research` optimizes for exploration and synthesis
- Monitor mode shows real-time progress in terminal
