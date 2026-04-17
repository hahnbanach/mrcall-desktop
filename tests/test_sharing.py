"""Tests for the intelligence sharing system."""

import pytest
from unittest.mock import MagicMock

from zylch.sharing.authorization import SharingAuthorizationManager
from zylch.sharing.intel_share import IntelShareManager, SharedIntel


class TestSharingAuthorizationManager:
    """Tests for SharingAuthorizationManager."""

    @pytest.fixture
    def auth_manager(self, tmp_path):
        """Create a fresh auth manager with temp database."""
        db_path = tmp_path / "test_sharing.db"
        return SharingAuthorizationManager(db_path=db_path)

    def test_register_user(self, auth_manager):
        """Test user registration."""
        result = auth_manager.register_user(
            owner_id="mario_owner", email="mario@azienda.com", display_name="Mario Rossi"
        )
        assert result is True

        # Verify user was registered
        user = auth_manager.get_user_by_email("mario@azienda.com")
        assert user is not None
        assert user["owner_id"] == "mario_owner"
        assert user["display_name"] == "Mario Rossi"

    def test_register_user_case_insensitive(self, auth_manager):
        """Test that email lookup is case-insensitive."""
        auth_manager.register_user(
            owner_id="mario_owner", email="MARIO@Azienda.COM", display_name="Mario Rossi"
        )

        user = auth_manager.get_user_by_email("mario@azienda.com")
        assert user is not None

    def test_register_recipient_success(self, auth_manager):
        """Test registering a recipient for sharing."""
        # Register both users first
        auth_manager.register_user("mario_owner", "mario@azienda.com", "Mario")
        auth_manager.register_user("luigi_owner", "luigi@azienda.com", "Luigi")

        success, msg = auth_manager.register_recipient(
            sender_email="mario@azienda.com", recipient_email="luigi@azienda.com"
        )

        assert success is True
        assert "Luigi" in msg

    def test_register_recipient_not_zylch_user(self, auth_manager):
        """Test registering a non-Zylch user fails."""
        auth_manager.register_user("mario_owner", "mario@azienda.com", "Mario")

        success, msg = auth_manager.register_recipient(
            sender_email="mario@azienda.com", recipient_email="unknown@other.com"
        )

        assert success is False
        assert "non è un utente Zylch" in msg

    def test_authorization_workflow(self, auth_manager):
        """Test complete authorization workflow: register -> accept."""
        # Setup users
        auth_manager.register_user("mario_owner", "mario@azienda.com", "Mario")
        auth_manager.register_user("luigi_owner", "luigi@azienda.com", "Luigi")

        # Mario registers Luigi as recipient
        success, _ = auth_manager.register_recipient(
            sender_email="mario@azienda.com", recipient_email="luigi@azienda.com"
        )
        assert success

        # Check status is pending
        status = auth_manager.get_authorization_status("mario@azienda.com", "luigi@azienda.com")
        assert status == "pending"

        # Luigi accepts
        success, msg = auth_manager.accept_authorization(
            recipient_email="luigi@azienda.com", sender_email="mario@azienda.com"
        )
        assert success
        assert "Accettato" in msg

        # Verify is_authorized
        assert auth_manager.is_authorized("mario@azienda.com", "luigi@azienda.com")

    def test_revoke_authorization(self, auth_manager):
        """Test revoking authorization."""
        # Setup and accept
        auth_manager.register_user("mario_owner", "mario@azienda.com", "Mario")
        auth_manager.register_user("luigi_owner", "luigi@azienda.com", "Luigi")
        auth_manager.register_recipient("mario@azienda.com", "luigi@azienda.com")
        auth_manager.accept_authorization("luigi@azienda.com", "mario@azienda.com")

        # Verify authorized
        assert auth_manager.is_authorized("mario@azienda.com", "luigi@azienda.com")

        # Revoke
        success, _ = auth_manager.revoke_authorization(
            recipient_email="luigi@azienda.com", sender_email="mario@azienda.com"
        )
        assert success

        # Verify no longer authorized
        assert not auth_manager.is_authorized("mario@azienda.com", "luigi@azienda.com")

    def test_list_authorized_senders(self, auth_manager):
        """Test listing authorized senders."""
        # Setup multiple senders
        auth_manager.register_user("luigi_owner", "luigi@azienda.com", "Luigi")
        auth_manager.register_user("mario_owner", "mario@azienda.com", "Mario")
        auth_manager.register_user("anna_owner", "anna@azienda.com", "Anna")

        # Both Mario and Anna want to share with Luigi
        auth_manager.register_recipient("mario@azienda.com", "luigi@azienda.com")
        auth_manager.register_recipient("anna@azienda.com", "luigi@azienda.com")

        # Luigi accepts both
        auth_manager.accept_authorization("luigi@azienda.com", "mario@azienda.com")
        auth_manager.accept_authorization("luigi@azienda.com", "anna@azienda.com")

        # Check list
        senders = auth_manager.list_authorized_senders("luigi@azienda.com")
        assert len(senders) == 2
        emails = [s["sender_email"] for s in senders]
        assert "mario@azienda.com" in emails
        assert "anna@azienda.com" in emails

    def test_pending_shares(self, auth_manager):
        """Test pending shares functionality."""
        auth_manager.register_user("mario_owner", "mario@azienda.com", "Mario")
        auth_manager.register_user("luigi_owner", "luigi@azienda.com", "Luigi")
        auth_manager.register_recipient("mario@azienda.com", "luigi@azienda.com")

        # Add pending share
        success, _ = auth_manager.add_pending_share(
            sender_email="mario@azienda.com",
            recipient_email="luigi@azienda.com",
            intel_context="Marco Ferrari ha firmato il contratto",
            identifiers={"email": "marco@ferrari.it", "name": "Marco Ferrari"},
        )
        assert success

        # Check pending requests
        pending = auth_manager.get_pending_requests("luigi@azienda.com")
        assert len(pending) == 1
        assert pending[0]["intel_context"] == "Marco Ferrari ha firmato il contratto"
        assert pending[0]["identifiers"]["name"] == "Marco Ferrari"


class TestIntelShareManager:
    """Tests for IntelShareManager."""

    @pytest.fixture
    def mock_memory(self):
        """Create mock ZylchMemory."""
        memory = MagicMock()
        memory.store_memory.return_value = "123"
        memory.retrieve_memories.return_value = []
        return memory

    @pytest.fixture
    def auth_manager(self, tmp_path):
        """Create auth manager with temp database."""
        db_path = tmp_path / "test_sharing.db"
        auth = SharingAuthorizationManager(db_path=db_path)
        # Setup users
        auth.register_user("mario_owner", "mario@azienda.com", "Mario")
        auth.register_user("luigi_owner", "luigi@azienda.com", "Luigi")
        return auth

    @pytest.fixture
    def intel_manager(self, mock_memory, auth_manager):
        """Create intel share manager."""
        return IntelShareManager(zylch_memory=mock_memory, auth_manager=auth_manager)

    def test_share_intel_success(self, intel_manager, auth_manager):
        """Test successful intel sharing."""
        # Setup authorization
        auth_manager.register_recipient("mario@azienda.com", "luigi@azienda.com")
        auth_manager.accept_authorization("luigi@azienda.com", "mario@azienda.com")

        # Share intel
        success, msg = intel_manager.share_intel(
            sender_owner_id="mario_owner",
            sender_email="mario@azienda.com",
            recipient_owner_id="luigi_owner",
            recipient_email="luigi@azienda.com",
            context="Marco Ferrari ha firmato il contratto",
            identifiers={"email": "marco@ferrari.it", "name": "Marco Ferrari"},
            sender_display_name="Mario",
        )

        assert success
        assert "Condiviso" in msg

    def test_share_intel_not_authorized(self, intel_manager, auth_manager):
        """Test sharing without authorization goes to pending."""
        # No authorization set up

        success, msg = intel_manager.share_intel(
            sender_owner_id="mario_owner",
            sender_email="mario@azienda.com",
            recipient_owner_id="luigi_owner",
            recipient_email="luigi@azienda.com",
            context="Marco Ferrari ha firmato il contratto",
            identifiers={"email": "marco@ferrari.it"},
        )

        # Should fail because not even registered
        assert success is False
        assert "/share" in msg

    def test_share_intel_pending(self, intel_manager, auth_manager):
        """Test sharing with pending authorization."""
        # Register but don't accept
        auth_manager.register_recipient("mario@azienda.com", "luigi@azienda.com")

        success, msg = intel_manager.share_intel(
            sender_owner_id="mario_owner",
            sender_email="mario@azienda.com",
            recipient_owner_id="luigi_owner",
            recipient_email="luigi@azienda.com",
            context="Marco Ferrari ha firmato il contratto",
            identifiers={"email": "marco@ferrari.it"},
        )

        assert success
        assert "attesa" in msg.lower()

    def test_process_accepted_authorization(self, intel_manager, auth_manager, mock_memory):
        """Test processing pending shares after acceptance."""
        # Register and add pending share
        auth_manager.register_recipient("mario@azienda.com", "luigi@azienda.com")
        auth_manager.add_pending_share(
            sender_email="mario@azienda.com",
            recipient_email="luigi@azienda.com",
            intel_context="Marco Ferrari ha firmato il contratto",
            identifiers={"email": "marco@ferrari.it"},
        )

        # Accept authorization
        auth_manager.accept_authorization("luigi@azienda.com", "mario@azienda.com")

        # Process pending shares
        processed = intel_manager.process_accepted_authorization(
            recipient_owner_id="luigi_owner",
            recipient_email="luigi@azienda.com",
            sender_email="mario@azienda.com",
        )

        assert processed == 1
        # Memory store should have been called
        mock_memory.store_memory.assert_called()

    def test_namespace_format(self, intel_manager):
        """Test namespace format is correct."""
        namespace = intel_manager._make_namespace("luigi_owner", "mario_owner")
        assert namespace == "shared:luigi_owner:mario_owner"

    def test_identifier_matching_email(self, intel_manager):
        """Test identifier matching by email."""
        search = {"email": "marco@ferrari.it"}
        stored = {"email": "Marco@Ferrari.it", "name": "Marco Ferrari"}

        assert intel_manager._identifiers_match(search, stored)

    def test_identifier_matching_phone(self, intel_manager):
        """Test identifier matching by phone."""
        search = {"phone": "+39 333 1234567"}
        stored = {"phone": "3331234567", "name": "Marco Ferrari"}

        assert intel_manager._identifiers_match(search, stored)

    def test_identifier_not_matching(self, intel_manager):
        """Test identifier not matching."""
        search = {"email": "other@email.com"}
        stored = {"email": "marco@ferrari.it"}

        assert not intel_manager._identifiers_match(search, stored)


class TestSharedIntel:
    """Tests for SharedIntel dataclass."""

    def test_to_dict(self):
        """Test SharedIntel conversion to dict."""
        intel = SharedIntel(
            memory_id="123",
            context="Marco Ferrari ha firmato il contratto",
            identifiers={"email": "marco@ferrari.it"},
            sender_owner_id="mario_owner",
            sender_email="mario@azienda.com",
            sender_display_name="Mario",
            shared_at="2025-11-28T15:00:00Z",
            confidence=1.0,
            similarity=0.95,
        )

        d = intel.to_dict()

        assert d["memory_id"] == "123"
        assert d["context"] == "Marco Ferrari ha firmato il contratto"
        assert d["sender_email"] == "mario@azienda.com"
        assert d["similarity"] == 0.95


@pytest.mark.asyncio
class TestSharingTools:
    """Tests for sharing tools."""

    @pytest.fixture
    def mock_intel_manager(self):
        """Create mock IntelShareManager."""
        manager = MagicMock()
        manager.share_intel.return_value = (True, "Condiviso con luigi@azienda.com")
        manager.get_shared_intel.return_value = []
        return manager

    @pytest.fixture
    def mock_auth_manager(self):
        """Create mock SharingAuthorizationManager."""
        manager = MagicMock()
        manager.list_authorized_recipients.return_value = []
        manager.list_pending_registrations.return_value = []
        manager.get_user_by_email.return_value = {
            "owner_id": "luigi_owner",
            "email": "luigi@azienda.com",
            "display_name": "Luigi",
        }
        manager.get_pending_requests.return_value = []
        return manager

    async def test_share_contact_intel_tool(self, mock_intel_manager, mock_auth_manager):
        """Test ShareContactIntelTool execution."""
        from zylch.tools.sharing_tools import ShareContactIntelTool

        tool = ShareContactIntelTool(
            intel_share_manager=mock_intel_manager,
            auth_manager=mock_auth_manager,
            owner_id="mario_owner",
            user_email="mario@azienda.com",
            user_display_name="Mario",
        )

        result = await tool.execute(
            recipient_email="luigi@azienda.com",
            intel="Marco Ferrari ha firmato il contratto",
            contact_name="Marco Ferrari",
            contact_email="marco@ferrari.it",
        )

        assert result.status.value == "success"
        assert result.data["shared"] is True

    async def test_get_shared_intel_tool(self, mock_intel_manager, mock_auth_manager):
        """Test GetSharedIntelTool execution."""
        from zylch.tools.sharing_tools import GetSharedIntelTool

        mock_intel_manager.get_shared_intel.return_value = [
            SharedIntel(
                memory_id="123",
                context="Test intel",
                identifiers={"email": "test@test.com"},
                sender_owner_id="other_owner",
                sender_email="other@email.com",
                sender_display_name="Other",
                shared_at="2025-11-28T15:00:00Z",
            )
        ]

        tool = GetSharedIntelTool(
            intel_share_manager=mock_intel_manager,
            owner_id="mario_owner",
            user_email="mario@azienda.com",
        )

        result = await tool.execute(contact_email="test@test.com")

        assert result.status.value == "success"
        assert result.data["count"] == 1

    async def test_accept_share_request_tool(self, mock_intel_manager, mock_auth_manager):
        """Test AcceptShareRequestTool execution."""
        from zylch.tools.sharing_tools import AcceptShareRequestTool

        mock_auth_manager.get_pending_requests.return_value = [
            {
                "sender_email": "other@email.com",
                "sender_display_name": "Other",
                "intel_context": "Test intel",
            }
        ]
        mock_auth_manager.accept_authorization.return_value = (True, "Accettato")
        mock_intel_manager.process_accepted_authorization.return_value = 1

        tool = AcceptShareRequestTool(
            intel_share_manager=mock_intel_manager,
            auth_manager=mock_auth_manager,
            owner_id="mario_owner",
            user_email="mario@azienda.com",
        )

        result = await tool.execute()

        assert result.status.value == "success"
        assert result.data["accepted"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
