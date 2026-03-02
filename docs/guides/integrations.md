---
description: |
  Unified connections system for managing external services. Available: Google (Gmail + Calendar),
  Microsoft (Outlook + Calendar), Pipedrive CRM, MrCall (phone + SMS), Vonage SMS, SendGrid
  (campaigns). Coming soon: WhatsApp, Slack, Teams. All use BYOK model - users connect via
  /connect command, credentials stored per-user in Supabase with Fernet encryption.
---

# Zylch Integrations Guide

**Last Updated**: December 2025

## Overview

Zylch provides a unified connections system for managing external service integrations. This guide covers how to view, connect, and manage integrations across email, CRM, messaging, telephony, and other services.

---

## Available Integrations

### 📧 Email & Calendar

| Provider | Category | Status | Auth Type |
|----------|----------|--------|-----------|
| **Google** (Gmail & Calendar) | Email | ✅ Available | OAuth 2.0 |
| **Microsoft** (Outlook & Calendar) | Email | ✅ Available | OAuth 2.0 |

### 💼 CRM & Sales

| Provider | Category | Status | Auth Type |
|----------|----------|--------|-----------|
| **Pipedrive** | CRM | ✅ Available | API Key |

### 💬 Messaging

| Provider | Category | Status | Auth Type |
|----------|----------|--------|-----------|
| **WhatsApp Business** | Messaging | ⏳ Coming Soon | OAuth 2.0 |
| **Slack** | Messaging | ⏳ Coming Soon | OAuth 2.0 |
| **Microsoft Teams** | Messaging | ⏳ Coming Soon | OAuth 2.0 |

### 📞 Telephony & SMS

| Provider | Category | Status | Auth Type |
|----------|----------|--------|-----------|
| **MrCall** (Phone & SMS) | Telephony | ✅ Available | API Key |
| **Vonage SMS** | Messaging | ✅ Available | API Key |

### 🎥 Video Conferencing

| Provider | Category | Status | Auth Type |
|----------|----------|--------|-----------|
| **Zoom** | Video | ⏳ Coming Soon | OAuth 2.0 |

### 🤖 AI Services

| Provider | Category | Status | Auth Type |
|----------|----------|--------|-----------|
| **Anthropic API (BYOK)** | AI | ✅ Available | API Key |

---

## Using the `/connections` Command

### View All Connections

```bash
> /connections
```

**Output:**
```
📡 Your Connections

✅ Connected:
1. 📧 Google (Gmail & Calendar) - user@gmail.com (synced 2 hours ago)
2. 📞 MrCall (Phone & SMS) - Business ID: 3002475397

❌ Available (Not Connected):
3. 📧 Microsoft (Outlook & Calendar) - Connect: /connections --connect microsoft
4. 💼 Pipedrive CRM - Requires configuration
5. 💬 Vonage SMS - Requires configuration

⏳ Coming Soon:
6. 💬 WhatsApp Business
7. 💬 Slack
8. 💬 Microsoft Teams
9. 🎥 Zoom

Summary: 2 connected, 3 available, 4 coming soon

Use /connections --connect <provider> to connect
```

### Connect a Provider

```bash
> /connections --connect google
```

**For OAuth providers (Google, Microsoft):**
```
🔗 Connect Google (Gmail & Calendar)

OAuth URL: /api/auth/google/authorize

For API clients:
Redirect user to this endpoint to initiate OAuth flow:
```
/api/auth/google/authorize?owner_id=YOUR_OWNER_ID
```

After authorization, user will be redirected back with tokens stored.
```

**For API key providers (Pipedrive, Vonage):**
```
🔧 Configure Pipedrive CRM

This integration requires manual configuration.

Required fields:
• api_token: API Token

Setup:
1. Get your credentials from Pipedrive CRM
2. Store them securely in environment variables or database
3. Run /connections to verify connection

Documentation: Contact support for setup help
```

---

## API Integration

### Get Connection Status

**Endpoint**: `GET /api/connections/status`

**Query Parameters**:
- `owner_id` (required): User's Firebase UID
- `include_unavailable` (optional): Include "coming soon" providers (default: false)

**Example Request**:
```bash
curl "http://localhost:8000/api/connections/status?owner_id=user123&include_unavailable=true"
```

**Example Response**:
```json
{
  "connections": [
    {
      "provider_key": "google",
      "display_name": "Google (Gmail & Calendar)",
      "category": "email",
      "description": "Access Gmail emails and Google Calendar events",
      "icon_url": null,
      "requires_oauth": true,
      "oauth_url": "/api/auth/google/authorize",
      "is_available": true,
      "status": "connected",
      "connected_email": "user@gmail.com",
      "last_sync": "2025-12-10T10:00:00Z",
      "connected_at": "2025-12-01T00:00:00Z"
    },
    {
      "provider_key": "microsoft",
      "display_name": "Microsoft (Outlook & Calendar)",
      "category": "email",
      "status": "disconnected",
      "requires_oauth": true,
      "oauth_url": "/api/auth/microsoft-login",
      "is_available": true
    },
    {
      "provider_key": "whatsapp",
      "display_name": "WhatsApp Business",
      "category": "messaging",
      "status": "coming_soon",
      "is_available": false
    }
  ],
  "total": 10,
  "connected_count": 1,
  "available_count": 5
}
```

### List Available Providers

**Endpoint**: `GET /api/connections/providers`

**Query Parameters**:
- `category` (optional): Filter by category (email, crm, messaging, telephony, video, ai)
- `include_unavailable` (optional): Include "coming soon" providers (default: false)

**Example Request**:
```bash
curl "http://localhost:8000/api/connections/providers?category=email"
```

**Example Response**:
```json
{
  "providers": [
    {
      "provider_key": "google",
      "display_name": "Google (Gmail & Calendar)",
      "category": "email",
      "description": "Access Gmail emails and Google Calendar events",
      "requires_oauth": true,
      "oauth_url": "/api/auth/google/authorize",
      "is_available": true,
      "config_fields": null
    },
    {
      "provider_key": "microsoft",
      "display_name": "Microsoft (Outlook & Calendar)",
      "category": "email",
      "description": "Access Outlook emails and Microsoft Calendar events",
      "requires_oauth": true,
      "oauth_url": "/api/auth/microsoft-login",
      "is_available": true,
      "config_fields": null
    }
  ]
}
```

### Get Provider Details

**Endpoint**: `GET /api/connections/providers/{provider_key}`

**Example Request**:
```bash
curl "http://localhost:8000/api/connections/providers/google"
```

**Example Response**:
```json
{
  "provider_key": "google",
  "display_name": "Google (Gmail & Calendar)",
  "category": "email",
  "description": "Access Gmail emails and Google Calendar events",
  "requires_oauth": true,
  "oauth_url": "/api/auth/google/authorize",
  "is_available": true,
  "documentation_url": null,
  "icon_url": null,
  "config_fields": null,
  "created_at": "2025-12-10T00:00:00Z",
  "updated_at": "2025-12-10T00:00:00Z"
}
```

---

## OAuth Connection Flow

### Google (Gmail & Calendar)

1. **User initiates connection**: Frontend redirects to `/api/auth/google/authorize`
2. **Google OAuth consent**: User authorizes Zylch to access Gmail and Calendar
3. **Callback**: Google redirects to `/api/auth/google/callback` with auth code
4. **Token storage**: Backend exchanges code for tokens and stores in `oauth_tokens` table
5. **Verification**: User runs `/connections` to verify connection

### Microsoft (Outlook & Calendar)

1. **User initiates connection**: Frontend redirects to `/api/auth/microsoft-login`
2. **Microsoft OAuth consent**: User authorizes Zylch to access Outlook and Calendar
3. **Token exchange**: Backend exchanges code for Graph API tokens
4. **Token storage**: Tokens stored in `oauth_tokens` table
5. **Verification**: User runs `/connections` to verify connection

---

## API Key Configuration

### Pipedrive CRM (BYOK)

**Credentials are NOT stored in .env** - each user provides their own via `/connect pipedrive`.

**Via CLI:**
```bash
> /connect pipedrive
# Enter your Pipedrive API token when prompted
# Token is stored encrypted in Supabase per-user
```

**Via API:**
```python
# POST /api/connections/provider/pipedrive/credentials
{
    "credentials": {"api_token": "your_api_token_here"}
}
```

### MrCall/StarChat

**Environment Variables**:
```bash
STARCHAT_API_URL=https://api.starchat.com
STARCHAT_API_KEY=your_api_key
STARCHAT_BUSINESS_ID=3002475397
```

**Or via CLI**:
```bash
> /mrcall 3002475397
```

### Vonage SMS (BYOK)

**Credentials are NOT stored in .env** - each user provides their own via `/connect vonage`.

**Via CLI:**
```bash
> /connect vonage
# Enter your Vonage API key, secret, and from number when prompted
# Credentials are stored encrypted in Supabase per-user
```

**Via API:**
```python
# POST /api/connections/provider/vonage/credentials
{
    "credentials": {
        "api_key": "your_api_key",
        "api_secret": "your_api_secret",
        "from_number": "+15551234567"
    }
}
```

---

## Database Schema

### `integration_providers` Table

Master registry of all available integrations:

```sql
CREATE TABLE integration_providers (
    id UUID PRIMARY KEY,
    provider_key TEXT UNIQUE NOT NULL,        -- 'google', 'microsoft', 'pipedrive'
    display_name TEXT NOT NULL,               -- 'Google (Gmail & Calendar)'
    category TEXT NOT NULL,                   -- 'email', 'crm', 'messaging', etc.
    icon_url TEXT,
    description TEXT,
    requires_oauth BOOLEAN DEFAULT true,      -- true = OAuth, false = API key
    oauth_url TEXT,                           -- OAuth endpoint
    config_fields JSONB,                      -- Required API key fields
    is_available BOOLEAN DEFAULT true,        -- false = "coming soon"
    documentation_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### `oauth_tokens` Table (Extended)

User connections with tracking:

```sql
ALTER TABLE oauth_tokens ADD COLUMN connection_status TEXT DEFAULT 'connected';
ALTER TABLE oauth_tokens ADD COLUMN last_sync TIMESTAMPTZ;
ALTER TABLE oauth_tokens ADD COLUMN error_message TEXT;
ALTER TABLE oauth_tokens ADD COLUMN display_name TEXT;
```

---

## Adding New Integrations

### Step 1: Add Provider to Database

```sql
INSERT INTO integration_providers (
    provider_key,
    display_name,
    category,
    requires_oauth,
    oauth_url,
    is_available,
    description
) VALUES (
    'whatsapp',
    'WhatsApp Business',
    'messaging',
    true,
    '/api/auth/whatsapp/authorize',
    false,  -- Coming soon
    'Send and receive WhatsApp messages via Business API'
);
```

### Step 2: Implement OAuth Endpoint (if OAuth-based)

Create `/api/auth/whatsapp/authorize` and `/api/auth/whatsapp/callback` endpoints.

### Step 3: Create Client

Create client in `/Users/mal/hb/zylch/zylch/tools/whatsapp.py`:

```python
class WhatsAppClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def send_message(self, to: str, message: str):
        # Implementation
        pass
```

### Step 4: Update Availability

```sql
UPDATE integration_providers SET is_available = true WHERE provider_key = 'whatsapp';
```

---

## Frontend Integration

### React Example

```jsx
import { useState, useEffect } from 'react';

function ConnectionsPage({ ownerId }) {
  const [connections, setConnections] = useState([]);

  useEffect(() => {
    fetch(`/api/connections/status?owner_id=${ownerId}`)
      .then(res => res.json())
      .then(data => setConnections(data.connections));
  }, [ownerId]);

  const connectProvider = async (providerKey) => {
    const response = await fetch(`/api/connections/providers/${providerKey}`);
    const provider = await response.json();

    if (provider.requires_oauth) {
      // Redirect to OAuth URL
      window.location.href = `${provider.oauth_url}?owner_id=${ownerId}`;
    } else {
      // Show API key config form
      showConfigModal(provider);
    }
  };

  return (
    <div>
      <h1>Your Connections</h1>
      {connections.map(conn => (
        <div key={conn.provider_key}>
          <h3>{conn.display_name}</h3>
          <p>Status: {conn.status}</p>
          {conn.status === 'disconnected' && (
            <button onClick={() => connectProvider(conn.provider_key)}>
              Connect
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
```

---

## Troubleshooting

### Connection Not Showing

**Issue**: Ran OAuth but connection not showing in `/connections`

**Solution**:
1. Check `oauth_tokens` table:
   ```sql
   SELECT * FROM oauth_tokens WHERE owner_id = 'YOUR_ID';
   ```
2. Verify `provider` field matches `integration_providers.provider_key`
3. Check logs for OAuth callback errors

### OAuth Redirect Loop

**Issue**: OAuth redirects back to authorize page

**Solution**:
1. Check callback URL matches registered URL in provider console
2. Verify token storage is working (check database)
3. Check for CORS issues in browser console

### Provider Not Available

**Issue**: Provider shows "coming soon" but should be available

**Solution**:
```sql
UPDATE integration_providers SET is_available = true WHERE provider_key = 'provider_key';
```

---

## Related Documentation

- [Quick Start Guide](quick-start.md) - Initial setup
- [CLI Commands](cli-commands.md) - Command reference
- [API Reference](../api/README.md) - API documentation
- [QA Testing Guide](qa_testing.md) - Testing procedures

---

**Last Updated**: December 2025
