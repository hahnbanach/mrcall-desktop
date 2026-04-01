"""Authorization management for intelligence sharing between Zylch users.

Handles:
- User registration (/share command)
- Authorization acceptance/rejection
- Revocation
- Pending share requests

All storage uses SQLAlchemy ORM with direct PostgreSQL access.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from zylch.storage.database import get_session
from zylch.storage.models import OAuthToken, SharingAuth

logger = logging.getLogger(__name__)


class SharingAuthorizationManager:
    """Manages authorization for sharing intelligence between Zylch users.

    Uses SQLAlchemy ORM against the `sharing_auth` and `oauth_tokens` tables.

    Authorization flow:
    1. Mario registers Luigi as recipient with /share luigi@email.com
    2. Mario shares intel: "Condividi con Luigi che Marco Ferrari ha firmato"
    3. Luigi sees pending request at next access
    4. Luigi accepts -> authorization status = "authorized"
    5. Pending shares are moved to the shared namespace
    6. Future shares from Mario to Luigi are automatic (no acceptance needed)
    """

    def __init__(self, db_path=None):
        """Initialize authorization manager using SQLAlchemy.

        Args:
            db_path: IGNORED - kept for backwards compatibility only.
                     All storage uses SQLAlchemy + PostgreSQL.
        """
        # Keep storage reference for non-client methods that may still be needed
        from ..storage import Storage
        self._storage = Storage.get_instance()
        logger.info("Sharing authorization manager initialized with SQLAlchemy backend")

    # ==================== User Management ====================

    def register_user(self, owner_id: str, email: str, display_name: Optional[str] = None) -> bool:
        """Register a Zylch user for sharing.

        Note: User registration is handled by Firebase auth. This method is kept
        for backwards compatibility but simply returns True.

        Args:
            owner_id: User's owner_id (from Firebase)
            email: User's email address
            display_name: Optional display name

        Returns:
            True (always succeeds as users are in Firebase)
        """
        logger.info(f"User registered via Firebase: {owner_id} ({email})")
        return True

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Look up a Zylch user by email.

        Uses oauth_tokens table to check if user exists in system.

        Args:
            email: Email address to look up

        Returns:
            User dict with owner_id, email or None
        """
        try:
            with get_session() as session:
                row = session.query(OAuthToken)\
                    .filter(OAuthToken.email == email.lower())\
                    .first()

                if row:
                    return {
                        "owner_id": row.owner_id,
                        "email": row.email,
                        "display_name": None  # Not stored separately
                    }
                return None
        except Exception as e:
            logger.warning(f"Failed to look up user by email: {e}")
            return None

    def get_user_by_owner_id(self, owner_id: str) -> Optional[Dict[str, Any]]:
        """Look up a Zylch user by owner_id.

        Args:
            owner_id: Owner ID to look up

        Returns:
            User dict or None
        """
        try:
            with get_session() as session:
                row = session.query(OAuthToken)\
                    .filter(OAuthToken.owner_id == owner_id)\
                    .first()

                if row:
                    return {
                        "owner_id": row.owner_id,
                        "email": row.email,
                        "display_name": None
                    }
                return None
        except Exception as e:
            logger.warning(f"Failed to look up user by owner_id: {e}")
            return None

    # ==================== Authorization Management ====================

    def register_recipient(self, sender_email: str, recipient_email: str) -> Tuple[bool, str]:
        """Register a recipient for future sharing (called by /share command).

        Args:
            sender_email: Email of the user who wants to share
            recipient_email: Email of the recipient

        Returns:
            (success, message) tuple
        """
        # Check if recipient is a registered Zylch user
        recipient = self.get_user_by_email(recipient_email)
        if not recipient:
            return False, f"{recipient_email} non è un utente Zylch registrato."

        try:
            with get_session() as session:
                # Check existing status via sharing_auth table
                row = session.query(SharingAuth)\
                    .filter(
                        SharingAuth.sender_email == sender_email.lower(),
                        SharingAuth.recipient_email == recipient_email.lower(),
                    )\
                    .first()

                if row:
                    status = row.status
                    display = recipient.get('display_name') or recipient_email

                    if status == "authorized":
                        return True, f"Puoi già condividere con {display}."
                    elif status == "pending":
                        return True, f"Richiesta già inviata a {display} (in attesa di accettazione)."
                    elif status in ["rejected", "revoked"]:
                        # Re-activate as pending
                        row.status = 'pending'

                else:
                    # Create new authorization using Storage
                    sender = self.get_user_by_email(sender_email)
                    sender_id = sender.get('owner_id') if sender else 'unknown'
                    self._storage.register_share_recipient(sender_id, sender_email.lower(), recipient_email.lower())

                display = recipient.get('display_name') or recipient_email
                return True, f"Registrato {display} come destinatario. Quando condividerai info, {display} dovrà accettare."

        except Exception as e:
            logger.error(f"Failed to register recipient: {e}")
            return False, f"Errore nella registrazione: {e}"

    def accept_authorization(self, recipient_email: str, sender_email: str) -> Tuple[bool, str]:
        """Accept sharing authorization from a sender.

        Args:
            recipient_email: Email of the recipient (who is accepting)
            sender_email: Email of the sender

        Returns:
            (success, message) tuple
        """
        try:
            result = self._storage.authorize_sender(recipient_email.lower(), sender_email.lower())
            if result:
                return True, f"Accettato. {sender_email} può ora condividere informazioni con te."
            return False, "Nessuna richiesta di condivisione trovata da questo mittente."
        except Exception as e:
            logger.error(f"Failed to accept authorization: {e}")
            return False, f"Errore: {e}"

    def reject_authorization(self, recipient_email: str, sender_email: str) -> Tuple[bool, str]:
        """Reject sharing authorization from a sender.

        Args:
            recipient_email: Email of the recipient (who is rejecting)
            sender_email: Email of the sender

        Returns:
            (success, message) tuple
        """
        try:
            with get_session() as session:
                session.query(SharingAuth)\
                    .filter(
                        SharingAuth.sender_email == sender_email.lower(),
                        SharingAuth.recipient_email == recipient_email.lower(),
                        SharingAuth.status == 'pending',
                    )\
                    .update({'status': 'rejected'})

            return True, f"Rifiutato. {sender_email} non potrà condividere informazioni con te."
        except Exception as e:
            logger.error(f"Failed to reject authorization: {e}")
            return False, f"Errore: {e}"

    def revoke_authorization(self, recipient_email: str, sender_email: str) -> Tuple[bool, str]:
        """Revoke an accepted authorization.

        Args:
            recipient_email: Email of the recipient (who is revoking)
            sender_email: Email of the sender

        Returns:
            (success, message) tuple
        """
        try:
            # Find sender_id to use revoke_sharing
            sender = self.get_user_by_email(sender_email)
            if sender:
                self._storage.revoke_sharing(sender.get('owner_id'), recipient_email.lower())
            else:
                # Fallback: update directly via SQLAlchemy
                with get_session() as session:
                    session.query(SharingAuth)\
                        .filter(
                            SharingAuth.sender_email == sender_email.lower(),
                            SharingAuth.recipient_email == recipient_email.lower(),
                        )\
                        .update({'status': 'revoked'})

            return True, f"Revocato. {sender_email} non può più condividere informazioni con te."
        except Exception as e:
            logger.error(f"Failed to revoke authorization: {e}")
            return False, f"Errore: {e}"

    def is_authorized(self, sender_email: str, recipient_email: str) -> bool:
        """Check if sender is authorized to share with recipient.

        Args:
            sender_email: Email of the sender
            recipient_email: Email of the recipient

        Returns:
            True if authorization is accepted/authorized
        """
        try:
            with get_session() as session:
                row = session.query(SharingAuth)\
                    .filter(
                        SharingAuth.sender_email == sender_email.lower(),
                        SharingAuth.recipient_email == recipient_email.lower(),
                        SharingAuth.status == 'authorized',
                    )\
                    .first()

                return row is not None
        except Exception as e:
            logger.warning(f"Failed to check authorization: {e}")
            return False

    def get_authorization_status(self, sender_email: str, recipient_email: str) -> Optional[str]:
        """Get authorization status between sender and recipient.

        Args:
            sender_email: Email of the sender
            recipient_email: Email of the recipient

        Returns:
            Status string or None if no authorization exists
        """
        try:
            with get_session() as session:
                row = session.query(SharingAuth)\
                    .filter(
                        SharingAuth.sender_email == sender_email.lower(),
                        SharingAuth.recipient_email == recipient_email.lower(),
                    )\
                    .first()

                return row.status if row else None
        except Exception as e:
            logger.warning(f"Failed to get authorization status: {e}")
            return None

    def list_authorized_senders(self, recipient_email: str) -> List[Dict[str, Any]]:
        """List all users who can share with this recipient (authorized).

        Args:
            recipient_email: Email of the recipient

        Returns:
            List of sender info dicts
        """
        try:
            with get_session() as session:
                rows = session.query(SharingAuth)\
                    .filter(
                        SharingAuth.recipient_email == recipient_email.lower(),
                        SharingAuth.status == 'authorized',
                    )\
                    .order_by(SharingAuth.authorized_at.desc())\
                    .all()

                return [
                    {
                        "sender_email": row.sender_email,
                        "accepted_at": (row.authorized_at or row.created_at).isoformat()
                            if (row.authorized_at or row.created_at) else None,
                        "owner_id": row.sender_id
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.warning(f"Failed to list authorized senders: {e}")
            return []

    def list_authorized_recipients(self, sender_email: str) -> List[Dict[str, Any]]:
        """List all users this sender can share with (authorized).

        Args:
            sender_email: Email of the sender

        Returns:
            List of recipient info dicts
        """
        try:
            with get_session() as session:
                rows = session.query(SharingAuth)\
                    .filter(
                        SharingAuth.sender_email == sender_email.lower(),
                        SharingAuth.status == 'authorized',
                    )\
                    .order_by(SharingAuth.authorized_at.desc())\
                    .all()

                return [
                    {
                        "recipient_email": row.recipient_email,
                        "accepted_at": (row.authorized_at or row.created_at).isoformat()
                            if (row.authorized_at or row.created_at) else None,
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.warning(f"Failed to list authorized recipients: {e}")
            return []

    def list_pending_registrations(self, sender_email: str) -> List[Dict[str, Any]]:
        """List pending registrations waiting for recipient acceptance.

        Args:
            sender_email: Email of the sender

        Returns:
            List of pending registration dicts
        """
        try:
            with get_session() as session:
                rows = session.query(SharingAuth)\
                    .filter(
                        SharingAuth.sender_email == sender_email.lower(),
                        SharingAuth.status == 'pending',
                    )\
                    .order_by(SharingAuth.created_at.desc())\
                    .all()

                return [
                    {
                        "recipient_email": row.recipient_email,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.warning(f"Failed to list pending registrations: {e}")
            return []

    # ==================== Pending Shares ====================
    #
    # Note: Pending shares are stored as JSON array in sharing_auth.pending_intel column.
    # This keeps all sharing data in a single table for simplicity.

    def add_pending_share(
        self,
        sender_email: str,
        recipient_email: str,
        intel_context: str,
        identifiers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Add a share to pending queue (when authorization is not yet accepted).

        Stores pending intel as JSON array in sharing_auth.pending_intel column.

        Args:
            sender_email: Email of sender
            recipient_email: Email of recipient
            intel_context: The intel being shared (e.g., "Marco Ferrari ha firmato il contratto")
            identifiers: Contact identifiers (email, phone, name)

        Returns:
            (success, message) tuple
        """
        try:
            with get_session() as session:
                # Get existing authorization
                row = session.query(SharingAuth)\
                    .filter(
                        SharingAuth.sender_email == sender_email.lower(),
                        SharingAuth.recipient_email == recipient_email.lower(),
                    )\
                    .first()

                if row:
                    status = row.status

                    if status == "rejected":
                        return False, "Il destinatario ha rifiutato la tua richiesta di condivisione."
                    elif status == "revoked":
                        return False, "Il destinatario ha revocato la tua autorizzazione."

                    # Append to existing pending_intel
                    pending_intel = row.pending_intel or []
                    if isinstance(pending_intel, str):
                        pending_intel = json.loads(pending_intel) if pending_intel else []

                    pending_intel.append({
                        'intel_context': intel_context,
                        'identifiers': identifiers,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    })

                    row.pending_intel = pending_intel

                else:
                    # Create new pending authorization with intel
                    sender = self.get_user_by_email(sender_email)
                    sender_id = sender.get('owner_id') if sender else 'unknown'

                    pending_intel = [{
                        'intel_context': intel_context,
                        'identifiers': identifiers,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }]

                    new_auth = SharingAuth(
                        sender_id=sender_id,
                        sender_email=sender_email.lower(),
                        recipient_email=recipient_email.lower(),
                        status='pending',
                        pending_intel=pending_intel,
                    )
                    session.add(new_auth)

            return True, "Info aggiunta alla coda. Sarà visibile quando il destinatario accetterà."

        except Exception as e:
            logger.error(f"Failed to add pending share: {e}")
            return False, f"Errore: {e}"

    def get_pending_requests(self, recipient_email: str) -> List[Dict[str, Any]]:
        """Get pending share requests for a recipient.

        Args:
            recipient_email: Email of recipient

        Returns:
            List of pending share dicts with sender info and intel
        """
        try:
            with get_session() as session:
                rows = session.query(SharingAuth)\
                    .filter(
                        SharingAuth.recipient_email == recipient_email.lower(),
                        SharingAuth.status == 'pending',
                    )\
                    .order_by(SharingAuth.created_at.asc())\
                    .all()

                results = []
                for row in rows:
                    pending_intel = row.pending_intel or []
                    if isinstance(pending_intel, str):
                        pending_intel = json.loads(pending_intel) if pending_intel else []

                    row_id = str(row.id)
                    # Return one entry per pending intel item
                    for i, intel in enumerate(pending_intel):
                        results.append({
                            "id": f"{row_id}_{i}",  # Composite ID
                            "intel_context": intel.get('intel_context', ''),
                            "identifiers": intel.get('identifiers', {}),
                            "created_at": intel.get('created_at',
                                row.created_at.isoformat() if row.created_at else None),
                            "sender_email": row.sender_email,
                            "sender_display_name": None,  # Could be fetched if needed
                            "sender_owner_id": row.sender_id
                        })

                return results

        except Exception as e:
            logger.warning(f"Failed to get pending requests: {e}")
            return []

    def get_pending_shares_for_authorization(self, auth_id: str) -> List[Dict[str, Any]]:
        """Get all pending shares for a specific authorization.

        Args:
            auth_id: Authorization ID (UUID)

        Returns:
            List of pending share dicts
        """
        try:
            with get_session() as session:
                row = session.query(SharingAuth)\
                    .filter(SharingAuth.id == auth_id)\
                    .first()

                if not row:
                    return []

                pending_intel = row.pending_intel or []
                if isinstance(pending_intel, str):
                    pending_intel = json.loads(pending_intel) if pending_intel else []

                return [
                    {
                        "id": i,
                        "intel_context": intel.get('intel_context', ''),
                        "identifiers": intel.get('identifiers', {}),
                        "created_at": intel.get('created_at')
                    }
                    for i, intel in enumerate(pending_intel)
                ]

        except Exception as e:
            logger.warning(f"Failed to get pending shares for auth {auth_id}: {e}")
            return []

    def delete_pending_shares(self, auth_id: str) -> int:
        """Delete all pending shares for an authorization (after acceptance).

        Clears the pending_intel JSON array.

        Args:
            auth_id: Authorization ID (UUID)

        Returns:
            Number of shares deleted
        """
        try:
            with get_session() as session:
                row = session.query(SharingAuth)\
                    .filter(SharingAuth.id == auth_id)\
                    .first()

                if not row:
                    return 0

                pending_intel = row.pending_intel or []
                if isinstance(pending_intel, str):
                    pending_intel = json.loads(pending_intel) if pending_intel else []

                count = len(pending_intel)

                # Clear pending_intel
                row.pending_intel = []

                return count

        except Exception as e:
            logger.warning(f"Failed to delete pending shares for auth {auth_id}: {e}")
            return 0

    def get_authorization_id(self, sender_email: str, recipient_email: str) -> Optional[str]:
        """Get authorization ID for a sender-recipient pair.

        Args:
            sender_email: Email of sender
            recipient_email: Email of recipient

        Returns:
            Authorization ID (UUID string) or None
        """
        try:
            with get_session() as session:
                row = session.query(SharingAuth)\
                    .filter(
                        SharingAuth.sender_email == sender_email.lower(),
                        SharingAuth.recipient_email == recipient_email.lower(),
                    )\
                    .first()

                return str(row.id) if row else None

        except Exception as e:
            logger.warning(f"Failed to get authorization ID: {e}")
            return None
