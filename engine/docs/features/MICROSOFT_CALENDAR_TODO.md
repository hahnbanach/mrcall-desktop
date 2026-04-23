---
description: |
  [TODO - Medium-High Priority] Outlook Calendar via Graph API for feature parity with Google
  Calendar. Outlook email client (tools/outlook.py) and partial OutlookCalendarClient already
  exist, OAuth flow works. Target: event CRUD, Teams meeting links (equivalent to Google Meet),
  calendar gap analysis. Critical for enterprise/B2B adoption (400M+ Outlook users).
---

# Microsoft Calendar - Future Development

## Status
🟡 **MEDIUM-HIGH PRIORITY** - Feature Parity

## Business Impact

**Target Users**:
- **Outlook users**: 400M+ active Outlook users worldwide
- **Enterprise customers**: Most corporations use Microsoft 365
- **Cross-platform users**: Users with both Gmail and Outlook accounts

**Why Important**:
- **Feature parity**: Gmail users have full calendar integration, Outlook users don't
- **Enterprise adoption**: B2B customers require Outlook/Teams support
- **Competitive advantage**: Multi-provider support differentiates from competitors
- **User retention**: Users won't switch if their primary calendar isn't supported

**Use Cases**:
- Professionals using Outlook for work, Gmail for personal
- Enterprise users with Microsoft 365 subscriptions
- Teams meeting link generation (equivalent to Google Meet)
- Calendar gap analysis for Outlook-scheduled meetings

## Current State

### What Exists
- ✅ **Outlook Email Client**: `tools/outlook.py` with Graph API integration
- ✅ **Partial Calendar Client**: `OutlookCalendarClient` class exists
- ✅ **OAuth Flow**: Microsoft OAuth authentication working
- ✅ **Graph API Access**: Microsoft Graph API client configured

### What's Missing
- ⚠️ **Incomplete Implementation**: `OutlookCalendarClient` is partially implemented
- ❌ **No Calendar Tools**: Calendar tools not registered in tool factory
- ❌ **No Teams Meeting Links**: Can't generate Teams meeting links
- ❌ **No Calendar Sync**: No automatic calendar event sync
- ❌ **No Gap Analysis**: Outlook calendar not integrated with relationship intelligence

### Code Reference
**File**: `zylch/services/command_handlers.py:167`
```python
calendar_client = None  # TODO: Microsoft Calendar support
```

## Planned Features

### 1. Complete Outlook Calendar Client

**Existing Methods** (verify and complete):
```python
class OutlookCalendarClient:
    async def list_events(
        self,
        start_date: datetime,
        end_date: datetime,
        max_results: int = 250
    ) -> List[CalendarEvent]:
        """List calendar events from Outlook"""
        # EXISTING: Needs testing and completion

    async def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        description: str = None,
        location: str = None,
        attendees: List[str] = None,
        add_teams_link: bool = False  # NEW: Teams meeting link
    ) -> CalendarEvent:
        """Create new calendar event with optional Teams link"""
        # PARTIALLY IMPLEMENTED: Add Teams link generation

    async def update_event(
        self,
        event_id: str,
        **kwargs
    ) -> CalendarEvent:
        """Update existing calendar event"""
        # TO IMPLEMENT

    async def search_events(
        self,
        query: str,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> List[CalendarEvent]:
        """Search calendar events by query"""
        # TO IMPLEMENT
```

### 2. Teams Meeting Link Generation

**Microsoft Graph API**:
```python
async def create_event_with_teams_link(
    self,
    summary: str,
    start_time: datetime,
    end_time: datetime,
    attendees: List[str],
) -> CalendarEvent:
    """Create calendar event with Teams meeting link"""

    event_body = {
        "subject": summary,
        "start": {
            "dateTime": start_time.isoformat(),
            "timeZone": "UTC"
        },
        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": "UTC"
        },
        "attendees": [
            {"emailAddress": {"address": email}}
            for email in attendees
        ],
        "isOnlineMeeting": True,
        "onlineMeetingProvider": "teamsForBusiness"
    }

    # POST to /me/events
    response = await self.graph_client.post('/me/events', json=event_body)

    # Extract Teams link
    teams_link = response.get('onlineMeeting', {}).get('joinUrl')

    return CalendarEvent(
        id=response['id'],
        summary=response['subject'],
        start_time=response['start']['dateTime'],
        teams_link=teams_link,
        **response
    )
```

### 3. Calendar Tools for Agent

**Tool Definitions**:
```python
class ListOutlookCalendarEventsTool(BaseTool):
    name = "list_outlook_calendar_events"
    description = "List upcoming Outlook calendar events"

    async def execute(
        self,
        days_ahead: int = 7
    ) -> str:
        client = OutlookCalendarClient()
        events = await client.list_events(
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=days_ahead)
        )
        return format_calendar_events(events)


class CreateOutlookCalendarEventTool(BaseTool):
    name = "create_outlook_calendar_event"
    description = "Create new Outlook calendar event with optional Teams link"

    async def execute(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        attendees: List[str] = None,
        add_teams_link: bool = False
    ) -> str:
        client = OutlookCalendarClient()
        event = await client.create_event(
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees,
            add_teams_link=add_teams_link
        )

        if add_teams_link:
            return f"✅ Event created with Teams link: {event.teams_link}"
        else:
            return f"✅ Event created: {event.summary}"
```

### 4. Calendar Sync Integration

**Extend SyncService**:
```python
async def sync_outlook_calendar(
    self,
    days_back: int = 30,
    days_ahead: int = 90
) -> dict:
    """Sync Outlook calendar events to local cache"""

    # Get events from Outlook
    outlook_client = OutlookCalendarClient()
    events = await outlook_client.list_events(
        start_date=datetime.now() - timedelta(days=days_back),
        end_date=datetime.now() + timedelta(days=days_ahead)
    )

    # Store in SQLite calendar_events table
    for event in events:
        await storage.upsert  # SQLite via SQLAlchemy('calendar_events').upsert({
            'owner_id': self.user_id,
            'provider': 'microsoft',  # NEW: Track provider
            'external_id': event.id,
            'summary': event.summary,
            'start_time': event.start_time,
            'end_time': event.end_time,
            'attendees': event.attendees,
            'teams_link': event.teams_link,  # NEW: Store Teams link
            'location': event.location
        }).execute()

    return {
        'provider': 'microsoft',
        'events_synced': len(events),
        'calendar_type': 'outlook'
    }
```

### 5. Gap Analysis for Outlook Calendar

**Extend RelationshipAnalyzer**:
```python
async def find_outlook_meetings_without_followup(
    self,
    days_back: int = 7,
    followup_window: int = 48
) -> List[Gap]:
    """Find Outlook meetings without follow-up email"""

    # Get Outlook calendar events
    events = await storage.upsert  # SQLite via SQLAlchemy('calendar_events').select('*').eq(
        'owner_id', self.user_id
    ).eq(
        'provider', 'microsoft'  # Filter for Outlook events
    ).gte(
        'start_time', datetime.now() - timedelta(days=days_back)
    ).execute()

    gaps = []
    for event in events.data:
        # Check if follow-up email was sent within window
        has_followup = await self._check_email_after_meeting(
            attendee_emails=event['attendees'],
            meeting_time=event['start_time'],
            window_hours=followup_window
        )

        if not has_followup:
            gaps.append({
                'type': 'outlook_meeting_no_followup',
                'meeting_id': event['id'],
                'summary': event['summary'],
                'attendees': event['attendees'],
                'days_ago': (datetime.now() - event['start_time']).days,
                'suggestion': 'Draft follow-up email for Outlook meeting'
            })

    return gaps
```

## Technical Requirements

### Backend Dependencies
```bash
# Microsoft Graph SDK (already installed)
pip install msgraph-sdk>=1.0.0
pip install azure-identity>=1.12.0
```

### Environment Variables
```bash
# Already configured for Outlook email
MICROSOFT_CLIENT_ID=<app_id>
MICROSOFT_CLIENT_SECRET=<secret>
MICROSOFT_TENANT_ID=<tenant_id>

# Ensure calendar scope is included
MICROSOFT_SCOPES=Calendars.ReadWrite,Mail.ReadWrite,User.Read
```

### Database Schema (Already Exists)
```sql
-- Extend calendar_events table with provider
ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'google';
ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS teams_link TEXT;

-- Index for provider filtering
CREATE INDEX IF NOT EXISTS idx_calendar_provider ON calendar_events(owner_id, provider);
```

## Implementation Phases

### Phase 1: Complete Calendar Client (Week 1)
**Duration**: 3-4 days
**Tasks**:
1. Review existing `OutlookCalendarClient` implementation
2. Complete `create_event()` method
3. Implement `update_event()` method
4. Implement `search_events()` method
5. Add Teams meeting link generation
6. Test all methods with Microsoft Graph API

### Phase 2: Calendar Tools (Week 1)
**Duration**: 2-3 days
**Tasks**:
1. Create `ListOutlookCalendarEventsTool`
2. Create `CreateOutlookCalendarEventTool`
3. Create `SearchOutlookCalendarEventsTool`
4. Create `UpdateOutlookCalendarEventTool`
5. Register tools in factory
6. Test tools via agent

### Phase 3: Calendar Sync (Week 2)
**Duration**: 2-3 days
**Tasks**:
1. Extend `SyncService` to support Outlook calendar
2. Implement `sync_outlook_calendar()` method
3. Add provider column to database
4. Update `/sync` command to include Outlook calendar
5. Test sync with real Outlook account

### Phase 4: Gap Analysis Integration (Week 2)
**Duration**: 2-3 days
**Tasks**:
1. Extend `RelationshipAnalyzer` for Outlook
2. Implement Outlook meeting gap detection
3. Integrate with existing gap analysis workflow
4. Update `/gaps` command to include Outlook meetings
5. Test multi-provider gap analysis (Google + Outlook)

### Phase 5: Documentation & Testing (Week 3)
**Duration**: 1-2 days
**Tasks**:
1. Write documentation for Outlook calendar features
2. Add Outlook examples to existing calendar docs
3. Create test cases for all new methods
4. Update user guides with Outlook setup instructions
5. Test edge cases (timezone handling, all-day events, recurring events)

## Success Metrics

### Technical Metrics
- **API Success Rate**: >99% of Graph API calls succeed
- **Sync Performance**: Outlook calendar syncs in <5 seconds
- **Feature Parity**: 100% of Google Calendar features available for Outlook

### Business Metrics
- **Outlook Adoption**: >40% of users connect Outlook calendar
- **Enterprise Customers**: >60% of enterprise users use Outlook
- **Multi-Provider Users**: >20% of users connect both Google and Outlook

### User Experience Metrics
- **Setup Time**: Connect Outlook calendar in <2 minutes
- **User Satisfaction**: >4.5/5 stars for Outlook calendar feature
- **Support Tickets**: <3% of users need help with Outlook setup

## Related Documentation

- **Architecture**: `docs/ARCHITECTURE.md` - Multi-provider architecture
- **Calendar Integration**: `docs/features/calendar-integration.md` - Google Calendar reference
- **Gap Analysis**: `docs/features/relationship-intelligence.md` - Relationship intelligence
- **Command Handlers**: `zylch/services/command_handlers.py:167` - TODO reference

## Open Questions

1. **Recurring Events**: How do we handle Outlook recurring events?
   - **Proposal**: Sync each occurrence as separate event

2. **Shared Calendars**: Should we support Outlook shared/delegated calendars?
   - **Proposal**: v1 = user's primary calendar only, v2 = shared calendars

3. **Timezone Handling**: Outlook uses different timezone format than Google
   - **Solution**: Always convert to UTC internally

4. **All-Day Events**: How to represent all-day events consistently?
   - **Proposal**: Use midnight-to-midnight UTC with `all_day: true` flag

5. **Calendar Selection**: If user has multiple Outlook calendars, which to sync?
   - **Proposal**: Default to primary, allow user to select others in settings

---

**Priority**: 🟡 **MEDIUM-HIGH - Feature Parity for Outlook Users**

**Owner**: Backend Team (Mario)

**Dependencies**:
- Microsoft Graph API access (DONE)
- Outlook OAuth flow (DONE)
- Database schema updates (SIMPLE)

**Next Steps**:
1. Review existing `OutlookCalendarClient` code
2. Complete missing methods
3. Add Teams meeting link generation
4. Test with real Outlook account

**Estimated Timeline**: 2-3 weeks

**Last Updated**: December 2025
