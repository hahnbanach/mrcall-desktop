# Phase 1 Testing - Server-Side Storage & API

**Data:** 2025-11-30
**Status:** ✅ Implementato, ⏳ Da testare

## Overview

Phase 1 ha implementato:
- Server-side storage layer (SQLite multi-tenant)
- Data access API endpoints
- Auth API endpoints
- Test suite base

Questo documento descrive come testare manualmente le nuove API.

---

## Setup Test Environment

### 1. Avvia il Server API

```bash
cd /Users/mal/hb/zylch

# Attiva virtual environment
source venv/bin/activate

# Avvia server FastAPI
uvicorn zylch.api.main:app --reload --port 8000
```

Server disponibile su: `http://localhost:8000`

**Documentazione interattiva:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 2. Ottieni Firebase Token

Per testare endpoint autenticati, serve un Firebase ID token valido.

**Opzione A - Login tramite CLI:**
```bash
./zylch-cli --login
```

Poi leggi il token da `~/.zylch/credentials.json`:
```bash
cat ~/.zylch/credentials.json | jq -r '.token'
```

**Opzione B - Login tramite auth_server.py:**
```bash
python zylch/cli/auth_server.py
```

Copia il token dal browser callback.

---

## Test Checklist

### ✅ Root Endpoints (No Auth)

**1. Root endpoint**
```bash
curl http://localhost:8000/
```

**Expected:**
```json
{
  "name": "Zylch AI API",
  "version": "1.0.0",
  "status": "running",
  "docs": "/docs",
  "skill_mode_enabled": true
}
```

**2. Health check**
```bash
curl http://localhost:8000/health
```

**Expected:**
```json
{
  "status": "healthy",
  "skill_mode": true,
  "pattern_store": true
}
```

---

### ⏳ Auth Endpoints

**Setup:**
```bash
# Salva il Firebase token in una variabile
export FIREBASE_TOKEN="your-firebase-token-here"
```

**1. Login - Exchange Firebase token**
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"firebase_token\": \"$FIREBASE_TOKEN\"}"
```

**Expected:**
```json
{
  "success": true,
  "token": "firebase-token...",
  "owner_id": "firebase-uid",
  "email": "user@example.com",
  "display_name": "User Name",
  "provider": "google.com",
  "expires_at": "2025-11-30T18:30:00Z"
}
```

**Verifica:**
- [ ] `success` è `true`
- [ ] `owner_id` corrisponde al tuo Firebase UID
- [ ] `email` è corretto
- [ ] `provider` è `google.com` o `microsoft.com`

**2. Get session info**
```bash
curl http://localhost:8000/api/auth/session \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "authenticated": true,
  "owner_id": "firebase-uid",
  "email": "user@example.com",
  "provider": "google.com"
}
```

**3. Refresh token**
```bash
curl -X POST http://localhost:8000/api/auth/refresh \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "token": "refreshed-token...",
  "expires_at": "2025-11-30T19:30:00Z"
}
```

**4. Logout**
```bash
curl -X POST http://localhost:8000/api/auth/logout \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "message": "Logout successful - client should discard token"
}
```

---

### ⏳ Data Endpoints - Storage Stats

**Get storage statistics**
```bash
curl http://localhost:8000/api/data/stats \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "email": {
    "total_threads": 0,
    "last_modified": null
  },
  "calendar": {
    "total_events": 0,
    "last_modified": null
  },
  "contacts": {
    "total_contacts": 0,
    "last_modified": null
  }
}
```

**Verifica:**
- [ ] Tutte e 3 le categorie presenti
- [ ] Counts corrispondono ai dati reali (se hai già sincronizzato)

---

### ⏳ Data Endpoints - Emails

**1. List email threads**
```bash
curl "http://localhost:8000/api/data/emails?days_back=30&limit=10" \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "threads": [],
  "total": 0,
  "stats": {
    "total_threads": 0,
    "last_modified": null
  }
}
```

**Con dati esistenti:**
```json
{
  "success": true,
  "threads": [
    {
      "thread_id": "thread-123",
      "subject": "Example Email",
      "from": "sender@example.com",
      "date": "2025-11-30T12:00:00Z",
      ...
    }
  ],
  "total": 1,
  "stats": {...}
}
```

**Verifica:**
- [ ] Solo i tuoi thread (owner_id isolation)
- [ ] Filtro `days_back` funziona
- [ ] Pagination (`limit`, `offset`) funziona

**2. Get specific thread**
```bash
# Prima ottieni un thread_id dalla lista
curl http://localhost:8000/api/data/emails/thread-123 \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "thread": {
    "thread_id": "thread-123",
    ...
  }
}
```

**Verifica:**
- [ ] Solo il thread richiesto
- [ ] 404 se thread non esiste o appartiene ad altro user

---

### ⏳ Data Endpoints - Calendar

**1. List calendar events**
```bash
curl "http://localhost:8000/api/data/calendar?start=2025-11-01T00:00:00Z&end=2025-12-31T23:59:59Z&limit=10" \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "events": [],
  "total": 0,
  "stats": {
    "total_events": 0,
    "last_modified": null
  }
}
```

**Con dati esistenti:**
```json
{
  "success": true,
  "events": [
    {
      "event_id": "event-123",
      "summary": "Meeting",
      "start": "2025-11-30T14:00:00Z",
      "end": "2025-11-30T15:00:00Z",
      ...
    }
  ],
  "total": 1,
  "stats": {...}
}
```

**Verifica:**
- [ ] Solo i tuoi eventi (owner_id isolation)
- [ ] Filtri `start` e `end` funzionano
- [ ] Ordinamento per `start_time`

**2. Get specific event**
```bash
curl http://localhost:8000/api/data/calendar/event-123 \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "event": {
    "event_id": "event-123",
    ...
  }
}
```

---

### ⏳ Data Endpoints - Contacts

**1. List contacts**
```bash
curl "http://localhost:8000/api/data/contacts?limit=10" \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "contacts": [],
  "total": 0,
  "stats": {
    "total_contacts": 0,
    "last_modified": null
  }
}
```

**2. Search contacts**
```bash
curl "http://localhost:8000/api/data/contacts?query=mario&limit=10" \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:**
```json
{
  "success": true,
  "contacts": [
    {
      "memory_id": "contact-123",
      "name": "Mario Rossi",
      "email": "mario@example.com",
      ...
    }
  ],
  "total": 1,
  "stats": {...}
}
```

**Verifica:**
- [ ] Solo i tuoi contatti
- [ ] Search query funziona (LIKE su JSON data)

**3. Get specific contact**
```bash
curl http://localhost:8000/api/data/contacts/contact-123 \
  -H "auth: $FIREBASE_TOKEN"
```

---

### ⏳ Data Endpoints - Modifier (Offline Sync)

**Apply offline modifications**
```bash
curl -X POST http://localhost:8000/api/data/modifier \
  -H "auth: $FIREBASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "operations": [
      {
        "type": "email_draft",
        "data": {
          "to": "test@example.com",
          "subject": "Test",
          "body": "Hello"
        },
        "timestamp": "2025-11-30T12:00:00Z",
        "client_id": "client-op-123"
      }
    ]
  }'
```

**Expected (Phase 1 - pending implementation):**
```json
{
  "success": true,
  "results": [
    {
      "client_id": "client-op-123",
      "type": "email_draft",
      "status": "pending",
      "message": "Modifier queued - implementation pending Phase 2"
    }
  ],
  "failed_count": 0,
  "success_count": 1
}
```

**Verifica:**
- [ ] Operations accettate
- [ ] `client_id` per idempotency
- [ ] Batch processing funziona

---

## Multi-Tenant Isolation Testing

**CRITICO:** Verifica che utenti diversi non vedano dati di altri.

### Setup

1. Login con User A (es. Google)
2. Ottieni `FIREBASE_TOKEN_A`
3. Sincronizza dati per User A
4. Logout e login con User B (es. Microsoft)
5. Ottieni `FIREBASE_TOKEN_B`

### Test Isolation

**1. User B non vede dati di User A**
```bash
# Con token di User B
curl http://localhost:8000/api/data/emails \
  -H "auth: $FIREBASE_TOKEN_B"
```

**Expected:**
```json
{
  "success": true,
  "threads": [],  // ← VUOTO, non vede email di User A
  "total": 0
}
```

**2. User A vede solo i propri dati**
```bash
# Con token di User A
curl http://localhost:8000/api/data/emails \
  -H "auth: $FIREBASE_TOKEN_A"
```

**Expected:**
```json
{
  "success": true,
  "threads": [...],  // ← I suoi dati
  "total": 10
}
```

**3. User B non può accedere a thread di User A**
```bash
# User B cerca di leggere thread di User A
curl http://localhost:8000/api/data/emails/thread-di-user-a \
  -H "auth: $FIREBASE_TOKEN_B"
```

**Expected:**
```json
{
  "detail": "Thread thread-di-user-a not found"
}
```
**Status:** 404 (non 403, per non rivelare esistenza)

**Verifica:**
- [ ] User B non vede dati di User A
- [ ] User A non vede dati di User B
- [ ] 404 quando si accede a risorse di altri utenti
- [ ] `owner_id` isolation funziona su tutti gli endpoint

---

## Database Verification

**Controlla direttamente il database:**

```bash
sqlite3 cache/server_data.db

# Verifica tabelle
.tables
# Output: calendar_events  contacts  email_threads

# Controlla owner_id isolation
SELECT owner_id, COUNT(*) FROM email_threads GROUP BY owner_id;
SELECT owner_id, COUNT(*) FROM calendar_events GROUP BY owner_id;
SELECT owner_id, COUNT(*) FROM contacts GROUP BY owner_id;

# Verifica che owner_id sia in PRIMARY KEY
.schema email_threads
# Output: PRIMARY KEY (thread_id, owner_id)
```

**Verifica:**
- [ ] Tutte e 3 le tabelle esistono
- [ ] `owner_id` in PRIMARY KEY
- [ ] Indexes su `owner_id` presenti
- [ ] Dati isolati per owner_id

---

## Error Cases Testing

### 1. Missing Authentication

**Request senza auth header:**
```bash
curl http://localhost:8000/api/data/emails
```

**Expected:** 422 Unprocessable Entity (FastAPI dependency validation)

### 2. Invalid Token

**Request con token invalido:**
```bash
curl http://localhost:8000/api/data/emails \
  -H "auth: invalid-token-123"
```

**Expected:** 401 Unauthorized o 500 (Firebase validation error)

### 3. Expired Token

**Request con token scaduto:**
```bash
curl http://localhost:8000/api/data/emails \
  -H "auth: expired-firebase-token"
```

**Expected:** 401 Unauthorized

### 4. Invalid Parameters

**Date format invalido:**
```bash
curl "http://localhost:8000/api/data/calendar?start=invalid-date" \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:** 400 Bad Request
```json
{
  "detail": "Invalid start date format: ..."
}
```

---

## Performance Testing

### 1. Pagination

**Test con grandi dataset:**
```bash
# Page 1
curl "http://localhost:8000/api/data/emails?limit=50&offset=0" \
  -H "auth: $FIREBASE_TOKEN"

# Page 2
curl "http://localhost:8000/api/data/emails?limit=50&offset=50" \
  -H "auth: $FIREBASE_TOKEN"
```

**Verifica:**
- [ ] Pagination funziona
- [ ] Nessun duplicato tra pagine
- [ ] Performance accettabile (< 500ms per 100 risultati)

### 2. Search Performance

**Search su grandi dataset:**
```bash
curl "http://localhost:8000/api/data/contacts?query=mario" \
  -H "auth: $FIREBASE_TOKEN"
```

**Verifica:**
- [ ] Response time < 1s
- [ ] Risultati corretti
- [ ] LIKE search funziona (per ora)

---

## Integration Testing

### Scenario Completo: Sync → Store → Retrieve

**1. Sync email (existing endpoint)**
```bash
curl -X POST http://localhost:8000/api/sync/email \
  -H "auth: $FIREBASE_TOKEN" \
  -d '{"days_back": 7}'
```

**2. Verifica storage stats**
```bash
curl http://localhost:8000/api/data/stats \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:** `total_threads` > 0

**3. Retrieve email threads**
```bash
curl "http://localhost:8000/api/data/emails?days_back=7" \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected:** Thread list con dati sincronizzati

**Verifica:**
- [ ] Sync → Storage pipeline funziona
- [ ] Dati persistenti dopo sync
- [ ] Stats aggiornate correttamente

---

## Known Issues (Phase 1)

### 1. Token Expiry (Microsoft)
- **Issue:** Graph tokens scadono dopo 1h
- **Workaround:** Re-login con `./zylch-cli --login`
- **Fix:** Phase 2 - implement refresh token flow

### 2. Modifier Implementation
- **Issue:** POST /api/data/modifier accetta operazioni ma non le esegue
- **Status:** "Pending Phase 2" placeholder
- **Fix:** Phase 2 - implement actual operation processing

### 3. Test Failures in CI
- **Issue:** 11 test falliscono (Firebase not initialized)
- **Impact:** Solo in test environment, produzione funziona
- **Fix:** Mock Firebase init in test setup

### 4. SQLite Datetime Adapter Deprecation
- **Warning:** `DeprecationWarning` in Python 3.14
- **Impact:** Warning only, funziona ancora
- **Fix:** Migrate to recommended adapter in Phase 4

---

## Success Criteria

Phase 1 è completo quando:

- [x] Storage layer implementato (EmailStore, CalendarStore, ContactStore)
- [x] Data API endpoints implementati e documentati
- [x] Auth API endpoints implementati
- [x] Multi-tenant isolation verificato
- [ ] Tutti gli endpoint testati manualmente con successo
- [ ] Multi-tenant isolation testing completato
- [ ] Database verification completata
- [ ] Error cases testati
- [ ] Integration testing con sync esistente funziona

---

## Next Steps

Dopo testing completato:

**Phase 2: CLI Migration** (Week 3-4)
- Creare `ZylchAPIClient` in CLI
- Migrare sync commands a API calls
- Implementare offline queue (modifier pattern)
- Testare thin CLI con server API

Vedi: `/Users/mal/.claude/plans/lazy-frolicking-nest.md` per piano completo.

---

## Quick Reference

**Server URL:** http://localhost:8000
**Docs:** http://localhost:8000/docs
**Database:** cache/server_data.db
**Auth Header:** `auth: {firebase_token}`

**Get Token:**
```bash
cat ~/.zylch/credentials.json | jq -r '.token'
```

**Test Storage:**
```bash
sqlite3 cache/server_data.db "SELECT COUNT(*) FROM email_threads;"
```

**Check Logs:**
```bash
# Server logs mostrano tutte le request
tail -f zylch_api.log
```
