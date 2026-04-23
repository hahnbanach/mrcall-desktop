"""Tests for MrCall OAuth 2.0 integration with PKCE.

Tests cover:
- PKCE code verifier/challenge generation
- OAuth endpoints (authorize, callback, status, revoke)
- Token storage and retrieval
- Token refresh logic
- Error handling and validation
"""

import base64
import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import httpx

# =============================================================================
# Test PKCE Functions
# =============================================================================


class TestPKCEGeneration:
    """Tests for PKCE code verifier and challenge generation."""

    def test_generate_code_verifier_length(self):
        """Test code verifier has valid length (43-128 chars)."""
        from zylch.api.routes.auth import generate_code_verifier

        verifier = generate_code_verifier()

        assert isinstance(verifier, str)
        assert 43 <= len(verifier) <= 128
        # URL-safe base64 should not contain '='
        assert "=" not in verifier

    def test_generate_code_verifier_uniqueness(self):
        """Test code verifiers are unique."""
        from zylch.api.routes.auth import generate_code_verifier

        verifier1 = generate_code_verifier()
        verifier2 = generate_code_verifier()

        assert verifier1 != verifier2

    def test_generate_code_challenge(self):
        """Test code challenge is correct SHA256 hash of verifier."""
        from zylch.api.routes.auth import generate_code_challenge

        verifier = "test_verifier_12345678901234567890123456789012"
        challenge = generate_code_challenge(verifier)

        # Manually compute expected challenge
        expected_digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).decode("utf-8").rstrip("=")

        assert challenge == expected_challenge
        assert "=" not in challenge

    def test_code_verifier_challenge_roundtrip(self):
        """Test verifier/challenge pair can be validated."""
        from zylch.api.routes.auth import generate_code_verifier, generate_code_challenge

        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)

        # Re-compute challenge from verifier and compare
        recomputed_challenge = generate_code_challenge(verifier)
        assert challenge == recomputed_challenge


# =============================================================================
# Test OAuth Endpoints
# =============================================================================


class TestMrCallOAuthEndpoints:
    """Tests for MrCall OAuth authorization endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client with mocked dependencies."""
        from zylch.api.main import app

        return TestClient(app)

    @pytest.fixture
    def mock_firebase_user(self):
        """Mock Firebase user token data."""
        return {
            "uid": "test_user_123",
            "email": "test@example.com",
            "name": "Test User",
            "token": "mock_firebase_token",
        }

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for OAuth."""
        return {
            "mrcall_client_id": "test_client_id",
            "mrcall_client_secret": "test_client_secret",
            "mrcall_base_url": "https://api.starchat.com",
            "mrcall_realm": "mrcall0",
        }

    @patch("zylch.api.routes.auth.get_current_user")
    @patch("zylch.api.routes.auth._get_storage")
    @patch("zylch.api.routes.auth.settings")
    def test_mrcall_authorize_returns_auth_url(
        self, mock_settings, mock_storage, mock_get_user, client, mock_firebase_user
    ):
        """Test /mrcall/authorize returns OAuth URL with correct parameters."""
        # Setup mocks
        mock_get_user.return_value = mock_firebase_user
        mock_settings.mrcall_client_id = "test_client_id"
        mock_settings.mrcall_client_secret = "test_client_secret"
        mock_settings.mrcall_base_url = "https://api.starchat.com"
        mock_settings.mrcall_realm = "mrcall0"

        storage_mock = MagicMock()
        storage_mock.store_oauth_state = MagicMock()
        mock_storage.return_value = storage_mock

        # Make request
        response = client.get(
            "/api/auth/mrcall/authorize", headers={"Authorization": "Bearer mock_firebase_token"}
        )

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "state" in data

        # Verify auth_url contains required OAuth parameters
        auth_url = data["auth_url"]
        assert "https://api.starchat.com/oauth/authorize" in auth_url
        assert "client_id=test_client_id" in auth_url
        assert "redirect_uri=http://localhost:8765/callback" in auth_url
        assert "response_type=code" in auth_url
        assert "scope=business:read+contacts:read" in auth_url
        assert f'state={data["state"]}' in auth_url
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url

        # Verify state was stored
        storage_mock.store_oauth_state.assert_called_once()
        call_args = storage_mock.store_oauth_state.call_args
        assert call_args[1]["state"] == data["state"]
        assert call_args[1]["owner_id"] == "test_user_123"
        assert call_args[1]["provider"] == "mrcall"
        assert "code_verifier" in call_args[1]["metadata"]

    @patch("zylch.api.routes.auth.get_current_user")
    @patch("zylch.api.routes.auth.settings")
    def test_mrcall_authorize_missing_credentials(
        self, mock_settings, mock_get_user, client, mock_firebase_user
    ):
        """Test /mrcall/authorize fails when OAuth credentials not configured."""
        mock_get_user.return_value = mock_firebase_user
        mock_settings.mrcall_client_id = None
        mock_settings.mrcall_client_secret = None

        response = client.get(
            "/api/auth/mrcall/authorize", headers={"Authorization": "Bearer mock_firebase_token"}
        )

        assert response.status_code == 500
        assert "not configured" in response.json()["detail"].lower()

    @patch("zylch.api.routes.auth._get_storage")
    @patch("zylch.api.routes.auth.settings")
    @patch("zylch.api.routes.auth.fetch_mrcall_business_id")
    def test_mrcall_callback_success(
        self, mock_fetch_business, mock_settings, mock_storage, client
    ):
        """Test /mrcall/callback successfully exchanges code for tokens."""
        # Setup mocks
        mock_settings.mrcall_base_url = "https://api.starchat.com"
        mock_settings.mrcall_client_id = "test_client_id"
        mock_settings.mrcall_client_secret = "test_client_secret"
        mock_settings.mrcall_realm = "mrcall0"

        # Mock storage to return valid state
        storage_mock = MagicMock()
        storage_mock.get_oauth_state.return_value = {
            "owner_id": "test_user_123",
            "email": "test@example.com",
            "provider": "mrcall",
            "metadata": {"code_verifier": "test_verifier_12345678901234567890"},
        }
        mock_storage.return_value = storage_mock

        # Mock business_id fetch
        mock_fetch_business.return_value = "business_123"

        # Mock token exchange HTTP request
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "mock_access_token",
                "refresh_token": "mock_refresh_token",
                "expires_in": 3600,
                "token_type": "Bearer",
            }

            mock_http = AsyncMock()
            mock_http.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http

            with patch("zylch.api.token_storage.save_mrcall_credentials") as mock_save:
                # Make callback request
                response = client.get(
                    "/api/auth/mrcall/callback",
                    params={"code": "auth_code_123", "state": "valid_state_token"},
                )

                # Verify response
                assert response.status_code == 200
                assert "MrCall" in response.text

                # Verify tokens were saved
                mock_save.assert_called_once()
                call_args = mock_save.call_args[1]
                assert call_args["owner_id"] == "test_user_123"
                assert call_args["access_token"] == "mock_access_token"
                assert call_args["refresh_token"] == "mock_refresh_token"
                assert call_args["business_id"] == "business_123"

    @patch("zylch.api.routes.auth._get_storage")
    def test_mrcall_callback_invalid_state(self, mock_storage, client):
        """Test /mrcall/callback rejects invalid state parameter."""
        # Mock storage to return None (invalid state)
        storage_mock = MagicMock()
        storage_mock.get_oauth_state.return_value = None
        mock_storage.return_value = storage_mock

        response = client.get(
            "/api/auth/mrcall/callback", params={"code": "auth_code_123", "state": "invalid_state"}
        )

        assert response.status_code == 200  # HTML error page
        assert "Invalid or expired state" in response.text

    def test_mrcall_callback_missing_parameters(self, client):
        """Test /mrcall/callback rejects missing code or state."""
        # Missing code
        response = client.get("/api/auth/mrcall/callback", params={"state": "some_state"})
        assert response.status_code == 200
        assert "Missing code or state" in response.text

        # Missing state
        response = client.get("/api/auth/mrcall/callback", params={"code": "some_code"})
        assert response.status_code == 200
        assert "Missing code or state" in response.text

    def test_mrcall_callback_oauth_error(self, client):
        """Test /mrcall/callback handles OAuth error responses."""
        response = client.get(
            "/api/auth/mrcall/callback",
            params={"error": "access_denied", "error_description": "User cancelled authorization"},
        )

        assert response.status_code == 200
        assert "MrCall OAuth failed" in response.text
        assert "access_denied" in response.text

    @patch("zylch.api.routes.auth.get_current_user")
    @patch("zylch.api.token_storage.get_mrcall_credentials")
    def test_mrcall_status_connected(
        self, mock_get_creds, mock_get_user, client, mock_firebase_user
    ):
        """Test /mrcall/status returns connection status when connected."""
        mock_get_user.return_value = mock_firebase_user

        # Mock credentials exist and are valid
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_get_creds.return_value = {
            "access_token": "mock_token",
            "business_id": "business_123",
            "realm": "mrcall0",
            "scopes": ["business:read", "contacts:read"],
            "expires_at": expires_at.isoformat(),
        }

        response = client.get(
            "/api/auth/mrcall/status", headers={"Authorization": "Bearer mock_firebase_token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["has_credentials"] is True
        assert data["business_id"] == "business_123"
        assert data["realm"] == "mrcall0"
        assert data["expired"] is False

    @patch("zylch.api.routes.auth.get_current_user")
    @patch("zylch.api.token_storage.get_mrcall_credentials")
    def test_mrcall_status_not_connected(
        self, mock_get_creds, mock_get_user, client, mock_firebase_user
    ):
        """Test /mrcall/status returns false when not connected."""
        mock_get_user.return_value = mock_firebase_user
        mock_get_creds.return_value = None

        response = client.get(
            "/api/auth/mrcall/status", headers={"Authorization": "Bearer mock_firebase_token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is False
        assert data["has_credentials"] is False

    @patch("zylch.api.routes.auth.get_current_user")
    @patch("zylch.api.token_storage.get_mrcall_credentials")
    def test_mrcall_status_expired_token(
        self, mock_get_creds, mock_get_user, client, mock_firebase_user
    ):
        """Test /mrcall/status detects expired tokens."""
        mock_get_user.return_value = mock_firebase_user

        # Mock expired credentials
        expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_get_creds.return_value = {
            "access_token": "mock_token",
            "expires_at": expires_at.isoformat(),
        }

        response = client.get(
            "/api/auth/mrcall/status", headers={"Authorization": "Bearer mock_firebase_token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["expired"] is True

    @patch("zylch.api.routes.auth.get_current_user")
    @patch("zylch.api.token_storage.get_mrcall_credentials")
    @patch("zylch.api.token_storage.delete_mrcall_credentials")
    def test_mrcall_revoke_success(
        self, mock_delete, mock_get_creds, mock_get_user, client, mock_firebase_user
    ):
        """Test /mrcall/revoke deletes credentials."""
        mock_get_user.return_value = mock_firebase_user
        mock_get_creds.return_value = {"access_token": "mock_token"}
        mock_delete.return_value = True

        with patch("httpx.AsyncClient") as mock_client:
            # Mock revoke endpoint call
            mock_response = AsyncMock()
            mock_response.status_code = 200

            mock_http = AsyncMock()
            mock_http.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http

            response = client.post(
                "/api/auth/mrcall/revoke", headers={"Authorization": "Bearer mock_firebase_token"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "disconnected" in data["message"].lower()

            # Verify delete was called
            mock_delete.assert_called_once_with("test_user_123")


# =============================================================================
# Test Token Storage
# =============================================================================


class TestMrCallTokenStorage:
    """Tests for MrCall token storage functions."""

    @pytest.fixture
    def mock_supabase(self):
        """Mock Storage."""
        with patch("zylch.api.token_storage._get_supabase") as mock:
            storage = MagicMock()
            mock.return_value = storage
            yield storage

    def test_save_mrcall_credentials(self, mock_supabase):
        """Test save_mrcall_credentials stores tokens with metadata."""
        from zylch.api.token_storage import save_mrcall_credentials

        save_mrcall_credentials(
            owner_id="test_user_123",
            access_token="access_token_abc",
            refresh_token="refresh_token_xyz",
            expires_in=3600,
            token_type="Bearer",
            business_id="business_123",
            target_owner="target_uid",
            realm="mrcall0",
        )

        # Verify storage was called
        mock_supabase.save_provider_credentials.assert_called_once()
        call_args = mock_supabase.save_provider_credentials.call_args[1]

        assert call_args["owner_id"] == "test_user_123"
        assert call_args["provider_key"] == "mrcall"

        # Check credentials dict
        creds = call_args["credentials_dict"]
        assert creds["access_token"] == "access_token_abc"
        assert creds["refresh_token"] == "refresh_token_xyz"
        assert creds["business_id"] == "business_123"

        # Check metadata dict
        metadata = call_args["metadata_dict"]
        assert "expires_at" in metadata
        assert metadata["scopes"] == ["business:read", "contacts:read"]
        assert metadata["realm"] == "mrcall0"

    def test_get_mrcall_credentials(self, mock_supabase):
        """Test get_mrcall_credentials retrieves stored tokens."""
        from zylch.api.token_storage import get_mrcall_credentials

        # Mock stored credentials
        mock_supabase.get_provider_credentials.return_value = {
            "access_token": "stored_access_token",
            "refresh_token": "stored_refresh_token",
            "business_id": "business_456",
        }

        result = get_mrcall_credentials("test_user_123")

        assert result is not None
        assert result["access_token"] == "stored_access_token"
        assert result["refresh_token"] == "stored_refresh_token"
        assert result["business_id"] == "business_456"

        mock_supabase.get_provider_credentials.assert_called_once_with(
            owner_id="test_user_123", provider_key="mrcall", include_metadata=True
        )

    def test_get_mrcall_credentials_not_found(self, mock_supabase):
        """Test get_mrcall_credentials returns None when not found."""
        from zylch.api.token_storage import get_mrcall_credentials

        mock_supabase.get_provider_credentials.return_value = None

        result = get_mrcall_credentials("nonexistent_user")

        assert result is None

    def test_delete_mrcall_credentials(self, mock_supabase):
        """Test delete_mrcall_credentials removes tokens."""
        from zylch.api.token_storage import delete_mrcall_credentials

        mock_supabase.delete_provider_credentials.return_value = True

        result = delete_mrcall_credentials("test_user_123")

        assert result is True
        mock_supabase.delete_provider_credentials.assert_called_once_with("test_user_123", "mrcall")


# =============================================================================
# Test Token Refresh
# =============================================================================


class TestMrCallTokenRefresh:
    """Tests for automatic token refresh logic."""

    @pytest.fixture
    def mock_credentials(self):
        """Mock stored credentials."""
        return {
            "access_token": "old_access_token",
            "refresh_token": "refresh_token_xyz",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat(),
            "business_id": "business_123",
            "realm": "mrcall0",
        }

    @pytest.mark.asyncio
    async def test_refresh_mrcall_token_success(self, mock_credentials):
        """Test successful token refresh."""
        from zylch.api.token_storage import refresh_mrcall_token

        with patch("zylch.api.token_storage.get_mrcall_credentials") as mock_get:
            with patch("zylch.api.token_storage.save_mrcall_credentials") as mock_save:
                with patch("zylch.api.token_storage.settings") as mock_settings:
                    with patch("httpx.AsyncClient") as mock_client:
                        mock_get.return_value = mock_credentials
                        mock_settings.mrcall_base_url = "https://api.starchat.com"
                        mock_settings.mrcall_client_id = "client_id"
                        mock_settings.mrcall_client_secret = "client_secret"
                        mock_settings.mrcall_realm = "mrcall0"

                        # Mock token refresh response
                        mock_response = AsyncMock()
                        mock_response.status_code = 200
                        mock_response.json.return_value = {
                            "access_token": "new_access_token",
                            "refresh_token": "new_refresh_token",
                            "expires_in": 3600,
                        }

                        mock_http = AsyncMock()
                        mock_http.__aenter__.return_value.post = AsyncMock(
                            return_value=mock_response
                        )
                        mock_client.return_value = mock_http

                        # Trigger refresh
                        await refresh_mrcall_token("test_user_123")

                        # Verify new credentials were saved
                        mock_save.assert_called_once()
                        call_args = mock_save.call_args[1]
                        assert call_args["access_token"] == "new_access_token"
                        assert call_args["owner_id"] == "test_user_123"

    @pytest.mark.asyncio
    async def test_refresh_mrcall_token_no_refresh_token(self):
        """Test refresh fails when no refresh token available."""
        from zylch.api.token_storage import refresh_mrcall_token

        with patch("zylch.api.token_storage.get_mrcall_credentials") as mock_get:
            # No refresh token in credentials
            mock_get.return_value = {"access_token": "access_token", "refresh_token": None}

            result = await refresh_mrcall_token("test_user_123")

            assert result is None

    @pytest.mark.asyncio
    async def test_refresh_mrcall_token_api_error(self, mock_credentials):
        """Test refresh handles API errors gracefully."""
        from zylch.api.token_storage import refresh_mrcall_token

        with patch("zylch.api.token_storage.get_mrcall_credentials") as mock_get:
            with patch("zylch.api.token_storage.settings") as mock_settings:
                with patch("httpx.AsyncClient") as mock_client:
                    mock_get.return_value = mock_credentials
                    mock_settings.mrcall_base_url = "https://api.starchat.com"
                    mock_settings.mrcall_client_id = "client_id"
                    mock_settings.mrcall_client_secret = "client_secret"

                    # Mock failed refresh response
                    mock_response = AsyncMock()
                    mock_response.status_code = 401

                    mock_http = AsyncMock()
                    mock_http.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
                    mock_client.return_value = mock_http

                    result = await refresh_mrcall_token("test_user_123")

                    assert result is None

    @pytest.mark.asyncio
    async def test_starchat_client_auto_refresh(self):
        """Test StarChat client automatically refreshes expiring tokens."""
        from zylch.tools.starchat import StarChatClient

        # Create client with OAuth auth
        expires_soon = datetime.now(timezone.utc) + timedelta(minutes=3)
        client = StarChatClient(
            base_url="https://api.starchat.com",
            auth_type="oauth",
            access_token="old_token",
            owner_id="test_user_123",
            realm="mrcall0",
        )

        # Mock token storage
        mock_storage = MagicMock()
        client.supabase = mock_storage

        with patch("zylch.tools.starchat.get_mrcall_credentials") as mock_get:
            with patch("zylch.tools.starchat.refresh_mrcall_token") as mock_refresh:
                # Mock credentials expiring soon
                mock_get.return_value = {
                    "access_token": "old_token",
                    "refresh_token": "refresh_token",
                    "expires_at": expires_soon.isoformat(),
                }

                # Mock successful refresh
                mock_refresh.return_value = {
                    "access_token": "new_token",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                }

                # Trigger refresh check
                await client._refresh_token_if_needed()

                # Verify refresh was called
                mock_refresh.assert_called_once_with("test_user_123")

                # Verify client token was updated
                assert client.access_token == "new_token"

    @pytest.mark.asyncio
    async def test_starchat_client_no_refresh_if_valid(self):
        """Test StarChat client skips refresh if token is valid."""
        from zylch.tools.starchat import StarChatClient

        # Token valid for 2 hours
        expires_later = datetime.now(timezone.utc) + timedelta(hours=2)

        client = StarChatClient(
            base_url="https://api.starchat.com",
            auth_type="oauth",
            access_token="valid_token",
            owner_id="test_user_123",
            realm="mrcall0",
        )

        mock_storage = MagicMock()
        client.supabase = mock_storage

        with patch("zylch.tools.starchat.get_mrcall_credentials") as mock_get:
            with patch("zylch.tools.starchat.refresh_mrcall_token") as mock_refresh:
                mock_get.return_value = {
                    "access_token": "valid_token",
                    "expires_at": expires_later.isoformat(),
                }

                # Trigger refresh check
                await client._refresh_token_if_needed()

                # Verify refresh was NOT called
                mock_refresh.assert_not_called()


# =============================================================================
# Test Error Handling
# =============================================================================


class TestMrCallOAuthErrorHandling:
    """Tests for error handling in OAuth flow."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from zylch.api.main import app

        return TestClient(app)

    @patch("zylch.api.routes.auth.get_current_user")
    def test_authorize_requires_authentication(self, mock_get_user, client):
        """Test /mrcall/authorize requires valid Firebase token."""
        mock_get_user.side_effect = Exception("Invalid token")

        response = client.get("/api/auth/mrcall/authorize")

        # FastAPI will return 401 or 500 depending on exception handling
        assert response.status_code in [401, 500]

    @patch("zylch.api.routes.auth._get_storage")
    @patch("zylch.api.routes.auth.settings")
    def test_callback_wrong_provider(self, mock_settings, mock_storage, client):
        """Test /mrcall/callback rejects state from different provider."""
        mock_settings.mrcall_base_url = "https://api.starchat.com"

        # State is for Google OAuth, not MrCall
        storage_mock = MagicMock()
        storage_mock.get_oauth_state.return_value = {
            "owner_id": "test_user",
            "provider": "google",  # Wrong provider!
            "metadata": {},
        }
        mock_storage.return_value = storage_mock

        response = client.get(
            "/api/auth/mrcall/callback", params={"code": "code123", "state": "state123"}
        )

        assert response.status_code == 200
        assert "Invalid or expired state" in response.text

    @patch("zylch.api.routes.auth._get_storage")
    @patch("zylch.api.routes.auth.settings")
    def test_callback_missing_code_verifier(self, mock_settings, mock_storage, client):
        """Test /mrcall/callback fails if code_verifier missing."""
        mock_settings.mrcall_base_url = "https://api.starchat.com"

        # State without code_verifier
        storage_mock = MagicMock()
        storage_mock.get_oauth_state.return_value = {
            "owner_id": "test_user",
            "provider": "mrcall",
            "metadata": {},  # No code_verifier!
        }
        mock_storage.return_value = storage_mock

        response = client.get(
            "/api/auth/mrcall/callback", params={"code": "code123", "state": "state123"}
        )

        assert response.status_code == 200
        assert "Invalid state data" in response.text

    @pytest.mark.asyncio
    async def test_token_refresh_network_error(self):
        """Test token refresh handles network failures."""
        from zylch.api.token_storage import refresh_mrcall_token

        with patch("zylch.api.token_storage.get_mrcall_credentials") as mock_get:
            with patch("zylch.api.token_storage.settings") as mock_settings:
                with patch("httpx.AsyncClient") as mock_client:
                    mock_get.return_value = {
                        "refresh_token": "refresh_token",
                        "expires_at": datetime.now(timezone.utc).isoformat(),
                    }
                    mock_settings.mrcall_base_url = "https://api.starchat.com"

                    # Simulate network error
                    mock_http = AsyncMock()
                    mock_http.__aenter__.return_value.post = AsyncMock(
                        side_effect=httpx.ConnectError("Network unreachable")
                    )
                    mock_client.return_value = mock_http

                    result = await refresh_mrcall_token("test_user_123")

                    assert result is None
