# Data Sharing

## Overview

Zylch's sharing system allows users to share their relational intelligence with colleagues. This enables:
- **Team context**: Colleagues see relationships you've built
- **Better handoffs**: When employees leave, relational knowledge stays
- **Meeting prep**: Shared context across team members

## How It Works

### Share Flow

```
1. Sender initiates:     /share colleague@example.com
2. System creates:       Pending share request in database
3. Recipient sees:       Incoming request in /sharing
4. Recipient authorizes: /sharing --authorize sender@example.com
5. Data flows:           Sender's avatars → Recipient's context
```

### What Gets Shared

| Data Type | Description |
|-----------|-------------|
| **Contact Avatars** | Vector representations of people |
| **Relationship Context** | How you know each person |
| **Email Intelligence** | Communication patterns, preferences |
| **Meeting History** | Past interactions with contacts |

### What Does NOT Get Shared

- Your email content (only metadata/patterns)
- Your calendar details
- Your personal preferences
- Your behavioral memory

## CLI Commands

### Share Data

```bash
/share <email>
```

Initiates sharing your data with a recipient.

**Example:**
```bash
/share colleague@example.com
```

**Output:**
```
✅ **Share Request Sent**

**Recipient:** colleague@example.com
**Status:** Pending authorization

The recipient needs to authorize this sharing from their Zylch account.

Once authorized, they will receive:
• Your contact intelligence
• Relationship context
• Avatar data
```

### Revoke Access

```bash
/revoke <email>
```

Stops sharing your data with a recipient.

**Example:**
```bash
/revoke colleague@example.com
```

**Output:**
```
✅ **Sharing Revoked**

**Recipient:** colleague@example.com

They will no longer receive your data updates.

**Note:** Any data already shared remains with them, but no new updates will be sent.
```

### View Status

```bash
/sharing
```

Shows all your sharing connections:

**Output:**
```
**📊 Sharing Status**

**📤 Your Recipients** (you share with them)
✅ alice@example.com (authorized)
⏳ bob@example.com (pending)

**📥 Incoming Shares** (they share with you)
✅ carol@example.com (authorized)
⏳ dave@example.com (pending)

**Commands:**
• `/share <email>` - Share with someone new
• `/revoke <email>` - Stop sharing
• `/sharing --authorize <email>` - Accept incoming share
```

### Authorize Incoming

```bash
/sharing --authorize <email>
```

Accepts a share request from another user.

**Example:**
```bash
/sharing --authorize sender@example.com
```

**Output:**
```
✅ **Sharing Authorized**

**From:** sender@example.com

You will now receive their shared data:
• Contact intelligence
• Relationship context
• Avatar data
```

## Database Schema

### sharing_auth Table

```sql
CREATE TABLE sharing_auth (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sender_id TEXT NOT NULL,           -- Owner ID of sender
    sender_email TEXT NOT NULL,        -- Email of sender
    recipient_email TEXT NOT NULL,     -- Email of recipient
    status TEXT DEFAULT 'pending',     -- pending, authorized, revoked
    created_at TIMESTAMPTZ DEFAULT NOW(),
    authorized_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX idx_sharing_sender ON sharing_auth(sender_id);
CREATE INDEX idx_sharing_recipient ON sharing_auth(recipient_email);
CREATE INDEX idx_sharing_status ON sharing_auth(status);
```

### Status Values

| Status | Description |
|--------|-------------|
| `pending` | Share request sent, awaiting recipient authorization |
| `authorized` | Recipient accepted, data flows |
| `revoked` | Sender cancelled sharing |

## Implementation

### Backend Services

| File | Purpose |
|------|---------|
| `zylch/services/command_handlers.py` | `/share`, `/revoke`, `/sharing` handlers |
| `zylch/storage/supabase_client.py` | Database operations |
| `zylch/sharing/` | Core sharing logic (if exists) |

### Key Functions

**Command Handlers** (`command_handlers.py`):
- `handle_share(args, owner_id, user_email)` - Create share request
- `handle_revoke(args, owner_id, user_email)` - Revoke sharing
- `handle_sharing(args, owner_id, user_email)` - Show status / authorize

**Storage** (`supabase_client.py`):
- `register_share_recipient(owner_id, sender_email, recipient_email)` - Create share
- `revoke_sharing(owner_id, recipient_email)` - Set status to revoked
- `authorize_sender(recipient_email, sender_email)` - Accept share
- `get_sharing_status(owner_id, user_email)` - Get all connections

## Security Model

### Authorization Required

Data only flows after explicit authorization by the recipient:

1. **Sender creates request** - Status is `pending`
2. **No data shared yet** - Recipient hasn't consented
3. **Recipient authorizes** - Status becomes `authorized`
4. **Data flows** - Avatars/context shared

### Revocation

- Sender can revoke at any time
- Already-shared data remains with recipient
- No new updates after revocation
- Can re-share by sending new request

### Privacy Boundaries

- **Email content**: Never shared (only patterns/metadata)
- **Calendar details**: Never shared
- **Personal preferences**: Never shared
- **Avatars**: Shared as vector embeddings (not raw data)

## Use Cases

### 1. Team Onboarding

New team member needs context on key contacts:

```bash
# Existing employee shares
/share newperson@company.com

# New employee authorizes
/sharing --authorize senior@company.com
```

Now the new employee has context about the contacts their colleague knows.

### 2. Employee Departure

When someone leaves, share their relational intelligence:

```bash
# Departing employee
/share successor@company.com

# Successor authorizes
/sharing --authorize departing@company.com
```

Relationships don't leave with the person.

### 3. Cross-Team Collaboration

Sales and support sharing context:

```bash
# Sales shares with support
/share support-lead@company.com

# Support shares with sales
/share sales-lead@company.com
```

Both teams have full context on shared customers.

## Troubleshooting

### Share Not Working

1. **Check email format**: Must be valid email
2. **Check authorization**: Recipient must authorize
3. **Check status**: Use `/sharing` to see current state

### Can't Find Incoming Share

1. **Email must match**: Your Zylch email must match recipient_email
2. **Re-authenticate**: If email changed, re-login
3. **Check with sender**: Confirm they sent the request

### Revoke Not Working

1. **Check recipient email**: Must be exact match
2. **Check you're the sender**: Only sender can revoke
3. **Use `/sharing`**: Verify the connection exists

## API Endpoints (Future)

REST endpoints for programmatic access:

```bash
# Create share request
POST /api/sharing
{
  "recipient_email": "colleague@example.com"
}

# Get sharing status
GET /api/sharing

# Authorize incoming share
POST /api/sharing/authorize
{
  "sender_email": "colleague@example.com"
}

# Revoke sharing
DELETE /api/sharing/{recipient_email}
```

## Best Practices

### When to Share

✅ **Do share:**
- With direct team members
- During onboarding
- Before employee departures
- For cross-functional collaboration

❌ **Don't share:**
- With external parties (without consideration)
- Company-wide (too broad)
- Without recipient consent

### Sharing Etiquette

1. **Inform recipients** - Let them know you're sharing
2. **Share selectively** - Not everyone needs all context
3. **Review periodically** - Revoke when no longer needed
4. **Respect privacy** - Don't share sensitive relationships

## Migration Notes

### From Old CLI

If you had sharing set up in the old CLI:

1. Check current status: `/sharing`
2. Re-create if needed: `/share <email>`
3. Recipients must re-authorize

The new system uses Supabase instead of local storage, so previous shares need to be re-established.
