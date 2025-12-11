# WhatsApp Integration - Future Development

## Status
🔴 **HIGH PRIORITY** - Multi-Channel Communication

## Business Impact

**Market Opportunity**:
- **6.9 billion WhatsApp users worldwide** (2025)
- **Business users**: 50M+ businesses use WhatsApp Business
- **Engagement**: 100 billion messages sent daily on WhatsApp

**Why Important**:
- **Sales intelligence**: Track WhatsApp conversations with leads/clients
- **Multi-channel view**: Unified intelligence across email, calendar, calls, SMS, WhatsApp
- **Business relationships**: Many professionals prefer WhatsApp over email
- **International**: Essential for international business (especially Europe, Latin America, Asia)

**Use Cases**:
- Sales reps tracking WhatsApp conversations with clients
- Customer support teams managing WhatsApp Business inquiries
- Executives maintaining relationships via WhatsApp
- Multi-channel relationship gap detection

## Current State

### What Exists
- ✅ **Tool structure ready**: `_GetWhatsAppContactsTool` defined in `factory.py`
- ✅ **StarChat integration**: Contact management system in place
- ✅ **Multi-channel architecture**: Email, SMS, calls already integrated
- ✅ **Tool factory pattern**: Easy to add new communication channels

### What's Missing
- ❌ **StarChat WhatsApp API**: REST endpoint not yet available from StarChat
- ❌ **WhatsApp message sync**: No message retrieval implementation
- ❌ **WhatsApp conversation threading**: No thread aggregation
- ❌ **WhatsApp send capability**: Can't send messages via agent
- ❌ **WhatsApp gap analysis**: No integration with relationship intelligence

### Blocking Issue
**CRITICAL**: Waiting for StarChat to provide WhatsApp REST API endpoint.

**Current Status** (from STARCHAT_REQUESTS.md:305):
```python
# TODO: STARCHAT_REQUEST - Quando disponibile, usare StarChat lookup_by_email
# Waiting for StarChat REST API endpoint for WhatsApp contacts
```

**Required from StarChat**:
1. `GET /api/whatsapp/contacts` - List WhatsApp contacts
2. `GET /api/whatsapp/messages?contact_id={id}` - Get message history
3. `POST /api/whatsapp/send` - Send WhatsApp message
4. Webhook for real-time message notifications

## Planned Features

### 1. WhatsApp Contact Sync

**Endpoint**: `GET /api/whatsapp/contacts`
**Response**:
```json
{
  "contacts": [
    {
      "id": "wa_contact_123",
      "phone_number": "+393281234567",
      "name": "Mario Alemi",
      "profile_picture": "https://...",
      "last_seen": "2025-12-08T10:30:00Z",
      "business_account": false
    }
  ]
}
```

**Implementation**:
```python
class WhatsAppClient:
    def __init__(self):
        self.starchat_api = StarChatAPI()

    async def get_contacts(self) -> List[WhatsAppContact]:
        """Fetch all WhatsApp contacts from StarChat"""
        response = await self.starchat_api.get('/api/whatsapp/contacts')
        return [WhatsAppContact(**contact) for contact in response['contacts']]
```

### 2. WhatsApp Message History

**Endpoint**: `GET /api/whatsapp/messages?contact_id={id}&days_back=30`
**Response**:
```json
{
  "messages": [
    {
      "id": "msg_123",
      "contact_id": "wa_contact_123",
      "sender": "me",
      "receiver": "+393281234567",
      "text": "Ciao Mario, ci sentiamo domani per il call?",
      "timestamp": "2025-12-07T15:30:00Z",
      "status": "delivered",
      "media": []
    }
  ]
}
```

**Implementation**:
```python
async def get_conversation_history(
    self,
    contact_id: str,
    days_back: int = 30
) -> List[WhatsAppMessage]:
    """Fetch WhatsApp conversation history"""
    response = await self.starchat_api.get(
        f'/api/whatsapp/messages',
        params={'contact_id': contact_id, 'days_back': days_back}
    )
    return [WhatsAppMessage(**msg) for msg in response['messages']]
```

### 3. Send WhatsApp Messages

**Endpoint**: `POST /api/whatsapp/send`
**Request**:
```json
{
  "to": "+393281234567",
  "text": "Confermo per domani alle 15:00. Ti mando il link Zoom via email.",
  "reply_to_message_id": "msg_123"  // Optional: reply to specific message
}
```

**Implementation**:
```python
async def send_message(
    self,
    to: str,
    text: str,
    reply_to: Optional[str] = None
) -> WhatsAppMessage:
    """Send WhatsApp message via StarChat"""
    response = await self.starchat_api.post('/api/whatsapp/send', {
        'to': to,
        'text': text,
        'reply_to_message_id': reply_to
    })
    return WhatsAppMessage(**response['message'])
```

### 4. WhatsApp Tool for Agent

**Tool Definition**:
```python
class SendWhatsAppTool(BaseTool):
    name = "send_whatsapp"
    description = "Send WhatsApp message to a contact"

    async def execute(
        self,
        contact_name: str,
        message: str
    ) -> str:
        # 1. Look up contact in StarChat
        contact = await self.starchat.lookup_contact(contact_name)

        # 2. Get WhatsApp number
        whatsapp_number = contact.get('whatsapp_phone')
        if not whatsapp_number:
            return f"❌ {contact_name} doesn't have WhatsApp number"

        # 3. Send message
        await self.whatsapp_client.send_message(whatsapp_number, message)

        # 4. Store in memory
        await self.memory.store_memory(
            f"whatsapp/{contact_name}",
            {
                'last_message': message,
                'timestamp': datetime.now().isoformat()
            }
        )

        return f"✅ WhatsApp message sent to {contact_name}"
```

### 5. Multi-Channel Conversation Threading

**Unified Thread View**:
```python
async def get_unified_conversation(contact_email: str) -> dict:
    """Get all communication with a contact across channels"""
    # Email threads
    email_threads = await gmail.get_threads_with_contact(contact_email)

    # WhatsApp messages
    whatsapp_contact = await starchat.lookup_by_email(contact_email)
    whatsapp_messages = await whatsapp.get_conversation_history(
        whatsapp_contact.id
    )

    # Calendar events
    calendar_events = await calendar.search_events(contact_email)

    # SMS messages
    sms_messages = await vonage.get_sms_history(
        whatsapp_contact.phone_number
    )

    # Merge and sort by timestamp
    all_interactions = sorted(
        email_threads + whatsapp_messages + calendar_events + sms_messages,
        key=lambda x: x.timestamp
    )

    return {
        'contact': contact_email,
        'channels': {
            'email': len(email_threads),
            'whatsapp': len(whatsapp_messages),
            'calendar': len(calendar_events),
            'sms': len(sms_messages)
        },
        'timeline': all_interactions
    }
```

### 6. WhatsApp Gap Analysis

**Extend Relationship Intelligence**:
```python
async def analyze_whatsapp_gaps(days_back: int = 7) -> List[Gap]:
    """Find relationship gaps in WhatsApp conversations"""
    gaps = []

    # Get all WhatsApp contacts
    contacts = await whatsapp_client.get_contacts()

    for contact in contacts:
        # Get conversation history
        messages = await whatsapp_client.get_conversation_history(
            contact.id, days_back
        )

        # Find gaps
        if last_message_from_contact_awaiting_response(messages):
            gaps.append({
                'type': 'whatsapp_unanswered',
                'contact': contact.name,
                'last_message': messages[-1].text,
                'days_waiting': days_since(messages[-1].timestamp),
                'priority': calculate_priority(contact, messages)
            })

        # Silent WhatsApp contacts (no messages in 30 days)
        if contact.has_previous_conversations and days_since_last_message > 30:
            gaps.append({
                'type': 'whatsapp_silent',
                'contact': contact.name,
                'days_silent': days_since_last_message,
                'suggestion': 'Send WhatsApp check-in message'
            })

    return gaps
```

## Technical Requirements

### Backend Dependencies
```bash
# StarChat SDK (when available)
pip install starchat-sdk>=1.0.0

# Or direct HTTP client
pip install httpx>=0.24.0
```

### Environment Variables
```bash
STARCHAT_API_KEY=sc_...
STARCHAT_API_URL=https://api.starchat.com/v1
```

### Database Schema
```sql
-- Store WhatsApp messages locally (mirror of StarChat data)
CREATE TABLE whatsapp_messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  owner_id TEXT NOT NULL REFERENCES users(id),
  starchat_message_id TEXT UNIQUE NOT NULL,
  contact_phone TEXT NOT NULL,
  contact_name TEXT,
  sender TEXT NOT NULL, -- 'me' or contact_phone
  text TEXT NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  status TEXT, -- 'sent', 'delivered', 'read'
  created_at TIMESTAMP DEFAULT NOW(),
  INDEX idx_owner_contact (owner_id, contact_phone),
  INDEX idx_timestamp (timestamp DESC)
);

-- WhatsApp contacts cache
CREATE TABLE whatsapp_contacts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  owner_id TEXT NOT NULL REFERENCES users(id),
  starchat_contact_id TEXT UNIQUE NOT NULL,
  phone_number TEXT NOT NULL,
  name TEXT,
  profile_picture TEXT,
  last_message_at TIMESTAMP,
  synced_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(owner_id, phone_number)
);
```

## Implementation Phases

### Phase 0: StarChat API Availability (Blocking)
**Duration**: Waiting on StarChat team
**Tasks**:
1. Request WhatsApp API endpoints from StarChat
2. Get API documentation
3. Test API in development environment
4. Confirm webhook availability

### Phase 1: Basic Integration (Week 1)
**Duration**: 3-5 days
**Prerequisites**: StarChat WhatsApp API available
**Tasks**:
1. Create `WhatsAppClient` class
2. Implement `get_contacts()` method
3. Implement `get_conversation_history()` method
4. Add database tables for local caching
5. Test contact sync

### Phase 2: Message Sending (Week 1-2)
**Duration**: 2-3 days
**Tasks**:
1. Implement `send_message()` method
2. Create `SendWhatsAppTool` for agent
3. Add to tool factory
4. Test sending messages via agent
5. Store sent messages in memory

### Phase 3: Multi-Channel Threading (Week 2)
**Duration**: 3-4 days
**Tasks**:
1. Create `get_unified_conversation()` function
2. Merge email, WhatsApp, calendar, SMS timelines
3. Add timeline view to dashboard
4. Test multi-channel correlation

### Phase 4: Gap Analysis (Week 3)
**Duration**: 3-4 days
**Tasks**:
1. Extend `GapService` to include WhatsApp
2. Implement WhatsApp-specific gap detection
3. Add WhatsApp gaps to `/gaps` briefing
4. Create WhatsApp-triggered automations

### Phase 5: Real-Time Sync (Week 4)
**Duration**: 2-3 days
**Prerequisites**: StarChat webhook support
**Tasks**:
1. Set up webhook endpoint for WhatsApp messages
2. Handle real-time message notifications
3. Update conversation cache on new messages
4. Trigger gap re-analysis on message arrival

## Success Metrics

### Technical Metrics
- **Sync Speed**: WhatsApp contacts synced in <5 seconds
- **Message Latency**: Send WhatsApp message in <2 seconds
- **Gap Detection Accuracy**: >90% of unanswered WhatsApp messages detected

### Business Metrics
- **Adoption Rate**: >50% of users connect WhatsApp within first week
- **Engagement**: Average 10+ WhatsApp messages per user per day
- **Multi-Channel Value**: Users with WhatsApp have 2x higher retention

### User Experience Metrics
- **Setup Time**: Connect WhatsApp in <1 minute
- **User Satisfaction**: >4.5/5 stars for WhatsApp feature
- **Support Tickets**: <2% of users need help with WhatsApp setup

## Related Documentation

- **Architecture**: `docs/architecture/overview.md` - Multi-channel architecture
- **Contact Tools**: Tool factory pattern for new channels
- **Gap Analysis**: `docs/features/relationship-intelligence.md` - Extend gap detection
- **StarChat Requests**: `STARCHAT_REQUESTS.md` - API requirements

## Open Questions

1. **WhatsApp Business API**: Does StarChat use WhatsApp Business API or personal WhatsApp?
   - **Impact**: Business API has different rate limits and features

2. **Message History Limits**: How far back can we retrieve WhatsApp messages?
   - **Impact**: Affects initial sync and gap analysis accuracy

3. **Media Support**: Can we retrieve/send images, videos, documents?
   - **Proposal**: Start with text only, add media in Phase 6

4. **Group Chats**: Do we support WhatsApp group conversations?
   - **Proposal**: Personal chats only in v1, groups in v2

5. **WhatsApp Web Sync**: Can we access messages sent from WhatsApp Web?
   - **Impact**: Ensures complete conversation history

6. **Rate Limits**: What are StarChat's API rate limits for WhatsApp?
   - **Impact**: Affects sync frequency and real-time updates

---

**Priority**: 🔴 **HIGH - Pending StarChat API**

**Owner**: Backend Team (Mario) + StarChat Integration

**Blocking Dependencies**:
- StarChat WhatsApp REST API endpoints
- StarChat API documentation
- StarChat webhook support (for real-time)

**Next Steps**:
1. ✅ Request WhatsApp API from StarChat (DONE)
2. ⏳ Wait for StarChat API availability (IN PROGRESS)
3. Review API documentation when ready
4. Implement Phase 1 (Basic Integration)

**Estimated Start Date**: Q1 2026 (pending StarChat)

**Last Updated**: December 2025
