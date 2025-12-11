# Zylch AI - API Reference

**Version**: 1.0.0
**Base URL**: `http://localhost:8000` (development) | `https://api.zylch.com` (production)
**Last Updated**: 2025-12-06

## Overview

Complete REST API for Zylch AI personal assistant. All endpoints require Firebase authentication unless otherwise noted.

### Authentication

All protected endpoints require a Bearer token in the Authorization header:

```bash
Authorization: Bearer <firebase_id_token>
```

### Interactive Documentation

- **Swagger UI**: `/docs`
- **ReDoc**: `/redoc`

---

## Table of Contents

1. [Root & Health](#root--health)
2. [Authentication](#authentication-apiauth)
3. [Chat](#chat-apichat)
4. [Data](#data-apidata)
5. [Sync](#sync-apisync)
6. [Gaps Analysis](#gaps-analysis-apigaps)
7. [Email Archive](#email-archive-apiarchive)
8. [Webhooks](#webhooks-apiwebhooks)
9. [Skills](#skills-apiskills)
10. [Patterns](#patterns-apipatterns)
11. [Admin](#admin-apiadmin)

---

## Root & Health

### GET /

Root endpoint - welcome message.

**Response**:
```json
{
  "message": "Welcome to Zylch AI API",
  "version": "1.0.0",
  "docs": "/docs"
}
```

### GET /health

Health check endpoint.

**Response**:
```json
{
  "status": "healthy",
  "skill_mode": true,
  "pattern_store": true
}
```

---

## Authentication (`/api/auth`)

### POST /api/auth/login

Authenticate with Firebase ID token.

**Request**:
```json
{
  "id_token": "<firebase_id_token>"
}
```

**Response**:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "uid": "user123",
    "email": "user@example.com",
    "name": "John Doe"
  }
}
```

### POST /api/auth/microsoft-login

Authenticate with Microsoft account.

**Request**:
```json
{
  "id_token": "<microsoft_id_token>",
  "access_token": "<microsoft_access_token>"
}
```

### POST /api/auth/refresh

Refresh access token.

**Request**:
```json
{
  "refresh_token": "<refresh_token>"
}
```

**Response**:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### POST /api/auth/logout

Logout and invalidate tokens.

**Response**:
```json
{
  "success": true,
  "message": "Logged out successfully"
}
```

### GET /api/auth/session

Get current session information.

**Response**:
```json
{
  "user": {
    "uid": "user123",
    "email": "user@example.com",
    "name": "John Doe"
  },
  "expires_at": "2025-12-06T12:00:00Z"
}
```

### GET /api/auth/check-allowlist

Check if user is in allowlist (alpha access).

**Response**:
```json
{
  "allowed": true,
  "tier": "alpha"
}
```

---

### Google OAuth

#### GET /api/auth/google/authorize

Initiate Google OAuth flow.

**Response**:
```json
{
  "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?..."
}
```

#### GET /api/auth/google/callback

OAuth callback handler (redirects to frontend).

**Query Parameters**:
- `code`: Authorization code from Google
- `state`: State parameter for CSRF protection

#### GET /api/auth/google/status

Check Google connection status.

**Response**:
```json
{
  "has_credentials": true,
  "email": "user@gmail.com",
  "valid": true,
  "expired": false
}
```

#### POST /api/auth/google/revoke

Revoke Google OAuth tokens.

**Response**:
```json
{
  "success": true,
  "message": "Google tokens revoked"
}
```

---

### Anthropic API Key (BYOK)

Bring Your Own Key - users provide their own Anthropic API key.

#### GET /api/auth/anthropic/status

Check if Anthropic API key is configured.

**Response**:
```json
{
  "has_key": true,
  "key_preview": "sk-ant-api0...7xyz"
}
```

Or if not configured:
```json
{
  "has_key": false
}
```

#### POST /api/auth/anthropic/key

Save Anthropic API key.

**Request**:
```json
{
  "api_key": "sk-ant-api03-..."
}
```

**Response**:
```json
{
  "success": true,
  "message": "API key saved successfully",
  "key_preview": "sk-ant-api0...7xyz"
}
```

**Errors**:
- `400`: Invalid API key format (must start with `sk-ant-`)
- `401`: Unauthorized

**Security**: API keys are encrypted at rest using Fernet (AES-128-CBC) before storage.

#### POST /api/auth/anthropic/revoke

Delete stored Anthropic API key.

**Response**:
```json
{
  "success": true,
  "message": "API key removed"
}
```

---

## Chat (`/api/chat`)

### POST /api/chat/message

Send a message to the AI assistant.

**Request**:
```json
{
  "message": "What emails do I have today?",
  "user_id": "user123",
  "conversation_history": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! How can I help?"}
  ],
  "session_id": "session_abc123",
  "context": {
    "current_business_id": "business_001"
  }
}
```

**Response**:
```json
{
  "response": "You have 3 emails today...",
  "tool_calls": [],
  "metadata": {
    "execution_time_ms": 2450.75,
    "tools_available": 25
  },
  "session_id": "session_abc123"
}
```

### GET /api/chat/history

Get chat history for a session.

**Query Parameters**:
- `session_id`: Session identifier
- `limit`: Max messages (default: 50)

### DELETE /api/chat/session/{session_id}

Delete a chat session.

### GET /api/chat/sessions

List all chat sessions.

### GET /api/chat/health

Check chat service health.

**Response**:
```json
{
  "status": "healthy",
  "agent": {
    "initialized": true,
    "tools_count": 25
  }
}
```

---

## Data (`/api/data`)

### GET /api/data/emails

List emails from cache.

**Query Parameters**:
- `limit`: Max results (default: 50)
- `offset`: Pagination offset
- `unread`: Filter unread only
- `from_date`: Start date filter

### GET /api/data/emails/{thread_id}

Get email thread details.

### GET /api/data/calendar

List calendar events.

**Query Parameters**:
- `days`: Days ahead (default: 7)
- `include_past`: Include past events

### GET /api/data/calendar/{event_id}

Get event details.

### GET /api/data/contacts

List contacts from memory.

**Query Parameters**:
- `limit`: Max results (default: 50)
- `search`: Search term

### GET /api/data/contacts/{memory_id}

Get contact details.

### POST /api/data/modifier

Apply a data modifier action.

**Request**:
```json
{
  "action": "mark_read",
  "target": "email",
  "target_id": "thread_123"
}
```

### GET /api/data/stats

Get overall statistics.

---

## Sync (`/api/sync`)

### GET /api/sync/status

Get sync status.

**Response**:
```json
{
  "last_email_sync": "2025-12-06T10:00:00Z",
  "last_calendar_sync": "2025-12-06T10:00:00Z",
  "emails_cached": 1500,
  "events_cached": 45
}
```

### POST /api/sync/start

Start background sync.

### POST /api/sync/emails

Sync emails from Gmail.

**Request**:
```json
{
  "days": 30,
  "force": false
}
```

### POST /api/sync/calendar

Sync calendar events.

### POST /api/sync/full

Run full sync (emails + calendar).

---

## Gaps Analysis (`/api/gaps`)

### POST /api/gaps/analyze

Analyze relationship gaps.

**Request**:
```json
{
  "days": 30,
  "threshold": 14
}
```

### GET /api/gaps/summary

Get gaps summary.

### GET /api/gaps/email-tasks

Get email-based tasks.

### GET /api/gaps/meeting-tasks

Get meeting-based tasks.

### GET /api/gaps/silent-contacts

Get contacts that need attention.

---

## Email Archive (`/api/archive`)

### POST /api/archive/init

Initialize email archive.

### POST /api/archive/sync

Sync emails to archive.

### GET /api/archive/stats

Get archive statistics.

### POST /api/archive/search

Search archived emails.

**Request**:
```json
{
  "query": "project update",
  "from": "john@example.com",
  "date_from": "2025-01-01",
  "limit": 20
}
```

### GET /api/archive/thread/{thread_id}

Get archived thread.

### GET /api/archive/threads

List archived threads.

---

## Webhooks (`/api/webhooks`)

### POST /api/webhooks/starchat

StarChat/MrCall webhook endpoint.

### POST /api/webhooks/sendgrid

SendGrid inbound email webhook.

### POST /api/webhooks/gmail/push

Gmail push notification webhook.

### POST /api/webhooks/vonage/status

Vonage SMS status webhook.

### POST /api/webhooks/vonage/inbound

Vonage inbound SMS webhook.

### POST /api/webhooks/test

Test webhook (development only).

### GET /api/webhooks/status

Get webhook processing status.

### GET /api/webhooks/events

List recent webhook events.

---

## Skills (`/api/skills`)

### POST /api/skills/classify

Classify user intent.

**Request**:
```json
{
  "message": "Schedule a meeting tomorrow"
}
```

**Response**:
```json
{
  "intent": "calendar_create",
  "confidence": 0.95,
  "skill": "calendar"
}
```

### POST /api/skills/execute

Execute a skill directly.

### POST /api/skills/process

Process message through skill system.

### GET /api/skills/list

List available skills.

### GET /api/skills/{skill_name}

Get skill details.

---

## Patterns (`/api/patterns`)

### POST /api/patterns/store

Store a learned pattern.

### POST /api/patterns/retrieve

Retrieve matching patterns.

### POST /api/patterns/update-confidence

Update pattern confidence score.

### GET /api/patterns/stats

Get pattern statistics.

---

## Admin (`/api/admin`)

### POST /api/admin/memory/clear

Clear memory store.

**Request**:
```json
{
  "scope": "all"  // or "contacts", "patterns", etc.
}
```

### POST /api/admin/cache/clear

Clear cache.

**Request**:
```json
{
  "type": "all"  // or "emails", "calendar", "gaps", "tasks"
}
```

### GET /api/admin/cache/info

Get cache information.

---

## Error Responses

All endpoints use consistent error format:

```json
{
  "detail": "Error message here",
  "code": "ERROR_CODE",
  "status_code": 400
}
```

### Common Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 422 | Validation Error |
| 429 | Rate Limited |
| 500 | Server Error |

---

## Rate Limits

| Tier | Requests/min | Requests/day |
|------|--------------|--------------|
| Alpha | 60 | 10,000 |
| Pro | 120 | 50,000 |
| Enterprise | Unlimited | Unlimited |

---

## Changelog

### 2025-12-06
- Added Anthropic BYOK endpoints (`/api/auth/anthropic/*`)
- API keys encrypted at rest with Fernet

### 2025-11-23
- Initial Chat API implementation
- 54 total endpoints

---

*For detailed Chat API documentation, see [chat-api.md](./chat-api.md)*
