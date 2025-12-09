# Guida Testing Fase A - Skill System

## Situazione Attuale

**Il skill system NON è ancora integrato nella CLI Zylch.**

La CLI esistente (`zylch`) usa ancora:
- Comandi diretti (sync, gaps, etc.)
- Agent tradizionale (non skill-based)

**Per testare il nuovo skill system devi usare script standalone.**

---

## Opzione 1: Test Automatici (Raccomandato per iniziare)

### Test senza API key

```bash
cd /Users/mal/starchat/zylch

# Test suite completa (non richiede API key)
./venv/bin/python3 tests/test_skill_system.py
```

**Output atteso:**
```
✅ Base skill test passed
✅ Registry test passed
✅ Email triage test passed
✅ Pattern store test passed
✅ Full system integration test passed
📊 Test Results: 5 passed, 0 failed
```

---

## Opzione 2: Test Manuali Interattivi

### Prerequisiti

1. **Crea/aggiorna il tuo .env:**

```bash
cd /Users/mal/starchat/zylch
cp .env.example .env
```

2. **Aggiungi la tua API key nel .env:**

```bash
# Modifica .env
ANTHROPIC_API_KEY=sk-ant-your-key-here
SKILL_MODE_ENABLED=true  # Abilita skill system
```

### Esegui test interattivo

```bash
./venv/bin/python3 test_phase_a_manual.py
```

**Menu interattivo:**
```
Select test to run:
  1. Pattern Store (no API key needed)
  2. Intent Router (requires API key)
  3. Email Triage (no API key needed, but needs email cache)
  4. Draft Composer (requires API key)
  5. Cross-Channel Orchestrator (requires API key)
  6. Full Workflow (requires API key)
  7. Run all tests
  0. Exit
```

---

## Opzione 3: Test Skill Individuali (Python REPL)

### Test Pattern Store

```bash
./venv/bin/python3
```

```python
from zylch.memory.pattern_store import PatternStore

# Inizializza
store = PatternStore()
print(f"DB path: {store.db_path}")

# Salva un pattern
pattern_id = store.store_pattern(
    skill="draft_composer",
    intent="write reminder to luisa",
    context={"contact": "luisa"},
    action={"tone": "formal"},
    outcome="approved",
    user_id="mario"
)
print(f"Stored: {pattern_id}")

# Recupera patterns simili
patterns = store.retrieve_similar(
    intent="write reminder to luisa",
    skill="draft_composer"
)
print(f"Found {len(patterns)} patterns")
for p in patterns:
    print(f"  - {p['summary']}")
```

### Test Intent Router (richiede API key)

```python
from zylch.skills.registry import registry
from zylch.skills.email_triage import EmailTriageSkill
from zylch.skills.draft_composer import DraftComposerSkill
from zylch.router.intent_classifier import IntentRouter
import asyncio

# Setup
registry._skills = {}
registry.register_skill(EmailTriageSkill())
registry.register_skill(DraftComposerSkill())

router = IntentRouter(registry)

# Test classification
async def test():
    result = await router.classify_intent(
        "Find emails from Luisa about the invoice"
    )
    print(f"Primary skill: {result['primary_skill']}")
    print(f"Params: {result['params']}")
    print(f"Confidence: {result['confidence']}")

asyncio.run(test())
```

### Test Draft Composer (richiede API key)

```python
from zylch.skills.draft_composer import DraftComposerSkill
from zylch.skills.base import SkillContext
import asyncio

skill = DraftComposerSkill()

context = SkillContext(
    user_id="mario",
    intent="write reminder to luisa about invoice",
    params={
        "contact": "Luisa",
        "task": "Send reminder about invoice",
        "instructions": "Professional, formal tone",
        "thread_context": "Invoice sent 2 weeks ago"
    },
    memory_rules=[
        {"correct_behavior": "Use 'lei' with Luisa"},
        {"correct_behavior": "Keep it brief"}
    ]
)

async def test():
    result = await skill.activate(context)
    if result.success:
        print("✅ Draft generated!")
        print(f"Subject: {result.data['subject']}")
        print(f"Body:\n{result.data['draft']}")
    else:
        print(f"❌ Failed: {result.message}")

asyncio.run(test())
```

---

## Cosa NON Puoi Fare Ancora

### ❌ Usare skill system dalla CLI Zylch

Questo **non funziona** ancora:
```bash
$ zylch
You: find emails from luisa  # ← Usa ancora agent tradizionale, non skill
```

**Perché?** Il skill system non è ancora integrato in `zylch/cli/main.py`.

### ✅ Cosa Fare Invece

**Per ora, testa con gli script standalone:**

```bash
# Test automatici
./venv/bin/python3 tests/test_skill_system.py

# Test interattivi
./venv/bin/python3 test_phase_a_manual.py

# Python REPL per testing granulare
./venv/bin/python3
>>> from zylch.skills...
```

---

## Prossimo Step: Integrazione CLI

**Quando pronto**, dovrai:

1. Modificare `zylch/cli/main.py` per:
   - Inizializzare skill registry
   - Inizializzare intent router
   - Processare input naturale via skill system

2. Aggiungere feature flag:
   ```python
   if settings.skill_mode_enabled:
       # Use skill-based processing
   else:
       # Use traditional agent
   ```

**Ma per ora, testa con gli script standalone che ti ho preparato.**

---

## Quick Test Commands

```bash
# Test base (no API key)
./venv/bin/python3 tests/test_skill_system.py

# Test pattern store
./venv/bin/python3 -c "
from zylch.memory.pattern_store import PatternStore
store = PatternStore()
print(f'✅ Pattern store initialized: {store.db_path}')
"

# Verifica configurazione
./venv/bin/python3 -c "
from zylch.config import settings
print(f'Router model: {settings.skill_router_model}')
print(f'Execution model: {settings.skill_execution_model}')
print(f'Pattern store: {settings.pattern_store_enabled}')
print(f'Prompt caching: {settings.enable_prompt_caching}')
print(f'Skill mode: {settings.skill_mode_enabled}')
"
```

---

## Riassunto

**Stato attuale:**
- ✅ Skill system implementato e funzionante
- ✅ Test suite completa
- ❌ Non ancora integrato in CLI Zylch

**Come testare:**
1. `tests/test_skill_system.py` - Test automatici
2. `test_phase_a_manual.py` - Test interattivi
3. Python REPL - Test granulare

**Per usare nella CLI:**
- Aspetta integrazione (prossimo step)
- Oppure integra manualmente modificando `cli/main.py`

