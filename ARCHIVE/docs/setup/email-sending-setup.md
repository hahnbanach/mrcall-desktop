# Email Sending Setup Guide

## Current Status

✅ **Code Implementation**: Complete - `gmail.send` scope and all sending methods are already implemented
✅ **Google Cloud Console**: `gmail.send` scope is already authorized in your OAuth consent screen
⚠️ **OAuth Token**: Needs refresh to acquire the send permission

## Re-authentication Steps

### 1. Start Zylch CLI

```bash
cd /Users/mal/hb/zylch
source venv/bin/activate
python -m zylch.cli.main
```

### 2. Trigger OAuth Re-authentication

In the CLI, ask the agent:

```
refresh google auth
```

Or simply:

```
re-authenticate gmail
```

The agent will:
- Delete the current token file (`~/.config/zylch/google_token.json`)
- Open your browser for OAuth consent
- Request all scopes including `gmail.send`

### 3. Complete Browser OAuth Flow

1. Browser will open automatically
2. Select your Google account
3. Review permissions - you'll see:
   - Read, compose, send, and permanently delete all your email from Gmail ✅
   - See, edit, create, and delete all your Google Calendar events
4. Click "Allow"

### 4. Verify Success

The CLI will confirm:
```
✅ Gmail authentication successful
```

## Testing Email Sending

### Test 1: Create and Send Draft

```
Create a draft email to mal@miruapp.com with subject "Zylch Test" and body "Testing email sending from Zylch AI"
```

Then:

```
Send the draft I just created
```

### Test 2: Verify Receipt

Check your inbox at mal@miruapp.com to confirm the email arrived.

## Security Notes

**Why Draft-First Workflow?**

Zylch uses a **draft → review → send** workflow instead of direct sending:

1. **Safety**: You can review drafts before they're sent
2. **Transparency**: All outgoing emails are visible in Gmail's Drafts folder
3. **Control**: The agent cannot send emails without explicit user confirmation
4. **Auditability**: Full email history is preserved in Gmail

**No Direct Send Tool**

There is intentionally no "send_email_directly" tool. All email sending must:
1. Create a draft first
2. Allow user review
3. Explicitly send the draft

This prevents accidental or unauthorized email sending.

## Implementation Details

### OAuth Scopes (gmail.py:19-27)

```python
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',      # ← Sending emails
    'https://www.googleapis.com/auth/gmail.modify',    # ← Draft management
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]
```

### Send Message Method (gmail.py:255-299)

```python
def send_message(self, to: str, subject: str, body: str,
                 cc: Optional[str] = None,
                 bcc: Optional[str] = None) -> Dict[str, Any]:
    """Send an email message (creates draft first for safety)."""
```

### Draft Workflow Methods (gmail.py)

- `create_draft()` - lines 301-399
- `list_drafts()` - lines 401-445
- `get_draft()` - lines 447-491
- `update_draft()` - lines 493-526
- `send_draft()` - lines 528-552 ← Sends pre-created draft

## Troubleshooting

### "Token has expired or been revoked"

Simply re-run the re-authentication steps above.

### "Insufficient permissions"

Verify that `gmail.send` is enabled in your Google Cloud Console:
- Go to APIs & Services → OAuth consent screen
- Check that "Send email on your behalf" is listed

### "Draft not found"

List drafts first to get the correct draft ID:
```
Show me my recent drafts
```

## Next Steps After Setup

Once re-authentication is complete, you can:

1. **Test the workflow** with the test steps above
2. **Use email sending** in normal conversations:
   - "Draft a follow-up email to John about the meeting"
   - "Send that draft"
3. **Leverage AI capabilities**:
   - Context-aware email composition
   - Meeting follow-up automation
   - Relationship-based suggestions

---

**Ready to proceed?** Start the CLI and run the re-authentication command above! 🚀
