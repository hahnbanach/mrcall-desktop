---
description: |
  Compares Google OAuth (standard OAuth 2.0, single identity system) vs MrCall/StarChat OAuth
  (OAuth 2.0 + PKCE, dual Firebase identity systems). Google is simpler - user's Google account
  is the identity. MrCall requires PKCE because two separate Firebase apps must be linked, mapping
  Zylch user (owner_id) to MrCall user (target_owner). Both use callback port 8766.
---

# OAuth Flows Comparison: Google vs MrCall/StarChat

This guide compares the OAuth authentication flows for Google and MrCall/StarChat integrations in Zylch.

## Quick Comparison

| Aspect | Google OAuth | MrCall/StarChat OAuth |
|--------|--------------|----------------------|
| **Security** | Standard OAuth 2.0 | OAuth 2.0 + PKCE |
| **Identity Systems** | Single (Google) | Dual (Zylch + MrCall Firebase) |
| **PKCE** | No | Yes (code_verifier/challenge) |
| **State Parameter** | Yes (CSRF) | Yes (CSRF + owner_id storage) |
| **Token Storage** | owner_id only | owner_id + target_owner |
| **Callback Port** | 8766 | 8766 |
| **User Experience** | Single login | May need separate MrCall login |

## Why the Flows Differ

### Google OAuth (Simpler)
- Google is a first-party identity provider
- User's Google account is the identity
- Single sign-on - same account throughout
- Standard OAuth 2.0 is sufficient

### MrCall/StarChat OAuth (More Complex)
- **Two separate Firebase apps**: Zylch has its own Firebase, MrCall/StarChat has another
- **Third-party delegation**: Zylch requests access to MrCall on user's behalf
- **PKCE required**: Prevents authorization code interception attacks
- **Dual identity mapping**: Links Zylch user (owner_id) to MrCall user (target_owner)

## Google OAuth Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                    GOOGLE OAUTH FLOW                              │
│           (Standard OAuth 2.0 Authorization Code)                │
└──────────────────────────────────────────────────────────────────┘

┌─────────┐         ┌─────────┐         ┌─────────┐         ┌─────────┐
│  User   │         │  Zylch  │         │  Zylch  │         │ Google  │
│  (CLI)  │         │   CLI   │         │ Backend │         │  OAuth  │
└────┬────┘         └────┬────┘         └────┬────┘         └────┬────┘
     │                   │                   │                   │
     │ /connect google   │                   │                   │
     │──────────────────>│                   │                   │
     │                   │                   │                   │
     │                   │ GET /api/auth/    │                   │
     │                   │ google/authorize  │                   │
     │                   │──────────────────>│                   │
     │                   │                   │                   │
     │                   │   OAuth URL       │                   │
     │                   │<──────────────────│                   │
     │                   │                   │                   │
     │                   │ Start local       │                   │
     │                   │ server :8766      │                   │
     │                   │                   │                   │
     │ Open browser      │                   │                   │
     │<──────────────────│                   │                   │
     │                   │                   │                   │
     │ ─────────────────────────────────────────────────────────>│
     │                   Login + Consent Page                    │
     │                   │                   │                   │
     │    User logs in with GOOGLE account (same identity)       │
     │<──────────────────────────────────────────────────────────│
     │                   │                   │                   │
     │ Approve           │                   │                   │
     │───────────────────────────────────────────────────────────>│
     │                   │                   │                   │
     │                   │ Redirect to       │                   │
     │                   │ localhost:8766/   │                   │
     │                   │ callback?code=xyz │                   │
     │                   │<─────────────────────────────────────│
     │                   │                   │                   │
     │                   │ POST /api/auth/   │                   │
     │                   │ google/callback   │                   │
     │                   │ {code: "xyz"}     │                   │
     │                   │──────────────────>│                   │
     │                   │                   │                   │
     │                   │                   │ Exchange code     │
     │                   │                   │ for tokens        │
     │                   │                   │──────────────────>│
     │                   │                   │                   │
     │                   │                   │<──────────────────│
     │                   │                   │ access_token,     │
     │                   │                   │ refresh_token     │
     │                   │                   │                   │
     │                   │                   │ Store tokens      │
     │                   │                   │ (encrypted)       │
     │                   │                   │ in Supabase       │
     │                   │                   │                   │
     │                   │   "Success!"      │                   │
     │                   │<──────────────────│                   │
     │                   │                   │                   │
     │ "Google           │                   │                   │
     │ connected!"       │                   │                   │
     │<──────────────────│                   │                   │
     ▼                   ▼                   ▼                   ▼
```

**Key Points:**
- User logs into GOOGLE directly
- Single identity system (same Google account throughout)
- Standard OAuth 2.0 without PKCE
- Tokens stored with Zylch `owner_id` only

## MrCall/StarChat OAuth Flow (with PKCE)

```
┌──────────────────────────────────────────────────────────────────┐
│                 MRCALL/STARCHAT OAUTH FLOW                       │
│        (OAuth 2.0 Authorization Code with PKCE)                  │
│           TWO SEPARATE FIREBASE IDENTITY SYSTEMS                 │
└──────────────────────────────────────────────────────────────────┘

┌─────────┐         ┌─────────┐         ┌─────────┐         ┌─────────┐
│  User   │         │  Zylch  │         │  Zylch  │         │StarChat │
│  (CLI)  │         │   CLI   │         │ Backend │         │  OAuth  │
└────┬────┘         └────┬────┘         └────┬────┘         └────┬────┘
     │                   │                   │                   │
     │ /connect mrcall   │                   │                   │
     │──────────────────>│                   │                   │
     │                   │                   │                   │
     │                   │ GET /api/auth/    │                   │
     │                   │ mrcall/authorize  │                   │
     │                   │ ?owner_id=abc123  │ (Zylch Firebase UID)
     │                   │──────────────────>│                   │
     │                   │                   │                   │
     │                   │                   │ Generate PKCE:    │
     │                   │                   │ - code_verifier   │
     │                   │                   │ - code_challenge  │
     │                   │                   │ - state (CSRF)    │
     │                   │                   │                   │
     │                   │                   │ Store state with  │
     │                   │                   │ owner_id=abc123   │
     │                   │                   │                   │
     │                   │   OAuth URL       │                   │
     │                   │   with PKCE       │                   │
     │                   │<──────────────────│                   │
     │                   │                   │                   │
     │                   │ Start local       │                   │
     │                   │ server :8766      │                   │
     │                   │                   │                   │
     │ Open browser      │                   │                   │
     │<──────────────────│                   │                   │
     │                   │                   │                   │
     │ ─────────────────────────────────────────────────────────>│
     │                   Login + Consent Page                    │
     │                   │                   │                   │
     │   User logs in with MRCALL/STARCHAT account              │
     │   (DIFFERENT Firebase identity: owner_id=xyz789)          │
     │<──────────────────────────────────────────────────────────│
     │                   │                   │                   │
     │ Approve           │                   │                   │
     │───────────────────────────────────────────────────────────>│
     │                   │                   │                   │
     │                   │ Redirect to       │                   │
     │                   │ localhost:8766/   │                   │
     │                   │ callback?code=xyz │                   │
     │                   │ &state=...        │                   │
     │                   │<─────────────────────────────────────│
     │                   │                   │                   │
     │                   │ POST /api/auth/   │                   │
     │                   │ mrcall/callback   │                   │
     │                   │ {code, state}     │                   │
     │                   │──────────────────>│                   │
     │                   │                   │                   │
     │                   │                   │ Validate state    │
     │                   │                   │ Retrieve          │
     │                   │                   │ code_verifier     │
     │                   │                   │                   │
     │                   │                   │ Exchange code     │
     │                   │                   │ + code_verifier   │
     │                   │                   │──────────────────>│
     │                   │                   │                   │
     │                   │                   │<──────────────────│
     │                   │                   │ access_token,     │
     │                   │                   │ refresh_token,    │
     │                   │                   │ target_owner=     │
     │                   │                   │   xyz789          │
     │                   │                   │ (MrCall Firebase  │
     │                   │                   │  UID)             │
     │                   │                   │                   │
     │                   │                   │ Store tokens with │
     │                   │                   │ BOTH identities:  │
     │                   │                   │ - owner_id=abc123 │
     │                   │                   │   (Zylch user)    │
     │                   │                   │ - target_owner=   │
     │                   │                   │   xyz789          │
     │                   │                   │   (MrCall user)   │
     │                   │                   │                   │
     │                   │   "Success!"      │                   │
     │                   │<──────────────────│                   │
     │                   │                   │                   │
     │ "MrCall           │                   │                   │
     │ connected!"       │                   │                   │
     │<──────────────────│                   │                   │
     ▼                   ▼                   ▼                   ▼
```

**Key Points:**
- User logs into MRCALL/STARCHAT (separate Firebase app!)
- TWO identity systems:
  - Zylch Firebase: `owner_id=abc123` (who's connecting)
  - MrCall Firebase: `target_owner=xyz789` (what they're connecting to)
- PKCE adds security layer (`code_verifier`/`code_challenge`)
- Tokens stored with BOTH `owner_id` AND `target_owner`
- One Zylch user can connect to multiple MrCall accounts

## The Two-Identity System Explained

### Why Two Identities?

Zylch and MrCall are **separate applications** with **separate Firebase projects**:

1. **Zylch Firebase**: Your Zylch account identity (`owner_id`)
2. **MrCall Firebase**: Your MrCall account identity (`target_owner`)

When you connect MrCall to Zylch, we need to:
- Know **which Zylch user** is connecting (for access control)
- Know **which MrCall account** they're connecting to (for API calls)

### Token Storage Schema

```json
{
  "owner_id": "abc123",           // Zylch user's Firebase UID
  "provider_key": "mrcall",
  "credentials": {
    "access_token": "...",
    "refresh_token": "...",
    "business_id": "...",
    "target_owner": "xyz789"      // MrCall user's Firebase UID
  }
}
```

### Implications

- **One Zylch user** can connect **multiple MrCall accounts**
- **Multiple Zylch users** could connect **the same MrCall account**
- The identity mapping is explicit and auditable

## Security Features

### PKCE (Proof Key for Code Exchange)

MrCall uses PKCE to prevent authorization code interception:

1. **code_verifier**: Random 43-128 character string generated client-side
2. **code_challenge**: SHA-256 hash of code_verifier, sent in authorization request
3. **Verification**: Token exchange requires original code_verifier

```python
# PKCE Generation
code_verifier = base64url(random_bytes(96))  # 128 chars
code_challenge = base64url(sha256(code_verifier))
```

### State Parameter

Both flows use state parameter for CSRF protection:

- **Google**: Random string for CSRF protection
- **MrCall**: Random string + stores `owner_id` for identity mapping

## Related Documentation

- [Gmail OAuth Setup](gmail-oauth.md) - Google OAuth setup guide
- [MrCall Integration](../features/mrcall-integration.md) - Full MrCall documentation
- [Integrations Guide](integrations.md) - All available integrations

---

**Last Updated**: December 2025
