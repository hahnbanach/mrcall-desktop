"""StarChat API client for contact management."""

import base64
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class StarChatClient:
    """Client for StarChat CRM API (MrCall Firebase endpoints).

    Handles contact CRUD operations via StarChat's REST API.
    """

    def __init__(
        self,
        base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        jwt_token: Optional[str] = None,
        realm: str = "default",
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        """Initialize StarChat client.

        Args:
            base_url: StarChat API base URL
            username: Username for Basic auth
            password: Password for Basic auth
            jwt_token: JWT token for Firebase auth
            realm: Firebase realm/config group
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.jwt_token = jwt_token
        self.realm = realm
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=self._build_headers(),
            verify=self.verify_ssl,
        )

        logger.info(f"Initialized StarChat client for {base_url}")

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers with authentication."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "mrpark/0.1.0",
        }

        # Prefer JWT if provided
        if self.jwt_token:
            headers["auth"] = self.jwt_token
        # Otherwise use Basic auth
        elif self.username and self.password:
            credentials = f"{self.username}:{self.password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    async def get_contact(self, contact_id: str) -> Optional[Dict[str, Any]]:
        """Get contact by ID.

        Args:
            contact_id: Contact ID

        Returns:
            Contact data or None if not found
        """
        logger.debug(f"Getting contact: {contact_id}")

        response = await self.client.request(
            "GET",
            f"/mrcall/v1/{self.realm}/crm/contact",
            json={"contactId": contact_id}
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        data = response.json()
        return data[0] if isinstance(data, list) and len(data) > 0 else data

    async def search_contacts(
        self,
        filter_expression: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        limit: int = 100,
        business_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search contacts by criteria.

        Args:
            filter_expression: Filter expression (e.g., "variables.PRIORITY_SCORE > 7")
            email: Filter by email (searches variables.EMAIL_ADDRESS)
            phone: Filter by phone (searches variables.PHONE_NUMBER)
            limit: Maximum results
            business_id: Business ID (uses BasicAuth endpoint if provided)

        Returns:
            List of matching contacts
        """
        logger.info(f"🔍 search_contacts called with: business_id={business_id}, email={email}, phone={phone}")
        logger.debug(f"Searching contacts with filter: {filter_expression}")

        if business_id:
            logger.info(f"✅ Using BasicAuth endpoint (business_id provided)")
            endpoint = f"/mrcall/v1/crm/contact/{business_id}"
            # Use GET to fetch all contacts
            logger.info(f"GET {endpoint}")
            response = await self.client.get(endpoint)
        else:
            # JWT endpoint supports proper search
            logger.info(f"⚠️  Using JWT endpoint (no business_id provided)")
            endpoint = f"/mrcall/v1/{self.realm}/crm/contact/search"
            search_body = {
                "from": 0,
                "size": limit,
            }
            if email:
                search_body["emails"] = [{"address": email}]
            if phone:
                search_body["phones"] = [{"number": phone}]
            response = await self.client.post(endpoint, json=search_body)

        response.raise_for_status()

        # Debug: log raw response
        response_text = response.text
        logger.info(f"Raw response text: {response_text[:500]}")  # First 500 chars

        data = response.json()
        logger.info(f"Parsed JSON type: {type(data)}, value: {data}")

        all_contacts = data if isinstance(data, list) else [data]
        logger.info(f"Retrieved {len(all_contacts)} total contacts from API")

        return all_contacts

    async def search_contacts_paginated(
        self,
        business_id: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        page_size: int = 100,
        max_total: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Search contacts with pagination support.

        Args:
            business_id: Business ID (uses BasicAuth endpoint)
            email: Filter by email
            phone: Filter by phone
            page_size: Results per page
            max_total: Maximum total results (None = fetch all)

        Returns:
            List of matching contacts (paginated)
        """
        logger.info(f"🔄 search_contacts_paginated: business_id={business_id}, email={email}, phone={phone}")

        logger.info(f"Fetching all contacts for business: {business_id}")

        endpoint = f"/mrcall/v1/crm/contact/{business_id}"
        response = await self.client.get(endpoint)
        response.raise_for_status()

        data = response.json()
        contacts = data if isinstance(data, list) else [data] if data else []

        # Apply max_total limit if specified
        if max_total and len(contacts) > max_total:
            contacts = contacts[:max_total]

        logger.info(f"✅ Total contacts fetched: {len(contacts)}")
        return contacts

    async def create_contact(
        self,
        contact_data: Dict[str, Any],
        business_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create new contact.

        Args:
            contact_data: Contact data including email, phone, variables
            business_id: Business ID (uses BasicAuth endpoint if provided)

        Returns:
            Created contact with ID
        """
        logger.info(f"Creating contact: {contact_data.get('email', 'unknown')}")

        # Ensure variables are strings (StarChat requirement)
        if "variables" in contact_data:
            for key, value in contact_data["variables"].items():
                if not isinstance(value, str):
                    contact_data["variables"][key] = json.dumps(value)

        # Use businessId endpoint if provided (BasicAuth)
        if business_id:
            endpoint = f"/mrcall/v1/crm/contact/{business_id}"
        else:
            endpoint = f"/mrcall/v1/{self.realm}/crm/contact"

        # Log the full request for debugging
        logger.info(f"POST {endpoint}")
        logger.info(f"Request body: {json.dumps(contact_data, indent=2)}")

        response = await self.client.post(endpoint, json=contact_data)

        # Log response details on error
        if response.status_code >= 400:
            logger.error(f"Response status: {response.status_code}")
            logger.error(f"Response body: {response.text}")

        response.raise_for_status()

        # Handle empty response (200 OK with no body)
        response_text = response.text
        if not response_text or response_text.strip() == "":
            logger.info("Contact created successfully (empty response)")
            return {"status": "created", "contact": contact_data}

        # Try to parse JSON response
        try:
            return response.json()
        except json.JSONDecodeError as e:
            logger.warning(f"Response is not valid JSON: {e}")
            logger.warning(f"Response text: {response_text[:200]}")
            # Return success anyway since we got 200 OK
            return {"status": "created", "contact": contact_data, "raw_response": response_text}

    async def update_contact(
        self,
        contact_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update contact data.

        Args:
            contact_id: Contact ID
            updates: Fields to update (can include variables)

        Returns:
            Updated contact
        """
        logger.info(f"Updating contact: {contact_id}")

        # Get current contact first
        current = await self.get_contact(contact_id)
        if not current:
            raise ValueError(f"Contact not found: {contact_id}")

        # Merge updates
        current.update(updates)

        # Ensure variables are strings
        if "variables" in current:
            for key, value in current["variables"].items():
                if not isinstance(value, str):
                    current["variables"][key] = json.dumps(value)

        response = await self.client.put(
            f"/mrcall/v1/{self.realm}/crm/contact",
            json=current
        )
        response.raise_for_status()

        return response.json()

    async def update_contact_variables(
        self,
        contact_id: str,
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update contact variables (merge with existing).

        Args:
            contact_id: Contact ID
            variables: Variables to update (will be merged)

        Returns:
            Updated contact
        """
        logger.debug(f"Updating variables for contact: {contact_id}")

        # Get current contact
        current = await self.get_contact(contact_id)
        if not current:
            raise ValueError(f"Contact not found: {contact_id}")

        # Merge variables
        if "variables" not in current:
            current["variables"] = {}

        for key, value in variables.items():
            # Convert to string if needed
            current["variables"][key] = json.dumps(value) if not isinstance(value, str) else value

        # Update contact
        response = await self.client.put(
            f"/mrcall/v1/{self.realm}/crm/contact",
            json=current
        )
        response.raise_for_status()

        return response.json()

    async def delete_contact(self, contact_id: str) -> None:
        """Delete contact.

        Args:
            contact_id: Contact ID to delete
        """
        logger.info(f"Deleting contact: {contact_id}")

        response = await self.client.delete(
            f"/mrcall/v1/{self.realm}/crm/contact",
            json={"contactIds": [contact_id]}
        )
        response.raise_for_status()

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
