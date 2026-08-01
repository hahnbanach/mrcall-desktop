# Memory: key-first entity identity (stop the fragmentation)
status: in-progress — design changes landed in `ebb1c7f` (2026-07-31); corpus cleanup + live verification pending
created: 2026-07-30
origin: extracted from cs-kernel `docs/execution-plans/2026-07-28-eternal-operator-loop.md` §1.3/§2.4 — this doc is now the source of truth for the ENGINE-side memory work; the cs-side (CRM cache, dossier tables in cs.db) stays there.

## Goal

Entity memory must resolve identity by **key** (email, phone, exact name)
before any similarity search, so that one real-world customer is one blob.
Machine-verifiable when done, on the support@ profile
(`~mrcalld/.zylch/profiles/9nXeYF8OXPetUFsSP4zDC3F2i673/zylch.db`):

- `Tandoori Villa Postipuisto` counts **1** (today: 25);
- re-processing the same inbound mail twice produces **0** new `user:` blobs;
- a week of live traffic produces **0** new blobs whose multi-word `Name:`
  already exists.

## Findings (measured 2026-07-30 on the live support@ profile)

### The two incidents are opposite failures of the same keyless design

**June — judgment broke OPEN.** The prompt-cache refactor `58f392a` dropped the
entire merge rule set (including the INSERT/refuse rule) from the cached system
prompt. Across 859 merges the model refused 0 times; the first PERSON blob
became a universal sink absorbing 400+ unrelated contacts. Fixed on 2026-06-28
(`5adad4b`) with the `merge_gate_selfcheck` canary, followed by a mass rebuild:
1269 of the current blobs were created that single day.

**Since then — recall breaks CLOSED.** The gate's judgment is healthy (canary
green, ~50% INSERT rate), but the right blob is never *found*, so the corpus
fragments instead of collapsing: **116 blobs created after the rebuild
duplicate a `Name:` that already existed**, accelerating with traffic (14 on
23 Jul, 15 on 25 Jul, 32 on 28 Jul alone).

### The mechanism, caught verbatim in the engine log

`ambulatorio cavoretto`, duplicated 2026-07-28 00:21 — every link failing:

1. A blob for this customer existed since 28 Jun, **with** its
   `person_identifiers` email row — findable by key.
2. The extractor emitted a stub **without the sender's address**:
   `Name: Ambulatorio Cavoretto | Website: (none) | Address: (none) |
   VAT: (none)`. No email → the identifier lookup had nothing to key on —
   even though the pipeline *knew* the sender: the source email row's
   `from_email` is structured data the extractor simply does not carry over.
3. Hybrid search ranked candidates for the stub and returned three unrelated
   businesses (`Studio Pusceddu` 0.637, `Into the wild dog village` 0.612,
   `Studio Ruzzon` 0.584) — the real blob nowhere. The text-search terms
   literally include the scaffolding tokens `entity`, `type:`, `company`,
   `(none)`, diluting the two tokens that matter.
4. `Found 0 candidates above threshold 0.65` → new blob created — itself
   identifier-less, so the next lookup for this customer is blinder still.
   The same customer was duplicated **again 20 minutes later** (00:41),
   identical sequence.

An exact match on `Name:` — one indexed lookup — would have found the 28-Jun
blob instantly, no LLM, no threshold.

### Corpus state (support@ profile, 2026-07-30)

| | count |
|---|---|
| `user:` blobs | 1548 |
| distinct `Name:` values | 632 |
| names appearing >1× | 233 names, **1131 blobs** |
| — multi-word names (almost surely same entity) | **174 names, 856 blobs (55%)** |
| — one-word first names (may be different people) | 59 names, 275 blobs |
| blobs with NO `person_identifiers` row | **1209 (78%)** |
| blobs stating `Email:` in prose but never indexed | **143 of 392** |
| blobs describing OUR OWN outbound mail (`STYLE`, "number migration reminder" ×40, …) | **164 (10%)** |
| `facts:` blobs | 738 — **0** linked to any contact, **243** contain a `+39` number |

The `facts:` point is a safety issue, not only a quality one: rows like
`Category: MrCall setup | Key: Call forwarding number | +390289040647` are
facts about ONE customer stored as facts about NOBODY. Nothing in
`hybrid_search.py` scopes a fact to the customer it came from; the failure mode
of heavier memory use is handing customer A customer B's forwarding number.

### Why the design got here

Similarity-plus-LLM identity resolution is the right tool when there are no
identifiers — a personal assistant reading a stranger's mail, which is the
public product's case. But every observation in this pipeline arrives FROM a
channel row that carries hard identifiers (`emails.from_email`,
`whatsapp_messages.sender_jid`, `mrcall_conversations.contact_phone`). The
pipeline throws the key away at extraction time, then pays an LLM to guess it
back — 25 times for one restaurant.

## Design: key-first resolution, similarity last

All changes are engine-generic — no CRM dependency, nothing company-specific.
(The empty `contacts` table already in the schema is the natural anchor if we
want a registry later; not required for this plan.)

1. **Carry the source identifier into the upsert.** When the extracted entity
   is the message's sender (the overwhelmingly common case), attach
   `from_email` / `sender_jid` / `contact_phone` to the entity BEFORE candidate
   lookup — it is structured data the pipeline already holds. Never rely on
   the LLM to re-extract a key the row already carries.
2. **Candidate lookup order: identifier → exact `Name:` → similarity.**
   Exact normalized-name match against existing blobs' `#IDENTIFIERS` runs
   before hybrid search, and its hits go to the merge gate first. Similarity
   remains as the last resort for genuinely keyless mentions.
3. **No identifier → no blob.** An extracted entity with no email, no phone
   and no exact-name match carries zero linkable identity. Discard it with a
   `logger.warning` — never create a blob. (The source identifier is always
   available: `emails.from_email`, `whatsapp_messages.sender_jid`,
   `mrcall_conversations.contact_phone`. If the pipeline reaches this point
   without one, something upstream is wrong.)
4. **Fix the text-search query.** Strip scaffolding tokens (`entity`, `type:`,
   `name:`, `(none)`, …) from the FTS terms in
   `hybrid_search._text_search` — today they dilute real tokens ~6:1.
5. **Index identifiers at write time, always.** A blob whose prose contains
   `Email:`/`Phone:` lines must get its `person_identifiers` rows in the same
   transaction (today: 143 blobs state an address that was never indexed, so
   the keyed path can't see them).
6. **Own the facts.** `facts:` rows acquire an owner link (contact identifier
   or blob FK) or are not written; retrieval scopes them to their owner.

## Status (2026-07-31)

Design points 1–4 are **landed** in commit `ebb1c7f` (uncommitted when built
this session, committed by Mario before end of session):

1. ✅ **Carry the source identifier into the upsert.** `_upsert_entity()`
   (`workers/memory.py`) now takes `contact_identifier`; `process_email`
   passes `from_email`, `process_whatsapp_message` resolves the sender phone
   from `sender_jid` (LID → `whatsapp_contacts` lookup, shared
   `_resolve_whatsapp_phone()` helper with `_format_whatsapp_data`). The
   identifier is injected into the `#IDENTIFIERS` parse if the LLM omitted
   it (normalised: lowercased email, `_normalise_phone` for phone) — never
   rely on the LLM to re-extract a key the row already carries. The sync
   path (`services/job_executor.py::_upsert_entity_sync`) got the same
   treatment plus the identifier-first lookup / `email_blobs` /
   `person_identifiers` writes it was missing (parity with the async path).
2. ✅ **Candidate lookup order: identifier → exact `Name:` → similarity.**
   (Identifier-first was already live since Phase 1b; the point above now
   guarantees the identifier is *present* in the parse.)
3. ✅ **No identifier → no blob** (simplified 2026-07-31 with Mario: no
   queue / dream-pass / join-table staging). An entity with no email, no
   phone and no exact-name match is discarded with a `logger.warning`.
   The source identifier is *always* available from the channel row
   (`emails.from_email`, `whatsapp_messages.sender_jid`,
   `mrcall_conversations.contact_phone`) — reaching this point keyless
   means an upstream bug, not a legitimate case.
4. ✅ **Fix the text-search query.** `hybrid_search._text_search` strips
   scaffolding tokens (`entity`, `type:`, `name:`, `(none)`, …) from the
   FTS terms.
5. ⏳ **Index identifiers at write time, always.** Covered for *new* blobs
   by point 1 (write already happened on upsert); the 143 historical blobs
   stating an address never indexed are a corpus-cleanup item.
6. ❌ **Own the facts.** Not started. `facts:` rows (738, 0 linked, 243
   with a `+39` number) still need an owner link or a refusal to write.

**Verification so far:** `ruff` clean; `pytest` 390 passed with the 42
pre-existing failures unchanged (A/B verified against baseline). **NOT yet
live-verified** — the three Goal counts, the re-feed of an already-processed
mail, and the `merge_gate_selfcheck` canary all still need to run against
the live `support@` profile.

**Corpus cleanup** (below) is next; the existing
`scripts/backfill_person_identifiers.py` (tracked since 2026-05-08, Phase 1a,
idempotent, `--dry-run`, reuses `_parse_identifiers_block`) covers cleanup
step 1.

## One-off corpus cleanup (support@ profile)

Each step verifiable by count, in this order:

1. Backfill `person_identifiers` for the 143 blobs stating an address in prose.
2. Collapse duplicates: the 174 multi-word names (856 blobs) merge on exact
   name (union of `#HISTORY`, one row out); the 59 one-word first names need an
   identifier or an LLM check first — never a blind name-merge ("Andrea" ×2
   may be two people).
3. Move the 164 `STYLE`/template blobs out of the entity namespace into their
   own — they are our writing samples, not customers, and they compete for
   top-k slots.
4. Give the 738 `facts:` rows an owner or drop them; the 243 with a `+39`
   number first.

Run steps 1–4 only AFTER the design changes land, or live traffic re-creates
the mess while it is being cleaned (32 duplicates on 28 Jul alone).

## Verification (semantic, on the real profile — unit tests don't count)

- Re-feed a real already-processed inbound mail through the memory worker:
  0 new blobs, 1 reconsolidation.
- `merge_gate_selfcheck` stays green (the canary guards the opposite failure).
- The three Goal counts above, re-measured on the live DB after a week.

## Out of scope (lives in mrcall-cs)

The CRM cache (`crm_business` in cs.db), the per-customer dossier tables, and
how the cs operator loop reads/writes memory — see cs-kernel
`docs/execution-plans/2026-07-28-eternal-operator-loop.md` §2.4. The engine
stays product-generic; MrCall-specific identity enrichment arrives from the
outside, through the same keyed interfaces this plan builds.
