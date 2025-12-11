"""Pipedrive CRM API integration."""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class PipedriveClient:
    """Client for Pipedrive CRM API operations.

    Handles person search, deal retrieval, and pipeline filtering.
    """

    def __init__(self, api_token: str, base_url: str = "https://api.pipedrive.com/v1"):
        """Initialize Pipedrive client.

        Args:
            api_token: Pipedrive API token
            base_url: Pipedrive API base URL
        """
        self.api_token = api_token
        self.base_url = base_url
        self.client = httpx.Client(timeout=30.0)

        logger.info("Initialized Pipedrive client")

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make authenticated request to Pipedrive API.

        Args:
            method: HTTP method
            endpoint: API endpoint (without base URL)
            **kwargs: Additional request parameters

        Returns:
            Response JSON
        """
        url = f"{self.base_url}/{endpoint}"

        # Add API token to params
        params = kwargs.pop('params', {})
        params['api_token'] = self.api_token

        response = self.client.request(
            method=method,
            url=url,
            params=params,
            **kwargs
        )

        response.raise_for_status()
        return response.json()

    def search_person_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Search for a person by email address.

        Args:
            email: Email address to search

        Returns:
            Person data if found, None otherwise
        """
        try:
            result = self._request(
                'GET',
                'persons/search',
                params={
                    'term': email,
                    'fields': 'email',
                    'exact_match': True
                }
            )

            if result.get('success') and result.get('data', {}).get('items'):
                items = result['data']['items']
                logger.debug(f"Pipedrive search returned {len(items)} items")

                # Return first exact match
                for item in items:
                    person = item.get('item', {})
                    logger.debug(f"Person object: {person}")

                    # Verify email match - handle both string and array formats
                    person_emails = person.get('emails', [])

                    # If emails is a string, convert to list
                    if isinstance(person_emails, str):
                        person_emails = [{'value': person_emails}]

                    for email_obj in person_emails:
                        # Handle both dict and string format
                        email_value = email_obj.get('value') if isinstance(email_obj, dict) else email_obj
                        if email_value and email_value.lower() == email.lower():
                            logger.info(f"Found person: {person.get('name')} (ID: {person.get('id')})")
                            return person

            logger.info(f"No person found for email: {email}")
            return None

        except Exception as e:
            logger.error(f"Failed to search person by email: {e}")
            raise

    def get_person(self, person_id: int) -> Dict[str, Any]:
        """Get detailed person information.

        Args:
            person_id: Pipedrive person ID

        Returns:
            Person data
        """
        try:
            result = self._request('GET', f'persons/{person_id}')

            if result.get('success') and result.get('data'):
                return result['data']

            raise ValueError(f"Person {person_id} not found")

        except Exception as e:
            logger.error(f"Failed to get person {person_id}: {e}")
            raise

    def get_person_deals(
        self,
        person_id: int,
        status: Optional[str] = None,
        pipeline_id: Optional[int] = None,
        stage_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get deals for a person with optional filters.

        Args:
            person_id: Pipedrive person ID
            status: Deal status filter ('open', 'won', 'lost', 'deleted', 'all_not_deleted')
            pipeline_id: Filter by pipeline ID
            stage_id: Filter by stage ID

        Returns:
            List of deals
        """
        try:
            params = {}
            if status:
                params['status'] = status

            result = self._request(
                'GET',
                f'persons/{person_id}/deals',
                params=params
            )

            if not result.get('success'):
                return []

            deals = result.get('data', [])

            # Apply pipeline/stage filters
            if pipeline_id is not None:
                deals = [d for d in deals if d.get('pipeline_id') == pipeline_id]

            if stage_id is not None:
                deals = [d for d in deals if d.get('stage_id') == stage_id]

            logger.info(f"Found {len(deals)} deals for person {person_id}")
            return deals

        except Exception as e:
            logger.error(f"Failed to get deals for person {person_id}: {e}")
            raise

    def get_pipelines(self) -> List[Dict[str, Any]]:
        """Get all pipelines.

        Returns:
            List of pipelines
        """
        try:
            result = self._request('GET', 'pipelines')

            if result.get('success'):
                return result.get('data', [])

            return []

        except Exception as e:
            logger.error(f"Failed to get pipelines: {e}")
            raise

    def get_stages(self, pipeline_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get stages, optionally filtered by pipeline.

        Args:
            pipeline_id: Filter stages by pipeline ID

        Returns:
            List of stages
        """
        try:
            params = {}
            if pipeline_id is not None:
                params['pipeline_id'] = pipeline_id

            result = self._request('GET', 'stages', params=params)

            if result.get('success'):
                return result.get('data', [])

            return []

        except Exception as e:
            logger.error(f"Failed to get stages: {e}")
            raise

    def get_person_activities(
        self,
        person_id: int,
        done: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Get activities for a person.

        Args:
            person_id: Pipedrive person ID
            done: Filter by done status (True=completed, False=pending, None=all)

        Returns:
            List of activities
        """
        try:
            params = {}
            if done is not None:
                params['done'] = 1 if done else 0

            result = self._request(
                'GET',
                f'persons/{person_id}/activities',
                params=params
            )

            if result.get('success'):
                return result.get('data', [])

            return []

        except Exception as e:
            logger.error(f"Failed to get activities for person {person_id}: {e}")
            raise

    def list_deals(
        self,
        status: str = "all_not_deleted",
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """List all deals from Pipedrive.

        Args:
            status: Filter by status ('open', 'won', 'lost', 'deleted', 'all_not_deleted')
            limit: Max deals to fetch (Pipedrive API max per page is 500)

        Returns:
            List of deal dictionaries
        """
        try:
            all_deals = []
            start = 0

            while True:
                result = self._request(
                    'GET',
                    'deals',
                    params={
                        'status': status,
                        'start': start,
                        'limit': min(limit - len(all_deals), 500)
                    }
                )

                if not result.get('success'):
                    break

                deals = result.get('data', [])
                if not deals:
                    break

                all_deals.extend(deals)

                # Check if there are more pages
                pagination = result.get('additional_data', {}).get('pagination', {})
                if not pagination.get('more_items_in_collection'):
                    break

                start = pagination.get('next_start', start + len(deals))

                # Respect limit
                if len(all_deals) >= limit:
                    break

            logger.info(f"Fetched {len(all_deals)} deals from Pipedrive")
            return all_deals[:limit]

        except Exception as e:
            logger.error(f"Failed to list deals: {e}")
            raise
