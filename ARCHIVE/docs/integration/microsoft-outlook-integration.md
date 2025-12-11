# Microsoft Outlook Integration

**Data:** 2025-11-30
**Status:** ✅ Implementato

## Panoramica

Zylch AI ora supporta sia Gmail che Microsoft Outlook/365 per la gestione delle email. Il provider viene selezionato automaticamente in base al metodo di login (Google o Microsoft).

## Architettura

```
Login Method → Provider Detection → Email Client
─────────────────────────────────────────────────
Google Login → provider="google.com" → GmailClient
Microsoft    → provider="microsoft.com" → OutlookClient
```

### Principio: Provider = Metodo di Login

- **Login con Google** → usa Gmail API
- **Login con Microsoft** → usa Graph API per Outlook
- Niente login Email/Password (o richiede scelta provider)

Un utente = un provider email. Semplice e chiaro.

---

## File Implementati

### 1. OutlookClient (`zylch/tools/outlook.py`)

Client completo per Microsoft Graph API.

**Metodi principali:**
```python
class OutlookClient:
    def authenticate() -> bool
    def search_messages(query: str, max_results: int) -> List[Dict]
    def get_message(message_id: str) -> Optional[Dict]
    def send_message(to: str, subject: str, body: str) -> Optional[Dict]
    def create_draft(to: str, subject: str, body: str, ...) -> Optional[Dict]
    def update_draft(draft_id: str, ...) -> Optional[Dict]
    def send_draft(draft_id: str) -> bool
    def list_drafts() -> List[Dict]
```

**Graph API Endpoints usati:**
- `GET /me/messages` - Lista messaggi
- `GET /me/messages/{id}` - Leggi messaggio
- `POST /me/sendMail` - Invia email
- `POST /me/messages` - Crea bozza
- `PATCH /me/messages/{id}` - Modifica bozza
- `POST /me/messages/{id}/send` - Invia bozza
- `GET /me/mailFolders/Drafts/messages` - Lista bozze

**Formato messaggi normalizzato:**
```python
{
    'id': str,                    # Graph API message ID
    'thread_id': str,             # conversationId
    'from': str,                  # Email mittente
    'to': List[str],              # Destinatari
    'cc': List[str],              # CC
    'subject': str,
    'date': str,                  # ISO format
    'body': str,                  # Plain text
    'message_id': str,            # Internet Message-ID
    'in_reply_to': str,           # Threading
    'references': str,            # Threading
}
```

Questo formato è identico a quello di GmailClient, permettendo compatibilità completa con EmailArchiveManager e tutti i tool esistenti.

---

### 2. Auth Server (`zylch/cli/auth_server.py`)

**Modifiche:**

Login Microsoft ora richiede scopes Graph API:
```javascript
provider.addScope('https://graph.microsoft.com/Mail.Read');
provider.addScope('https://graph.microsoft.com/Mail.Send');
provider.addScope('https://graph.microsoft.com/Mail.ReadWrite');
provider.addScope('https://graph.microsoft.com/User.Read');
```

Il Graph token viene estratto dal credential OAuth:
```javascript
const credential = result.credential;
const graphToken = credential ? credential.accessToken : null;
await sendTokenToServer(result.user, graphToken, 'microsoft.com');
```

**Callback server salvage:**
- `graph_token` - Microsoft Graph API access token
- `provider` - "google.com" o "microsoft.com"

---

### 3. Configurazione (`zylch/config.py`)

**Nuovi campi:**
```python
# Microsoft Graph API (for Outlook email)
graph_token: str = Field(
    default="",
    description="Microsoft Graph API access token (from login)"
)
graph_refresh_token: str = Field(
    default="",
    description="Microsoft Graph API refresh token"
)
auth_provider: str = Field(
    default="google.com",
    description="Authentication provider (google.com or microsoft.com)"
)
```

---

### 4. CLI Main (`zylch/cli/main.py`)

**Caricamento credenziali:**
```python
# Get user info from credentials
creds = self.auth.get_credentials()
self.owner_id = creds["owner_id"]
self.user_email = creds.get("email", "")
self.user_display_name = creds.get("display_name", "")

# Set provider and Microsoft Graph token in settings
settings.auth_provider = creds.get("provider", "google.com")
if "graph_token" in creds:
    settings.graph_token = creds["graph_token"]
if "graph_refresh_token" in creds:
    settings.graph_refresh_token = creds.get("graph_refresh_token", "")
```

---

### 5. Factory (`zylch/tools/factory.py`)

**Provider detection:**
```python
# Email client - choose based on auth provider
if config.auth_provider == "microsoft.com":
    # Microsoft Outlook client
    email_client = OutlookClient(
        graph_token=config.graph_token,
        account=config.user_email,
    )
    logger.info("Using Microsoft Outlook for email")
else:
    # Gmail client (default)
    email_client = GmailClient(
        credentials_path=config.google_credentials_path,
        token_dir=config.google_token_path,
    )
    logger.info("Using Gmail for email")

# Email archive manager (works with both)
email_archive = EmailArchiveManager(gmail_client=email_client)
```

Tutti i tool email usano `email_client` invece di `gmail` hardcodato.

---

## Credentials File

**Formato:** `~/.zylch/credentials.json`

```json
{
    "token": "firebase_id_token...",
    "owner_id": "firebase_uid",
    "email": "mario@outlook.com",
    "display_name": "Mario",
    "provider": "microsoft.com",
    "graph_token": "graph_api_access_token...",
    "graph_expires_at": "2025-11-30T14:30:00Z",
    "expires_at": "2025-11-30T14:30:00Z",
    "created_at": "2025-11-30T13:30:00Z"
}
```

**Campi provider-specific:**
- **Google:** Nessun campo extra (usa token pickle separato)
- **Microsoft:** `graph_token`, `graph_expires_at`

---

## Azure AD Configuration

### Permessi Richiesti

**App Registration → API permissions → Microsoft Graph:**
- `Mail.Read` - Delegated - Leggere email dell'utente
- `Mail.Send` - Delegated - Inviare email come utente
- `Mail.ReadWrite` - Delegated - Leggere e modificare email (per bozze)
- `Calendars.Read` - Delegated - Leggere calendario dell'utente
- `Calendars.ReadWrite` - Delegated - Leggere e modificare calendario (per creare eventi)
- `User.Read` - Delegated - Leggere profilo utente (già presente dal login)

**Note:**
- Usare permessi **Delegated**, non Application
- Non serve Admin Consent per account personali Microsoft
- Gli utenti vedranno il consenso al primo login

### Redirect URI

Configurato nell'app Azure AD:
```
https://zylch-test-9a895.firebaseapp.com/__/auth/handler
```

Firebase gestisce il redirect OAuth.

---

## Testing

### 1. Test Login Microsoft

```bash
# Logout da Google se loggato
./zylch-cli --logout

# Login con Microsoft
./zylch-cli --login
```

**Nel browser:**
1. Click "Continue with Microsoft"
2. Login con account Microsoft (@outlook.com, @hotmail.com, @live.com, o aziendale)
3. Accetta permessi:
   - Sign you in and read your profile
   - Maintain access to data you have given it access to
   - Read your mail
   - Send mail as you
   - Read and write access to your mail

**Verifica credentials:**
```bash
cat ~/.zylch/credentials.json | jq .
```

Dovrebbe contenere:
- `"provider": "microsoft.com"`
- `"graph_token": "eyJ..."`
- `"email": "tuo@outlook.com"`

### 2. Test CLI con Outlook

```bash
# Avvia CLI
./zylch-cli -l info
```

**Log atteso:**
```
🏗️  Initializing Zylch AI...
Using Microsoft Outlook for email
Microsoft Graph API authenticated successfully for mario@outlook.com
```

**Comandi da testare:**
```
/sync                    # Sync email da Outlook
/archive --stats         # Verifica archivio email
/archive --search "test" # Cerca email
```

**Inviare bozza:**
```
You: Draft an email to test@example.com subject "Test" saying "Hello from Outlook via Zylch!"
```

### 3. Test Search & Send

**Programmaticamente:**
```python
from zylch.tools.outlook import OutlookClient

client = OutlookClient(graph_token="your_token")
client.authenticate()

# Search
messages = client.search_messages("test", max_results=10)
for msg in messages:
    print(f"{msg['from']}: {msg['subject']}")

# Send
client.send_message(
    to="test@example.com",
    subject="Test from Outlook API",
    body="Hello from Zylch!"
)
```

---

## Limitazioni Attuali

### 1. Token Expiry

**Problema:** Graph tokens scadono dopo 1 ora.

**Soluzione temporanea:** Rifare login con `./zylch-cli --login`

**Soluzione permanente (TODO):** Implementare refresh automatico:
```python
def refresh_graph_token(refresh_token: str) -> dict:
    """Refresh Microsoft Graph access token using refresh token."""
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": AZURE_CLIENT_ID,
        "scope": "https://graph.microsoft.com/Mail.Read ...",
    }
    response = requests.post(url, data=data)
    return response.json()
```

**Nota:** Firebase OAuth non fornisce `refresh_token` per Graph API. Serve implementare OAuth flow diretto con Azure AD.

### 2. HTML to Plain Text

**Problema:** Graph API restituisce email in HTML. Conversione HTML → plain text è basica.

**Soluzione (TODO):** Usare libreria come `html2text` o `beautifulsoup4`:
```python
from html2text import html2text

body = html2text(body_html)
```

### 3. Threading Headers

**Problema:** `in_reply_to` e `references` non estratti (servono per threading perfetto).

**Soluzione (TODO):** Parsare `internetMessageHeaders` da Graph API:
```python
headers = msg.get("internetMessageHeaders", [])
in_reply_to = next((h["value"] for h in headers if h["name"] == "In-Reply-To"), "")
references = next((h["value"] for h in headers if h["name"] == "References"), "")
```

---

## Compatibilità

### Email Archive

`EmailArchiveManager` funziona con entrambi i provider senza modifiche. Il formato messaggio normalizzato è identico.

### Sync Manager

`EmailSyncManager` usa l'archive, quindi funziona con entrambi.

### Tool Email

Tutti i tool email (`_SendEmailTool`, `_DraftEmailTool`, etc.) funzionano con entrambi i client perché usano la stessa interfaccia.

### Google Calendar

Anche gli utenti Microsoft possono collegare Google Calendar (OAuth separato). Il calendario non dipende dal provider email.

---

## Future Enhancements

### 1. Microsoft Calendar

Aggiungere supporto per Outlook Calendar via Graph API:
```python
# GET /me/calendars
# GET /me/events
# POST /me/events
```

Creare `OutlookCalendarClient` parallelo a `GoogleCalendarClient`.

### 2. Dual Provider Support

Permettere a un utente di collegare ENTRAMBI Gmail e Outlook:
```json
{
    "provider": "both",
    "gmail_enabled": true,
    "outlook_enabled": true,
    "graph_token": "...",
}
```

Factory creerebbe entrambi i client e l'archive gestirebbe email da entrambe le fonti.

### 3. Token Refresh Automatico

Background job che refresha il Graph token ogni 50 minuti.

### 4. Offline Access

Salvare `refresh_token` per permettere accesso anche dopo scadenza token.

---

## Troubleshooting

### "Microsoft Graph token not found"

**Causa:** Hai fatto login con Google, non Microsoft.

**Soluzione:**
```bash
./zylch-cli --logout
./zylch-cli --login  # Scegli Microsoft
```

### "Token validation failed: 401"

**Causa:** Token scaduto (1 ora).

**Soluzione:**
```bash
./zylch-cli --login  # Refresh token
```

### "Auth provider google.com but using Outlook"

**Causa:** Credentials file corrotto o vecchio.

**Soluzione:**
```bash
rm ~/.zylch/credentials.json
./zylch-cli --login
```

### "No messages found" ma ci sono email

**Causa:** Graph API $search richiede sintassi specifica.

**Debug:**
```python
# In OutlookClient.search_messages(), aggiungi:
logger.info(f"Search params: {params}")
```

---

## API Reference

### Microsoft Graph API

**Base URL:** `https://graph.microsoft.com/v1.0`

**Documentazione:**
- [Graph Mail API Overview](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview)
- [Messages API Reference](https://learn.microsoft.com/en-us/graph/api/resources/message)
- [Send Mail](https://learn.microsoft.com/en-us/graph/api/user-sendmail)

**Rate Limits:**
- 10,000 requests per 10 minutes per app
- Throttling: 429 Too Many Requests

**Pagination:**
```python
response = requests.get(endpoint, params={"$top": 50})
next_link = response.json().get("@odata.nextLink")
```

---

## Multi-Tenant Security (2025-11-30)

### Bug Critici Fixati

Durante il testing è emerso un bug critico: utente loggato con Microsoft vedeva dati dell'account Google.

**Root Cause Identificate:**

1. **GmailClient senza account parameter** (factory.py:151)
   - Fix: Aggiunto `account=config.user_email`
   - Ora usa token account-specific invece di generico

2. **Token path condiviso** (config.py:41-43)
   - Fix: Cambiato da `credentials/google_tokens/` a `~/.zylch/google_tokens`
   - Isolamento per-user nella home directory

3. **GoogleCalendarClient sempre inizializzato** (factory.py:169-192)
   - Fix: Condizionale in base a provider
   - Microsoft users non caricano Google Calendar a meno che esplicitamente configurato

**Token Isolation Pattern:**
- Google: `~/.zylch/google_tokens/token_<email>.pickle`
- Microsoft: `~/.zylch/credentials.json` (graph_token)
- Nessun token condiviso tra owner diversi

**Architettura Multi-Tenant:**
```
Firebase UID (owner_id)
    ↓
Zylch Assistant (1:1 enforced)
    ↓
Email Channels (Google/Microsoft)
```

**StarChat Requirements:**
- Database schema: vedere `STARCHAT_REQUESTS.md` Request #5
- Tabella `zylch_assistants` per owner_id → zylch_assistant_id mapping
- Tabella `zylch_oauth_tokens` per token storage centralizzato
- firebase_uid isolation su tutte le tabelle

---

## Summary

✅ **Implementato:**
- OutlookClient completo
- Login Microsoft con Graph scopes
- Provider detection automatica
- Compatibilità con tutti i tool esistenti
- **Multi-tenant security fixes** (account isolation, token path isolation, conditional calendar)

⏳ **TODO Future:**
- Token refresh automatico
- HTML to plain text migliorato
- Threading headers extraction
- Microsoft Calendar support

**Effort totale:** ~6 ore sviluppo + 2 ore security fixes

**Testing:** Pronto per testing manuale con account Microsoft reale.
