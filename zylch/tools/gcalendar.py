"""Google Calendar API integration for calendar operations."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .base import Tool, ToolResult, ToolStatus
from zylch.api import token_storage

logger = logging.getLogger(__name__)

# Google API scopes (Gmail + Calendar combined)
SCOPES = [
    # Gmail scopes
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    # Calendar scopes
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]


class GoogleCalendarClient:
    """Client for Google Calendar API operations.

    Handles OAuth authentication and calendar operations.
    All tokens are stored in Supabase (no filesystem storage).
    """

    def __init__(
        self,
        calendar_id: str = "primary",
        account: Optional[str] = None,
        owner_id: Optional[str] = None,
    ):
        """Initialize Google Calendar client.

        Args:
            calendar_id: Calendar ID to use (default: 'primary')
            account: Account email for token isolation (optional)
            owner_id: Firebase UID (required for Supabase token storage)
        """
        if not owner_id:
            raise ValueError("owner_id is required - GoogleCalendarClient requires Supabase token storage")

        self.calendar_id = calendar_id
        self.account = account
        self.owner_id = owner_id
        self.service = None

        logger.info(f"Initialized Google Calendar client for calendar: {calendar_id}, owner_id: {owner_id}")

    def authenticate(self) -> None:
        """Authenticate with Google Calendar API using OAuth 2.0.

        Loads credentials from Supabase. Never starts OAuth flow - that's the CLI's job.
        """
        # Load from Supabase via token_storage
        creds = token_storage.get_google_credentials(self.owner_id)
        if creds:
            logger.info(f"Loaded credentials from Supabase for owner {self.owner_id}")

        # If no valid credentials, request new ones
        # Use try-except to handle timezone comparison errors in Google OAuth library
        try:
            creds_valid = creds and creds.valid
            creds_expired = creds.expired if creds else False
        except TypeError:
            # Timezone-aware vs naive datetime comparison error
            creds_valid = False
            creds_expired = True

        if not creds_valid:
            if creds and creds_expired and creds.refresh_token:
                logger.info("Refreshing expired credentials")
                creds.refresh(Request())
                # Save refreshed credentials
                self._save_credentials(creds)
            else:
                raise ValueError(
                    f"Google credentials not found in Supabase for owner {self.owner_id}. "
                    "Please connect your Google account using the CLI or dashboard: /connect google"
                )

        # Build Calendar service
        self.service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        logger.info("Google Calendar API authenticated successfully")

    def _save_credentials(self, creds: Credentials) -> None:
        """Save credentials to Supabase.

        Args:
            creds: Google OAuth credentials
        """
        token_storage.save_google_credentials(
            owner_id=self.owner_id,
            credentials=creds,
            email=self.account or ""
        )
        logger.info(f"Saved credentials to Supabase for owner {self.owner_id}")

    def list_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 10,
        calendar_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List calendar events.

        Args:
            time_min: Start time (default: now)
            time_max: End time (default: 7 days from now)
            max_results: Maximum results to return
            calendar_id: Calendar ID (default: self.calendar_id)

        Returns:
            List of event objects
        """
        if not self.service:
            self.authenticate()

        # Default time range: now to 7 days
        if time_min is None:
            time_min = datetime.utcnow()
        if time_max is None:
            time_max = time_min + timedelta(days=7)

        # Convert to RFC3339 format
        time_min_str = time_min.isoformat() + 'Z'
        time_max_str = time_max.isoformat() + 'Z'

        calendar_id = calendar_id or self.calendar_id

        logger.debug(f"Listing events from {time_min_str} to {time_max_str}")

        try:
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=time_min_str,
                timeMax=time_max_str,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            logger.info(f"Found {len(events)} events")

            return [self._parse_event(event) for event in events]

        except Exception as e:
            logger.error(f"Failed to list events: {e}")
            raise

    def _parse_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Calendar event into simplified format.

        Args:
            event: Raw Calendar event object

        Returns:
            Parsed event with key fields
        """
        # Handle all-day events vs timed events
        start = event.get('start', {})
        end = event.get('end', {})

        start_time = start.get('dateTime', start.get('date'))
        end_time = end.get('dateTime', end.get('date'))

        # Extract Meet link if present
        meet_link = None
        conference_data = event.get('conferenceData', {})
        if conference_data:
            entry_points = conference_data.get('entryPoints', [])
            for entry in entry_points:
                if entry.get('entryPointType') == 'video':
                    meet_link = entry.get('uri')
                    break

        return {
            'id': event.get('id'),
            'summary': event.get('summary', '(No title)'),
            'description': event.get('description', ''),
            'start': start_time,
            'end': end_time,
            'location': event.get('location', ''),
            'meet_link': meet_link,  # Google Meet video conference link
            'attendees': [
                {
                    'email': a.get('email'),
                    'name': a.get('displayName', ''),
                    'response_status': a.get('responseStatus', 'needsAction')
                }
                for a in event.get('attendees', [])
            ],
            'organizer': event.get('organizer', {}),
            'html_link': event.get('htmlLink', ''),
            'status': event.get('status', ''),
        }

    def get_event(
        self,
        event_id: str,
        calendar_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get single event by ID.

        Args:
            event_id: Calendar event ID
            calendar_id: Calendar ID (default: self.calendar_id)

        Returns:
            Parsed event
        """
        if not self.service:
            self.authenticate()

        calendar_id = calendar_id or self.calendar_id

        try:
            event = self.service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()

            return self._parse_event(event)

        except Exception as e:
            logger.error(f"Failed to get event {event_id}: {e}")
            raise

    def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        calendar_id: Optional[str] = None,
        add_meet_link: bool = False,
    ) -> Dict[str, Any]:
        """Create calendar event.

        Args:
            summary: Event title
            start_time: Start time
            end_time: End time
            description: Event description
            location: Event location
            attendees: List of attendee emails
            calendar_id: Calendar ID (default: self.calendar_id)
            add_meet_link: If True, adds a Google Meet video conference link

        Returns:
            Created event with Meet link if requested
        """
        if not self.service:
            self.authenticate()

        calendar_id = calendar_id or self.calendar_id

        # Build event body
        # Note: Use local timezone (Europe/Rome for Italy) instead of UTC
        # to ensure events are created at the correct local time
        # Strip timezone info from datetime if present, as we specify it separately
        start_time_naive = start_time.replace(tzinfo=None) if start_time.tzinfo else start_time
        end_time_naive = end_time.replace(tzinfo=None) if end_time.tzinfo else end_time

        event_body = {
            'summary': summary,
            'description': description,
            'location': location,
            'start': {
                'dateTime': start_time_naive.isoformat(),
                'timeZone': 'Europe/Rome',  # Use local timezone
            },
            'end': {
                'dateTime': end_time_naive.isoformat(),
                'timeZone': 'Europe/Rome',  # Use local timezone
            },
        }

        # Add attendees if provided
        if attendees:
            event_body['attendees'] = [{'email': email} for email in attendees]

        # Add Google Meet conference if requested
        if add_meet_link:
            event_body['conferenceData'] = {
                'createRequest': {
                    'requestId': f"meet-{int(start_time.timestamp())}",
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            }

        try:
            # Must use conferenceDataVersion=1 to create Meet link
            event = self.service.events().insert(
                calendarId=calendar_id,
                body=event_body,
                conferenceDataVersion=1 if add_meet_link else 0,
                sendUpdates='all'  # Send invites to attendees
            ).execute()

            logger.info(f"Created event: {summary} at {start_time}" + (" with Meet link" if add_meet_link else ""))
            return self._parse_event(event)

        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            raise

    def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update calendar event.

        Args:
            event_id: Event ID to update
            summary: New title (optional)
            start_time: New start time (optional)
            end_time: New end time (optional)
            description: New description (optional)
            location: New location (optional)
            calendar_id: Calendar ID (default: self.calendar_id)

        Returns:
            Updated event
        """
        if not self.service:
            self.authenticate()

        calendar_id = calendar_id or self.calendar_id

        # Get existing event
        try:
            event = self.service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()

            # Update fields if provided
            if summary is not None:
                event['summary'] = summary
            if description is not None:
                event['description'] = description
            if location is not None:
                event['location'] = location
            if start_time is not None:
                event['start'] = {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'UTC',
                }
            if end_time is not None:
                event['end'] = {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'UTC',
                }

            # Update event
            updated_event = self.service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event
            ).execute()

            logger.info(f"Updated event: {event_id}")
            return self._parse_event(updated_event)

        except Exception as e:
            logger.error(f"Failed to update event {event_id}: {e}")
            raise

    def delete_event(
        self,
        event_id: str,
        calendar_id: Optional[str] = None
    ) -> None:
        """Delete calendar event.

        Args:
            event_id: Event ID to delete
            calendar_id: Calendar ID (default: self.calendar_id)
        """
        if not self.service:
            self.authenticate()

        calendar_id = calendar_id or self.calendar_id

        try:
            self.service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()

            logger.info(f"Deleted event: {event_id}")

        except Exception as e:
            logger.error(f"Failed to delete event {event_id}: {e}")
            raise

    def search_events(
        self,
        query: str,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 50,
        calendar_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search calendar events.

        Args:
            query: Search query
            time_min: Start time (default: 30 days ago)
            time_max: End time (default: 30 days from now)
            max_results: Maximum results
            calendar_id: Calendar ID (default: self.calendar_id)

        Returns:
            List of matching events
        """
        if not self.service:
            self.authenticate()

        # Default time range: -30 to +30 days
        if time_min is None:
            time_min = datetime.utcnow() - timedelta(days=30)
        if time_max is None:
            time_max = datetime.utcnow() + timedelta(days=30)

        # Convert to RFC3339 format
        time_min_str = time_min.isoformat() + 'Z'
        time_max_str = time_max.isoformat() + 'Z'

        calendar_id = calendar_id or self.calendar_id

        logger.debug(f"Searching events: {query}")

        try:
            events_result = self.service.events().list(
                calendarId=calendar_id,
                q=query,
                timeMin=time_min_str,
                timeMax=time_max_str,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            logger.info(f"Found {len(events)} events matching '{query}' (from {time_min.strftime('%Y-%m-%d')} to {time_max.strftime('%Y-%m-%d')})")

            return [self._parse_event(event) for event in events]

        except Exception as e:
            logger.error(f"Failed to search events: {e}")
            raise


# ========================
# Tool Wrappers for Agent
# ========================


class ListCalendarEventsTool(Tool):
    """Tool to list upcoming calendar events."""

    def __init__(self, calendar_client: GoogleCalendarClient):
        super().__init__(
            name="list_calendar_events",
            description="List upcoming calendar events"
        )
        self.calendar = calendar_client

    async def execute(
        self,
        days_ahead: int = 7,
        max_results: int = 10
    ) -> ToolResult:
        """List upcoming calendar events.

        Args:
            days_ahead: Number of days ahead to search (default: 7)
            max_results: Maximum number of events to return (default: 10)

        Returns:
            ToolResult with list of events
        """
        try:
            time_min = datetime.utcnow()
            time_max = time_min + timedelta(days=days_ahead)

            events = self.calendar.list_events(
                time_min=time_min,
                time_max=time_max,
                max_results=max_results
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=events,
                message=f"Found {len(events)} events in next {days_ahead} days"
            )

        except Exception as e:
            logger.error(f"Failed to list calendar events: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": self.description + ". Use to see upcoming appointments and commitments.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "Number of days ahead to search (default: 7)",
                        "default": 7
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of events to return (default: 10)",
                        "default": 10
                    }
                },
                "required": []
            }
        }


class CreateCalendarEventTool(Tool):
    """Tool to create a calendar event."""

    def __init__(self, calendar_client: GoogleCalendarClient):
        super().__init__(
            name="create_calendar_event",
            description="Create a new calendar event"
        )
        self.calendar = calendar_client

    async def execute(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        add_meet_link: bool = False
    ) -> ToolResult:
        """Create a calendar event.

        Args:
            summary: Event title
            start_time: Start time (ISO format: YYYY-MM-DDTHH:MM:SS)
            end_time: End time (ISO format: YYYY-MM-DDTHH:MM:SS)
            description: Event description
            location: Event location
            attendees: List of attendee emails
            add_meet_link: If True, adds a Google Meet video conference link

        Returns:
            ToolResult with created event (including Meet link if requested)
        """
        try:
            # Parse ISO format times
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

            event = self.calendar.create_event(
                summary=summary,
                start_time=start_dt,
                end_time=end_dt,
                description=description,
                location=location,
                attendees=attendees,
                add_meet_link=add_meet_link
            )

            meet_info = f" with Meet link: {event.get('meet_link')}" if event.get('meet_link') else ""
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=event,
                message=f"Created event: {summary} at {start_time}{meet_info}"
            )

        except Exception as e:
            logger.error(f"Failed to create calendar event: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": self.description + ". Use to schedule meetings, reminders, and follow-ups. Can add Google Meet video conference links.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Event title (e.g., 'Call with Mario')"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time in ISO format (YYYY-MM-DDTHH:MM:SS)"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End time in ISO format (YYYY-MM-DDTHH:MM:SS)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description/notes",
                        "default": ""
                    },
                    "location": {
                        "type": "string",
                        "description": "Event location (physical address or video link)",
                        "default": ""
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of attendee email addresses",
                        "default": []
                    },
                    "add_meet_link": {
                        "type": "boolean",
                        "description": "If true, automatically creates a Google Meet video conference link",
                        "default": False
                    }
                },
                "required": ["summary", "start_time", "end_time"]
            }
        }


class SearchCalendarEventsTool(Tool):
    """Tool to search calendar events by query."""

    def __init__(self, calendar_client: GoogleCalendarClient):
        super().__init__(
            name="search_calendar_events",
            description="Search calendar events by keyword"
        )
        self.calendar = calendar_client

    async def execute(
        self,
        query: str,
        max_results: int = 20
    ) -> ToolResult:
        """Search calendar events.

        Args:
            query: Search query (searches in title, description, location)
            max_results: Maximum number of results (default: 20)

        Returns:
            ToolResult with matching events
        """
        try:
            # Default search range: -30 to +30 days
            time_min = datetime.utcnow() - timedelta(days=30)
            time_max = datetime.utcnow() + timedelta(days=30)

            events = self.calendar.search_events(
                query=query,
                max_results=max_results,
                time_min=time_min,
                time_max=time_max
            )

            date_from = time_min.strftime("%Y-%m-%d")
            date_to = time_max.strftime("%Y-%m-%d")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=events,
                message=f"Found {len(events)} events matching '{query}' (from {date_from} to {date_to})"
            )

        except Exception as e:
            logger.error(f"Failed to search calendar events: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": self.description + ". Use to find past or future events by name, person, or topic.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'Mario', 'standup', 'client meeting')"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 20)",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        }


class UpdateCalendarEventTool(Tool):
    """Tool to update an existing calendar event."""

    def __init__(self, calendar_client: GoogleCalendarClient):
        super().__init__(
            name="update_calendar_event",
            description="Update an existing calendar event"
        )
        self.calendar = calendar_client

    async def execute(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None
    ) -> ToolResult:
        """Update calendar event.

        Args:
            event_id: Event ID to update
            summary: New event title (optional)
            start_time: New start time in ISO format (optional)
            end_time: New end time in ISO format (optional)
            description: New description (optional)
            location: New location (optional)

        Returns:
            ToolResult with updated event
        """
        try:
            # Parse times if provided
            start_dt = None
            end_dt = None
            if start_time:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            if end_time:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

            event = self.calendar.update_event(
                event_id=event_id,
                summary=summary,
                start_time=start_dt,
                end_time=end_dt,
                description=description,
                location=location
            )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=event,
                message=f"Updated event: {event_id}"
            )

        except Exception as e:
            logger.error(f"Failed to update calendar event: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get Anthropic function schema."""
        return {
            "name": self.name,
            "description": self.description + ". Use to reschedule or modify event details.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Calendar event ID to update"
                    },
                    "summary": {
                        "type": "string",
                        "description": "New event title"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "New start time in ISO format (YYYY-MM-DDTHH:MM:SS)"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "New end time in ISO format (YYYY-MM-DDTHH:MM:SS)"
                    },
                    "description": {
                        "type": "string",
                        "description": "New event description"
                    },
                    "location": {
                        "type": "string",
                        "description": "New event location"
                    }
                },
                "required": ["event_id"]
            }
        }
