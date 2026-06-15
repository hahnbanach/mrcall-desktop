---
description: |
  Analisi di come la Claude Agent SDK di Anthropic (Python) possa
  essere applicata a mrcall-desktop. Confronta primitive dell'SDK
  con l'architettura corrente dell'engine (loop agentico, tool
  framework, memory, workers, slash commands, sessione chat),
  identifica vincoli (transport proxy con auth Firebase JWT) e
  propone un ordine d'attacco per gradi.
status: analysis
created: 2026-05-08
---

# Claude Agent SDK — analisi per mrcall-desktop

## TL;DR strategico

La Claude Agent SDK è progettata per girare contro `api.anthropic.com`
con auth standard `x-api-key`. **Non supporta nativamente l'header
`auth: <jwt>` del nostro `MrCallProxyClient`** — `ANTHROPIC_BASE_URL`
ridireziona l'URL ma non cambia la forma dell'auth. Questo è il
vincolo che governa ogni decisione: l'SDK come runtime end-to-end è
adottabile solo per la modalità BYOK
(`engine/zylch/llm/client.py:309 make_llm_client` ramo `direct`); la
modalità credits passa per `mrcall-agent` ed è incompatibile a meno
di interventi server-side.

Quindi il "salto di qualità" non è "passiamo all'Agent SDK". È
**selezionare con criterio i 4-5 primitive dell'SDK che pagano di
più anche a runtime nostro**, applicarli dove l'engine oggi reinventa
o sottoperforma, e tenere d'occhio un percorso di migrazione del
proxy che renda l'SDK adottabile come runtime per entrambi i
transport.

## Mappa attuale (le pezze dolenti)

| Area | Stato oggi | File chiave |
|---|---|---|
| Loop agentico chat | Riscritto a mano, ~500 righe | `assistant/core.py:121-291` (`ZylchAIAgent.process_message`) |
| Compaction | Custom Haiku-driven, soglia 80k token, KEEP_FIRST=1/KEEP_RECENT=10 | `services/chat_compaction.py` |
| Tool framework | ABC custom (`Tool`/`ToolResult`/`ToolStatus`), ~40 tool registrati | `tools/base.py:36`, `tools/factory.py:90` |
| "Sub-agenti" | `EmailerAgent`, `TaskOrchestratorAgent` rotolati a mano; orchestrator chiama via `call_agent` tool | `agents/base_agent.py:22`, `agents/task_orchestrator_agent.py` |
| Memoria | Sistema sofisticato sentence-level + embeddings + hybrid search + identifier-based reconsolidation | `memory/blob_storage.py`, `memory/hybrid_search.py:50` |
| Tool memoria per LLM | Coppia create/update/search guidata dall'LLM (post commit `0b9e4e8`) | `tools/{create,update}_memory_tool.py`, `tools/contact_tools.py:SearchLocalMemoryTool` |
| Hook lifecycle | **Nessuno**. Logging via `logger.debug`, approval via callback hardcoded `APPROVAL_TOOLS` | `assistant/core.py` |
| Sessione chat | **In-memory only**. Sidecar restart = storia persa | `services/chat_session.py:33` |
| Slash commands | Imperativo, dispatch string/embedding match, ~50 comandi in 4400 righe | `services/command_handlers.py:4282 COMMAND_PATTERNS` |
| Workers offline (memory/task) | LLM 1-shot per email, gestione errori swallow, no retry/backoff esplicito, no Batch API | `workers/memory.py`, `workers/task_creation.py` |
| F9 topic dedup | One Opus call con TUTTI i task attivi (~$0.30/run) | `workers/task_topic_dedup.py` |
| Background scheduling | **Nessuno schedulatore in-process**; tutto driven da RPC `update.run` | — |
| Citazioni / provenance | Ad-hoc nei prompt, non strutturate | — |
| Extended thinking | Non usato | — |
| Prompt caching | Sì, applicato a mano in `core.py:188` | — |

## Cosa offre l'Agent SDK e dove combaciare

Ordino per **leverage / costo di integrazione**, non per "ordine
logico".

### Tier 1 — vincite alte, costo basso, compatibili con il transport corrente

**1. Hook system (anche minimale).** `PreToolUse / PostToolUse /
SessionStart / SessionEnd / UserPromptSubmit / Stop` con valori di
ritorno `PermissionResultAllow|Deny`. Oggi `core.py:226-291` mescola
tool_use loop, controlli di approval (`APPROVAL_TOOLS` hardcoded),
logging e `DIRECT_RESPONSE_TOOLS` short-circuit. Estraggo
un'astrazione hook minima (anche solo registry interno, non l'intera
SDK) e:

- pre-tool log strutturato (input/output/latency) → sostituisce
  decine di `logger.debug` sparsi
- pre-tool permission gate → rimpiazza l'`if tool.name in
  APPROVAL_TOOLS` cablato
- post-tool retry/circuit-breaker per tool flaky (IMAP, StarChat)
- on-stop → persistenza chat in SQLite (vedi punto 3)
- pre-model-call → injection di "now()" e USER_NOTES *fuori* dal
  cache breakpoint, non *dentro* (oggi `core.py:196-198` lo fa già
  ma il pattern è sparso)

Niente runtime SDK richiesto. È solo prendere il pattern.

**2. Memory tool di Anthropic (complementare, non sostitutivo).**
L'SDK espone un tool `memory` con
`view/create/str_replace/insert/delete/rename` su una directory
`/memories`. La nostra memoria sentence-level + hybrid search +
identifier-based reconsolidation (post `3a88e96`) è **più
sofisticata** per l'estrazione automatica di entità — non va toccata.
Ma copre male un altro caso d'uso, oggi servito malamente da
`USER_NOTES` iniettato nel system prompt:

- preferenze ("Mario vuole risposte terse, niente footer")
- note operative dell'assistente ("ho già scritto a Salamone due
  volte; se arriva un terzo missed call, segnalarlo")
- stato di un task in corso multi-turn ("sto risolvendo task X, ho
  già provato Y")

Questo è memoria *che l'LLM scrive a sé stesso*, non estratta da
email. Aggiungere un secondo tool memoria — file in
`~/.zylch/profiles/<uid>/memories/` — risolverebbe il limite del
prompt-injection statico. Implementabile in 1 PR con i pattern
dell'SDK senza adottare l'SDK.

**3. Persistenza sessione su SQLite.** `services/chat_session.py:33`
è un dataclass in memoria. SDK persiste sessioni come JSONL. Per noi:

- nuovo modello `ChatSession`/`ChatMessage` in `storage/models.py`
- chat sopravvive a restart sidecar
- l'utente può scorrere conversazioni passate
- diventa training data per future trainer (`agents/trainers/*`)
- la Renderer IndexedDB (per-window) non è un sostituto: non è
  per-profilo, non è LLM-readable, non sopravvive a un nuovo Mac

L'`IdentityBanner` (`bc011be`) ha già reso esplicito *quale*
identità sta scrivendo; manca solo *dove* finisce quello che scrive.

**4. Skills system per i comandi user-defined.**
`command_handlers.py` a 4400 righe ha 50+ comandi imperativi.
Pattern SDK:

```
~/.zylch/profiles/<uid>/skills/
  digest/SKILL.md          # name, description, instructions
  follow-up/SKILL.md
  unsubscribe/SKILL.md
```

Ogni skill è una procedura invocabile via `/digest`, `/follow-up`,
`/unsubscribe`. Vantaggio non è solo riduzione di righe: è che
**l'utente** (o il futuro-Mario) aggiunge comandi senza toccare
codice. Mette anche fine a una catena di duplicazioni nel codice
quando un comando deve avere varianti per profilo.

### Tier 2 — vincite specifiche su pipeline esistenti

**5. Extended thinking sui call ad alto stake.** F9 topic dedup, F4
reanalyze sweep, LLM merge in `memory/llm_merge.py` — sono
ragionamenti, non azioni. SDK espone
`thinking={"type":"enabled","budget_tokens":N}`. Su F9 (cluster di
task da chiudere o tenere) il guadagno atteso è netto: oggi Opus 4.6
in single-shot decide chiudere/tenere su 30+ task e a volte ne spara
fuori uno troppo aggressivamente (vedi
`engine/docs/active-context.md` "F9 cross-contact topic dedup").
Thinking budget 5-10k token su quei call vale i token spesi.

**6. Batch API per il memory worker.** `workers/memory.py` chiama
l'LLM una volta per email; il run di `update` su un nuovo profilo fa
200+ call sequenziali. Anthropic Batch: 50% costo, async, perfetto
per workload offline. Non è esposto direttamente dall'SDK ma il
pattern è banale sull'SDK Anthropic bare. Su un primo `update` da
200 email il risparmio cassa a vista è metà del costo memory phase.

**7. Subagent-style decomposition di pipeline che oggi sono un fat
call.** L'SDK ha la `AgentDefinition` per delegare a subagent
isolati con system prompt/tool subset propri. Anche senza adottare
l'SDK il *pattern* paga su:

- F9 topic dedup: invece di "manda 30 task in un unico prompt",
  separa **clusterer-subagent** (raggruppa per topic) →
  **arbiter-subagent per cluster** (chi è il keeper?) →
  **auditor** (sanity check sui chiusi). Più context isolato per
  decisione, meno cross-contamination, meglio testabile.
- TaskOrchestratorAgent: già fa una cosa simile ma rotola la
  propria infrastruttura (`agents/task_orchestrator_agent.py:74`
  tiene la "agent capabilities prompt" hardcoded). Andrebbe
  rifattorizzato sul pattern SDK anche se non si adotta il runtime.
- Memory reconsolidation merge (`memory/llm_merge.py`): un subagent
  dedicato con tool subset solo "leggi blob X, leggi blob Y, propone
  merge".

### Tier 3 — vincite grosse ma con prerequisiti

**8. MCP — server bridge in entrambe le direzioni.** Questa è
strategica e merita il suo peso:

- **Outbound** (mrcall-desktop come MCP client di server esterni):
  l'utente collega Notion / Linear / Jira / GitHub / Slack via MCP.
  Tutti i tool di quei sistemi diventano disponibili nel chat
  assistant senza scrivere custom tool wrapper come oggi facciamo
  con Pipedrive (`tools/pipedrive.py`) e StarChat
  (`tools/starchat.py`). Per ogni nuova integrazione il delta di
  codice diventa "registra un MCP server", non "scrivi 200 righe di
  tool wrapper".

- **Inbound** (mrcall-desktop come MCP server): espone email
  search, task list, memory search, calendar come MCP server stdio
  sulla socket Electron. Qualsiasi MCP client — Claude Desktop, VS
  Code extension, agenti custom dell'utente — può interrogare i
  dati on-device del singolo utente. **Questo cambia il prodotto
  da "app standalone" a "substrate programmabile per workflow AI
  sui dati personali"**. È un differenziatore vero rispetto a
  tutto il mercato adiacente (Superhuman, Granola, Notion AI).

**9. Sostituzione del runtime in `assistant/core.py` con
`ClaudeSDKClient`** (BYOK only, almeno inizialmente). Eliminerebbe
~500 righe di loop bespoke, regalerebbe streaming, compaction, hook
system, session persistence. Costo: la modalità credits resta sul
vecchio path finché il proxy non parla la wire-protocol che l'SDK
si aspetta. Strada migliore: due transport in coabitazione per
qualche release; deprezza il vecchio loop quando il proxy è migrato.

**10. Scheduling.** Il dream system (`services/dream.py`) e il
digest sono on-demand via RPC. SDK ha "scheduled remote agents"
(cron-style). Per noi è prematuro on-device (non vogliamo daemon
nascosti) ma è il binario corretto se in futuro mrcall-desktop avrà
una controparte cloud che esegue digest e proattività anche quando
il client è chiuso.

## Il problema del proxy (e la decisione strategica che ne consegue)

`MrCallProxyClient` (`engine/zylch/llm/proxy_client.py:402`) mima
`anthropic.Anthropic.messages.create` ma con header
`auth: <firebase_jwt>` invece di `x-api-key`. L'Agent SDK non chiama
`messages.create` direttamente — fa partire un binario Claude Code
che fa HTTP verso `api.anthropic.com` con `x-api-key`.
`ANTHROPIC_BASE_URL` ridireziona, ma se il proxy non accetta
`x-api-key` (perché valida JWT) l'auth fallisce.

Tre vie:

| Strada | Cosa serve | Quando |
|---|---|---|
| **A.** Proxy parla la wire-protocol dell'SDK | Server-side change in `mrcall-agent`: `/api/desktop/llm/proxy` accetta sia `x-api-key` placeholder sia `auth: <jwt>` (o nuovo endpoint drop-in) | Quando vuoi adottare l'SDK come runtime unico |
| **B.** SDK solo per BYOK, bare Anthropic SDK + pattern borrowing per credits | Zero, è già lo stato attuale, separi solo le code-path | Per iterare adesso senza dipendere da `mrcall-agent` |
| **C.** Tieni bare Anthropic SDK ovunque, prendi solo i pattern (hooks, memory tool, skills, subagent shape) dall'SDK | Zero | Oggi è la strada di minor resistenza |

**Raccomandazione**: (C) per i prossimi 1-2 cicli (Tier 1 + Tier 2
punti 5/6/7), in parallelo a uno scoping di (A) come piano di
esecuzione separato. (A) sblocca poi (8) e (9) come step naturale.
(B) è il fallback se (A) si dimostra non prioritario lato
`mrcall-agent`.

## Cosa **non** prendere

- **Built-in tools dell'SDK (Read/Write/Edit/Bash/Grep/Glob).** Sono
  filesystem tool per coding. Non hanno senso esposti all'LLM in
  un'app privacy-first che fa email e CRM. Tutt'al più `Read` per
  la futura `~/.zylch/profiles/<uid>/documents/` (vedi
  `engine/docs/execution-plans/next-features.md` "User Profile +
  Documents Folder"). `Bash` non lo esponiamo, mai.
- **Memory tool come sostituto di blob_storage.** La nostra memoria
  sentence-level + hybrid search + identifier-based reconsolidation
  (post `3a88e96`) è più adatta all'estrazione automatica di
  entità. Coabitano, non si sostituiscono.
- **Permission mode "plan".** Plan mode è per coding workflow. Per
  l'utente desktop l'approval gate sui tool destructive (send email,
  archive, delete) è già il pattern giusto via callback in
  `core.py`; serve solo formalizzarlo come hook (vedi punto 1).

## Ordine d'attacco proposto

Se Mario vuole un singolo prossimo PR, **(1) hook system minimale +
(3) chat session su SQLite** è il combo più alto-leverage e più
contenuto: sono refactor interni, niente cambia per il renderer,
niente dipende da `mrcall-agent`, e sblocca tutti gli altri
(post-tool retry, on-stop persistence, event bus per future feature).

Se invece vuole un singolo intervento ad alto impatto-utente, **(8)
outbound MCP** dà al chat assistant accesso immediato a Notion /
Linear / GitHub e cambia in modo visibile cosa l'utente può
chiedere.

Per scoping di ognuno (PR sizing, file da toccare, rischi di
regressione, test plan in stile "live testing not unit") un piano
di esecuzione separato sotto `engine/docs/execution-plans/` o
`docs/execution-plans/` quando si decide su quale partire.

## Fonti

- [Claude Agent SDK Python Reference](https://code.claude.com/docs/en/agent-sdk/python)
- [Claude Agent SDK Overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Memory Tool Documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
- [MCP Connector Documentation](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector)
- [Batch Processing Guide](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
- [Agent Skills Overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Tool Use Overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [`anthropics/claude-agent-sdk-python` su GitHub](https://github.com/anthropics/claude-agent-sdk-python)
