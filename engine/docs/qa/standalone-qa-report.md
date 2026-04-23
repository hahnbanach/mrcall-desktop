# QA Report — Zylch Standalone (Sales Assistant)

**Data**: 2026-03-31
**Tester**: Claude (QA Engineer)
**Account test**: support@mrcall.ai (Firebase UID: EWy1peBy8WdiV1AED2e1Qv0hdcM2)
**Ambiente**: Docker locale → Railway DB di produzione
**Email analizzate**: 193 (DB) + 5014 totali (IMAP), 148 non-notification negli ultimi 30 giorni

---

## 1. Matrice Funzionalità

| Comando | Risultato | Pass/Fail | Note |
|---------|-----------|-----------|------|
| `/connect status` | Mostra 9 provider, 1 connesso | **PASS** | Solo dopo seed manuale di `integration_providers` |
| `/connect google` | Restituisce OAuth URL | **FAIL** | `redirect_uri` hardcoded a porta 8000, non funziona su 8001 |
| `/sync` | Avvia sync in background | **PASS** | Job ID, progress tracking, non bloccante |
| `/sync --status` | Mostra progress sync | **PASS** | |
| `/stats` | 193 email, 92 thread, 11 task | **PASS** | |
| `/tasks` | 11 task dettagliati con priorità | **PASS** | Qualità eccellente (vedi sezione 3) |
| `/gaps` | "Command not found" | **FAIL** | Comando documentato ma non implementato |
| `/memory stats` | 49 blob, 346 sentences | **PASS** | |
| `/memory search <persona>` | Trova template, non info persona | **PARTIAL** | Ritorna template di risposta, non fatti sulla persona |
| `/calendar` | Non testato | — | Nessun calendario connesso |
| `/help` | Non testato | — | |

## 2. Bug e Errori

### BUG-001: `integration_providers` vuota su DB fresco/Railway (CRITICO)
La tabella `integration_providers` non viene populata dalle migration Alembic. I seed SQL sono in `zylch/integrations/migrations/` ma non sono integrati nel sistema di migration. Su un DB nuovo, `/connect` mostra "No providers available".

**Impatto**: Un nuovo utente non può connettere nessun servizio.
**Fix**: Integrare i seed come Alembic data migration o eseguirli in `entrypoint.sh`.

### BUG-002: `/gaps` non implementato (MEDIO)
Il comando è documentato in `docs/guides/cli-commands.md` e `docs/features/relationship-intelligence.md` ma restituisce "Command not found".

### BUG-003: `redirect_uri` OAuth hardcoded a porta 8000 (BASSO)
`/connect google` genera un OAuth URL con `redirect_uri=http://localhost:8000/...` anche quando il server gira su 8001. Dovrebbe usare la porta configurata.

### BUG-004: Firebase UID mismatch con custom token (BASSO)
Creare un utente via custom token genera un UID diverso (`support-mrcall-ai`) da quello reale (`EWy1peBy8WdiV1AED2e1Qv0hdcM2`). I dati nel DB non sono accessibili con il nuovo UID. Non è un bug di Zylch ma un gotcha dell'ambiente di test.

### BUG-005: `alembic upgrade head` fallisce con migration duplicate (MEDIO)
Due migration con ID `0002` (`add_business_id_to_background_jobs` e `add_error_logs`) causano "Multiple head revisions". La seconda è stata rinominata `0003` nel repo standalone ma il fix non è nel repo principale.

## 3. Qualità AI — Task Detection

### Valutazione complessiva: **ECCELLENTE**

Cross-reference con le email reali (IMAP) di support@mrcall.ai:

| Contatto | Task Zylch | Priorità | Accuratezza |
|----------|-----------|----------|-------------|
| Roberto Minasi (Studio Dentistico) | 3 issue: email mancanti, WhatsApp, iPhone 17 | MEDIUM | ✅ Corretto, draft dettagliato |
| Pietro Nudo | Hallucination AI, necessità istruzioni config | MEDIUM | ✅ Corretto, riconosce thread di 2 mesi |
| Marco Mazzocco (Efficient Driving) | Cambio comportamento AI, domanda voci custom | MEDIUM | ✅ Corretto |
| Domenico Santoro (Studio Dentalsi) | 3 issue tecniche, draft pronto | MEDIUM | ✅ Corretto |
| La Baita Case | Consulenza da schedulare | MEDIUM | ✅ Corretto |
| Massimo De Luca | Richiesta prefisso 081 | MEDIUM | ✅ Corretto, riconosce trial customer |
| Mr Brown Suite (Caterina) | 5+ richieste dettagliate, conversione in corso | MEDIUM | ✅ **Eccellente** — riconosce momento conversione |
| Antonietta Lonati | Config rotta senza preavviso, furiosa | MEDIUM | ✅ Corretto |
| Akezhan Yergali | Internship, da inoltrare | LOW | ✅ Corretto, non è support |
| Dario Occhiaperti (L'Eredità) | Pacchetto custom €500 | LOW | ✅ Corretto |
| Francesco Zuccaro | Riattivazione con domande piano | LOW | ✅ Corretto |

**False Positive**: 0
**False Negative**: Antonio Sorvillo (cancellazione abbonamento) — ma email del 30-31 marzo, fuori finestra sync (fino al 27)

**Draft email**: Presenti per 6/11 task. Qualità media-alta, tono corretto (professionale, empatico), ma a volte troppo lunghi.

### Punti di forza:
- **Aggregazione thread**: più email dello stesso contatto → 1 task. Funziona benissimo.
- **Contesto storico**: riconosce thread lunghi (Pietro Nudo ~2 mesi), promesse passate (sconto €15 Zuccaro)
- **Prioritizzazione**: coerente, anche se tendenzialmente troppo "MEDIUM" (nessun HIGH)
- **Draft automatici**: pronti all'uso, risparmiano tempo significativo

### Punti deboli:
- **Tutte le priorità MEDIUM**: manca granularità. Lonati (furiosa) e La Baita (nuova consulenza) non dovrebbero avere la stessa priorità
- **Nessun task HIGH**: per un support team, Lonati e Di Chiara (errore pagamento) dovrebbero essere HIGH

## 4. Qualità Memoria

### Valutazione: **PROBLEMATICA**

La memoria contiene 49 blob, ma sono quasi tutti **template di risposta** (pattern di email support), non informazioni sulle persone/entità.

- `/memory search "Antonietta Lonati"` → restituisce template generici, score 0.20
- Non ci sono blob tipo "Antonietta Lonati è dermatologa a [città], cliente dal [data], usa il numero 347..."
- La memoria funziona come **knowledge base di template email**, non come **relationship intelligence**

Questo è un problema architetturale: il memory processing (`/agent memory run email`) sta estraendo pattern di risposta invece di fatti sulle persone.

## 5. UX Issues

### UX-001: Flusso di setup troppo manuale (CRITICO)
Per arrivare a "vedere i task" un utente deve:
1. `/connect google` → completare OAuth nel browser
2. `/sync` → aspettare minuti
3. `/agent task process` → (secondo la doc, necessario ma non testato)
4. `/tasks` → finalmente vede i task

**Proposta**: Un singolo comando `/setup` o auto-sync al primo login.

### UX-002: `/gaps` documentato ma non funziona
L'utente segue la documentazione, prova `/gaps`, riceve "Command not found". Frustrazione immediata.

### UX-003: Nessun feedback durante sync lunga
La sync mostra "10%" e poi nulla per minuti. Dovrebbe mostrare conteggio email scaricate.

### UX-004: Priorità task poco differenziate
Tutti MEDIUM. Un utente con 11 task non sa da dove cominciare. Servono HIGH/CRITICAL per i casi urgenti.

### UX-005: Memoria non utile per lookup persone
`/memory search` dovrebbe restituire info sulla persona, non template di email. L'utente chiede "chi è Antonietta Lonati?" e riceve un template generico.

### UX-006: Token Firebase scade in 1 ora
Per test automatici e CLI long-running, il token scade troppo presto. Il refresh token esiste ma non c'è auto-refresh nel client.

### UX-007: `integration_providers` non seeded
Un utente che deploya Zylch fresh non può connettersi a nulla. Manca seed automatico.

## 6. Proposte di Miglioramento

### Priorità 1 (Bloccanti)
1. **Seed `integration_providers` in Alembic** — altrimenti nessun nuovo deployment funziona
2. **Implementare `/gaps`** — o rimuoverlo dalla doc
3. **Fix priorità task**: aggiungere HIGH/CRITICAL, non tutto MEDIUM

### Priorità 2 (UX significativa)
4. **Comando `/setup` one-shot**: connect + sync + process in un flusso guidato
5. **Memory processing orientato alle persone**: estrarre fatti su entità (chi è, cosa fa, storia) non solo template
6. **Auto-sync**: al login, se ultima sync > 24h, sync automatica in background

### Priorità 3 (Polish)
7. **Fix `redirect_uri` per porta variabile**
8. **Fix migration duplicate** (0002 → 0003)
9. **Progress più granulare durante sync** (email count, non solo %)
10. **Token auto-refresh** nel CLI

---

## Appendice: Ground Truth (IMAP)

Email analizzate via IMAP diretto a support@mrcall.ai:
- 5014 email totali in INBOX
- 409 negli ultimi 30 giorni
- 148 non-notification (escluse MrCall transactional)
- 71 nell'ultima settimana

Top mittenti (ultimi 30 giorni):
- Dario Occhiaperti (Banijay/L'Eredità): 9 email
- Immobiliare Leonardi: 5 email
- Mr Brown Suite: 5 email
- Francesco Zuccaro: 5 email
- Pietro Nudo: 4 email
- Capital Casa Livorno: 4 email
