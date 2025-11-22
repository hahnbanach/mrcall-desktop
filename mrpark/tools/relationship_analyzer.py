"""Relationship intelligence analyzer.

Correlates email threads and calendar events to identify communication gaps,
missed follow-ups, and relationship opportunities.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RelationshipAnalyzer:
    """Analyzes communication patterns across channels to identify gaps."""

    def __init__(
        self,
        email_cache_path: str = "cache/emails/threads.json",
        calendar_cache_path: str = "cache/calendar/events.json",
        anthropic_api_key: Optional[str] = None,
        memory_bank = None
    ):
        """Initialize relationship analyzer.

        Args:
            email_cache_path: Path to email threads cache
            calendar_cache_path: Path to calendar events cache
            anthropic_api_key: Anthropic API key for semantic filtering
            memory_bank: ReasoningBankMemory instance for user preferences
        """
        self.email_cache_path = Path(email_cache_path)
        self.calendar_cache_path = Path(calendar_cache_path)
        self.anthropic_api_key = anthropic_api_key
        self.memory_bank = memory_bank

        # Initialize Anthropic client if API key provided
        self.anthropic_client = None
        if anthropic_api_key:
            try:
                import anthropic
                self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)
                logger.info("Sonnet semantic filtering enabled")
            except ImportError:
                logger.warning("Anthropic package not installed, semantic filtering disabled")
            except Exception as e:
                logger.warning(f"Failed to initialize Anthropic client: {e}")

        logger.info("Initialized RelationshipAnalyzer")

    def _load_threads(self) -> Dict[str, Any]:
        """Load email threads from cache."""
        if not self.email_cache_path.exists():
            logger.warning(f"Email cache not found: {self.email_cache_path}")
            return {"threads": {}}

        with open(self.email_cache_path, 'r') as f:
            return json.load(f)

    def _load_events(self) -> Dict[str, Any]:
        """Load calendar events from cache."""
        if not self.calendar_cache_path.exists():
            logger.warning(f"Calendar cache not found: {self.calendar_cache_path}")
            return {"events": {}}

        with open(self.calendar_cache_path, 'r') as f:
            return json.load(f)

    def find_meeting_without_followup(
        self,
        days_back: int = 7,
        followup_window: int = 48  # hours
    ) -> List[Dict[str, Any]]:
        """Find meetings that were NOT followed by an email.

        This is a critical relationship gap - after meeting someone,
        you should follow up with an email.

        Args:
            days_back: How many days back to check for meetings
            followup_window: Hours after meeting to look for email (default: 48h)

        Returns:
            List of meetings without follow-up emails
        """
        logger.info(f"🔍 Analyzing meetings without follow-up (last {days_back} days)...")

        events_data = self._load_events()
        threads_data = self._load_threads()

        events = events_data.get('events', {})
        threads = threads_data.get('threads', {})

        gaps = []
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        for event in events.values():
            # Only check past external meetings
            if not event.get('is_past'):
                continue

            if not event.get('external_attendees'):
                continue

            # Check if within time window
            try:
                start_dt = datetime.fromisoformat(
                    event['start'].replace('Z', '+00:00')
                ).replace(tzinfo=None)  # Strip timezone for naive comparison
                if start_dt < cutoff_date:
                    continue
            except:
                continue

            # Check if user accepted the meeting (skip if declined/tentative/needsAction)
            user_accepted = self._user_accepted_meeting(event)
            if not user_accepted:
                continue

            # Check each external attendee
            for attendee_email in event.get('external_attendees', []):
                # Look for emails with this contact after the meeting
                has_followup = self._has_email_after(
                    attendee_email,
                    start_dt,
                    followup_window,
                    threads
                )

                if not has_followup:
                    gaps.append({
                        "type": "meeting_no_followup",
                        "meeting_id": event['id'],
                        "meeting_summary": event.get('summary', ''),
                        "meeting_date": event['start'],
                        "contact_email": attendee_email,
                        "contact_name": self._extract_name_from_email(attendee_email),
                        "days_ago": (datetime.now(timezone.utc) - start_dt).days,
                        "severity": "high" if (datetime.now(timezone.utc) - start_dt).days > 2 else "medium",
                        "suggested_action": "Draft follow-up email"
                    })

        logger.info(f"Found {len(gaps)} meetings without follow-up")
        return gaps

    def find_email_tasks(
        self,
        days_back: int = 7
    ) -> List[Dict[str, Any]]:
        """Find email TASKS aggregated by PERSON.

        NEW LOGIC:
        1. Group all threads by person (contact email)
        2. For each person, pass ALL their threads to Sonnet
        3. Sonnet analyzes entire relationship and decides: TASK or NO TASK
        4. If TASK → Sonnet provides action recommendation

        Args:
            days_back: How many days back to check

        Returns:
            List of person-level tasks (one per person max)
        """
        logger.info(f"🔍 Finding email tasks by PERSON (last {days_back} days)...")

        threads_data = self._load_threads()
        threads = threads_data.get('threads', {})

        # Group threads by person
        person_threads = {}
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        for thread in threads.values():
            # Only consider threads with action
            if not thread.get('requires_action'):
                continue

            # Check if recent
            last_msg_date = self._parse_email_date(thread.get('last_message_date', ''))
            if not last_msg_date or last_msg_date < cutoff_date:
                continue

            # Extract contact
            last_email = thread.get('last_email', {})
            from_field = last_email.get('from', '')
            if not from_field:
                continue

            contact_email = self._extract_email_from_field(from_field)
            if not contact_email or self._is_bot_email(contact_email):
                continue

            # Group by person
            if contact_email not in person_threads:
                person_threads[contact_email] = {
                    'contact_email': contact_email,
                    'contact_name': self._extract_name_from_from_field(from_field),
                    'threads': []
                }

            person_threads[contact_email]['threads'].append(thread)

        logger.info(f"Grouped into {len(person_threads)} people with active threads")

        # Analyze each person with Sonnet
        tasks = []
        for person_data in person_threads.values():
            task = self._analyze_person_for_task(person_data)
            if task:  # Only if Sonnet says there's a TASK
                tasks.append(task)

        logger.info(f"Found {len(tasks)} person-level tasks")
        return tasks

    def find_silent_contacts(
        self,
        days_threshold: int = 30,
        min_past_interactions: int = 3
    ) -> List[Dict[str, Any]]:
        """Find important contacts who have gone silent.

        Identifies contacts with past interactions but no recent communication.

        Args:
            days_threshold: Days of silence to flag
            min_past_interactions: Minimum past interactions to consider

        Returns:
            List of silent contacts
        """
        logger.info(f"🔍 Analyzing silent contacts (>{days_threshold} days)...")

        threads_data = self._load_threads()
        events_data = self._load_events()

        threads = threads_data.get('threads', {})
        events = events_data.get('events', {})

        # Build contact interaction map
        contact_interactions = {}
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_threshold)

        # Count email interactions
        for thread in threads.values():
            for participant in thread.get('participants', []):
                # Handle both string emails and dict format (for compatibility)
                if isinstance(participant, str):
                    email = participant
                    name = self._extract_name_from_email(email)
                else:
                    email = participant.get('email', '')
                    name = participant.get('name', email)

                if not email:
                    continue

                if email not in contact_interactions:
                    contact_interactions[email] = {
                        "email": email,
                        "name": name,
                        "total_emails": 0,
                        "total_meetings": 0,
                        "last_email": None,
                        "last_meeting": None
                    }

                contact_interactions[email]["total_emails"] += 1

                # Track last email date
                try:
                    msg_date = datetime.fromisoformat(
                        thread.get('last_message_date', '').replace('Z', '+00:00')
                    ).replace(tzinfo=None)  # Strip timezone for naive comparison
                    if (not contact_interactions[email]["last_email"] or
                        msg_date > contact_interactions[email]["last_email"]):
                        contact_interactions[email]["last_email"] = msg_date
                except:
                    pass

        # Count meeting interactions
        for event in events.values():
            for attendee_email in event.get('attendees', []):
                if attendee_email not in contact_interactions:
                    contact_interactions[attendee_email] = {
                        "email": attendee_email,
                        "name": self._extract_name_from_email(attendee_email),
                        "total_emails": 0,
                        "total_meetings": 0,
                        "last_email": None,
                        "last_meeting": None
                    }

                contact_interactions[attendee_email]["total_meetings"] += 1

                # Track last meeting date
                try:
                    meeting_date = datetime.fromisoformat(
                        event['start'].replace('Z', '+00:00')
                    ).replace(tzinfo=None)  # Strip timezone for naive comparison
                    if (not contact_interactions[attendee_email]["last_meeting"] or
                        meeting_date > contact_interactions[attendee_email]["last_meeting"]):
                        contact_interactions[attendee_email]["last_meeting"] = meeting_date
                except:
                    pass

        # Find silent contacts
        silent = []
        for contact in contact_interactions.values():
            total_interactions = contact["total_emails"] + contact["total_meetings"]

            if total_interactions < min_past_interactions:
                continue

            # Get most recent interaction
            last_interaction = None
            if contact["last_email"] and contact["last_meeting"]:
                last_interaction = max(contact["last_email"], contact["last_meeting"])
            elif contact["last_email"]:
                last_interaction = contact["last_email"]
            elif contact["last_meeting"]:
                last_interaction = contact["last_meeting"]

            if last_interaction and last_interaction < cutoff_date:
                days_silent = (datetime.now(timezone.utc) - last_interaction).days

                silent.append({
                    "type": "silent_contact",
                    "contact_email": contact["email"],
                    "contact_name": contact["name"],
                    "total_interactions": total_interactions,
                    "total_emails": contact["total_emails"],
                    "total_meetings": contact["total_meetings"],
                    "last_interaction": last_interaction.isoformat(),
                    "days_silent": days_silent,
                    "severity": "high" if days_silent > 60 else "medium",
                    "suggested_action": "Re-engage with check-in email"
                })

        # Sort by days silent (longest first)
        silent.sort(key=lambda x: x["days_silent"], reverse=True)

        logger.info(f"Found {len(silent)} silent contacts")
        return silent

    def analyze_all_gaps(
        self,
        days_back: int = 7
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Find all TASKS that need to be created.

        SIMPLE LOGIC:
        1. Email with requires_action = True → TASK
        2. Meeting without follow-up email → TASK
        3. Silent contacts → TASK (optional, can disable)

        No complex filtering. Sonnet will decide what to do with each task.

        Args:
            days_back: Days to analyze

        Returns:
            Dict with all task types
        """
        logger.info(f"🔍 Finding all TASKS (last {days_back} days)...")

        results = {
            "email_tasks": self.find_email_tasks(days_back),
            "meeting_followup_tasks": self.find_meeting_without_followup(days_back),
            "silent_contacts": self.find_silent_contacts(days_threshold=30),
            "analyzed_at": datetime.now(timezone.utc).isoformat()
        }

        total_tasks = sum(len(v) for k, v in results.items() if isinstance(v, list))
        logger.info(f"✅ Analysis complete: {total_tasks} total TASKS found")

        return results

    def _analyze_person_for_task(self, person_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyze entire relationship with a person using Sonnet.

        Sonnet studies ALL interactions and decides: TASK or NO TASK?

        Args:
            person_data: Dict with contact_email, contact_name, threads[]

        Returns:
            Task dict if Sonnet decides there's a task, None otherwise
        """
        contact_email = person_data['contact_email']
        contact_name = person_data['contact_name']
        threads = person_data['threads']

        # Sort threads by date (oldest first for chronological story)
        threads_sorted = sorted(threads, key=lambda t: t.get('last_message_date', ''))

        # Build thread summaries for Sonnet
        thread_summaries = []
        for i, thread in enumerate(threads_sorted, 1):
            date = thread.get('last_message_date', 'unknown date')
            subject = thread.get('subject', '(no subject)')
            summary = thread.get('summary', '')
            expected_action = thread.get('expected_action', 'unknown')

            # Get last message body (first 500 chars) for better context
            last_body = thread.get('last_email', {}).get('body', '')[:500]

            thread_summaries.append(f"""
Thread {i} ({date}):
Subject: {subject}
Summary: {summary}
Expected action: {expected_action}
Last message preview: {last_body}
""")

        threads_text = "\n".join(thread_summaries)

        prompt = f"""You are an assistant helping Mario manage customer relationships.

CONTACT: {contact_name} <{contact_email}>

Mario has had {len(threads)} email conversations with this person in recent days.
You must analyze ALL communications and understand the evolution of the relationship.

CONVERSATIONS (in chronological order):
{threads_text}

=== PRELIMINARY ANALYSIS: AI-GENERATED EMAIL ===

FIRST, verify if this email was AI-generated:

SIGNALS OF AI-GENERATED COLD OUTREACH:
1. **Marketing buzzwords**: "unit economics", "pipeline", "LTV:CAC", "inputs and outputs", "hundreds of thousands"
2. **Name-dropping for social proof**: Lists client names without context
3. **Classic sales structure**: Problem → Solution → Social Proof → Call-to-Action
4. **Mail-merge personalization**: Only mentions company name once (from {{ company_name }} template variable)
5. **Offering "free tool/calculator"**: Classic lead magnet tactic
6. **Generic sender**: "The GTM Company", "Founder" titles without details
7. **Template errors**: Duplicate names, repeated phrases (AI generation artifacts)
8. **No prior relationship**: First-time contact offering unsolicited help

⚠️ CRITICAL: Just mentioning the company name (Mrcall, Mario, etc.) is NOT genuine personalization!
That's mail-merge automation. TRUE personalization requires:
- Reference to specific conversations or context
- Knowledge of Mario's actual problems or situation
- Authentic connection, not templated opener

CRITICAL RULE:
- Cold outreach offering "tools" or "calculators" = LEAD MAGNET = Sales pitch
- "Founder, [Generic Company]" + buzzwords = AI-GENERATED SPAM
- Name-dropping clients without context = Social proof template
- ANY cold email from unknown sender offering free resources = qualified spam

If the email matches 3+ signals above:
→ has_task = false, is_ai_generated = true (reason: "AI-generated cold outreach with mail-merge personalization")

=== THE TWO FUNDAMENTAL QUESTIONS ===

If the email is NOT AI-generated spam, answer:

a) Does this person expect something from Mario NOW?
b) Does Mario expect something from this person?

IMPORTANT:
- Study the ENTIRE history, not just the last message
- Try to understand if problems have been RESOLVED or are still OPEN
- If the last exchange indicates "everything is fine", probably NO TASK needed
- If there are unmet promises, unresolved issues, or pending requests → TASK

=== EXAMPLES ===

Example 1 - NO TASK (problem resolved):
Luisa Boni had problems with WhatsApp and assistant, but in the last exchange
says everything works now. → NO TASK

Example 2 - NO TASK (AI-generated email):
Irene Lorenzo from Sesamers sends perfectly formatted email with bullet points,
marketing buzzwords, offering "opportunities" at "Startup Village" (= selling booth).
→ NO TASK (100% AI-generated email from business developer)

Example 3 - TASK (personal request):
Giuseppe personally asks for product information with natural language
and specific references to previous conversation.
→ TASK (authentic request)

Respond ONLY with valid JSON in this format:

{{
  "has_task": true,
  "task_description": "Brief description of what Mario needs to do",
  "reason": "Explanation of why this task is needed",
  "is_ai_generated": false
}}

or:

{{
  "has_task": false,
  "reason": "Explanation of why NO task is needed",
  "is_ai_generated": true
}}

CRITICAL INSTRUCTIONS:
- YOUR RESPONSE MUST BE VALID JSON ONLY
- DO NOT USE MARKDOWN CODE BLOCKS
- THE RESPONSE MUST START WITH {{ AND END WITH }}
- NO TEXT BEFORE OR AFTER THE JSON

RETURN ONLY THE JSON, NOTHING ELSE."""

        # Call Sonnet
        if not self.anthropic_client:
            # Fallback: assume task needed if any thread requires action
            return {
                "type": "email_task",
                "contact_email": contact_email,
                "contact_name": contact_name,
                "task_description": f"Follow up with {contact_name}",
                "thread_count": len(threads),
                "threads": [t['thread_id'] for t in threads]
            }

        try:
            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            result_text = response.content[0].text.strip()

            # Parse JSON (handle markdown blocks)
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', result_text, re.DOTALL)
            if json_match:
                result_text = json_match.group(1)

            result = json.loads(result_text)

            # If no task needed, return None
            if not result.get('has_task', False):
                logger.debug(f"No task for {contact_name}: {result.get('reason', '')}")
                return None

            # Build task
            return {
                "type": "email_task",
                "contact_email": contact_email,
                "contact_name": contact_name,
                "task_description": result.get('task_description', f"Follow up with {contact_name}"),
                "reason": result.get('reason', ''),
                "thread_count": len(threads),
                "threads": [t['thread_id'] for t in threads],
                "last_interaction": threads_sorted[-1].get('last_message_date', ''),
                "priority_score": max(t.get('priority_score', 5) for t in threads)
            }

        except Exception as e:
            logger.error(f"Sonnet analysis failed for {contact_email}: {e}")
            # Fallback: create task
            return {
                "type": "email_task",
                "contact_email": contact_email,
                "contact_name": contact_name,
                "task_description": f"Follow up with {contact_name}",
                "thread_count": len(threads),
                "threads": [t['thread_id'] for t in threads],
                "error": str(e)
            }

    # Helper methods

    def _has_email_after(
        self,
        contact_email: str,
        after_date: datetime,
        window_hours: int,
        threads: Dict[str, Any]
    ) -> bool:
        """Check if there's an email with contact after a given date."""
        cutoff_date = after_date + timedelta(hours=window_hours)

        for thread in threads.values():
            # Check if contact is in thread
            # Handle both string emails and dict format (for compatibility)
            participants = []
            for p in thread.get('participants', []):
                if isinstance(p, str):
                    participants.append(p)
                else:
                    participants.append(p.get('email', ''))

            if contact_email not in participants:
                continue

            # Check if email is after meeting but within window
            try:
                last_msg_date = datetime.fromisoformat(
                    thread.get('last_message_date', '').replace('Z', '+00:00')
                ).replace(tzinfo=None)  # Strip timezone for naive comparison
                if after_date < last_msg_date < cutoff_date:
                    return True
            except:
                continue

        return False

    def _has_scheduled_meeting(
        self,
        contact_email: str,
        after_date: datetime,
        events: Dict[str, Any]
    ) -> bool:
        """Check if there's a scheduled meeting with contact after a date."""
        for event in events.values():
            # Check if contact is in attendees
            if contact_email not in event.get('attendees', []):
                continue

            # Check if meeting is after the date
            try:
                meeting_date = datetime.fromisoformat(
                    event['start'].replace('Z', '+00:00')
                )
                if meeting_date > after_date:
                    return True
            except:
                continue

        return False

    def _sonnet_requires_response(
        self,
        thread: Dict[str, Any],
        contact_email: str,
        contact_name: str
    ) -> bool:
        """Use Sonnet to determine if email genuinely requires response.

        Args:
            thread: Email thread data
            contact_email: Contact's email address
            contact_name: Contact's name

        Returns:
            True if email requires response, False otherwise
        """
        try:
            # Get email details
            subject = thread.get('subject', '')
            summary = thread.get('summary', '')
            last_email = thread.get('last_email', {})
            body = last_email.get('body', '')[:1000]  # First 1000 chars

            # Get user's learned preferences from memory
            memory_rules = ""
            if self.memory_bank:
                memories = self.memory_bank.get_relevant_memories(
                    channel='email',
                    min_confidence=0.5
                )
                if memories:
                    memory_rules = "\n\nUSER'S PERSONAL RULES (must be respected):\n"
                    for mem in memories:
                        wrong = mem.get('what_went_wrong', '')
                        correct = mem.get('correct_behavior', '')
                        memory_rules += f"- {wrong} → {correct}\n"

            prompt = f"""Analyze this email and determine if it requires a response or action from me.

From: {contact_name} <{contact_email}>
Subject: {subject}
Summary: {summary}

Body (first 1000 characters):
{body}
{memory_rules}

=== AI-GENERATED EMAIL DETECTION ===

BEFORE evaluating if response is needed, verify if the email is AI-generated:

SIGNALS OF AI-GENERATED COLD OUTREACH:
1. **Marketing buzzwords**: "unit economics", "pipeline", "LTV:CAC", "inputs and outputs", "hundreds of thousands"
2. **Name-dropping for social proof**: Lists client names without context
3. **Classic sales structure**: Problem → Solution → Social Proof → Call-to-Action
4. **Mail-merge personalization**: Only mentions company name once (template variable)
5. **Offering "free tool/calculator"**: Lead magnet tactic
6. **Generic sender**: "The GTM Company", "Founder" titles
7. **Template errors**: Duplicate names, repeated phrases (AI artifacts)
8. **No prior relationship**: First-time contact, unsolicited

⚠️ CRITICAL: Just mentioning the company name is NOT genuine personalization!
That's mail-merge. TRUE personalization requires specific conversation references or context.

CRITICAL RULE:
- Cold outreach offering "tools" or "calculators" = LEAD MAGNET = Sales
- "Founder, [Generic Company]" + buzzwords = AI-GENERATED SPAM
- Name-dropping without context = Social proof template
- Unknown sender offering free resources = qualified spam

If email matches 3+ signals: requires_response = FALSE

CRITICAL INSTRUCTIONS:
- YOUR RESPONSE MUST BE VALID JSON ONLY
- DO NOT USE MARKDOWN CODE BLOCKS
- DO NOT ADD ANY TEXT BEFORE OR AFTER THE JSON
- THE RESPONSE MUST START WITH {{ AND END WITH }}

Respond with this exact format:
{{
  "requires_response": true,
  "reason": "brief explanation",
  "is_ai_generated": false
}}

Criteria for requires_response=true:
- Personal email asking a specific question
- Request for information or documents
- Authentic collaboration or meeting proposal
- Follow-up to previous conversation requiring my action

Criteria for requires_response=false:
- Newsletter, automatic updates
- Marketing, promotions
- Service notifications (billing, renewal, etc)
- Informational emails not requiring action
- Thanks without follow-up needed
- **AI-GENERATED EMAIL FROM BUSINESS DEVELOPER** (qualified spam)

IMPORTANT: User's personal rules have ABSOLUTE PRIORITY over all other criteria.

REMEMBER: RETURN ONLY THE JSON OBJECT, NOTHING ELSE. NO MARKDOWN, NO EXPLANATIONS."""

            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            result_text = response.content[0].text.strip()

            # Parse JSON response (handle markdown code blocks)
            import json as json_module
            import re

            # Try to extract JSON from markdown code block if present
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', result_text, re.DOTALL)
            if json_match:
                result_text = json_match.group(1)

            result = json_module.loads(result_text)

            requires = result.get('requires_response', False)
            reason = result.get('reason', '')

            if not requires:
                logger.info(f"Sonnet filtered: {contact_name} - {reason}")

            return requires

        except Exception as e:
            logger.error(f"Sonnet analysis failed for {contact_email}: {e}")
            # On error, be conservative and assume it requires response
            return True

    def _user_accepted_meeting(self, event: Dict[str, Any]) -> bool:
        """Check if the user accepted the meeting.

        Args:
            event: Calendar event with attendees_with_status

        Returns:
            True if user accepted (responseStatus='accepted') or is organizer, False otherwise
        """
        # Get user's email from config (we need to know who "we" are)
        # For now, hardcode common patterns - TODO: add to config
        user_emails = [
            'mario.alemi@mrcall.ai',
            'support@mrcall.ai',
            'angelo.leto@mrcall.ai'
        ]

        # Check if user is the organizer (implicit acceptance)
        organizer = event.get('organizer', '')
        if organizer in user_emails:
            return True

        # Get attendees with status info
        attendees_with_status = event.get('attendees_with_status', [])

        # Find the user in the attendees
        for attendee in attendees_with_status:
            attendee_email = attendee.get('email', '')
            if attendee_email in user_emails:
                # User found - check if they accepted
                response = attendee.get('responseStatus', 'needsAction')
                # Only count as accepted if explicitly accepted
                return response == 'accepted'

        # If user not found, assume not their meeting
        return False

    def _is_bot_email(self, email: str) -> bool:
        """Check if email is from a bot/automated system.

        Args:
            email: Email address to check

        Returns:
            True if email appears to be automated/bot
        """
        email_lower = email.lower()

        # Get the local part (before @)
        local_part = email_lower.split('@')[0] if '@' in email_lower else email_lower

        # Bot patterns that must appear in the local part
        bot_patterns = [
            'noreply',
            'no-reply',
            'no_reply',
            'donotreply',
            'do-not-reply',
            'notifications',
            'notification',
            'alerts',
            'newsletter',
            'automated',
            'auto-',
            'bounce',
            'mailer-daemon',
            'postmaster',
            'ads-',
            'advertising',
        ]

        # Check if local part contains any bot pattern
        for pattern in bot_patterns:
            if pattern in local_part:
                return True

        # Bot patterns that must be at the start of email (like info@, support@)
        bot_prefixes = [
            'news@',
            'info@',
            'support@',
            'hello@',
            'hi@',
            'team@',
            'contact@',
            'feedback@',
            'updates@',
            'marketing@',
            'promo@',
            'promotions@',
            'account@',
            'accounts@',
            'security@',
            'verify@',
            'verification@',
            'billing@',
            'invoices@',
            'invoice@'
        ]

        # Check if email starts with bot prefix
        for prefix in bot_prefixes:
            if email_lower.startswith(prefix):
                return True

        # Check for common automated domains (subdomain patterns)
        # Note: we check for these in the domain part only, after the @
        if '@' in email_lower:
            domain_part = email_lower.split('@')[1]
            automated_subdomain_patterns = [
                'notifications.',
                'alerts.',
                'newsletter.',
                'email.',
                'bounce.',
                'noreply.'
            ]

            for pattern in automated_subdomain_patterns:
                if domain_part.startswith(pattern):
                    return True

        return False

    def _parse_email_date(self, date_str: str) -> Optional[datetime]:
        """Parse email date that can be in ISO or RFC2822 format.

        Args:
            date_str: Date string in ISO or RFC2822 format

        Returns:
            Naive datetime object, or None if parsing fails
        """
        if not date_str:
            return None

        try:
            # Try ISO format first (e.g., "2025-11-20T10:30:59+01:00")
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.replace(tzinfo=None)
        except:
            pass

        try:
            # Try RFC2822 format (e.g., "Thu, 20 Nov 2025 10:30:59 +0100")
            dt = parsedate_to_datetime(date_str)
            return dt.replace(tzinfo=None)
        except:
            pass

        return None

    def _extract_email_from_field(self, from_field: str) -> str:
        """Extract email from 'Name <email@domain.com>' format.

        Args:
            from_field: From field like "Giuseppe Alcini <giusalcini@gmail.com>"

        Returns:
            Just the email address
        """
        import re
        # Match email in angle brackets: <email@domain.com>
        match = re.search(r'<([^>]+)>', from_field)
        if match:
            return match.group(1).strip().lower()

        # If no angle brackets, assume the whole thing is an email
        return from_field.strip().lower()

    def _extract_name_from_from_field(self, from_field: str) -> str:
        """Extract name from 'Name <email@domain.com>' format.

        Args:
            from_field: From field like "Giuseppe Alcini <giusalcini@gmail.com>"

        Returns:
            Just the name part, or email if no name
        """
        import re
        # Try to extract name before angle brackets
        match = re.match(r'([^<]+)<', from_field)
        if match:
            name = match.group(1).strip()
            # Remove quotes if present
            name = name.strip('"').strip("'")
            return name if name else self._extract_name_from_email(self._extract_email_from_field(from_field))

        # No angle brackets, extract from email
        email = from_field.strip()
        return self._extract_name_from_email(email)

    def _extract_name_from_email(self, email: str) -> str:
        """Extract name from email address."""
        # Simple heuristic: use part before @
        if '@' in email:
            local_part = email.split('@')[0]
            # Replace dots and underscores with spaces
            name = local_part.replace('.', ' ').replace('_', ' ')
            # Title case
            return name.title()
        return email
