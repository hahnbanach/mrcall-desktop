# Unified Credentials & Token Storage

**See [ARCHITECTURE.md](../ARCHITECTURE.md) for system overview**

## Critical: Credential Storage Policy

### ⚠️ NO FILESYSTEM FALLBACK

**1. NO FILESYSTEM FALLBACK**
- All credentials are stored in Supabase **only**
- The filesystem fallback has been **completely removed** from `token_storage.py`
- If Supabase is not configured, the system raises `ValueError` (no silent degradation)
- This applies to: OAuth tokens, API keys, all provider credentials

**2. BYOK (Bring Your Own Key) ONLY**
- User-specific API credentials are **NOT** loaded from system `.env`
- Users must connect each service via `/connect <provider>` command
- Credentials stored per-user in Supabase with Fernet encryption
- **BYOK providers**: Anthropic, Pipedrive, Vonage, future integrations

**3. System vs User Credentials**

| Credential Type | Storage Location | Example |
|-----------------|------------------|---------|
| System config | `.env` / Railway | `SUPABASE_URL`, `FIREBASE_*`, `ENCRYPTION_KEY` |
| User credentials | Supabase `oauth_tokens` | Anthropic API key, Vonage API key/secret |
| OAuth tokens | Supabase `oauth_tokens` | Google OAuth, Microsoft Graph tokens |

**Why BYOK?**
- Multi-tenant security: Each user's data isolated
- Cost transparency: Users pay for their own API usage
- Privacy: No shared API keys across users
- Compliance: Users control their own credentials

## Token Storage Architecture

All credentials are now stored in a single JSONB column for flexibility and ease of adding new providers.

### Database Schema

**`oauth_tokens` table**:

| Column | Purpose | Encrypted? |
|--------|---------|------------|
| `owner_id` | Firebase UID (partition key) | — |
| `provider` | Short key matching `integration_providers.provider_key` (`google`, `microsoft`, `anthropic`, `vonage`, etc.) | — |
| `email` | User's email address | ❌ |
| `credentials` | **JSONB**: All provider credentials in unified format | ✅ Fernet (whole JSONB) |
| `connection_status` | `connected`, `disconnected`, `error` | ❌ |
| `scopes` | OAuth scopes (comma-separated) | ❌ |
| `updated_at` | Last credential update timestamp | ❌ |

### Credentials JSONB Structure

```json
{
  "google": {
    "token_data": "base64_pickled_credentials",
    "provider": "google",
    "email": "user@gmail.com"
  },
  "microsoft": {
    "access_token": "...",
    "refresh_token": "...",
    "expires_at": "2025-12-10T15:30:00Z",
    "provider": "microsoft",
    "email": "user@outlook.com"
  },
  "anthropic": {
    "api_key": "sk-ant-...",
    "provider": "anthropic"
  },
  "vonage": {
    "api_key": "...",
    "api_secret": "...",
    "from_number": "+1234567890",
    "provider": "vonage"
  }
}
```

### Key Design Decisions

1. **Short provider keys**: Use `google`, `microsoft`, `anthropic` (not `google.com`, `microsoft.com`) to match `integration_providers.provider_key`
2. **Whole-JSONB encryption**: The entire credentials object is encrypted as one blob (not per-field)
3. **Provider self-identification**: Each credential object includes a `provider` field for validation
4. **No legacy columns**: Old columns (`google_token_data`, `graph_access_token`, etc.) removed in favor of unified storage

### Storage Methods

**`zylch/storage/supabase_client.py`**:

```python
# Store credentials (encrypts automatically)
store_oauth_token(
    owner_id=owner_id,
    provider="google",  # Short key
    email=email,
    google_token_data=token_data  # Stored in credentials JSONB
)

# The JSONB structure is built internally:
# credentials = {
#     "google": {
#         "token_data": token_data,
#         "provider": "google",
#         "email": email
#     }
# }
# data['credentials'] = encrypt(json.dumps(credentials))
```

### Detection Logic

**`zylch/integrations/registry.py`**:

```python
# Check if user has credentials for a provider
if conn.get('credentials'):
    decrypted_json = decrypt(conn['credentials'])
    all_creds = json.loads(decrypted_json)
    has_credentials = bool(all_creds.get(provider_key))  # e.g., all_creds.get('google')
```

### Benefits of Unified Approach

- ✅ Easy to add new providers (just add to JSONB, no schema changes)
- ✅ Consistent encryption handling
- ✅ Single lookup query returns all user's credentials
- ✅ No NULL column bloat (80% empty columns eliminated)

## Configuration

- **Environment**: Railway env vars (backend), Vercel env vars (frontend)
- **Defaults**: `zylch/config.py` (Pydantic settings)
- **System .env only contains**: Supabase config, Firebase config, Google OAuth client, encryption key
- **NOT in .env**: User credentials (Anthropic, Pipedrive, Vonage) - these are BYOK via `/connect`

## Firebase Service Account

Stored as **Base64-encoded JSON** in Railway env vars:

```bash
# Encode the service account JSON:
cat firebase-service-account.json | base64

# Set in Railway:
FIREBASE_SERVICE_ACCOUNT_BASE64=eyJ0eXBlIjoic2VydmljZV9hY2NvdW50Ii...
```

Backend decodes automatically on startup (`zylch/api/firebase_auth.py`).

## Encryption

### Sensitive Data Encryption

**All User Credentials (BYOK)**:
- **Storage**: Supabase `oauth_tokens` table in unified `credentials` JSONB column
- **Encryption**: Fernet (AES-128-CBC + HMAC) via `zylch/utils/encryption.py`
- **Key**: `ENCRYPTION_KEY` environment variable (set in Railway)
- **No fallback**: If user hasn't connected a provider, tools return helpful error (not system default)
- **Applies to**: Anthropic API key, Vonage credentials, Pipedrive token, OAuth tokens

**Flow**:
```
User runs /connect <provider>
  → User enters credentials
  → encrypt(credentials_json) → Supabase (encrypted blob)

Tool execution
  → get_provider_credentials(owner_id, provider)
  → decrypt() → use with provider API
  → If not found: "Provider not connected. Use /connect <provider>"
```

**OAuth Tokens (Google/Microsoft)**:
- **Storage**: Supabase `oauth_tokens` table in `credentials` JSONB
- **Encryption**: Same Fernet encryption (whole JSONB encrypted)
- **Scopes stored**: Plaintext (not sensitive)

### Encryption Implementation

**`zylch/utils/encryption.py`**:

```python
from zylch.utils.encryption import encrypt, decrypt, is_encryption_enabled

# Check if encryption is available
if is_encryption_enabled():
    encrypted = encrypt("sk-ant-xxx")  # Returns gAAA... (Fernet token)
    decrypted = decrypt(encrypted)      # Returns original key

# Graceful fallback: returns original if ENCRYPTION_KEY not set
```

### Key Management

- Generate key once: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- Store in Railway env vars as `ENCRYPTION_KEY`
- **Never commit** encryption keys to git

## Unified Credentials System (StarChat Pattern)

### Problem

Each integration provider (Google, Anthropic, Pipedrive, Vonage, WhatsApp, Slack) previously required:
- New database columns (ALTER TABLE migrations)
- New save/get functions in `supabase_client.py`
- Hardcoded credential checking in `registry.py`
- Updated CLI autocomplete logic

This created **schema bloat** (80% NULL columns per row) and **tight coupling** between providers and code.

### Solution

Unified JSONB credentials storage inspired by StarChat's business variables pattern (database-driven instead of CSV-driven).

### Architecture

```
integration_providers.config_fields (schema definition)
  ↓
Backend APIs read schema from database
  ↓
CLI/Web UI dynamically generate input prompts
  ↓
User provides credentials
  ↓
Stored in oauth_tokens.credentials (JSONB, encrypted)
```

### Database Schema

**`integration_providers` table**:

```sql
CREATE TABLE integration_providers (
    id UUID PRIMARY KEY,
    provider_key TEXT UNIQUE NOT NULL,       -- 'google', 'anthropic', 'vonage', 'whatsapp'
    display_name TEXT NOT NULL,              -- 'Google (Gmail & Calendar)'
    category TEXT NOT NULL,                  -- 'email', 'crm', 'messaging', 'telephony'
    requires_oauth BOOLEAN DEFAULT true,     -- true = OAuth flow, false = API key
    config_fields JSONB,                     -- Schema: what credentials are needed
    is_available BOOLEAN DEFAULT true,       -- false = "Coming soon"
    oauth_url TEXT,                          -- '/api/auth/google/authorize'
    documentation_url TEXT
);
```

**Example `config_fields`**:

```json
{
  "api_key": {
    "type": "string",
    "label": "API Key",
    "required": true,
    "encrypted": true,
    "description": "Your Vonage API key"
  },
  "api_secret": {
    "type": "string",
    "label": "API Secret",
    "required": true,
    "encrypted": true,
    "description": "Your Vonage API secret"
  },
  "from_number": {
    "type": "string",
    "label": "From Number",
    "required": true,
    "encrypted": false,
    "description": "Phone number to send SMS from",
    "placeholder": "+1234567890"
  }
}
```

**`oauth_tokens.credentials` JSONB column**:

```json
{
  "vonage": {
    "api_key": "encrypted:gAAAAABh...",
    "api_secret": "encrypted:gAAAAABi...",
    "from_number": "+1234567890"
  },
  "anthropic": {
    "api_key": "encrypted:gAAAAABj..."
  },
  "google": {
    "access_token": "encrypted:gAAAAABk...",
    "refresh_token": "encrypted:gAAAAABl...",
    "expires_at": "2025-12-10T15:30:00Z",
    "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]
  },
  "metadata": {
    "vonage": {
      "connected_at": "2025-12-10T10:00:00Z"
    }
  }
}
```

### Generic Storage Methods

**Save credentials** (`supabase_client.py`):

```python
def save_provider_credentials(
    owner_id: str,
    provider_key: str,
    credentials_dict: Dict[str, Any],
    metadata_dict: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Save credentials for ANY provider using unified JSONB storage.
    Automatically encrypts sensitive fields based on config_fields.encrypted flag.
    """
    # Fetch provider config
    config_fields = get_provider_config(provider_key)

    # Encrypt sensitive fields
    encrypted_creds = {}
    for field_name, field_value in credentials_dict.items():
        if config_fields[field_name].get('encrypted', True):
            encrypted_creds[field_name] = f"encrypted:{encrypt(field_value)}"
        else:
            encrypted_creds[field_name] = field_value

    # Build unified structure
    all_credentials[provider_key] = encrypted_creds

    # Store encrypted JSONB
    oauth_tokens.credentials = encrypt(json.dumps(all_credentials))
```

**Get credentials** (`supabase_client.py`):

```python
def get_provider_credentials(
    owner_id: str,
    provider_key: str,
    include_metadata: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Get credentials for ANY provider using unified JSONB storage.
    Automatically decrypts sensitive fields.

    DUAL-READ: Tries new credentials column first, falls back to legacy columns.
    """
```

**Universal API endpoint** (`api/routes/connections.py`):

```python
POST /api/connections/provider/{provider_key}/credentials
{
  "credentials": {
    "api_key": "abc123",
    "api_secret": "xyz789",
    "from_number": "+1234567890"
  },
  "metadata": { ... }
}
```

### How to Add a New Provider

**Before (Legacy Approach)**:
1. Write SQL migration: `ALTER TABLE oauth_tokens ADD COLUMN whatsapp_phone_id TEXT, whatsapp_access_token TEXT, whatsapp_business_id TEXT;`
2. Add `save_whatsapp_credentials()` to `supabase_client.py`
3. Add `get_whatsapp_credentials()` to `supabase_client.py`
4. Update `registry.py` credential checking logic
5. Update CLI autocomplete
6. Deploy new code

**After (Unified Approach)**:
1. Insert row into `integration_providers` table:

```sql
INSERT INTO integration_providers (provider_key, display_name, category, config_fields, is_available)
VALUES (
  'whatsapp',
  'WhatsApp Business',
  'messaging',
  '{"phone_id": {"type": "string", "label": "Phone ID", "required": true, "encrypted": false},
    "access_token": {"type": "string", "label": "Access Token", "required": true, "encrypted": true},
    "business_account_id": {"type": "string", "label": "Business Account ID", "required": true, "encrypted": false}}'::jsonb,
  true
);
```

That's it! No code changes, no migrations, no deployment needed. The universal API endpoint and CLI will automatically:
- Generate input prompts from `config_fields`
- Validate required fields
- Encrypt sensitive fields
- Store in unified JSONB format

### Migration Strategy (Pre-Alpha)

**Current Status** (December 2025):
- ✅ Legacy columns removed (no backward compatibility needed - pre-alpha)
- ✅ All credentials use unified `credentials` JSONB column only
- ✅ No dual-write/dual-read code
- ✅ Filesystem fallback removed from `token_storage.py`

**Why no migration?**
- Pre-alpha development (see warning at top of ARCHITECTURE.md)
- No production users, no data to migrate
- Clean slate approach: just use the new unified storage

### Key Files

**Database**:
- `zylch/integrations/migrations/001_create_providers_table.sql` - Initial schema
- `zylch/integrations/migrations/002_unified_credentials.sql` - Adds `credentials` JSONB column

**Backend Storage**:
- `zylch/storage/supabase_client.py` - `save_provider_credentials()`, `get_provider_credentials()`
- `zylch/integrations/registry.py` - `get_user_connections()` (dynamic credential checking)

**Backend APIs**:
- `zylch/api/routes/connections.py` - Universal credentials endpoints

**Migration**:
- `scripts/migrate_to_unified_credentials.py` - Data migration script

### Benefits

✅ **Zero schema changes** to add providers (just insert database row)
✅ **Database-driven configuration** (no CSV files like StarChat)
✅ **Dynamic UI generation** (CLI and Web read config_fields and build forms)
✅ **Less code** (3 generic functions replace 20+ provider-specific functions)
✅ **Easier testing** (one code path instead of N provider-specific paths)
✅ **Follows StarChat pattern** (adapted for SQL instead of CSV)

### Case Study: Fixing the Anthropic Connection Bug

**Problem**: User saved Anthropic API key, but `/connections` showed "Not Connected"

**Root cause**: `registry.py` returned ALL rows from `oauth_tokens` without checking if `anthropic_api_key` column had data (row existed with NULL value)

**Old fix**: Hardcoded check for `anthropic_api_key` field
**New fix**: Dynamic check for ANY provider in `credentials` JSONB

```python
# OLD (hardcoded per provider)
if provider == 'anthropic':
    has_credentials = bool(conn.get('anthropic_api_key'))
elif provider == 'pipedrive':
    has_credentials = bool(conn.get('pipedrive_api_token'))
# ... etc for each provider

# NEW (dynamic for ANY provider)
if conn.get('credentials'):
    decrypted_json = decrypt(conn['credentials'])
    all_creds = json.loads(decrypted_json)
    has_credentials = bool(all_creds.get(provider))
```

**Result**: Adding WhatsApp/Slack/Teams in the future requires ZERO code changes to credential checking logic.

## Authentication

### Firebase Authentication

- **Firebase Auth**: JWT tokens validated on all API endpoints
- **Per-user isolation**: All data scoped by `owner_id` (Firebase UID)

### OAuth 2.0 Flow (Google, Microsoft)

**CLI OAuth Flow** (December 2025):

The CLI implements a secure OAuth 2.0 flow with local callback server and CSRF protection.

**Flow Steps**:

```
1. User runs /connect google
   ↓
2. CLI spawns local HTTP server on random port (http://localhost:XXXX/callback)
   ↓
3. CLI calls backend: GET /api/auth/google/authorize?cli_callback=http://localhost:XXXX/callback
   ↓
4. Backend:
   - Generates random state token (CSRF protection)
   - Stores state in oauth_states table (owner_id, state, cli_callback, expires_at)
   - Returns Google OAuth URL with state parameter
   ↓
5. CLI opens browser to Google OAuth URL
   ↓
6. User grants permissions on Google consent screen
   ↓
7. Google redirects to: http://localhost:8000/api/auth/google/callback?code=XXX&state=YYY
   ↓
8. Backend callback handler:
   - Validates state token (from oauth_states table)
   - Exchanges authorization code for tokens (POST to Google)
   - Saves credentials to oauth_tokens table (encrypted)
   - Redirects to CLI callback: http://localhost:XXXX/callback?token=success&email=...
   ↓
9. CLI local server receives callback
   - Displays success message
   - Closes browser popup
   - Shuts down local server
```

**Key Security Features**:

1. **CSRF Protection**: State parameter stored in database, one-time use, auto-expires after 10 minutes
2. **Multi-instance Safe**: State stored in Supabase (not in-memory), works across Railway replicas
3. **No Credentials in URL**: Only non-sensitive data (`token=success`, `email=...`) in redirect
4. **Encrypted Storage**: All OAuth tokens encrypted with Fernet before database storage

**Database Tables**:

- `oauth_states`: Temporary CSRF state tokens
  - `state` (TEXT, unique): Random token
  - `owner_id` (TEXT): Firebase UID
  - `cli_callback` (TEXT): Local callback URL
  - `expires_at` (TIMESTAMPTZ): Auto-expire after 10 minutes
  - Auto-deleted after use (one-time validation)

- `oauth_tokens`: Encrypted credentials
  - `owner_id` (TEXT): Firebase UID
  - `provider` (TEXT): `google`, `microsoft`, etc.
  - `credentials` (JSONB, encrypted): All provider credentials
  - Primary key: `(owner_id, provider)`

**Files**:
- `zylch-cli/zylch_cli/cli.py`: CLI OAuth flow (`_connect_google()`, `_connect_service()`)
- `zylch/api/routes/auth.py`: Backend OAuth endpoints (`google_oauth_authorize`, `google_oauth_callback`)
- `zylch/storage/supabase_client.py`: State management (`store_oauth_state()`, `get_oauth_state()`)
- `scripts/create_oauth_states_table.sql`: Database schema for CSRF protection

## Token Auto-Refresh

### Frontend Token Refresh

Firebase ID tokens expire after 1 hour. The frontend implements automatic token refresh:

**Flow**:
1. On OAuth callback, backend redirects with `?token=xxx&refresh_token=xxx`
2. Frontend stores both in localStorage (`zylch_token`, `zylch_refresh_token`)
3. `scheduleRefresh()` parses JWT expiry and sets timer for 5 minutes before expiration
4. When timer fires, `doRefreshToken()` calls Firebase's token refresh API
5. New tokens stored, new timer scheduled

**Implementation** (`frontend/src/stores/auth.ts`):

```typescript
// Firebase token refresh API
POST https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}
Body: { grant_type: 'refresh_token', refresh_token: '...' }
Response: { id_token: '...', refresh_token: '...' }
```

**Key files**:
- `frontend/src/stores/auth.ts` - `scheduleRefresh()`, `doRefreshToken()`, `getTokenExpiry()`
- `frontend/src/views/AuthCallbackView.vue` - Extracts `refresh_token` from URL
- `zylch/api/routes/auth.py` - Includes `refresh_token` in OAuth callback redirect

### CLI Token Refresh

The CLI also implements automatic token refresh:

**Flow**:
1. On login, the local auth server receives `refreshToken` from Firebase SDK
2. Stored in `~/.zylch/credentials/{provider}/credentials.json`
3. Before each prompt in the main loop, `needs_refresh()` checks if token expires within 5 minutes
4. If expiring, `refresh_firebase_token()` calls Firebase's token refresh API
5. New tokens saved to credentials file

**Implementation** (`zylch/cli/auth.py`):

```python
def refresh_firebase_token(self) -> bool:
    # Call Firebase API with stored refresh_token
    response = requests.post(
        f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}",
        json={"grant_type": "refresh_token", "refresh_token": refresh_token}
    )
    # Update credentials with new id_token
```

**Key files**:
- `zylch/cli/auth.py` - `refresh_firebase_token()`, `needs_refresh()`, `ensure_valid_token()`
- `zylch/cli/auth_server.py` - Captures `refreshToken` from Firebase SDK during login
- `zylch/cli/main.py` - Auto-refresh check in main loop

## Security & Privacy

### Data Privacy

- All user data scoped by Firebase UID (`owner_id`)
- Email content stored in Supabase (encrypted at rest by Supabase)
- Anthropic API keys encrypted with Fernet (application-level encryption)
- No data shared between users (RLS enforced)
- Data sent to Claude for analysis uses user's own API key (BYOK model)

### RLS & Service Role Key

**Important**: The backend uses Supabase's **service role key**, which **bypasses RLS entirely**.

```python
# From supabase_client.py
# Use service_role key for backend (bypasses RLS, we enforce owner_id manually)
```

**Why?**
- We use **Firebase Auth** (not Supabase Auth)
- `owner_id` is a Firebase UID (text string like `"abc123xyz"`), not a Supabase UUID
- Supabase's `auth.uid()` returns Supabase UUIDs, which don't match Firebase UIDs
- RLS policies using `auth.uid()` won't work with Firebase tokens

**How we enforce security instead**:
- Every query manually filters by `owner_id`
- The backend validates Firebase JWT before any operation
- Service role key is never exposed to frontend

**RLS policies in migrations**:
- Still defined for defense-in-depth
- Would protect if someone accidentally used the anon key
- Use `current_setting('request.jwt.claims', true)::json->>'sub'` pattern for JWT-based RLS (not `auth.uid()`)
