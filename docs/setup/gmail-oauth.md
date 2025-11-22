# Gmail OAuth Setup Guide

## Quick Setup (5 minutes)

### Step 1: Google Cloud Console

1. Go to: https://console.cloud.google.com/
2. Select your existing project or create new one
3. In search bar, type "Gmail API" → Enable it
4. Go to "APIs & Services" → "Credentials"
5. Click "+ CREATE CREDENTIALS" → "OAuth client ID"
6. If prompted, configure OAuth consent screen first:
   - User Type: **External** (for testing)
   - App name: "MrPark Dev"
   - User support email: your email
   - Developer contact: your email
   - Click "Save and Continue" (skip scopes, test users for now)
7. Back to Create OAuth Client ID:
   - Application type: **Desktop app**
   - Name: "MrPark Desktop"
   - Click "Create"
8. **Download JSON** file (click download icon)

### Step 2: Save Credentials

Move the downloaded JSON to:
```bash
mv ~/Downloads/client_secret_*.json /Users/mal/starchat/mrpark/credentials/gmail_oauth.json
```

### Step 3: Test Authentication

```bash
cd /Users/mal/starchat/mrpark
source venv/bin/activate
python -c "
from mrpark.tools.gmail import GmailClient
gmail = GmailClient()
gmail.authenticate()
print('✅ Gmail OAuth successful!')
"
```

This will:
1. Open browser
2. Ask you to sign in with Google
3. Ask for permission to access Gmail
4. Save token in `credentials/gmail_tokens/token.pickle`

### Step 4: Test Search

```bash
python -c "
from mrpark.tools.gmail import GmailClient
gmail = GmailClient()
gmail.authenticate()
messages = gmail.search_messages('is:inbox', max_results=5)
print(f'Found {len(messages)} recent messages')
for msg in messages[:3]:
    print(f'  - {msg[\"subject\"][:50]}')
"
```

## Troubleshooting

**Error: "Access blocked: This app's request is invalid"**
- Go back to OAuth consent screen
- Add your email to "Test users"
- Try again

**Error: "Credentials not found"**
- Check file exists: `ls credentials/gmail_oauth.json`
- Check JSON is valid: `cat credentials/gmail_oauth.json | python -m json.tool`

**Success looks like:**
```
✅ Gmail authenticated
Found 5 recent messages
  - Subject 1...
  - Subject 2...
  - Subject 3...
```
