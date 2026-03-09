"""
API endpoints for integration connections management.

Provides RESTful API for querying available providers and user connection status.
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from zylch.api.firebase_auth import get_current_user
from zylch.storage.supabase_client import SupabaseStorage
from zylch.storage.database import get_session
from zylch.storage.models import IntegrationProvider
from zylch.integrations.registry import (
    get_available_providers,
    get_user_connections,
    get_connection_status
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


class ConnectionStatusResponse(BaseModel):
    """Response model for connection status"""
    connections: list
    total: int
    connected_count: int
    available_count: int


class CredentialsSaveRequest(BaseModel):
    """Request model for saving provider credentials"""
    credentials: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None


class CredentialsResponse(BaseModel):
    """Response model for credential operations"""
    success: bool
    provider: str
    status: str
    message: Optional[str] = None


@router.get("/status", response_model=ConnectionStatusResponse)
async def get_connections_status(
    user: dict = Depends(get_current_user),
    include_unavailable: bool = Query(False, description="Include 'coming soon' providers")
):
    """
    Get user's connection status for all available providers.

    Returns:
    - List of all providers with connection status
    - Count of connected, available, and total providers

    **Example Response:**
    ```json
    {
      "connections": [
        {
          "provider_key": "google",
          "display_name": "Google (Gmail & Calendar)",
          "category": "email",
          "status": "connected",
          "connected_email": "user@gmail.com",
          "last_sync": "2025-12-10T10:00:00Z",
          "oauth_url": "/api/auth/google/authorize"
        },
        {
          "provider_key": "pipedrive",
          "display_name": "Pipedrive CRM",
          "category": "crm",
          "status": "disconnected",
          "requires_oauth": false
        }
      ],
      "total": 10,
      "connected_count": 2,
      "available_count": 6
    }
    ```
    """
    from zylch.api.firebase_auth import get_user_id_from_token

    owner_id = get_user_id_from_token(user)

    try:
        supabase = SupabaseStorage()
        status_data = get_connection_status(
            supabase,
            owner_id,
            include_unavailable=include_unavailable
        )

        return ConnectionStatusResponse(**status_data)

    except Exception as e:
        logger.error(f"Failed to get connection status for {owner_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get connection status: {str(e)}")


@router.get("/providers")
async def list_providers(
    category: Optional[str] = Query(None, description="Filter by category (email, crm, messaging, etc.)"),
    include_unavailable: bool = Query(False, description="Include 'coming soon' providers")
):
    """
    Get list of all available integration providers.

    **Query Parameters:**
    - `category`: Filter by category (email, crm, messaging, telephony, video, ai)
    - `include_unavailable`: Include providers that are not yet available

    **Example Response:**
    ```json
    {
      "providers": [
        {
          "provider_key": "google",
          "display_name": "Google (Gmail & Calendar)",
          "category": "email",
          "description": "Access Gmail emails and Google Calendar events",
          "requires_oauth": true,
          "oauth_url": "/api/auth/google/authorize",
          "is_available": true
        }
      ]
    }
    ```
    """
    try:
        supabase = SupabaseStorage()
        providers = get_available_providers(
            supabase,
            category=category,
            include_unavailable=include_unavailable
        )

        return {"providers": providers}

    except Exception as e:
        logger.error(f"Failed to list providers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list providers: {str(e)}")


@router.get("/providers/{provider_key}")
async def get_provider_info(provider_key: str):
    """
    Get detailed information about a specific provider.

    **Path Parameters:**
    - `provider_key`: Provider identifier (google, microsoft, pipedrive, etc.)

    **Example Response:**
    ```json
    {
      "provider_key": "google",
      "display_name": "Google (Gmail & Calendar)",
      "category": "email",
      "description": "Access Gmail emails and Google Calendar events",
      "requires_oauth": true,
      "oauth_url": "/api/auth/google/authorize",
      "is_available": true,
      "documentation_url": "https://docs.zylchai.com/integrations/google"
    }
    ```
    """
    try:
        with get_session() as session:
            row = session.query(IntegrationProvider).filter(
                IntegrationProvider.provider_key == provider_key
            ).first()

        if not row:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_key}' not found")

        return row.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get provider info for {provider_key}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get provider info: {str(e)}")


@router.get("/user/{owner_id}")
async def get_user_connection_list(owner_id: str):
    """
    Get list of user's active connections.

    **Path Parameters:**
    - `owner_id`: User's Firebase UID

    **Example Response:**
    ```json
    {
      "connections": [
        {
          "provider": "google",
          "email": "user@gmail.com",
          "connection_status": "connected",
          "last_sync": "2025-12-10T10:00:00Z",
          "created_at": "2025-12-01T00:00:00Z"
        }
      ]
    }
    ```
    """
    try:
        supabase = SupabaseStorage()
        connections = get_user_connections(supabase, owner_id)

        return {"connections": connections}

    except Exception as e:
        logger.error(f"Failed to get user connections for {owner_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get user connections: {str(e)}")


# ==========================================================
# UNIVERSAL CREDENTIALS ENDPOINTS (JSONB-based)
# ==========================================================

@router.post("/provider/{provider_key}/credentials", response_model=CredentialsResponse)
async def save_provider_credentials(
    provider_key: str,
    request: CredentialsSaveRequest,
    user: dict = Depends(get_current_user)
):
    """
    Save credentials for any provider using unified JSONB storage.

    This is the universal endpoint that works for ANY provider (Google, Anthropic,
    Pipedrive, Vonage, WhatsApp, Slack, etc.) without code changes.

    **Path Parameters:**
    - `provider_key`: Provider identifier (google, microsoft, anthropic, pipedrive, vonage, etc.)

    **Request Body:**
    ```json
    {
      "credentials": {
        "api_key": "abc123",
        "api_secret": "xyz789",
        "from_number": "+1234567890"
      },
      "metadata": {
        "scopes": ["read", "write"],
        "token_uri": "https://api.provider.com/token"
      }
    }
    ```

    **Example Usage:**

    **Vonage:**
    ```json
    POST /api/connections/provider/vonage/credentials
    {
      "credentials": {
        "api_key": "abc123",
        "api_secret": "xyz789",
        "from_number": "+1234567890"
      }
    }
    ```

    **Anthropic:**
    ```json
    POST /api/connections/provider/anthropic/credentials
    {
      "credentials": {
        "api_key": "sk-ant-api03-..."
      }
    }
    ```

    **WhatsApp (future):**
    ```json
    POST /api/connections/provider/whatsapp/credentials
    {
      "credentials": {
        "phone_id": "123456789",
        "access_token": "EAAG...",
        "business_account_id": "987654321"
      }
    }
    ```
    """
    owner_id = user['uid']
    try:
        supabase = SupabaseStorage()

        # Verify provider exists via ORM
        with get_session() as session:
            provider_row = session.query(IntegrationProvider).filter(
                IntegrationProvider.provider_key == provider_key
            ).first()

        if not provider_row:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_key}' not found")

        provider_info = provider_row.to_dict()

        # Check if provider is available
        if not provider_info['is_available']:
            raise HTTPException(
                status_code=400,
                detail=f"Provider '{provider_key}' is not yet available"
            )

        # Validate required fields from config_fields
        config_fields = provider_info.get('config_fields', {})
        missing_fields = []
        for field_name, field_config in config_fields.items():
            if field_config.get('required', False):
                if field_name not in request.credentials:
                    missing_fields.append(field_name)

        if missing_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required fields: {', '.join(missing_fields)}"
            )

        # Save credentials using unified storage
        success = supabase.save_provider_credentials(
            owner_id=owner_id,
            provider_key=provider_key,
            credentials_dict=request.credentials,
            metadata_dict=request.metadata
        )

        if success:
            logger.info(f"Saved credentials for {provider_key} for owner {owner_id}")
            return CredentialsResponse(
                success=True,
                provider=provider_key,
                status="connected",
                message=f"Successfully connected to {provider_info['display_name']}"
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to save credentials")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save credentials for {provider_key}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save credentials: {str(e)}")


@router.get("/provider/{provider_key}/credentials")
async def get_provider_credentials_endpoint(
    provider_key: str,
    user: dict = Depends(get_current_user),
    include_metadata: bool = Query(False, description="Include metadata in response")
):
    """
    Get credentials for a specific provider (decrypted).

    **Path Parameters:**
    - `provider_key`: Provider identifier

    **Query Parameters:**
    - `include_metadata`: Include metadata (scopes, token_uri, etc.)

    **Example Response:**
    ```json
    {
      "provider": "vonage",
      "credentials": {
        "api_key": "abc123",
        "api_secret": "xyz789",
        "from_number": "+1234567890"
      },
      "metadata": {
        "connected_at": "2025-12-10T10:00:00Z"
      }
    }
    ```

    **Note:** Sensitive fields are automatically decrypted.
    """
    owner_id = user['uid']
    try:
        supabase = SupabaseStorage()

        credentials = supabase.get_provider_credentials(
            owner_id=owner_id,
            provider_key=provider_key,
            include_metadata=include_metadata
        )

        if not credentials:
            raise HTTPException(
                status_code=404,
                detail=f"No credentials found for provider '{provider_key}'"
            )

        return {
            "provider": provider_key,
            "credentials": credentials
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get credentials for {provider_key}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get credentials: {str(e)}")


@router.delete("/provider/{provider_key}/credentials", response_model=CredentialsResponse)
async def delete_provider_credentials_endpoint(
    provider_key: str,
    user: dict = Depends(get_current_user)
):
    """
    Delete credentials for a specific provider.

    **Path Parameters:**
    - `provider_key`: Provider identifier

    **Example Response:**
    ```json
    {
      "success": true,
      "provider": "vonage",
      "status": "disconnected",
      "message": "Successfully disconnected from Vonage SMS"
    }
    ```
    """
    owner_id = user['uid']
    try:
        supabase = SupabaseStorage()

        # Get provider info for display name via ORM
        with get_session() as session:
            provider_row = session.query(IntegrationProvider.display_name).filter(
                IntegrationProvider.provider_key == provider_key
            ).first()

        provider_name = provider_row[0] if provider_row else provider_key

        # Delete credentials
        success = supabase.delete_provider_credentials(owner_id, provider_key)

        if success:
            logger.info(f"Deleted credentials for {provider_key} for owner {owner_id}")
            return CredentialsResponse(
                success=True,
                provider=provider_key,
                status="disconnected",
                message=f"Successfully disconnected from {provider_name}"
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to delete credentials")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete credentials for {provider_key}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete credentials: {str(e)}")
