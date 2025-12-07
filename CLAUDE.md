# Zylch Development - Claude Configuration

## 🎯 What Zylch Is

**Zylch is a research lab building relational memory infrastructure, with a commercial product as bridge to sustainability.**

The thesis: LLMs are perfect for relational intelligence because professional relationships are already encoded in language. LeCun is right about world models for physical intelligence, but the "world of professional relationships" is already made of text. The missing piece is persistent relational memory — that's what Zylch builds.

**Core architecture concepts:**
- **Avatar**: A vector-based representation of a person, built from interaction history
- **Small-world topology**: Retrieval optimized for relational networks
- **Reconsolidation**: Similar memories update (not duplicate), mimicking human memory
- **Shareable avatars**: When employees leave, relational knowledge stays

The commercial product (email/phone/WhatsApp assistant) generates revenue and data. The research bet is avatar architecture ready for continuous training when LLMs support it (3-5 year horizon).

---

## 🚨 Critical Rules

### NO LOCAL FILESYSTEM - DATABASE ONLY

**CRITICAL: The backend uses Supabase for ALL data storage. NO local filesystem.**

- **OAuth tokens** → Supabase `oauth_tokens` table (encrypted)
- **Email metadata** → Supabase `thread_analysis` table
- **User data** → Supabase (scoped by `owner_id`)
- **Memory/Avatars** → Supabase pg_vector

**NEVER:**
- Store tokens in local files
- Use pickle files on filesystem
- Reference `credentials/` directory for runtime data
- Fall back to filesystem storage

**The `credentials/` and `cache/` directories are LEGACY and UNUSED.**

### Execution Rules

**NEVER ask questions about methodology or approach. Execute immediately.**

When user says:
- "Initialize hive-mind" → Query memory, read context, start execution
- "Resume hive-mind" → Load namespace memory, continue work
- "Use swarm" → Execute with claude-flow swarm
- Any explicit instruction → Execute immediately, no questions

---

## 🐝 Claude-Flow Integration

**This project uses claude-flow for orchestration:**
- Memory stored in `.swarm/memory.db`
- Namespace isolation (zylch, zylch-frontend, zylch-deploy, etc.)
- MCP tools: `swarm_init`, `agent_spawn`, `task_orchestrate`, `memory_usage`
- Always query relevant namespaces BEFORE starting work
- Always store decisions/implementations in specified namespace AFTER work

**Memory Query Pattern:**
```bash
# Before any task:
1. Query namespace memory for context
2. Read relevant docs if mentioned
3. Execute task
4. Store results in namespace
```

---

## 📁 File Organization

**NEVER save to root directory.**

| Directory | Purpose |
|-----------|---------|
| `/src`, `/zylch` | Backend Python code |
| `/zylch_memory` | Avatar/memory system (core research) |
| `/frontend` | Vue.js dashboard |
| `/tests` | Test files |
| `/docs` | User documentation |
| `/spec` | Technical specifications, business model |
| `/scripts` | Utility scripts |
| `/.claude` | Architecture, development plan, conventions |

---

## 🔄 Technology Stack

**Backend:**
- Python 3.11+, FastAPI, async throughout
- Supabase Postgres (all server data)
- Firebase Auth (multi-tenant, Google/Microsoft OAuth)
- Anthropic Claude (Haiku/Sonnet/Opus tiering)
- Railway hosting (api.zylchai.com)

**Frontend:**
- Vue 3, Vite, TypeScript, Pinia, TailwindCSS
- Axios → Backend FastAPI
- Vercel hosting (app.zylchai.com)

**Email Storage (Local-First, like Superhuman):**
- IndexedDB (browser) — encrypted with Web Crypto API (AES-GCM 256-bit)
- Email content NEVER on Zylch servers
- Only AI summaries stored in Supabase

**Avatar/Memory Architecture:**
- Supabase pg_vector + sentence-transformers
- Small-world topology for retrieval
- Reconsolidation (update, not duplicate)
- Namespace isolation per person/entity

**Integrations:**
- Gmail & Outlook (OAuth 2.0)
- Google & Outlook Calendar
- StarChat/MrCall (contacts, telephony)
- SendGrid (email campaigns), Vonage (SMS)

---

## 🎯 Hive-Mind Namespaces

| Namespace | Purpose | Key Files |
|-----------|---------|-----------|
| `zylch` | Backend, API, planning, research, execution | `/zylch`, `/.claude`, `/spec` |
| `zylch-cli` | CLI thin client | `/zylch-cli` (separate repo) |
| `zylch-frontend` | Vue dashboard | `/frontend` |
| `zylch-memory` | Avatar architecture research | `/zylch_memory` |
| `zylch-deploy` | Deployment configs | `/docs/DEPLOYMENT.md` |

---

## 💡 Quick Commands Reference
```bash
# Memory operations
npx claude-flow@alpha memory query "[topic]" --namespace [ns]
npx claude-flow@alpha memory list --namespace [ns]
npx claude-flow@alpha memory status

# Hive-mind operations
npx claude-flow@alpha hive-mind status
npx claude-flow@alpha hive-mind spawn "[task]" --claude
```

---

## 🐛 Common Tasks

### Debug Session
When user says "debug" or reports bugs:
1. Query memory: `zylch`, `zylch-frontend`
2. Read `./frontend/ARCHITECTURE.md` if frontend issue
3. For each bug: Analyze → Propose → Get approval → Fix → Test
4. Store patterns in `zylch-frontend-debug` namespace

### Execute Development Plan
When user references DEVELOPMENT_PLAN.md:
1. Query memory: `zylch`
2. Read `.claude/DEVELOPMENT_PLAN.md`
3. Assess current status from memory
4. Prioritize and get approval
5. Execute approved phases
6. Store progress in `zylch` namespace

### Deploy Task
When user mentions deployment:
1. Query memory: `zylch`, `zylch-deploy`
2. Read deployment docs
3. Plan infrastructure
4. Execute deployment steps
5. Store config in `zylch-deploy` namespace

### Research/Architecture Work
When user discusses vision, avatars, memory architecture:
1. Query memory: `zylch`, `zylch-memory`
2. Read `/spec/ZYLCH_BUSINESS_MODEL.md` and `/.claude/ARCHITECTURE.md`
3. Ensure changes align with strategic vision (research lab, not SaaS)
4. Store decisions in `zylch` namespace

### Planning Session
When user discusses roadmap, priorities, or says "planning":
1. Query memory: `zylch`
2. Read `/.claude/DEVELOPMENT_PLAN.md` and `/spec/ZYLCH_BUSINESS_MODEL.md`
3. Assess: what's done, what's blocked, what's next
4. Propose prioritized plan with rationale
5. After approval, update `DEVELOPMENT_PLAN.md`
6. Store decisions in `zylch` namespace

### Architecture Review
When user discusses system design, memory system, or avatars:
1. Query memory: `zylch`, `zylch-memory`
2. Read `/.claude/ARCHITECTURE.md` and `/zylch_memory/README.md`
3. Validate changes against strategic vision (avatar architecture, not just features)
4. Update `ARCHITECTURE.md` if structural decisions made
5. Store rationale in `zylch-memory` namespace

### Business Model / Investor Prep
When user discusses pitch, investors, funding, or business:
1. Query memory: `zylch`
2. Read `/spec/ZYLCH_BUSINESS_MODEL.md`
3. Search web if needed (market data, competitor analysis, LLM trends)
4. Ensure framing is "research lab with commercial bridge", not "SaaS startup"
5. Store insights in `zylch` namespace

### Documentation Update
When user says "update docs" or documentation is stale:
1. Query memory: `zylch`
2. Read `/.claude/DOCUMENTATION.md` for standards
3. Identify gaps between code and docs
4. Update relevant docs in `/docs` (user-facing) or `/.claude` (developer)
5. Store what was updated in `zylch` namespace

### Full Sync / Status Report
When user says "status", "where are we", or "sync":
1. Query namespaces: `zylch`, `zylch-frontend`, `zylch-cli`, `zylch-deploy`
2. Read `DEVELOPMENT_PLAN.md` for milestones
3. Compile: completed phases, current blockers, next priorities
4. Output concise status report
5. No storage needed (read-only task)

### New Feature Implementation
When user requests a new feature:
1. Query memory: `zylch`
2. Check if feature aligns with `DEVELOPMENT_PLAN.md` phases
3. If not in plan: flag and ask if it should be added
4. Implement following patterns in `/.claude/CONVENTIONS.md`
5. Store implementation decisions in `zylch` namespace

### Memory/Avatar System Work
When user specifically works on memory, avatars, or reconsolidation:
1. Query memory: `zylch`, `zylch-memory`
2. Read `/zylch_memory/ZYLCH_MEMORY_ARCHITECTURE.md`
3. This is core research — document WHY, not just WHAT
4. Ensure small-world topology and reconsolidation principles preserved
5. Store architectural decisions in `zylch-memory` namespace
6. Update `/.claude/ARCHITECTURE.md` "Memory System Philosophy" section

### Integration Work (MrCall, StarChat, external APIs)
When user works on external integrations:
1. Query memory: `zylch`, `zylch-deploy`
2. Read relevant tool files in `/zylch/tools/`
3. Check `/spec` for integration requirements
4. Follow security rules: NEVER bypass authentication, ALWAYS use REST APIs
5. Store integration patterns in `zylch` namespace

### CLI Development
When user works on CLI (zylch-cli):
1. Query memory: `zylch-cli`, `zylch`
2. Remember: CLI is a **thin client** - all business logic is on the server
3. CLI only handles: UI rendering, local auth, HTTP calls to API
4. OAuth tokens stored in Supabase (not local filesystem)
5. Store CLI patterns in `zylch-cli` namespace

**CLI Commands:**
- `--login`, `--logout`, `--status`: Firebase authentication
- `--chat`: Interactive chat mode with server
- `/connect google`: Connect Google OAuth for Gmail/Calendar API
- `/connect --reset`: Disconnect all integrations

**CLI Architecture:**
- Location: `/zylch-cli/` (separate directory)
- Config: `~/.zylch/cli_config.json`
- API server: `https://api.zylchai.com`

---

## 🌐 Production URLs

| Service | URL |
|---------|-----|
| Frontend | https://app.zylchai.com |
| Backend API | https://api.zylchai.com |
| Website | https://zylchai.com |

---

**Remember: Execute immediately. Query memory first. Store results after. Align with research vision.**