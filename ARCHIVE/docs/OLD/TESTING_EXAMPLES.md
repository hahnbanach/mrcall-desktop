# Zylch - Esempi di Testing Completi

**Guida pratica per testare Service Layer + HTTP API + Skill System**

---

## Setup Iniziale

### 1. Assicurati che .env sia configurato

```bash
cd /Users/mal/starchat/zylch

# Verifica .env
cat .env | grep ANTHROPIC_API_KEY
cat .env | grep SKILL_MODE_ENABLED

# Se mancano, aggiungi:
echo "ANTHROPIC_API_KEY=sk-ant-your-key" >> .env
echo "SKILL_MODE_ENABLED=true" >> .env
```

---

## Test 1: Skill System (Standalone - NO API)

**Test base del sistema skill senza API:**

```bash
cd /Users/mal/starchat/zylch

# Test suite automatico
./venv/bin/python3 tests/test_skill_system.py
```

**Output atteso:**
```
🚀 Starting Zylch Skill System Tests (Phase A)
============================================================

=== Test 1: Base Skill ===
✅ Base skill test passed

=== Test 2: Skill Registry ===
✅ Registry test passed

=== Test 3: Email Triage Skill ===
✅ Email triage test passed

=== Test 4: Pattern Store ===
✅ Pattern store test passed

=== Test 5: Full System Integration ===
✅ Router initialized
✅ Full system integration test passed

============================================================
📊 Test Results: 5 passed, 0 failed
🎉 All tests passed!
```

---

## Test 2: HTTP API (Terminal 1 - Server)

### Avvia il server API

```bash
cd /Users/mal/starchat/zylch

# Avvia server in modalità development (auto-reload)
./venv/bin/uvicorn zylch.api.main:app --reload --port 8000
```

**Output atteso:**
```
INFO:     Will watch for changes in these directories: ['/Users/mal/starchat/zylch']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using WatchFiles
INFO:     Started server process [12346]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**✅ Server running! Lascia questo terminale aperto.**

---

## Test 3: HTTP API (Terminal 2 - Test Script)

**In un NUOVO terminale:**

```bash
cd /Users/mal/starchat/zylch

# Script di test automatico
./test_api.sh
```

**Output atteso:**
```
🧪 Testing Zylch AI HTTP API
============================

Checking if API server is running...
✓ Server is running

=== Health Check ===
Testing Health... ✓ OK
   Response: {"status":"healthy","skill_mode":true,"pattern_store":true}...

=== Skills API ===
Testing List Skills... ✓ OK
   Response: {"skills":[{"name":"email_triage","description":"Find and prioritize email threads...

=== Gaps API ===
Testing Gaps Summary... ✓ OK
   Response: {"has_data":false,"message":"No gap analysis found. Run sync first."}...

=== Patterns API ===
Testing Pattern Stats... ✓ OK
   Response: {"enabled":true,"total_patterns":0,"by_skill":{},"average_confidence":0.0...

============================
✅ API testing complete!

Full documentation: http://localhost:8000/docs
```

---

## Test 4: API Manuale con curl (Terminal 2)

### Test 1: Health Check

```bash
curl http://localhost:8000/health | jq
```

**Output:**
```json
{
  "status": "healthy",
  "skill_mode": true,
  "pattern_store": true
}
```

### Test 2: List Available Skills

```bash
curl http://localhost:8000/api/skills/list | jq
```

**Output:**
```json
{
  "skills": [
    {
      "name": "email_triage",
      "description": "Find and prioritize email threads by contact, subject, or content",
      "model": "claude-sonnet-4-20250514"
    },
    {
      "name": "draft_composer",
      "description": "Compose email drafts using memory rules and learned patterns",
      "model": "claude-sonnet-4-20250514"
    },
    {
      "name": "cross_channel_orchestrator",
      "description": "Coordinate actions across email, phone, and calendar",
      "model": "claude-sonnet-4-20250514"
    }
  ],
  "count": 3
}
```

### Test 3: Classify Intent (richiede API key)

```bash
curl -X POST http://localhost:8000/api/skills/classify \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Find emails from Luisa about the invoice"
  }' | jq
```

**Output:**
```json
{
  "primary_skill": "email_triage",
  "context_skills": [],
  "params": {
    "contact": "Luisa",
    "subject": "invoice"
  },
  "confidence": 0.95
}
```

### Test 4: Execute Email Triage Skill

```bash
curl -X POST http://localhost:8000/api/skills/execute \
  -H "Content-Type: application/json" \
  -d '{
    "skill_name": "email_triage",
    "user_id": "mario",
    "intent": "find emails from luisa",
    "params": {
      "contact": "luisa",
      "days_back": 30
    }
  }' | jq
```

**Output:**
```json
{
  "success": true,
  "data": {
    "threads": [],
    "count": 0,
    "search_criteria": {
      "contact": "luisa",
      "subject": null,
      "priority": null,
      "days_back": 30,
      "query": null
    }
  },
  "message": "email_triage completed successfully",
  "skill_name": "email_triage",
  "execution_time_ms": 12.5,
  "model_used": "claude-sonnet-4-20250514",
  "tokens_used": null,
  "error": null
}
```

### Test 5: Store a Pattern

```bash
curl -X POST http://localhost:8000/api/patterns/store \
  -H "Content-Type: application/json" \
  -d '{
    "skill": "draft_composer",
    "intent": "write reminder to luisa",
    "context": {"contact": "Luisa", "type": "reminder"},
    "action": {"tone": "formal", "pronoun": "lei"},
    "outcome": "User approved draft",
    "user_id": "mario"
  }' | jq
```

**Output:**
```json
{
  "success": true,
  "pattern_id": "a1b2c3d4e5f6"
}
```

### Test 6: Retrieve Pattern Stats

```bash
curl http://localhost:8000/api/patterns/stats | jq
```

**Output:**
```json
{
  "enabled": true,
  "total_patterns": 1,
  "by_skill": {
    "draft_composer": 1
  },
  "average_confidence": 0.5,
  "high_confidence_patterns": 0,
  "db_path": ".swarm/patterns.db"
}
```

---

## Test 5: Swagger UI (Browser)

**Apri nel browser:**

```
http://localhost:8000/docs
```

### Cosa puoi fare in Swagger UI:

1. **Vedere tutti gli endpoint** organizzati per categoria
2. **Testare interattivamente** cliccando "Try it out"
3. **Vedere esempi di request/response**
4. **Copiare curl commands** automaticamente

### Esempio test in Swagger:

1. Vai a **Skills → POST /api/skills/classify**
2. Clicca **"Try it out"**
3. Modifica il body:
   ```json
   {
     "user_input": "Draft a reminder to Marco about the proposal",
     "conversation_history": null
   }
   ```
4. Clicca **"Execute"**
5. Vedi la response in tempo reale

---

## Test 6: Full Workflow End-to-End

**Scenario:** Draft email usando skill system via API

### Step 1: Classify Intent

```bash
curl -X POST http://localhost:8000/api/skills/classify \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Draft a professional reminder email to Luisa about the invoice payment"
  }' | jq '.primary_skill, .params'
```

**Output:**
```
"draft_composer"
{
  "contact": "Luisa",
  "task": "reminder about invoice payment",
  "instructions": "professional tone"
}
```

### Step 2: Process Natural Language (End-to-End)

```bash
curl -X POST http://localhost:8000/api/skills/process \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Draft a professional reminder email to Luisa about the invoice payment",
    "user_id": "mario",
    "conversation_history": []
  }' | jq
```

**Output:**
```json
{
  "success": true,
  "classification": {
    "primary_skill": "draft_composer",
    "context_skills": [],
    "params": {
      "contact": "Luisa",
      "task": "reminder about invoice payment"
    },
    "confidence": 0.92
  },
  "execution": {
    "skill_name": "draft_composer",
    "success": true,
    "data": {
      "draft": "Gentile Luisa,\n\nLe scrivo per ricordarle cortesemente...",
      "subject": "Reminder: Pagamento Fattura"
    },
    "message": "draft_composer completed successfully",
    "execution_time_ms": 2341.5,
    "model_used": "claude-sonnet-4-20250514"
  }
}
```

### Step 3: Store Pattern (if user approves)

```bash
curl -X POST http://localhost:8000/api/patterns/store \
  -H "Content-Type: application/json" \
  -d '{
    "skill": "draft_composer",
    "intent": "draft reminder to luisa about invoice",
    "context": {"contact": "Luisa", "type": "invoice_reminder"},
    "action": {"tone": "formal", "approved": true},
    "outcome": "User approved and sent",
    "user_id": "mario"
  }' | jq
```

**Output:**
```json
{
  "success": true,
  "pattern_id": "f6e5d4c3b2a1"
}
```

---

## Test 7: Service Layer Diretto (Python)

**Test services senza API (per debugging):**

```bash
./venv/bin/python3
```

```python
# Test SkillService
from zylch.services.skill_service import SkillService
import asyncio

service = SkillService()

# List skills
skills = service.list_available_skills()
print(f"Available skills: {len(skills)}")
for skill in skills:
    print(f"  - {skill['name']}: {skill['description']}")

# Classify intent
async def test():
    result = await service.classify_intent(
        "Find emails from Luisa about invoice"
    )
    print(f"\nClassification: {result['primary_skill']}")
    print(f"Params: {result['params']}")
    print(f"Confidence: {result['confidence']:.0%}")

asyncio.run(test())
```

**Output:**
```
Available skills: 3
  - email_triage: Find and prioritize email threads...
  - draft_composer: Compose email drafts...
  - cross_channel_orchestrator: Coordinate actions...

Classification: email_triage
Params: {'contact': 'Luisa', 'subject': 'invoice'}
Confidence: 95%
```

---

## Test 8: Pattern Store (Python)

```python
from zylch.services.pattern_service import PatternService

service = PatternService()

# Store pattern
pattern_id = service.store_pattern(
    skill="draft_composer",
    intent="write formal email to luisa",
    context={"contact": "Luisa"},
    action={"tone": "formal", "pronoun": "lei"},
    outcome="approved",
    user_id="mario"
)
print(f"Stored pattern: {pattern_id}")

# Retrieve similar
patterns = service.retrieve_similar_patterns(
    intent="write formal email to luisa",
    skill="draft_composer",
    limit=3
)
print(f"\nFound {len(patterns)} similar patterns:")
for p in patterns:
    print(f"  - {p['summary']}")

# Get stats
stats = service.get_pattern_stats()
print(f"\nPattern Stats:")
print(f"  Total: {stats['total_patterns']}")
print(f"  By skill: {stats['by_skill']}")
print(f"  Avg confidence: {stats['average_confidence']:.0%}")
```

---

## Troubleshooting

### ❌ "Connection refused" su API

**Problema:** Server non è avviato

**Fix:**
```bash
# Terminal 1
./venv/bin/uvicorn zylch.api.main:app --reload
```

### ❌ "Skill mode not enabled"

**Problema:** .env non ha SKILL_MODE_ENABLED

**Fix:**
```bash
echo "SKILL_MODE_ENABLED=true" >> .env
# Riavvia server
```

### ❌ "Module not found"

**Problema:** Package non installato

**Fix:**
```bash
pip install -e .
```

### ❌ Test pattern store fallisce

**Problema:** Directory .swarm non esiste

**Fix:**
```bash
mkdir -p .swarm
```

---

## Checklist Testing Completo

### ✅ Base Tests
- [ ] `tests/test_skill_system.py` passa (5/5)
- [ ] Server API si avvia senza errori
- [ ] Health check risponde

### ✅ API Tests
- [ ] `./test_api.sh` passa tutti i test
- [ ] Swagger UI è accessibile
- [ ] Tutti gli endpoint rispondono

### ✅ Skills Tests
- [ ] Intent classification funziona
- [ ] Email triage skill esegue
- [ ] Draft composer genera draft (con API key)
- [ ] Pattern store salva e recupera

### ✅ End-to-End Tests
- [ ] Full workflow (classify → execute → store pattern)
- [ ] Service layer chiamabile direttamente
- [ ] Pattern learning accumula confidence

---

## Quick Commands Reference

```bash
# Start API server
./venv/bin/uvicorn zylch.api.main:app --reload

# Run skill tests
./venv/bin/python3 tests/test_skill_system.py

# Run API tests
./test_api.sh

# Health check
curl http://localhost:8000/health

# List skills
curl http://localhost:8000/api/skills/list | jq

# Swagger UI
open http://localhost:8000/docs

# Pattern stats
curl http://localhost:8000/api/patterns/stats | jq
```

---

**Ora hai tutto per testare il sistema completo!** 🚀
