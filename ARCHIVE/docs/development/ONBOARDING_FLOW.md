# Lead Onboarding Flow

**Status:** Spec Ready - Not Implemented
**Priority:** P0 - Critical
**Last Updated:** November 29, 2025

---

## Overview

This document specifies the automated lead capture and qualification flow for Zylch AI. The flow uses email + phone verification to authenticate leads before a sales call.

---

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    LEAD ONBOARDING FLOW                         │
└─────────────────────────────────────────────────────────────────┘

    ┌──────────────┐
    │  1. WEBSITE  │  Lead enters email on website (HubSpot/landing page)
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │  2. EMAIL    │  Zylch sends welcome email from zylch@zylchai.com
    │   SENT       │  "Thanks for your interest! Reply to start..."
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │  3. LEAD     │  Lead replies to email
    │   REPLIES    │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │  4. CONTACT  │  Zylch creates contact record
    │   CREATED    │  Sends follow-up: "Call +1-202-XXX-XXXX to continue"
    └──────┬───────┘
           │
           ├─────────────────────────────────────┐
           │                                     │
           ▼                                     ▼
    ┌──────────────┐                     ┌──────────────┐
    │  5a. CALL    │                     │  5b. NO CALL │
    │   RECEIVED   │                     │   (30 min)   │
    └──────┬───────┘                     └──────┬───────┘
           │                                     │
           ▼                                     ▼
    ┌──────────────┐                     ┌──────────────┐
    │  DEMO CALL   │                     │  6. OFFER    │
    │  (MrCall AI) │                     │   CALLBACK   │
    └──────────────┘                     │   + SMS CODE │
                                         └──────┬───────┘
                                                │
                                                ▼
                                         ┌──────────────┐
                                         │  7. CODE     │
                                         │   VERIFIED   │
                                         └──────┬───────┘
                                                │
                                                ▼
                                         ┌──────────────┐
                                         │  8. OUTBOUND │
                                         │   CALL       │
                                         └──────────────┘
```

---

## Step-by-Step Specification

### Step 1: Website Lead Capture

**Trigger:** Lead submits email on website (HubSpot form, landing page, etc.)

**Data Captured:**
- Email address (required)
- Name (optional)
- Company (optional)
- Phone (optional - captured later if needed)

**Integration:** HubSpot webhook → Zylch API

---

### Step 2: Welcome Email

**Trigger:** New lead received via webhook

**From:** `zylch@zylchai.com`
**Subject:** `Welcome to Zylch AI - Let's get started`

**Email Template:**
```
Hi [Name or "there"],

Thanks for your interest in Zylch AI!

I'm your AI assistant, and I'll help you discover how Zylch can
transform your business communications.

Simply reply to this email to start our conversation, and I'll
guide you through everything.

Looking forward to hearing from you!

Best,
Zylch AI
```

**Technical Notes:**
- Track email open (pixel)
- Track email reply (Gmail webhook or polling)
- Store `lead_status: email_sent`

---

### Step 3: Lead Replies

**Trigger:** Reply detected from lead's email

**Action:**
1. Parse reply content
2. Extract any additional info (phone, company, use case)
3. Create/update contact record
4. Proceed to Step 4

**Technical Notes:**
- Match reply by email address
- Handle threading (In-Reply-To header)

---

### Step 4: Contact Created + Call Invitation

**Trigger:** Valid reply received

**Actions:**
1. Create contact in StarChat/CRM
2. Update `lead_status: contact_created`
3. Send follow-up email with phone number

**Email Template:**
```
Great to hear from you!

I've set up your account. To continue and hear a live demo of
what Zylch can do, please call:

📞 +1-202-XXX-XXXX

I'll answer and walk you through everything in about 5 minutes.

Talk soon!

Zylch AI
```

**Phone Number:**
- Dedicated MrCall assistant for onboarding
- Configured with onboarding script/demo

---

### Step 5a: Inbound Call Received

**Trigger:** Lead calls the provided number

**MrCall Behavior:**
1. Recognize caller by phone number (if provided earlier)
2. If unknown number, ask for email to match
3. Deliver onboarding demo script
4. Capture requirements/use case
5. Offer to schedule sales call with human

**Demo Script Topics:**
- What Zylch does (email intelligence)
- Quick demo of capabilities
- Ask about their use case
- Qualify lead (company size, budget, timeline)
- CTA: Schedule call with sales

**Technical Notes:**
- Log call in contact record
- Update `lead_status: demo_completed`
- Create task for sales follow-up

---

### Step 5b: No Call Within 30 Minutes

**Trigger:** 30 minutes elapsed since Step 4 email, no inbound call

**Action:** Send callback offer email

**Email Template:**
```
Hi again,

I noticed you haven't had a chance to call yet - no problem!

Would you like me to call YOU instead? For privacy and security,
I need to verify it's really you first.

Here's how it works:
1. I'll send a verification code to your phone via SMS
2. Reply to this email with the code
3. I'll call you right away!

Just reply with your phone number and I'll send the code.

Best,
Zylch AI
```

---

### Step 6: SMS Verification

**Trigger:** Lead replies with phone number

**Actions:**
1. Parse phone number from reply
2. Generate 6-digit verification code
3. Send SMS via Vonage

**SMS Template:**
```
Your Zylch verification code is: XXXXXX

Reply to the email with this code and we'll call you!
```

**Technical Notes:**
- Code expires in 10 minutes
- Max 3 attempts
- Store `verification_code` and `verification_expires` in contact
- Update `lead_status: code_sent`

---

### Step 7: Code Verification

**Trigger:** Lead replies to email with code

**Actions:**
1. Parse code from reply
2. Validate against stored code
3. Check expiration
4. If valid → proceed to Step 8
5. If invalid → send error, allow retry

**Success Email:**
```
Code verified! ✓

Calling you now at [phone number]...

If you miss the call, just reply to this email and we'll try again.
```

**Failure Email:**
```
Hmm, that code doesn't match. Please try again.

Your code was sent to [last 4 digits of phone].

Need a new code? Just reply "resend" and I'll send another.
```

---

### Step 8: Outbound Call

**Trigger:** Code verified

**Actions:**
1. Initiate outbound call via MrCall
2. Same demo script as Step 5a
3. Log outcome

**Technical Notes:**
- Use MrCall outbound API
- Caller ID: Zylch number
- If no answer: leave voicemail, send follow-up email
- Update `lead_status: demo_completed` or `demo_attempted`

---

## Data Model

### Lead Status Values

```python
class LeadStatus(Enum):
    NEW = "new"                      # Just captured
    EMAIL_SENT = "email_sent"        # Welcome email sent
    EMAIL_REPLIED = "email_replied"  # Lead replied
    CONTACT_CREATED = "contact_created"  # Contact record created
    CALL_INVITED = "call_invited"    # Phone number provided
    CODE_SENT = "code_sent"          # SMS verification sent
    CODE_VERIFIED = "code_verified"  # Phone verified
    DEMO_COMPLETED = "demo_completed"  # Demo call completed
    DEMO_ATTEMPTED = "demo_attempted"  # Call attempted, no answer
    QUALIFIED = "qualified"          # Ready for sales
    DISQUALIFIED = "disqualified"    # Not a fit
```

### Contact Record Fields

```python
@dataclass
class OnboardingContact:
    email: str
    name: Optional[str]
    phone: Optional[str]
    company: Optional[str]

    lead_status: LeadStatus

    # Tracking
    created_at: datetime
    welcome_email_sent_at: Optional[datetime]
    first_reply_at: Optional[datetime]
    call_invite_sent_at: Optional[datetime]

    # Verification
    verification_code: Optional[str]
    verification_expires: Optional[datetime]
    verification_attempts: int = 0

    # Call tracking
    inbound_calls: List[dict]
    outbound_calls: List[dict]

    # Qualification
    use_case: Optional[str]
    company_size: Optional[str]
    budget: Optional[str]
    timeline: Optional[str]
    notes: str = ""
```

---

## Timing Configuration

| Event | Timeout | Action on Timeout |
|-------|---------|-------------------|
| No reply to welcome email | 24 hours | Send reminder email |
| No reply to reminder | 48 hours | Mark as cold, stop sequence |
| No call after invite | 30 minutes | Send callback offer |
| No reply to callback offer | 24 hours | Send final follow-up |
| Verification code | 10 minutes | Code expires |

---

## MrCall Configuration

### Onboarding Assistant

Create dedicated MrCall assistant for onboarding:

**Assistant ID:** `zylch_onboarding`
**Phone Number:** `+1-202-XXX-XXXX`

**Welcome Script:**
```
Hi! Thanks for calling Zylch AI. I'm your AI assistant, and I'm
excited to show you what we can do.

Before we dive in, can you tell me your name and company?

[Wait for response]

Great, [Name]! Let me give you a quick 3-minute overview of
Zylch, and then I'd love to hear about your specific needs.

[Deliver demo]
```

**Demo Topics:**
1. What Zylch does (30 sec)
2. Key capabilities: email search, drafting, calendar (1 min)
3. Memory and learning (30 sec)
4. Contact intelligence (30 sec)
5. Ask about their use case (30 sec)

**Qualification Questions:**
- "What's your biggest pain point with email/communication today?"
- "How many people would use this on your team?"
- "Are you looking to implement something soon, or just exploring?"

**Handoff:**
```
This sounds like a great fit! I'd love to connect you with our
team to discuss next steps. Would you like me to schedule a call
with them? They can do a deeper demo and answer any questions.
```

---

## Implementation Checklist

### Phase 1: Email Flow
- [ ] HubSpot webhook integration
- [ ] Welcome email template and sending
- [ ] Reply detection and parsing
- [ ] Contact creation in StarChat

### Phase 2: Call Flow
- [ ] MrCall onboarding assistant setup
- [ ] Inbound call handling
- [ ] Call logging and status updates

### Phase 3: Verification Flow
- [ ] SMS sending via Vonage
- [ ] Code generation and validation
- [ ] Outbound call initiation

### Phase 4: Automation
- [ ] Timeout handling (30 min, 24 hour triggers)
- [ ] Status-based email sequences
- [ ] Lead scoring and qualification

---

## Open Questions (TO BE DECIDED)

1. **After demo call - what happens next?**
   - Automatic Calendly link?
   - Human sales rep takes over?
   - Self-service signup?

2. **What if lead gives wrong phone number?**
   - Allow retry?
   - Email verification instead?

3. **Multiple failed verification attempts?**
   - Lock out?
   - Flag for manual review?

4. **Lead qualification thresholds?**
   - What makes a lead "qualified"?
   - Auto-disqualification criteria?

---

## Related Documents

- [TODO.md](./TODO.md) - Feature backlog
- [ZYLCH_SPEC.md](./ZYLCH_SPEC.md) - Main technical spec
- [ZYLCH_DEVELOPMENT_PLAN.md](./ZYLCH_DEVELOPMENT_PLAN.md) - Development roadmap
