---
status: completed
completed_at: 2026-05-12
completed_in: commit 91421d2e (single landing covering 2a + 2b + 2c + parser hardening)
target_phase: Phase 2 (D2 + D4) — WhatsApp memory extraction
prerequisites_done:
  - Phase 1a (`d0baa6b1`): person_identifiers index, additive write.
  - Phase 1b (`315c56d1`): identifier-first match in `_upsert_entity`.
  - Phase 1c (`6ae8a5fa`): identifier-clustered `reconsolidate_now`
    + cross-reference migration. Live-verified on support / cafe124.
outcome: |
  Landed end-to-end and live-verified on the gmail profile
  (`HxiZh…`). 106 of 106 WhatsApp 1-on-1 messages processed; 0
  LID-as-phone rows in person_identifiers; first cross-channel
  blob landed (CANNING ITALIA S.R.L., email + WhatsApp). Detailed
  outcome lives in `../active-context.md` "WhatsApp pipeline parity
  — Phase 2 a/b/c". Next: Phase 3 (D3 + D5) — task creation from
  WhatsApp.
created: 2026-05-08
---

# Handoff prompt — Phase 2 of whatsapp-pipeline-parity

Paste this prompt verbatim at the start of the next fresh session.

---

````
Phase 2 di whatsapp-pipeline-parity. Obiettivo: WhatsApp memory extraction
funzionante, con cross-channel identity (un blob solo per persona che
scrive sia via email sia via WA).

PRIMA DI TOCCARE CODICE:
1. Leggi engine/docs/execution-plans/whatsapp-pipeline-parity.md INTEGRO
   (status: in-progress; Phase 1 a/b/c già DONE; Phase 2 è il prossimo
   landing).
2. Leggi engine/docs/active-context.md, sezione "Cross-channel person
   identity — Phase 1 a/b/c" e "WhatsApp" — capirai cosa c'è già.
3. Conferma con me le 5 domande del brief che probabilmente sono ormai
   risolte (1-on-1 only v1, self-sent come email, contact_phone v.
   contact_email, prompt cost, identifier kinds). Le mie risposte di
   default: tutte raccomandazioni del brief, escluso group v1.

PUNTI CRITICI da chiarire con me PRIMA di iniziare:
- Lo skeleton dead a memory.py:856-946 (process_whatsapp_message +
  process_whatsapp_batch) è ROTTO: chiama
  storage.mark_whatsapp_memory_processed che non esiste, usa namespace
  PERSON:{sender} invece di user:{owner_id}, non scriverebbe
  whatsapp_blobs. Decidi con me: cancellare e riscrivere da zero, o
  riscrivere in-place. Io preferisco cancellare prima → commit pulito
  "remove dead skeleton" → poi commit feature.
- Prompt strategy: il brief proponeva due opzioni: (a) generalizzare
  memory_email → memory_message channel-aware, oppure (b) trainer
  separato memory_whatsapp. Io ho raccomandato (a) — mi confermi?
  Impatto significativo perché agents/trainers/memory_email.py va
  refactored.
- Confirm column WhatsAppMessage.memory_processed_at: già esiste
  (models.py:599). NIENTE migrazione necessaria.

LANDING SUGGERITO (Phase 2 in 3 sub-commit):
**2a — schema + storage**: WhatsAppBlob model (mirror di EmailBlob) +
storage helpers add_whatsapp_blob_link / get_blobs_for_whatsapp_message.
Nessuna behavior change. Test storage.

**2b — prompt generalization**: refactor memory_email trainer →
memory_message con channel-aware envelope. CRITICAL: il prompt deve
emettere Phone: nel #IDENTIFIERS strutturato anche per WA (così
l'identifier index Phase 1 cattura il match cross-canale). Test
trainer output.

**2c — process_whatsapp_message + wiring**: cancella skeleton dead,
scrivi process_whatsapp_message che mirrori process_email
(formattazione → _extract_entities → _upsert_entity riusa
identifier-first match Phase 1b → write whatsapp_blobs link). Wire in
process_pipeline step [3/5] dopo email loop, per messaggi più nuovi
del watermark memory_processed_at. Cap concorrenza come email
(asyncio.Semaphore=5). Test end-to-end con mock LLM.

VERIFICA LIVE (mandatory, dopo ogni sub-commit):
- Apri il profilo gmail nell'app, fai connect WA se non connesso
  (Settings → WhatsApp), poi click Update.
- Per 2c: verifica che [3/5] della pipeline mostri "Extracting memory
  from N WA messages" oltre agli email.
- Verifica che il memory worker scriva blob WA con #IDENTIFIERS che
  contengono Phone: e/o LID:. Query SQL:
    sqlite3 ~/.zylch/profiles/HxiZh.../zylch.db \
      "SELECT content FROM blobs ORDER BY created_at DESC LIMIT 3"
- Verifica cross-canale: trova un WA contact che è anche email
  contact, confermare che hanno UN solo blob (sia via Phase 1b
  identifier match al primo arrivo WA, sia via reconsolidate_now
  successivo).

DISCIPLINE (Mario's standard):
- Italian register nella chat.
- One change at a time. Mai due sub-commit in un solo PR mentale.
- NEVER push to origin.
- NEVER commit until Mario clicca Update reale e dice "funziona".
- Unit test, typecheck, log inspection NON contano come "verified" —
  solo Mario che vede il risultato in app conta.
- Se trovi qualcosa di rotto durante la verifica live, FIX prima del
  commit del feature, non dopo.

OUT OF SCOPE Phase 2:
- Task creation da WA (Phase 3, non toccare).
- UI renderer changes (Phase 4).
- Group chats / is_group=True (deferred).
- Calendar (ha già il suo path).
````

---

## Background context (do not paste; useful for the next agent to read)

### What Phase 1 left behind

Three commits on `main`, pushed: `d0baa6b1`, `315c56d1`, `6ae8a5fa`.
Test file `engine/tests/workers/test_person_identifiers.py` (47 cases,
green). Backfill script `engine/scripts/backfill_person_identifiers.py`.
Storage helpers in `engine/zylch/storage/storage.py`. Module-level
parser + normaliser in `engine/zylch/workers/memory.py`. Refactored
`engine/zylch/memory/llm_merge.py`.

Live impact (CLI sweeps, BYOK):
- `support@mrcall.ai`: 805 → 307 blobs (-62%, 0 identifier dup-keys).
- `mario.alemi@cafe124.it`: 731 → 315 blobs (-57%, 0 identifier dup-keys).
- `mario.alemi@gmail.com`: pending; Mario clicks Settings → Maintenance
  → "Reconsolidate memory" (Firebase session needed).

### What's broken in production today (relevant to Phase 2)

`engine/zylch/workers/memory.py:856-946` — `process_whatsapp_message`
and `process_whatsapp_batch` are dead skeleton. They:
- call `self.storage.mark_whatsapp_memory_processed(...)` which is
  **not defined** anywhere on `Storage` → AttributeError on first call;
- use `namespace = f"PERSON:{sender}"` instead of the canonical
  `f"user:{owner_id}"` → blobs would land in a parallel namespace and
  never merge with email blobs;
- search candidates by `sender_name` instead of `#IDENTIFIERS`
  block → cross-channel identity would not trigger.

Phase 2 either deletes these methods first (clean slate, single
"remove dead skeleton" commit) or rewrites them in place. Mario's
preference per the handoff prompt: delete first.

### Files Phase 2 will touch

```
engine/zylch/storage/models.py            +WhatsAppBlob
engine/zylch/storage/storage.py           +add_whatsapp_blob_link, +get_blobs_for_whatsapp_message
engine/zylch/workers/memory.py            -dead skeleton, +process_whatsapp_message (real)
engine/zylch/services/process_pipeline.py wire WA memory loop in step [3/5]
engine/zylch/agents/trainers/memory_email.py -> memory_message  (channel-aware refactor)
engine/scripts/backfill_whatsapp_blobs.py NEW (no-op if table fresh; mirror of backfill_email_blobs.py)
engine/tests/workers/test_memory_whatsapp.py NEW
```

### Open prerequisite questions for Mario (must be answered before code)

1. **Group chats**: 1-on-1 only in v1, group chats deferred?
   (Recommendation: yes.)
2. **Self-sent WA (`is_from_me=True`)**: same rule as email — LLM
   decides? (Recommendation: yes.)
3. **`task_items.contact_email` vs new `contact_phone`**: out of
   scope for Phase 2 (it's Phase 3 territory) but flag it now so
   schema is consistent. (Recommendation: add `contact_phone` nullable
   in Phase 3, not Phase 2.)
4. **Memory cost**: per-message granularity, prompt cache makes it
   cheap. Revisit if Mario sees a credit spike. (Recommendation: yes.)
5. **Identifier kinds in the prompt output**: Phase 1 already locked
   email/phone/lid. Phase 2's prompt must continue to emit `Phone:`
   and `LID:` lines explicitly for WA blobs.
