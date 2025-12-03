"""Mock data for tutorial sandbox demonstrations."""

from datetime import datetime, timedelta
from typing import Optional

# Mock contacts for demonstration
MOCK_CONTACTS = [
    {
        "name": "Marco Ferrari",
        "email": "marco.ferrari@techcorp.example.com",
        "phone": "+39 333 123 4567",
        "company": "TechCorp Italia",
        "role": "Sales Director",
        "last_contact": "2 days ago",
        "relationship": "Client - Active deal",
        "notes": "Prefers morning calls, very direct communicator",
    },
    {
        "name": "Sofia Bianchi",
        "email": "sofia.bianchi@designstudio.example.com",
        "phone": "+39 333 987 6543",
        "company": "Creative Design Studio",
        "role": "Creative Director",
        "last_contact": "1 week ago",
        "relationship": "Partner",
        "notes": "Working on Q4 campaign together",
    },
    {
        "name": "Elena Verdi",
        "email": "elena.verdi@lawfirm.example.com",
        "phone": "+39 02 555 1234",
        "company": "Verdi & Associates",
        "role": "Legal Counsel",
        "last_contact": "3 days ago",
        "relationship": "Service Provider",
        "notes": "Handling contract review",
    },
    {
        "name": "Giovanni Rossi",
        "email": "giovanni.rossi@startup.example.com",
        "phone": "+39 333 456 7890",
        "company": "InnovateTech",
        "role": "CEO",
        "last_contact": "2 weeks ago",
        "relationship": "Prospect",
        "notes": "Interested in enterprise solution",
    },
    {
        "name": "Laura Conti",
        "email": "laura.conti@mediagroup.example.com",
        "phone": "+39 333 111 2222",
        "company": "Media Group Italia",
        "role": "Marketing Manager",
        "last_contact": "5 days ago",
        "relationship": "Lead",
        "notes": "Met at conference last month",
    },
]

# Mock emails for demonstration
MOCK_EMAILS = [
    {
        "id": "email_001",
        "from": "marco.ferrari@techcorp.example.com",
        "from_name": "Marco Ferrari",
        "to": "you@company.example.com",
        "subject": "Re: Q4 Proposal - Ready for Review",
        "snippet": "Thanks for sending the updated proposal. I've reviewed the numbers and have a few questions about the timeline...",
        "date": "2 days ago",
        "needs_reply": True,
        "priority": "high",
    },
    {
        "id": "email_002",
        "from": "sofia.bianchi@designstudio.example.com",
        "from_name": "Sofia Bianchi",
        "to": "you@company.example.com",
        "subject": "Campaign Assets - First Draft",
        "snippet": "Hi! Attached are the first drafts of the campaign visuals. Let me know what you think...",
        "date": "1 week ago",
        "needs_reply": False,
        "priority": "medium",
    },
    {
        "id": "email_003",
        "from": "elena.verdi@lawfirm.example.com",
        "from_name": "Elena Verdi",
        "to": "you@company.example.com",
        "subject": "Contract Review - Action Required",
        "snippet": "I've completed my review of the TechCorp agreement. Please see my comments highlighted in the attached...",
        "date": "3 days ago",
        "needs_reply": True,
        "priority": "high",
    },
    {
        "id": "email_004",
        "from": "giovanni.rossi@startup.example.com",
        "from_name": "Giovanni Rossi",
        "to": "you@company.example.com",
        "subject": "Follow-up: Enterprise Demo",
        "snippet": "Great meeting you at the conference. I'd love to schedule a demo of your enterprise solution for my team...",
        "date": "2 weeks ago",
        "needs_reply": True,
        "priority": "medium",
    },
    {
        "id": "email_005",
        "from": "laura.conti@mediagroup.example.com",
        "from_name": "Laura Conti",
        "to": "you@company.example.com",
        "subject": "Partnership Opportunity",
        "snippet": "I've been thinking about what we discussed. There might be a great opportunity for collaboration between our companies...",
        "date": "5 days ago",
        "needs_reply": False,
        "priority": "low",
    },
]

# Mock calendar events for demonstration
MOCK_EVENTS = [
    {
        "id": "event_001",
        "title": "Follow-up call with Marco",
        "date": "Tomorrow 10:00",
        "end_time": "Tomorrow 10:30",
        "attendees": ["marco.ferrari@techcorp.example.com"],
        "has_meet_link": True,
        "meet_link": "https://meet.google.com/abc-defg-hij",
        "description": "Discuss Q4 proposal questions",
    },
    {
        "id": "event_002",
        "title": "Team Sync",
        "date": "Tomorrow 14:00",
        "end_time": "Tomorrow 15:00",
        "attendees": ["team@company.example.com"],
        "has_meet_link": True,
        "meet_link": "https://meet.google.com/xyz-uvwx-yz",
        "description": "Weekly team sync",
    },
    {
        "id": "event_003",
        "title": "Campaign Review with Sofia",
        "date": "Thursday 11:00",
        "end_time": "Thursday 12:00",
        "attendees": ["sofia.bianchi@designstudio.example.com"],
        "has_meet_link": False,
        "description": "Review first draft of campaign assets",
    },
    {
        "id": "event_004",
        "title": "Contract signing - TechCorp",
        "date": "Friday 15:00",
        "end_time": "Friday 16:00",
        "attendees": [
            "marco.ferrari@techcorp.example.com",
            "elena.verdi@lawfirm.example.com",
        ],
        "has_meet_link": True,
        "meet_link": "https://meet.google.com/qrs-tuvw-xyz",
        "description": "Final contract signing with TechCorp",
    },
]

# Mock tasks for demonstration
MOCK_TASKS = [
    {
        "id": "task_001",
        "description": "Send updated pricing to Marco",
        "due": "Today",
        "priority": "high",
        "contact": "Marco Ferrari",
        "source": "Email conversation",
    },
    {
        "id": "task_002",
        "description": "Review Elena's contract comments",
        "due": "Tomorrow",
        "priority": "high",
        "contact": "Elena Verdi",
        "source": "Email",
    },
    {
        "id": "task_003",
        "description": "Schedule demo for Giovanni",
        "due": "This week",
        "priority": "medium",
        "contact": "Giovanni Rossi",
        "source": "Conference follow-up",
    },
    {
        "id": "task_004",
        "description": "Send feedback on campaign visuals",
        "due": "Thursday",
        "priority": "medium",
        "contact": "Sofia Bianchi",
        "source": "Email",
    },
]


def get_mock_contact(name: str) -> Optional[dict]:
    """Get a mock contact by name (partial match)."""
    name_lower = name.lower()
    for contact in MOCK_CONTACTS:
        if name_lower in contact["name"].lower():
            return contact
    return None


def get_mock_email_thread(contact_name: str) -> list[dict]:
    """Get mock emails involving a contact."""
    emails = []
    name_lower = contact_name.lower()
    for email in MOCK_EMAILS:
        if name_lower in email["from_name"].lower():
            emails.append(email)
    return emails


def get_mock_briefing() -> dict:
    """Generate a mock daily briefing."""
    return {
        "date": datetime.now().strftime("%A, %B %d, %Y"),
        "meetings_today": [e for e in MOCK_EVENTS if "Tomorrow" in e["date"]][:2],
        "priority_emails": [e for e in MOCK_EMAILS if e["needs_reply"]][:3],
        "pending_tasks": [t for t in MOCK_TASKS if t["priority"] == "high"][:2],
        "relationship_gaps": [
            {
                "contact": "Giovanni Rossi",
                "last_contact": "2 weeks ago",
                "usual_frequency": "weekly",
                "suggestion": "Follow up on enterprise demo interest",
            }
        ],
    }
