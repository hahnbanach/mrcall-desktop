"""Calendar synchronization and intelligent caching system."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic

logger = logging.getLogger(__name__)


class CalendarSyncManager:
    """Manages calendar event synchronization and intelligent caching.

    Fetches events, analyzes patterns, and caches with actionable metadata
    for relationship intelligence.
    """

    def __init__(
        self,
        calendar_client,
        cache_dir: str = "cache/calendar",
        anthropic_api_key: Optional[str] = None,
        days_back: int = 30,
        days_forward: int = 30,
        my_emails: Optional[List[str]] = None,
    ):
        """Initialize calendar sync manager.

        Args:
            calendar_client: GoogleCalendarClient instance
            cache_dir: Directory to store calendar cache
            anthropic_api_key: API key for event analysis
            days_back: Days in past to sync (default: 30)
            days_forward: Days in future to sync (default: 30)
            my_emails: List of my email addresses (for identifying external attendees)
        """
        self.calendar = calendar_client
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key) if anthropic_api_key else None
        self.days_back = days_back
        self.days_forward = days_forward
        self.my_emails = my_emails or []

        logger.info(
            f"Initialized CalendarSyncManager (cache: {cache_dir}, "
            f"window: -{days_back}/+{days_forward} days, my_emails: {len(self.my_emails)})"
        )

    def _get_cache_path(self) -> Path:
        """Get path to calendar cache file."""
        return self.cache_dir / "events.json"

    def _load_cache(self) -> Dict[str, Any]:
        """Load existing calendar cache."""
        cache_path = self._get_cache_path()
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                return json.load(f)
        return {
            "last_sync": None,
            "sync_window": {
                "days_back": self.days_back,
                "days_forward": self.days_forward
            },
            "events": {}
        }

    def _save_cache(self, cache: Dict[str, Any]) -> None:
        """Save calendar cache to disk."""
        cache_path = self._get_cache_path()
        with open(cache_path, 'w') as f:
            json.dump(cache, f, indent=2, default=str)
        logger.info(f"Saved {len(cache['events'])} events to cache")

    def sync_events(self, force_full: bool = False) -> Dict[str, Any]:
        """Sync calendar events and update cache.

        Fetches events from past (30 days) and future (30 days) to understand
        meeting patterns and identify relationship gaps.

        Args:
            force_full: Force full sync (ignore last_sync)

        Returns:
            Sync results with stats
        """
        logger.info("📅 Starting calendar event sync...")

        # Load existing cache
        cache = self._load_cache()

        # Determine sync window
        now = datetime.now(timezone.utc)
        time_min = now - timedelta(days=self.days_back)
        time_max = now + timedelta(days=self.days_forward)

        if force_full or not cache.get('last_sync'):
            logger.info(
                f"📦 Full sync: fetching events from "
                f"{time_min.strftime('%Y-%m-%d')} to {time_max.strftime('%Y-%m-%d')}"
            )
        else:
            logger.info(f"📥 Incremental sync since {cache['last_sync']}")

        # Fetch events from Google Calendar
        try:
            events = self.calendar.list_events(
                time_min=time_min,
                time_max=time_max,
                max_results=1000  # Get all events in window
            )
            logger.info(f"📨 Fetched {len(events)} events from calendar")
        except Exception as e:
            logger.error(f"Failed to fetch calendar events: {e}")
            return {
                "success": False,
                "error": str(e),
                "events_fetched": 0
            }

        # Process and cache events
        new_events = 0
        updated_events = 0

        for event in events:
            event_id = event['id']

            # Check if event exists in cache
            if event_id in cache['events']:
                # Update existing event
                cached_event = cache['events'][event_id]
                if self._event_changed(cached_event, event):
                    cache['events'][event_id] = self._process_event(event)
                    updated_events += 1
            else:
                # New event
                cache['events'][event_id] = self._process_event(event)
                new_events += 1

        # Update sync metadata
        cache['last_sync'] = datetime.now(timezone.utc).isoformat()
        cache['sync_window'] = {
            "days_back": self.days_back,
            "days_forward": self.days_forward,
            "time_min": time_min.isoformat(),
            "time_max": time_max.isoformat()
        }

        # Save cache
        self._save_cache(cache)

        results = {
            "success": True,
            "total_events": len(cache['events']),
            "new_events": new_events,
            "updated_events": updated_events,
            "last_sync": cache['last_sync']
        }

        logger.info(
            f"✅ Sync complete: {new_events} new, {updated_events} updated, "
            f"{len(cache['events'])} total"
        )

        return results

    def _process_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process and enrich a calendar event.

        Args:
            event: Raw event from Google Calendar

        Returns:
            Processed event with metadata
        """
        # Extract attendee emails and response status (for relationship tracking)
        attendee_emails = []
        attendees_with_status = []
        external_attendees = []

        for attendee in event.get('attendees', []):
            email = attendee.get('email', '')
            if email:
                attendee_emails.append(email)
                # Store full attendee info with response status
                attendees_with_status.append({
                    'email': email,
                    'responseStatus': attendee.get('responseStatus', 'needsAction'),
                    'optional': attendee.get('optional', False),
                    'self': attendee.get('self', False)
                })

                # Check if this attendee is external (not in my_emails list)
                is_internal = False
                for my_email in self.my_emails:
                    # Support wildcards like *@domain.com
                    if my_email.startswith('*@'):
                        domain = my_email[1:]  # Remove * to get @domain.com
                        if email.endswith(domain):
                            is_internal = True
                            break
                    elif my_email == email:
                        is_internal = True
                        break

                # If not internal, it's external
                if not is_internal:
                    external_attendees.append(email)

        # Parse start/end times
        start_str = event.get('start', '')
        end_str = event.get('end', '')

        # Determine if past or future
        now = datetime.now(timezone.utc)
        is_past = None
        try:
            # Handle both dict format and string format
            if isinstance(start_str, dict):
                # Google Calendar can return {'dateTime': '...', 'timeZone': '...'}
                start_str = start_str.get('dateTime', '')

            if start_str:
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                # Make naive for comparison (remove tzinfo)
                start_dt_naive = start_dt.replace(tzinfo=None) if start_dt.tzinfo else start_dt
                now_naive = now.replace(tzinfo=None)
                is_past = start_dt_naive < now_naive
        except Exception as e:
            logger.debug(f"Failed to parse start time '{start_str}': {e}")
            is_past = None

        # Build processed event
        processed = {
            "id": event['id'],
            "summary": event.get('summary', '(No title)'),
            "description": event.get('description', ''),
            "location": event.get('location', ''),
            "start": start_str,
            "end": end_str,
            "is_past": is_past,
            "attendees": attendee_emails,
            "attendees_with_status": attendees_with_status,  # New: full attendee info
            "external_attendees": external_attendees,
            "attendee_count": len(attendee_emails),
            "organizer": event.get('organizer', {}).get('email', ''),
            "status": event.get('status', ''),
            "html_link": event.get('html_link', ''),
            "created_at": event.get('created', ''),
            "updated_at": event.get('updated', ''),
            "cached_at": datetime.now(timezone.utc).isoformat()
        }

        return processed

    def _event_changed(self, cached: Dict[str, Any], fresh: Dict[str, Any]) -> bool:
        """Check if event has changed since last cache.

        Args:
            cached: Cached event
            fresh: Fresh event from API

        Returns:
            True if changed
        """
        # Compare updated timestamps
        cached_updated = cached.get('updated_at', '')
        fresh_updated = fresh.get('updated', '')

        return cached_updated != fresh_updated

    def get_events_by_contact(
        self,
        contact_email: str,
        days_back: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all events involving a specific contact.

        Args:
            contact_email: Contact's email address
            days_back: Optional filter (only events in last N days)

        Returns:
            List of events with this contact
        """
        cache = self._load_cache()

        matching_events = []
        cutoff_date = None

        if days_back:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        for event in cache['events'].values():
            # Check if contact is in attendees
            if contact_email in event.get('attendees', []):
                # Apply date filter if specified
                if cutoff_date:
                    try:
                        start_dt = datetime.fromisoformat(
                            event['start'].replace('Z', '+00:00')
                        )
                        if start_dt < cutoff_date:
                            continue
                    except:
                        pass

                matching_events.append(event)

        # Sort by start time (most recent first)
        matching_events.sort(
            key=lambda e: e.get('start', ''),
            reverse=True
        )

        return matching_events

    def get_recent_meetings(
        self,
        days_back: int = 7,
        only_past: bool = True,
        only_external: bool = False
    ) -> List[Dict[str, Any]]:
        """Get recent meetings for relationship gap analysis.

        Args:
            days_back: How many days back to look
            only_past: Only include past meetings
            only_external: Only include meetings with external attendees

        Returns:
            List of recent meetings
        """
        cache = self._load_cache()

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        meetings = []

        for event in cache['events'].values():
            # Filter by date
            try:
                start_dt = datetime.fromisoformat(
                    event['start'].replace('Z', '+00:00')
                )
                if start_dt < cutoff_date:
                    continue

                # Filter by past/future
                if only_past and not event.get('is_past', False):
                    continue

                # Filter by external attendees
                if only_external and not event.get('external_attendees', []):
                    continue

                meetings.append(event)
            except:
                continue

        # Sort by start time (most recent first)
        meetings.sort(
            key=lambda e: e.get('start', ''),
            reverse=True
        )

        return meetings

    def search_events(
        self,
        query: str,
        days_back: Optional[int] = None,
        days_forward: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Search events by keyword in title or description.

        Args:
            query: Search query
            days_back: Optional past window
            days_forward: Optional future window

        Returns:
            Matching events
        """
        cache = self._load_cache()

        query_lower = query.lower()
        matching = []

        now = datetime.now(timezone.utc)
        cutoff_past = now - timedelta(days=days_back) if days_back else None
        cutoff_future = now + timedelta(days=days_forward) if days_forward else None

        for event in cache['events'].values():
            # Search in summary and description
            summary = event.get('summary', '').lower()
            description = event.get('description', '').lower()

            if query_lower in summary or query_lower in description:
                # Apply date filters
                try:
                    start_dt = datetime.fromisoformat(
                        event['start'].replace('Z', '+00:00')
                    )

                    if cutoff_past and start_dt < cutoff_past:
                        continue
                    if cutoff_future and start_dt > cutoff_future:
                        continue

                    matching.append(event)
                except:
                    matching.append(event)  # Include if date parsing fails

        # Sort by start time (most recent first)
        matching.sort(
            key=lambda e: e.get('start', ''),
            reverse=True
        )

        return matching

    def get_stats(self) -> Dict[str, Any]:
        """Get calendar cache statistics.

        Returns:
            Stats dict
        """
        cache = self._load_cache()

        now = datetime.now(timezone.utc)
        past_count = 0
        future_count = 0
        external_count = 0

        for event in cache['events'].values():
            if event.get('is_past'):
                past_count += 1
            else:
                future_count += 1

            if event.get('external_attendees'):
                external_count += 1

        return {
            "total_events": len(cache['events']),
            "past_events": past_count,
            "future_events": future_count,
            "external_meetings": external_count,
            "last_sync": cache.get('last_sync'),
            "sync_window": cache.get('sync_window', {})
        }
