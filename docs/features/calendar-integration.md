# Google Calendar & Meet Integration

**Complete guide to Zylch AI's calendar management and Google Meet video conference features**

---

## Overview

Zylch AI integrates with Google Calendar to:
- **Schedule events** with automatic Google Meet links
- **Create events from emails** with all participants
- **Send calendar invites** automatically to all attendees
- **Extract proposed times** from email conversations
- **Manage meetings** with full context from email threads

---

## Google Meet Link Generation

### Automatic Meet Links

When creating a calendar event, set `add_meet_link=true` to automatically generate a Google Meet video conference link.

**Example:**
```python
event = calendar.create_event(
    summary="Call - Project Kickoff",
    start_time=datetime(2025, 11, 27, 10, 0),
    end_time=datetime(2025, 11, 27, 11, 0),
    attendees=["john@company.com", "jane@company.com"],
    add_meet_link=True  # ← Generates Meet link
)

# Result:
# event['meet_link'] = "https://meet.google.com/abc-defg-hij"
```

### Meet Link Features

- **Unique per event**: Each event gets a unique Meet URL
- **Automatic in invites**: Meet link included in calendar invitations
- **One-click join**: Attendees can join directly from calendar
- **No manual setup**: No need to create Meet rooms separately

---

## Creating Events from Emails

### Email-to-Event Workflow

**User request:**
> "Rispondi gentilmente a Anna che va benissimo, crea un invito per tutti i partecipanti dell'ultima mail all'orario richiesto, con link meet"

**What Zylch AI does:**

1. **Searches the email** from Anna
2. **Extracts proposed time** from email body
   - Example: "giovedì 27/11 alle ore 10:00" → Thursday, Nov 27, 2025 at 10:00 CET
3. **Identifies all participants**:
   - Sender: contact@example.com
   - To/CC recipients: mario.alemi@mrcall.ai, ...
4. **Creates calendar event** with:
   - Title: Based on email subject ("Call - Flusso Dati IVR Connecto")
   - Time: Parsed from email
   - Attendees: All email participants
   - Meet link: Auto-generated
   - Description: Context from email
5. **Sends invites** to all participants with Meet link
6. **Creates draft reply** confirming the meeting

---

## API Reference

### `create_event()`

Create a new calendar event with optional Google Meet link.

**Parameters:**
- `summary` (str): Event title
- `start_time` (datetime): Start time (timezone-aware)
- `end_time` (datetime): End time (timezone-aware)
- `description` (str, optional): Event description
- `location` (str, optional): Physical location
- `attendees` (List[str], optional): List of attendee emails
- `add_meet_link` (bool, optional): If True, generates Google Meet link

**Returns:**
- Event dict with `meet_link` field if requested

**Example:**
```python
from datetime import datetime, timedelta
from zylch.tools.gcalendar import GoogleCalendarClient

calendar = GoogleCalendarClient()
calendar.authenticate()

# Create event with Meet link
event = calendar.create_event(
    summary="Weekly Sync",
    start_time=datetime(2025, 11, 25, 14, 0),
    end_time=datetime(2025, 11, 25, 15, 0),
    description="Weekly team sync meeting",
    attendees=["team@company.com"],
    add_meet_link=True
)

print(f"Meet link: {event['meet_link']}")
# Output: Meet link: https://meet.google.com/xxx-yyyy-zzz
```

---

## Agent Usage

### Natural Language Commands

**Creating events with Meet links:**
```
You: Schedule a meeting with John tomorrow at 3pm with video link
→ Zylch AI creates event with Meet link

You: Create a calendar invite for the team call on Friday 10am
→ Event with Meet link for all team members

You: Add video conference to the client meeting
→ Updates existing event with Meet link
```

### Email-Triggered Event Creation

**When asked to create event from email:**
```
You: Create invite for all participants in Sarah's email at the proposed time with Meet link
```

**Zylch AI automatically:**
1. Finds Sarah's latest email
2. Parses the proposed date/time (e.g., "next Tuesday at 2pm")
3. Extracts all participants from From/To/CC
4. Creates event with Meet link
5. Sends calendar invites to everyone

---

## Agent Prompt Guidelines

When Zylch AI creates events from emails, it follows these rules:

### Participant Extraction
```
Participants = [
    Email sender,
    All To: recipients,
    All CC: recipients
]
```

### Time Parsing Examples
- "giovedì 27/11 alle ore 10:00" → Thursday, Nov 27 at 10:00
- "next Tuesday at 2pm" → Next Tuesday at 14:00
- "tomorrow morning" → Tomorrow at 09:00 (default)

### Event Title Format
- Based on email subject
- Prefixed with "Call -" for video meetings
- Example: "Call - Flusso Dati IVR Connecto"

### Description Content
- Original email subject
- Date received
- Key context from email body

---

## Implementation Details

### Google Calendar API

**Conference Creation:**
```python
event_body = {
    'summary': 'Meeting Title',
    'start': {'dateTime': '2025-11-27T10:00:00', 'timeZone': 'UTC'},
    'end': {'dateTime': '2025-11-27T11:00:00', 'timeZone': 'UTC'},
    'attendees': [{'email': 'user@example.com'}],
    'conferenceData': {
        'createRequest': {
            'requestId': 'meet-1732521600',
            'conferenceSolutionKey': {'type': 'hangoutsMeet'}
        }
    }
}

# Must use conferenceDataVersion=1
event = service.events().insert(
    calendarId='primary',
    body=event_body,
    conferenceDataVersion=1,
    sendUpdates='all'  # Sends invites to all attendees
).execute()
```

**Meet Link Extraction:**
```python
meet_link = None
conference_data = event.get('conferenceData', {})
if conference_data:
    entry_points = conference_data.get('entryPoints', [])
    for entry in entry_points:
        if entry.get('entryPointType') == 'video':
            meet_link = entry.get('uri')
            break
```

---

## Testing

### Test Script: `test_calendar_with_meet.py`

**What it tests:**
- Gmail API authentication
- Email search and participant extraction
- Calendar event creation with Meet link
- Meet link generation verification

**Run test:**
```bash
python test_calendar_with_meet.py
```

**Expected output:**
```
✅ Event created successfully!
  Event ID: 0be19qekcdud1ae7fadb2p0mms
  Meet link: https://meet.google.com/juk-ctqu-prz
  Attendees: 2
🎥 Google Meet link was successfully generated!
```

---

## Common Use Cases

### 1. Quick Meeting with Meet Link
```
You: Schedule 30min with John tomorrow at 10am with video
→ Creates event with Meet link, sends invite to John
```

### 2. Team Meeting from Email Thread
```
You: Create event for all people in this thread, Friday 2pm with Meet
→ Extracts all participants, creates event with Meet link
```

### 3. Follow-up Meeting
```
You: Schedule follow-up meeting with client next week with video conference
→ Finds client's latest email, creates event with Meet link
```

### 4. International Meeting
```
You: Schedule call with Tokyo team tomorrow 9am JST with Meet link
→ Converts timezone, creates event with Meet link
```

---

## Troubleshooting

### "OAuth not working"
- Run `/connect google` to initiate OAuth flow
- Google Calendar requires same OAuth as Gmail
- Tokens are stored in Supabase `oauth_tokens` table (encrypted)
- Follow setup: `docs/guides/gmail-oauth.md`

### "Meet link not generated"
- Check `add_meet_link=True` is set
- Verify `conferenceDataVersion=1` in API call
- Ensure Google Workspace or Google account supports Meet

### "Attendees not receiving invites"
- Check `sendUpdates='all'` in API call
- Verify attendee email addresses are valid
- Check spam folders

### "Wrong timezone"
- Always use timezone-aware datetime objects
- Zylch AI defaults to UTC, converts to local
- Specify timezone explicitly for international meetings

---

## Future Enhancements

### Planned Features
- ⏳ Zoom/Teams integration as alternative to Meet
- ⏳ Recurring meeting support
- ⏳ Meeting room booking integration
- ⏳ Calendar conflict detection
- ⏳ Automatic meeting notes creation

---

**Last Updated:** November 2025
**Version:** 0.2.0
