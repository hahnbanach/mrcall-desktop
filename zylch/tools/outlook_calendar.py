"""Outlook Calendar API integration using Microsoft Graph API."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)


class OutlookCalendarClient:
    """Client for Outlook Calendar operations using Microsoft Graph API.

    Uses the graph_token from OutlookClient for authentication.
    """

    def __init__(
        self,
        graph_token: Optional[str] = None,
        calendar_id: str = "primary",
    ):
        """Initialize Outlook Calendar client.

        Args:
            graph_token: Microsoft Graph API access token
            calendar_id: Calendar ID to use (default: 'primary' for main calendar)
        """
        self.graph_token = graph_token
        self.calendar_id = calendar_id
        self.base_url = "https://graph.microsoft.com/v1.0"

        logger.info(f"Initialized Outlook Calendar client for calendar: {calendar_id}")

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers for Microsoft Graph API."""
        if not self.graph_token:
            raise ValueError("No graph_token provided. OutlookCalendarClient requires authentication.")

        return {
            "Authorization": f"Bearer {self.graph_token}",
            "Content-Type": "application/json",
        }

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
        # Default time range: now to 7 days
        if time_min is None:
            time_min = datetime.utcnow()
        if time_max is None:
            time_max = time_min + timedelta(days=7)

        # Format for Graph API
        time_min_str = time_min.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max_str = time_max.strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.debug(f"Listing events from {time_min_str} to {time_max_str}")

        try:
            # Build query parameters
            params = {
                "$top": max_results,
                "$orderby": "start/dateTime",
                "$filter": f"start/dateTime ge '{time_min_str}' and end/dateTime le '{time_max_str}'",
            }

            url = f"{self.base_url}/me/calendar/events"
            response = requests.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()

            data = response.json()
            events = data.get("value", [])

            logger.info(f"Found {len(events)} events")

            return [self._parse_event(event) for event in events]

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to list events: {e}")
            raise

    def _parse_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Outlook event into simplified format.

        Args:
            event: Raw Outlook event object

        Returns:
            Parsed event with key fields matching GoogleCalendarClient format
        """
        # Extract start/end times
        start = event.get("start", {})
        end = event.get("end", {})

        start_time = start.get("dateTime")
        end_time = end.get("dateTime")

        # Extract Teams meeting link if present
        meet_link = None
        online_meeting = event.get("onlineMeeting")
        if online_meeting:
            meet_link = online_meeting.get("joinUrl")

        # Parse attendees
        attendees = []
        for attendee in event.get("attendees", []):
            email_address = attendee.get("emailAddress", {})
            attendees.append({
                "email": email_address.get("address"),
                "name": email_address.get("name", ""),
                "response_status": attendee.get("status", {}).get("response", "none"),
            })

        # Parse organizer
        organizer_data = event.get("organizer", {})
        organizer_email = organizer_data.get("emailAddress", {})
        organizer = {
            "email": organizer_email.get("address"),
            "name": organizer_email.get("name", ""),
        }

        return {
            "id": event.get("id"),
            "summary": event.get("subject", "(No title)"),
            "description": event.get("bodyPreview", ""),  # Use preview, full body is in 'body.content'
            "start": start_time,
            "end": end_time,
            "location": event.get("location", {}).get("displayName", ""),
            "meet_link": meet_link,  # Teams meeting link
            "attendees": attendees,
            "organizer": organizer,
            "html_link": event.get("webLink", ""),
            "status": "confirmed" if not event.get("isCancelled") else "cancelled",
        }

    def get_event(
        self,
        event_id: str,
        calendar_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get single event by ID.

        Args:
            event_id: Calendar event ID
            calendar_id: Calendar ID (unused for Outlook, kept for interface compatibility)

        Returns:
            Parsed event
        """
        try:
            url = f"{self.base_url}/me/calendar/events/{event_id}"
            response = requests.get(url, headers=self._get_headers())
            response.raise_for_status()

            event = response.json()
            return self._parse_event(event)

        except requests.exceptions.RequestException as e:
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
            calendar_id: Calendar ID (unused for Outlook, kept for interface compatibility)
            add_meet_link: If True, creates a Teams meeting link

        Returns:
            Created event with Teams link if requested
        """
        try:
            # Strip timezone info from datetime if present
            start_time_naive = start_time.replace(tzinfo=None) if start_time.tzinfo else start_time
            end_time_naive = end_time.replace(tzinfo=None) if end_time.tzinfo else end_time

            # Build event body
            event_body = {
                "subject": summary,
                "body": {
                    "contentType": "HTML",
                    "content": description
                },
                "start": {
                    "dateTime": start_time_naive.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timeZone": "Europe/Rome"  # Use local timezone
                },
                "end": {
                    "dateTime": end_time_naive.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timeZone": "Europe/Rome"
                },
                "location": {
                    "displayName": location
                }
            }

            # Add attendees if provided
            if attendees:
                event_body["attendees"] = [
                    {
                        "emailAddress": {"address": email},
                        "type": "required"
                    }
                    for email in attendees
                ]

            # Add Teams meeting if requested
            if add_meet_link:
                event_body["isOnlineMeeting"] = True
                event_body["onlineMeetingProvider"] = "teamsForBusiness"

            url = f"{self.base_url}/me/calendar/events"
            response = requests.post(url, headers=self._get_headers(), json=event_body)
            response.raise_for_status()

            event = response.json()

            logger.info(f"Created event: {summary} at {start_time}" + (" with Teams link" if add_meet_link else ""))
            return self._parse_event(event)

        except requests.exceptions.RequestException as e:
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
            calendar_id: Calendar ID (unused for Outlook, kept for interface compatibility)

        Returns:
            Updated event
        """
        try:
            # Build update body with only provided fields
            update_body = {}

            if summary is not None:
                update_body["subject"] = summary
            if description is not None:
                update_body["body"] = {
                    "contentType": "HTML",
                    "content": description
                }
            if location is not None:
                update_body["location"] = {"displayName": location}
            if start_time is not None:
                update_body["start"] = {
                    "dateTime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timeZone": "UTC"
                }
            if end_time is not None:
                update_body["end"] = {
                    "dateTime": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timeZone": "UTC"
                }

            url = f"{self.base_url}/me/calendar/events/{event_id}"
            response = requests.patch(url, headers=self._get_headers(), json=update_body)
            response.raise_for_status()

            event = response.json()

            logger.info(f"Updated event: {event_id}")
            return self._parse_event(event)

        except requests.exceptions.RequestException as e:
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
            calendar_id: Calendar ID (unused for Outlook, kept for interface compatibility)
        """
        try:
            url = f"{self.base_url}/me/calendar/events/{event_id}"
            response = requests.delete(url, headers=self._get_headers())
            response.raise_for_status()

            logger.info(f"Deleted event: {event_id}")

        except requests.exceptions.RequestException as e:
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
            calendar_id: Calendar ID (unused for Outlook, kept for interface compatibility)

        Returns:
            List of matching events
        """
        # Default time range: -30 to +30 days
        if time_min is None:
            time_min = datetime.utcnow() - timedelta(days=30)
        if time_max is None:
            time_max = datetime.utcnow() + timedelta(days=30)

        # Format for Graph API
        time_min_str = time_min.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max_str = time_max.strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.debug(f"Searching events: {query}")

        try:
            # Build query parameters with search
            params = {
                "$top": max_results,
                "$orderby": "start/dateTime",
                "$filter": f"start/dateTime ge '{time_min_str}' and end/dateTime le '{time_max_str}'",
                "$search": f'"{query}"',  # Search in subject, body, etc.
            }

            url = f"{self.base_url}/me/calendar/events"
            response = requests.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()

            data = response.json()
            events = data.get("value", [])

            logger.info(f"Found {len(events)} events matching '{query}' (from {time_min.strftime('%Y-%m-%d')} to {time_max.strftime('%Y-%m-%d')})")

            return [self._parse_event(event) for event in events]

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to search events: {e}")
            raise
