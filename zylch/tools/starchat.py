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

    CRITICAL NOTE:
    Most endpoints MUST use the realm, e.g., `/mrcall/v1/{realm}/crm/business`.
    Using generic paths like `/mrcall/v1/crm/business` will result in 401 Unauthorized.
    Always construct paths using `self.realm`.
    """

    def __init__(
        self,
        base_url: str,
        auth_type: str = "basic",
        username: Optional[str] = None,
        password: Optional[str] = None,
        jwt_token: Optional[str] = None,
        access_token: Optional[str] = None,
        realm: str = "default",
        timeout: int = 30,
        verify_ssl: bool = True,
        owner_id: Optional[str] = None,
        supabase_storage: Optional[Any] = None,
    ):
        """Initialize StarChat client.

        Args:
            base_url: StarChat API base URL
            auth_type: Authentication type ("basic", "firebase", or "oauth")
            username: Username for Basic auth
            password: Password for Basic auth
            jwt_token: JWT token for Firebase auth
            access_token: OAuth access token
            realm: Firebase realm/config group
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            owner_id: Firebase UID (for OAuth token refresh)
            supabase_storage: SupabaseStorage instance (for OAuth token refresh)
        """
        self.base_url = base_url.rstrip("/")
        self.auth_type = auth_type
        self.username = username
        self.password = password
        self.jwt_token = jwt_token
        self.access_token = access_token
        self.realm = realm
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=self._build_headers(),
            verify=self.verify_ssl,
        )

        logger.info(f"Initialized StarChat client for {base_url} with {auth_type} auth")

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers with authentication."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "zylch/0.1.0",
        }

        # Priority: OAuth > JWT (Firebase) > Basic Auth
        # CRITICAL: MrCall uses 'auth' header for both Firebase and OAuth tokens
        if self.auth_type == "oauth" and self.access_token:
            headers["auth"] = self.access_token
        elif self.auth_type == "firebase" and self.jwt_token:
            headers["auth"] = self.jwt_token
        elif self.auth_type == "basic" and self.username and self.password:
            credentials = f"{self.username}:{self.password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        # Backward compatibility: if no auth_type specified, use old logic
        elif self.jwt_token:
            headers["auth"] = self.jwt_token
        elif self.username and self.password:
            credentials = f"{self.username}:{self.password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    async def _refresh_token_if_needed(self):
        """Check if OAuth token expired and refresh if needed."""
        if self.auth_type != "oauth" or not self.supabase or not self.owner_id:
            return

        from zylch.api.token_storage import get_mrcall_credentials, refresh_mrcall_token
        from datetime import datetime, timezone, timedelta

        try:
            credentials = get_mrcall_credentials(self.owner_id)

            if not credentials:
                raise ValueError("MrCall not connected")

            expires_at = credentials.get("expires_at")
            if expires_at:
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))

                # Refresh if expiring within 5 minutes
                if expires_at < datetime.now(timezone.utc) + timedelta(minutes=5):
                    logger.info(f"MrCall token expiring soon, refreshing for owner {self.owner_id}")
                    new_credentials = await refresh_mrcall_token(self.owner_id)

                    if new_credentials:
                        # Update access token and rebuild headers
                        self.access_token = new_credentials["access_token"]
                        self.client.headers.update(self._build_headers())
                        logger.info("Successfully refreshed MrCall token")
                    else:
                        logger.error("Failed to refresh MrCall token")
        except Exception as e:
            logger.error(f"Error checking/refreshing MrCall token: {e}")

    async def get_contact(self, contact_id: str) -> Optional[Dict[str, Any]]:
        """Get contact by ID.

        Args:
            contact_id: Contact ID

        Returns:
            Contact data or None if not found
        """
        logger.debug(f"Getting contact: {contact_id}")

        # Refresh token if needed before making request
        await self._refresh_token_if_needed()

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

    async def get_contact_by_email(
        self,
        email: str,
        business_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get contact by email address (async version).

        Args:
            email: Email address to search for
            business_id: Business ID (required for BasicAuth endpoint)

        Returns:
            Contact data or None if not found
        """
        logger.debug(f"Getting contact by email: {email}")

        contacts = await self.search_contacts(email=email, business_id=business_id, limit=1)

        return self._filter_contact_by_email(contacts, email)

    def get_contact_by_email_sync(
        self,
        email: str,
        business_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get contact by email address (sync version).

        Args:
            email: Email address to search for
            business_id: Business ID (required for BasicAuth endpoint)

        Returns:
            Contact data or None if not found
        """
        import asyncio
        logger.debug(f"Getting contact by email (sync): {email}")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, create a new event loop in a thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.search_contacts(email=email, business_id=business_id, limit=1)
                    )
                    contacts = future.result()
            else:
                contacts = loop.run_until_complete(
                    self.search_contacts(email=email, business_id=business_id, limit=1)
                )
        except RuntimeError:
            # No event loop exists, create one
            contacts = asyncio.run(
                self.search_contacts(email=email, business_id=business_id, limit=1)
            )

        return self._filter_contact_by_email(contacts, email)

    def _filter_contact_by_email(
        self,
        contacts: List[Dict[str, Any]],
        email: str
    ) -> Optional[Dict[str, Any]]:
        """Filter contacts list to find exact email match.

        Args:
            contacts: List of contacts from search
            email: Email to match

        Returns:
            Matching contact or None
        """
        if not contacts:
            return None

        email_lower = email.lower()
        for contact in contacts:
            # Check primary email
            contact_email = contact.get("email", "").lower()
            if contact_email == email_lower:
                return contact

            # Check emails array
            emails = contact.get("emails", [])
            for e in emails:
                if isinstance(e, dict) and e.get("address", "").lower() == email_lower:
                    return contact
                elif isinstance(e, str) and e.lower() == email_lower:
                    return contact

            # Check variables.EMAIL_ADDRESS
            variables = contact.get("variables", {})
            var_email = variables.get("EMAIL_ADDRESS", "").lower()
            if var_email == email_lower:
                return contact

        return None

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
        logger.info(f"Raw response text: {response_text}")

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
            logger.warning(f"Response text: {response_text}")
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

    # ==========================================================================
    # MrCall Business Configuration Methods
    # ==========================================================================

    async def get_business_config(self, business_id: str) -> Optional[Dict[str, Any]]:
        """Fetch business configuration with current variable values.

        Args:
            business_id: Business ID

        Returns:
            Business configuration including current variable values, or None if not found
        """
        logger.info(f"Fetching business configuration: {business_id}")

        try:
            # Note: This endpoint uses POST with JSON body for search
            # CRITICAL: For OAuth/Delegated access, we must use the delegated_{realm} prefix
            # path: /mrcall/v1/delegated_{realm}/crm/business/search
            endpoint = f"/mrcall/v1/delegated_{self.realm}/crm/business/search"
            
            logger.info(f"Using business search endpoint: {endpoint}")
            
            response = await self.client.request(
                "POST",
                endpoint,
                json={"businessId": business_id}
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()

            # API returns a list, extract first element
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
            else:
                return None

        except Exception as e:
            logger.error(f"Failed to fetch business config: {e}")
            raise

    async def get_variable_schema(
        self,
        template_name: str = "private",
        language: str = "it-IT",
        nested: bool = True,
    ) -> Dict[str, Any]:
        """Fetch variable catalog schema from StarChat.

        This returns the variable definitions/schema from business_variable.csv,
        not the current values for a specific business.

        Args:
            template_name: Template name (e.g., "private", "businesspro")
            language: Language code (e.g., "en-US", "it-IT")
            nested: Return nested structure

        Returns:
            Variable catalog schema
        """
        logger.info(f"Fetching variable schema: template={template_name}, lang={language}")

        params = {
            "templateName": template_name,
            "language": language,
            "nested": str(nested).lower(),
        }

        # CRITICAL: For OAuth/Delegated access, we must use the delegated_{realm} prefix
        endpoint = f"/mrcall/v1/delegated_{self.realm}/crm/variables"
        logger.info(f"Fetching variable schema from: {endpoint} with params={params}")

        response = await self.client.get(endpoint, params=params)
        response.raise_for_status()

        return response.json()

    async def get_all_variables(self, business_id: str) -> List[Dict[str, Any]]:
        """Get all variables with descriptions and current values.

        Downloads schema from StarChat to get descriptions, and fetches
        business config to get current values.

        Args:
            business_id: Business ID

        Returns:
            List of dicts with name, description, and value
        """
        try:
            # 1. Get business config for current values and template
            business = await self.get_business_config(business_id)
            if not business:
                raise ValueError(f"Business not found: {business_id}")

            current_values = business.get("variables", {})
            template = business.get("template", "businesspro")
            logger.info(f"Fetching variables for template: {template}")

            # 2. Get schema for descriptions
            # Note: The API returns a Map[String, CrmVariable] or List?
            # Based on usage, likely a list or dict.
            schema = await self.get_variable_schema(template_name=template, nested=False)
            
            # 3. Combine them
            combined = []
            
            # Handle schema if it's a list or dict
            # Schema is typically { "VAR_NAME": { "description": "...", ... } } or list
            schema_items = []
            if isinstance(schema, dict):
                for k, v in schema.items():
                    if isinstance(v, dict):
                        v['name'] = k
                        schema_items.append(v)
            elif isinstance(schema, list):
                schema_items = schema

            for item in schema_items:
                name = item.get("name")
                if not name:
                    continue
                
                # Get description (handle multiple languages if present, or just 'description')
                desc = item.get("description", "")
                if isinstance(desc, dict):
                    # Try to get English or Italian
                    desc = desc.get("en-US") or desc.get("en-GB") or desc.get("it-IT") or list(desc.values())[0]
                
                # Get current value
                value = current_values.get(name, "Not set")
                
                combined.append({
                    "name": name,
                    "description": desc,
                    "value": value
                })
                
            # Sort by name
            combined.sort(key=lambda x: x["name"])
            return combined

        except Exception as e:
            logger.error(f"Error in get_all_variables: {e}")
            raise

    async def update_business_variable(
        self,
        business_id: str,
        variable_name: str,
        value: str,
    ) -> Dict[str, Any]:
        """Update a business variable.

        Args:
            business_id: Business ID
            variable_name: Variable name (e.g., OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT)
            value: New value

        Returns:
            API response

        Raises:
            ValueError: If business not found
            Exception: If request fails
        """
        logger.info(f"Updating variable {variable_name} for business: {business_id}")

        # First, get the current business to preserve other fields
        business_data = await self.get_business_config(business_id)

        if not business_data:
            raise ValueError(f"No business found with ID: {business_id}")

        # Update the specific variable
        if "variables" not in business_data:
            business_data["variables"] = {}

        business_data["variables"][variable_name] = value

        # Fields to exclude from PUT request (read-only or search metadata)
        # Based on CrmBusiness.scala - these are server-managed fields
        readonly_fields = {
            'totalHits',           # Search pagination metadata
            'creationDateTime',    # Read-only timestamp
            'lastUpdateDateTime',  # Server-set timestamp
            'protected',           # System-managed flag
            'recurrentResources',  # System-managed JSON
        }

        # Filter out read-only fields before PUT
        filtered_data = {k: v for k, v in business_data.items() if k not in readonly_fields}

        # PUT the updated business back
        # CRITICAL: For OAuth/Delegated access, we must use the delegated_{realm} prefix
        endpoint = f"/mrcall/v1/delegated_{self.realm}/crm/business"
        logger.info(f"Putting updated business to: {endpoint}")
        logger.debug(f"PUT request body keys: {list(filtered_data.keys())}")

        response = await self.client.put(
            endpoint,
            json=filtered_data,
        )

        if response.status_code >= 400:
            logger.error(f"PUT failed: {response.status_code} - {response.text}")
        response.raise_for_status()

        return response.json()

    async def check_user_role(self, business_id: str) -> Optional[str]:
        """Check user's role for a business.

        Determines if the current user has admin privileges for the business.

        Args:
            business_id: Business ID to check

        Returns:
            Role string (e.g., "admin", "user") or None if cannot determine
        """
        # Try to get business info which may include user role
        # The exact implementation depends on StarChat's API
        try:
            business = await self.get_business_config(business_id)
            if business:
                # Check various possible role fields
                role = business.get("userRole") or business.get("role") or business.get("user_role")
                if role:
                    return role.lower()

                # Check if user is owner
                if business.get("isOwner") or business.get("is_owner"):
                    return "admin"

            return None
        except Exception as e:
            logger.warning(f"Could not determine user role: {e}")
            return None

    async def get_whatsapp_contacts(
        self,
        business_id: str,
        days_back: int = 30
    ) -> List[Dict[str, Any]]:
        """Get contacts from WhatsApp messages via StarChat API.

        Requires StarChat REST API endpoint for WhatsApp messages.
        See STARCHAT_REQUESTS.md Request #3 for API specification.

        Args:
            business_id: Business ID
            days_back: Number of days to look back for messages

        Returns:
            List of contacts with WhatsApp context
        """
        logger.info(f"Getting WhatsApp contacts for business: {business_id}")

        # TODO: Implement when StarChat provides REST API endpoint
        # Proposed endpoint: GET /mrcall/v1/crm/whatsapp/{businessId}/messages
        # See STARCHAT_REQUESTS.md Request #3 for full specification

        logger.warning("WhatsApp integration requires StarChat REST API endpoint - not yet available")
        return []

    async def initiate_outbound_call(
        self,
        phone_number: str,
        business_id: str,
        caller_id: Optional[str] = None,
        contact_id: Optional[str] = None,
        variables: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Initiate an outbound phone call via MrCall.

        This triggers the MrCall AI assistant to call the specified phone number.
        The call will use the assistant configuration for the given business_id.

        Args:
            phone_number: Phone number to call (with country code, e.g., +12025551234)
            business_id: MrCall business/assistant ID to use for the call
            caller_id: Optional caller ID to display (must be verified number)
            contact_id: Optional contact ID if calling a known contact
            variables: Optional variables to pass to the call script

        Returns:
            Dict with call_id and status

        Raises:
            httpx.HTTPStatusError: If API call fails
        """
        logger.info(f"Initiating outbound call to {phone_number} via business {business_id}")

        # Normalize phone number
        if not phone_number.startswith('+'):
            phone_number = '+' + phone_number.lstrip('0')

        # Build request body
        call_data = {
            "phoneNumber": phone_number,
            "businessId": business_id,
        }

        if caller_id:
            call_data["callerId"] = caller_id
        if contact_id:
            call_data["contactId"] = contact_id
        if variables:
            # Ensure all variables are strings
            call_data["variables"] = {
                k: str(v) if not isinstance(v, str) else v
                for k, v in variables.items()
            }

        # StarChat outbound call endpoint
        # Note: Endpoint format may vary based on StarChat API version
        endpoint = f"/mrcall/v1/call/outbound/{business_id}"

        logger.info(f"POST {endpoint}")
        logger.debug(f"Call data: {call_data}")

        response = await self.client.post(endpoint, json=call_data)

        if response.status_code >= 400:
            logger.error(f"Outbound call failed: {response.status_code}")
            logger.error(f"Response: {response.text}")

        response.raise_for_status()

        # Parse response
        response_text = response.text
        if not response_text or response_text.strip() == "":
            return {
                "status": "initiated",
                "phone_number": phone_number,
                "business_id": business_id,
            }

        try:
            result = response.json()
            result["status"] = result.get("status", "initiated")
            return result
        except json.JSONDecodeError:
            return {
                "status": "initiated",
                "phone_number": phone_number,
                "business_id": business_id,
                "raw_response": response_text,
            }

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()


# =============================================================================
# Factory Function for Creating StarChat Clients
# =============================================================================

async def create_starchat_client(owner_id: str, supabase_storage: Optional[Any] = None) -> StarChatClient:
    """
    Create StarChat client with appropriate auth method.

    Priority:
    1. OAuth (if mrcall credentials exist in Supabase)
    2. Basic Auth (fallback to env vars if configured)

    Args:
        owner_id: Firebase UID
        supabase_storage: SupabaseStorage instance (optional, will create if not provided)

    Returns:
        StarChatClient configured with best available auth method

    Raises:
        ValueError: If no auth method available
    """
    from zylch.config import settings
    from zylch.api.token_storage import get_mrcall_credentials

    # Get or create Supabase storage
    if not supabase_storage:
        from zylch.storage.supabase_client import SupabaseStorage
        supabase_storage = SupabaseStorage()

    # Try OAuth first (preferred method)
    try:
        credentials = get_mrcall_credentials(owner_id)

        if credentials and credentials.get("access_token"):
            logger.info(f"Creating StarChat client with OAuth for owner {owner_id}")
            return StarChatClient(
                base_url=settings.mrcall_base_url.rstrip('/'),
                auth_type="oauth",
                access_token=credentials["access_token"],
                realm=settings.mrcall_realm,
                owner_id=owner_id,
                supabase_storage=supabase_storage
            )
    except Exception as e:
        logger.debug(f"OAuth credentials not available: {e}")

    # Fallback to Basic Auth (for backward compatibility)
    # Only if STARCHAT_USERNAME and STARCHAT_PASSWORD are set
    if hasattr(settings, "starchat_username") and settings.starchat_username:
        logger.info(f"Creating StarChat client with Basic Auth (fallback) for owner {owner_id}")
        return StarChatClient(
            base_url=settings.mrcall_base_url.rstrip('/'),
            auth_type="basic",
            username=settings.starchat_username,
            password=settings.starchat_password,
            realm=settings.mrcall_realm
        )

    raise ValueError("MrCall not connected. Please use /connect mrcall to authorize.")
