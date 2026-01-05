"""Intelligence sharing manager for Zylch.

Handles the actual sharing and retrieval of contact intelligence between users.
Uses ZylchMemory with namespace: shared:{recipient_owner_id}:{sender_owner_id}
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..memory import ZylchMemory
from .authorization import SharingAuthorizationManager

logger = logging.getLogger(__name__)


class SharedIntel:
    """Represents a piece of shared intelligence."""

    def __init__(
        self,
        memory_id: str,
        context: str,
        identifiers: Dict[str, str],
        sender_owner_id: str,
        sender_email: str,
        sender_display_name: Optional[str],
        shared_at: str,
        confidence: float = 1.0,
        similarity: float = 0.0
    ):
        self.memory_id = memory_id
        self.context = context
        self.identifiers = identifiers
        self.sender_owner_id = sender_owner_id
        self.sender_email = sender_email
        self.sender_display_name = sender_display_name
        self.shared_at = shared_at
        self.confidence = confidence
        self.similarity = similarity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "context": self.context,
            "identifiers": self.identifiers,
            "sender_owner_id": self.sender_owner_id,
            "sender_email": self.sender_email,
            "sender_display_name": self.sender_display_name,
            "shared_at": self.shared_at,
            "confidence": self.confidence,
            "similarity": self.similarity
        }


class IntelShareManager:
    """Manages sharing and retrieval of contact intelligence.

    Shared intel is stored in ZylchMemory with namespace pattern:
    shared:{recipient_owner_id}:{sender_owner_id}

    This allows:
    - Easy lookup of all intel shared WITH a user (shared:luigi:*)
    - Attribution to sender (the namespace includes sender_owner_id)
    - Privacy (only recipient can see their shared:* namespaces)
    """

    def __init__(
        self,
        memory_system: ZylchMemory,
        auth_manager: SharingAuthorizationManager
    ):
        """Initialize intel share manager.

        Args:
            memory_system: ZylchMemory instance for storing shared intel
            auth_manager: Authorization manager for checking permissions
        """
        self.memory = memory_system
        self.auth_manager = auth_manager

    def _make_namespace(self, recipient_owner_id: str, sender_owner_id: str) -> str:
        """Create namespace for shared intel.

        Args:
            recipient_owner_id: Owner ID of the recipient
            sender_owner_id: Owner ID of the sender

        Returns:
            Namespace string: shared:{recipient}:{sender}
        """
        return f"shared:{recipient_owner_id}:{sender_owner_id}"

    def share_intel(
        self,
        sender_owner_id: str,
        sender_email: str,
        recipient_owner_id: str,
        recipient_email: str,
        context: str,
        identifiers: Dict[str, str],
        sender_display_name: Optional[str] = None
    ) -> tuple[bool, str]:
        """Share intelligence about a contact with another user.

        Args:
            sender_owner_id: Owner ID of the sender
            sender_email: Email of the sender
            recipient_owner_id: Owner ID of the recipient
            recipient_email: Email of the recipient
            context: The intelligence being shared (e.g., "Marco Ferrari ha firmato il contratto")
            identifiers: Contact identifiers for matching (email, phone, name)
            sender_display_name: Optional sender display name

        Returns:
            (success, message) tuple
        """
        # Check authorization
        if not self.auth_manager.is_authorized(sender_email, recipient_email):
            # Check if pending
            status = self.auth_manager.get_authorization_status(sender_email, recipient_email)

            if status == "pending":
                # Add to pending shares queue
                success, msg = self.auth_manager.add_pending_share(
                    sender_email=sender_email,
                    recipient_email=recipient_email,
                    intel_context=context,
                    identifiers=identifiers
                )
                if success:
                    return True, f"Info in attesa di accettazione da parte del destinatario."
                return False, msg

            elif status == "rejected":
                return False, "Il destinatario ha rifiutato la tua richiesta di condivisione."

            elif status == "revoked":
                return False, "Il destinatario ha revocato la tua autorizzazione."

            else:
                # No authorization at all - need to register first
                return False, f"Devi prima registrare {recipient_email} con /share {recipient_email}"

        # Authorization is accepted - store in shared namespace
        namespace = self._make_namespace(recipient_owner_id, sender_owner_id)

        # Build pattern for storage
        # Pattern format: JSON with all metadata
        pattern_data = {
            "sender_owner_id": sender_owner_id,
            "sender_email": sender_email,
            "sender_display_name": sender_display_name,
            "identifiers": identifiers,
            "shared_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }

        try:
            memory_id = self.memory.store_memory(
                namespace=namespace,
                category="contact_intel",
                context=context,
                pattern=json.dumps(pattern_data),
                examples=[],
                user_id=None,
                confidence=1.0,
                force_new=True  # Always create new shared intel (no reconsolidation)
            )

            logger.info(f"Shared intel: {sender_owner_id} -> {recipient_owner_id}, memory_id={memory_id}")

            # Build confirmation message
            contact_desc = identifiers.get("name") or identifiers.get("email") or "contatto"
            return True, f"Condiviso con {recipient_email}: {contact_desc} - {context}"

        except Exception as e:
            logger.error(f"Failed to share intel: {e}")
            return False, f"Errore nella condivisione: {e}"

    def process_accepted_authorization(
        self,
        recipient_owner_id: str,
        recipient_email: str,
        sender_email: str
    ) -> int:
        """Process pending shares after authorization is accepted.

        Moves all pending shares from the queue to the shared namespace.

        Args:
            recipient_owner_id: Owner ID of the recipient
            recipient_email: Email of the recipient
            sender_email: Email of the sender

        Returns:
            Number of shares processed
        """
        # Get authorization ID
        auth_id = self.auth_manager.get_authorization_id(sender_email, recipient_email)
        if not auth_id:
            return 0

        # Get sender info
        sender_user = self.auth_manager.get_user_by_email(sender_email)
        if not sender_user:
            return 0

        sender_owner_id = sender_user["owner_id"]
        sender_display_name = sender_user.get("display_name")

        # Get pending shares
        pending = self.auth_manager.get_pending_shares_for_authorization(auth_id)

        if not pending:
            return 0

        # Process each pending share
        processed = 0
        for share in pending:
            success, _ = self.share_intel(
                sender_owner_id=sender_owner_id,
                sender_email=sender_email,
                recipient_owner_id=recipient_owner_id,
                recipient_email=recipient_email,
                context=share["intel_context"],
                identifiers=share["identifiers"],
                sender_display_name=sender_display_name
            )
            if success:
                processed += 1

        # Delete processed pending shares
        self.auth_manager.delete_pending_shares(auth_id)

        logger.info(f"Processed {processed} pending shares for {sender_email} -> {recipient_email}")
        return processed

    def get_shared_intel(
        self,
        recipient_owner_id: str,
        identifiers: Dict[str, str],
        limit: int = 10
    ) -> List[SharedIntel]:
        """Retrieve shared intel about a contact.

        Searches all shared:recipient:* namespaces for matching identifiers.

        Args:
            recipient_owner_id: Owner ID of the recipient (who is searching)
            identifiers: Contact identifiers to match (email, phone, name)
            limit: Maximum results to return

        Returns:
            List of SharedIntel objects
        """
        results = []

        # Get all authorized senders for this recipient
        recipient_user = self.auth_manager.get_user_by_owner_id(recipient_owner_id)
        if not recipient_user:
            return results

        recipient_email = recipient_user["email"]
        authorized_senders = self.auth_manager.list_authorized_senders(recipient_email)

        if not authorized_senders:
            return results

        # Search each sender's shared namespace
        for sender_info in authorized_senders:
            sender_owner_id = sender_info.get("owner_id")
            if not sender_owner_id:
                continue

            namespace = self._make_namespace(recipient_owner_id, sender_owner_id)

            # Build search query from identifiers
            search_parts = []
            if identifiers.get("email"):
                search_parts.append(identifiers["email"])
            if identifiers.get("phone"):
                search_parts.append(identifiers["phone"])
            if identifiers.get("name"):
                search_parts.append(identifiers["name"])

            if not search_parts:
                continue

            search_query = " ".join(search_parts)

            try:
                memories = self.memory.retrieve_memories(
                    query=search_query,
                    category="contact_intel",
                    namespace=namespace,
                    limit=limit
                )

                for mem in memories:
                    # Parse pattern data
                    try:
                        pattern_data = json.loads(mem.get("pattern", "{}"))
                    except json.JSONDecodeError:
                        pattern_data = {}

                    # Check identifier match
                    mem_identifiers = pattern_data.get("identifiers", {})
                    if not self._identifiers_match(identifiers, mem_identifiers):
                        continue

                    shared_intel = SharedIntel(
                        memory_id=str(mem.get("id")),
                        context=mem.get("context", ""),
                        identifiers=mem_identifiers,
                        sender_owner_id=pattern_data.get("sender_owner_id", sender_owner_id),
                        sender_email=pattern_data.get("sender_email", sender_info["sender_email"]),
                        sender_display_name=pattern_data.get("sender_display_name") or sender_info.get("display_name"),
                        shared_at=pattern_data.get("shared_at", ""),
                        confidence=mem.get("confidence", 1.0),
                        similarity=mem.get("similarity", 0.0)
                    )
                    results.append(shared_intel)

            except Exception as e:
                logger.warning(f"Error searching namespace {namespace}: {e}")
                continue

        # Sort by shared_at (newest first)
        results.sort(key=lambda x: x.shared_at, reverse=True)

        return results[:limit]

    def _identifiers_match(
        self,
        search_ids: Dict[str, str],
        stored_ids: Dict[str, str]
    ) -> bool:
        """Check if identifiers match (at least one must match).

        Args:
            search_ids: Identifiers we're searching for
            stored_ids: Identifiers stored in the memory

        Returns:
            True if at least one identifier matches
        """
        # Email match (case-insensitive)
        if search_ids.get("email") and stored_ids.get("email"):
            if search_ids["email"].lower() == stored_ids["email"].lower():
                return True

        # Phone match (normalize and compare last 9 digits)
        if search_ids.get("phone") and stored_ids.get("phone"):
            search_phone = self._normalize_phone(search_ids["phone"])
            stored_phone = self._normalize_phone(stored_ids["phone"])
            # Compare last 9 digits (ignores country code variations)
            if search_phone and stored_phone:
                if search_phone[-9:] == stored_phone[-9:]:
                    return True

        return False

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number for comparison.

        Args:
            phone: Phone number string

        Returns:
            Normalized phone (digits only)
        """
        if not phone:
            return ""
        # Keep only digits
        return "".join(c for c in phone if c.isdigit())

    def get_all_shared_intel_from_sender(
        self,
        recipient_owner_id: str,
        sender_owner_id: str,
        limit: int = 50
    ) -> List[SharedIntel]:
        """Get all intel shared by a specific sender.

        Args:
            recipient_owner_id: Owner ID of the recipient
            sender_owner_id: Owner ID of the sender
            limit: Maximum results

        Returns:
            List of SharedIntel objects
        """
        results = []
        namespace = self._make_namespace(recipient_owner_id, sender_owner_id)

        try:
            # Get sender info for display
            sender_user = self.auth_manager.get_user_by_owner_id(sender_owner_id)

            memories = self.memory.retrieve_memories(
                query="*",  # Get all
                category="contact_intel",
                namespace=namespace,
                limit=limit
            )

            for mem in memories:
                try:
                    pattern_data = json.loads(mem.get("pattern", "{}"))
                except json.JSONDecodeError:
                    pattern_data = {}

                shared_intel = SharedIntel(
                    memory_id=str(mem.get("id")),
                    context=mem.get("context", ""),
                    identifiers=pattern_data.get("identifiers", {}),
                    sender_owner_id=sender_owner_id,
                    sender_email=pattern_data.get("sender_email", sender_user.get("email", "") if sender_user else ""),
                    sender_display_name=pattern_data.get("sender_display_name") or (sender_user.get("display_name") if sender_user else None),
                    shared_at=pattern_data.get("shared_at", ""),
                    confidence=mem.get("confidence", 1.0),
                    similarity=mem.get("similarity", 0.0)
                )
                results.append(shared_intel)

        except Exception as e:
            logger.warning(f"Error retrieving shared intel from {sender_owner_id}: {e}")

        # Sort by shared_at (newest first)
        results.sort(key=lambda x: x.shared_at, reverse=True)

        return results[:limit]
