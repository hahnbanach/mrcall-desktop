"""Authorization management for intelligence sharing between Zylch users.

Handles:
- User registration (/share command)
- Authorization acceptance/rejection
- Revocation
- Pending share requests
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SharingAuthorizationManager:
    """Manages authorization for sharing intelligence between Zylch users.

    Authorization flow:
    1. Mario registers Luigi as recipient with /share luigi@email.com
    2. Mario shares intel: "Condividi con Luigi che Marco Ferrari ha firmato"
    3. Luigi sees pending request at next access
    4. Luigi accepts -> authorization status = "accepted"
    5. Pending shares are moved to the shared namespace
    6. Future shares from Mario to Luigi are automatic (no acceptance needed)
    """

    def __init__(self, db_path: Path):
        """Initialize authorization manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Zylch users table - maps email to owner_id
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS zylch_users (
                owner_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                display_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Share authorizations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS share_authorizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_email TEXT NOT NULL,
                recipient_email TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                accepted_at TIMESTAMP NULL,
                revoked_at TIMESTAMP NULL,
                UNIQUE(sender_email, recipient_email)
            )
        """)

        # Pending shares table - intel waiting for acceptance
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                authorization_id INTEGER NOT NULL,
                intel_context TEXT NOT NULL,
                identifiers TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (authorization_id) REFERENCES share_authorizations(id)
            )
        """)

        conn.commit()
        conn.close()

        logger.info(f"Sharing tables initialized at {self.db_path}")

    # ==================== User Management ====================

    def register_user(self, owner_id: str, email: str, display_name: Optional[str] = None) -> bool:
        """Register a Zylch user for sharing.

        Args:
            owner_id: User's owner_id (from settings)
            email: User's email address
            display_name: Optional display name

        Returns:
            True if registered/updated, False on error
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO zylch_users (owner_id, email, display_name)
                VALUES (?, ?, ?)
                ON CONFLICT(owner_id) DO UPDATE SET
                    email = excluded.email,
                    display_name = excluded.display_name
            """, (owner_id, email.lower(), display_name))

            conn.commit()
            logger.info(f"Registered Zylch user: {owner_id} ({email})")
            return True

        except Exception as e:
            logger.error(f"Failed to register user: {e}")
            return False
        finally:
            conn.close()

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Look up a Zylch user by email.

        Args:
            email: Email address to look up

        Returns:
            User dict with owner_id, email, display_name or None
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT owner_id, email, display_name, created_at
            FROM zylch_users
            WHERE email = ?
        """, (email.lower(),))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "owner_id": row[0],
                "email": row[1],
                "display_name": row[2],
                "created_at": row[3]
            }
        return None

    def get_user_by_owner_id(self, owner_id: str) -> Optional[Dict[str, Any]]:
        """Look up a Zylch user by owner_id.

        Args:
            owner_id: Owner ID to look up

        Returns:
            User dict or None
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT owner_id, email, display_name, created_at
            FROM zylch_users
            WHERE owner_id = ?
        """, (owner_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "owner_id": row[0],
                "email": row[1],
                "display_name": row[2],
                "created_at": row[3]
            }
        return None

    # ==================== Authorization Management ====================

    def register_recipient(self, sender_email: str, recipient_email: str) -> Tuple[bool, str]:
        """Register a recipient for future sharing (called by /share command).

        This creates a pending authorization. The recipient must accept before
        shares actually go through.

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

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            # Check if authorization already exists
            cursor.execute("""
                SELECT id, status FROM share_authorizations
                WHERE sender_email = ? AND recipient_email = ?
            """, (sender_email.lower(), recipient_email.lower()))

            existing = cursor.fetchone()

            if existing:
                auth_id, status = existing
                if status == "accepted":
                    return True, f"Puoi già condividere con {recipient.get('display_name') or recipient_email}."
                elif status == "pending":
                    return True, f"Richiesta già inviata a {recipient.get('display_name') or recipient_email} (in attesa di accettazione)."
                elif status == "rejected":
                    # Allow re-request after rejection
                    cursor.execute("""
                        UPDATE share_authorizations
                        SET status = 'pending', created_at = CURRENT_TIMESTAMP,
                            accepted_at = NULL, revoked_at = NULL
                        WHERE id = ?
                    """, (auth_id,))
                elif status == "revoked":
                    # Allow re-request after revocation
                    cursor.execute("""
                        UPDATE share_authorizations
                        SET status = 'pending', created_at = CURRENT_TIMESTAMP,
                            accepted_at = NULL, revoked_at = NULL
                        WHERE id = ?
                    """, (auth_id,))
            else:
                # Create new authorization
                cursor.execute("""
                    INSERT INTO share_authorizations (sender_email, recipient_email, status)
                    VALUES (?, ?, 'pending')
                """, (sender_email.lower(), recipient_email.lower()))

            conn.commit()
            display = recipient.get('display_name') or recipient_email
            return True, f"Registrato {display} come destinatario. Quando condividerai info, {display} dovrà accettare."

        except Exception as e:
            logger.error(f"Failed to register recipient: {e}")
            return False, f"Errore nella registrazione: {e}"
        finally:
            conn.close()

    def accept_authorization(self, recipient_email: str, sender_email: str) -> Tuple[bool, str]:
        """Accept sharing authorization from a sender.

        Args:
            recipient_email: Email of the recipient (who is accepting)
            sender_email: Email of the sender

        Returns:
            (success, message) tuple
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE share_authorizations
                SET status = 'accepted', accepted_at = CURRENT_TIMESTAMP
                WHERE sender_email = ? AND recipient_email = ? AND status = 'pending'
            """, (sender_email.lower(), recipient_email.lower()))

            if cursor.rowcount == 0:
                return False, "Nessuna richiesta di condivisione trovata da questo mittente."

            conn.commit()
            return True, f"Accettato. {sender_email} può ora condividere informazioni con te."

        except Exception as e:
            logger.error(f"Failed to accept authorization: {e}")
            return False, f"Errore: {e}"
        finally:
            conn.close()

    def reject_authorization(self, recipient_email: str, sender_email: str) -> Tuple[bool, str]:
        """Reject sharing authorization from a sender.

        Args:
            recipient_email: Email of the recipient (who is rejecting)
            sender_email: Email of the sender

        Returns:
            (success, message) tuple
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE share_authorizations
                SET status = 'rejected'
                WHERE sender_email = ? AND recipient_email = ? AND status = 'pending'
            """, (sender_email.lower(), recipient_email.lower()))

            if cursor.rowcount == 0:
                return False, "Nessuna richiesta di condivisione trovata da questo mittente."

            conn.commit()
            return True, f"Rifiutato. {sender_email} non potrà condividere informazioni con te."

        except Exception as e:
            logger.error(f"Failed to reject authorization: {e}")
            return False, f"Errore: {e}"
        finally:
            conn.close()

    def revoke_authorization(self, recipient_email: str, sender_email: str) -> Tuple[bool, str]:
        """Revoke an accepted authorization.

        This stops future shares but keeps existing shared intel visible.

        Args:
            recipient_email: Email of the recipient (who is revoking)
            sender_email: Email of the sender

        Returns:
            (success, message) tuple
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE share_authorizations
                SET status = 'revoked', revoked_at = CURRENT_TIMESTAMP
                WHERE sender_email = ? AND recipient_email = ? AND status = 'accepted'
            """, (sender_email.lower(), recipient_email.lower()))

            if cursor.rowcount == 0:
                return False, "Nessuna autorizzazione attiva trovata da questo mittente."

            conn.commit()
            return True, f"Revocato. {sender_email} non può più condividere informazioni con te."

        except Exception as e:
            logger.error(f"Failed to revoke authorization: {e}")
            return False, f"Errore: {e}"
        finally:
            conn.close()

    def is_authorized(self, sender_email: str, recipient_email: str) -> bool:
        """Check if sender is authorized to share with recipient.

        Args:
            sender_email: Email of the sender
            recipient_email: Email of the recipient

        Returns:
            True if authorization is accepted
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT status FROM share_authorizations
            WHERE sender_email = ? AND recipient_email = ? AND status = 'accepted'
        """, (sender_email.lower(), recipient_email.lower()))

        result = cursor.fetchone()
        conn.close()

        return result is not None

    def get_authorization_status(self, sender_email: str, recipient_email: str) -> Optional[str]:
        """Get authorization status between sender and recipient.

        Args:
            sender_email: Email of the sender
            recipient_email: Email of the recipient

        Returns:
            Status string or None if no authorization exists
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT status FROM share_authorizations
            WHERE sender_email = ? AND recipient_email = ?
        """, (sender_email.lower(), recipient_email.lower()))

        result = cursor.fetchone()
        conn.close()

        return result[0] if result else None

    def list_authorized_senders(self, recipient_email: str) -> List[Dict[str, Any]]:
        """List all users who can share with this recipient (accepted).

        Args:
            recipient_email: Email of the recipient

        Returns:
            List of sender info dicts
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT sa.sender_email, sa.accepted_at, zu.display_name, zu.owner_id
            FROM share_authorizations sa
            LEFT JOIN zylch_users zu ON zu.email = sa.sender_email
            WHERE sa.recipient_email = ? AND sa.status = 'accepted'
            ORDER BY sa.accepted_at DESC
        """, (recipient_email.lower(),))

        results = []
        for row in cursor.fetchall():
            results.append({
                "sender_email": row[0],
                "accepted_at": row[1],
                "display_name": row[2],
                "owner_id": row[3]
            })

        conn.close()
        return results

    def list_authorized_recipients(self, sender_email: str) -> List[Dict[str, Any]]:
        """List all users this sender can share with (accepted).

        Args:
            sender_email: Email of the sender

        Returns:
            List of recipient info dicts
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT sa.recipient_email, sa.accepted_at, zu.display_name, zu.owner_id
            FROM share_authorizations sa
            LEFT JOIN zylch_users zu ON zu.email = sa.recipient_email
            WHERE sa.sender_email = ? AND sa.status = 'accepted'
            ORDER BY sa.accepted_at DESC
        """, (sender_email.lower(),))

        results = []
        for row in cursor.fetchall():
            results.append({
                "recipient_email": row[0],
                "accepted_at": row[1],
                "display_name": row[2],
                "owner_id": row[3]
            })

        conn.close()
        return results

    def list_pending_registrations(self, sender_email: str) -> List[Dict[str, Any]]:
        """List pending registrations waiting for recipient acceptance.

        Args:
            sender_email: Email of the sender

        Returns:
            List of pending registration dicts
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT sa.recipient_email, sa.created_at, zu.display_name, zu.owner_id
            FROM share_authorizations sa
            LEFT JOIN zylch_users zu ON zu.email = sa.recipient_email
            WHERE sa.sender_email = ? AND sa.status = 'pending'
            ORDER BY sa.created_at DESC
        """, (sender_email.lower(),))

        results = []
        for row in cursor.fetchall():
            results.append({
                "recipient_email": row[0],
                "created_at": row[1],
                "display_name": row[2],
                "owner_id": row[3]
            })

        conn.close()
        return results

    # ==================== Pending Shares ====================

    def add_pending_share(
        self,
        sender_email: str,
        recipient_email: str,
        intel_context: str,
        identifiers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Add a share to pending queue (when authorization is not yet accepted).

        Args:
            sender_email: Email of sender
            recipient_email: Email of recipient
            intel_context: The intel being shared (e.g., "Marco Ferrari ha firmato il contratto")
            identifiers: Contact identifiers (email, phone, name)

        Returns:
            (success, message) tuple
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            # Get or create authorization
            cursor.execute("""
                SELECT id, status FROM share_authorizations
                WHERE sender_email = ? AND recipient_email = ?
            """, (sender_email.lower(), recipient_email.lower()))

            auth_row = cursor.fetchone()

            if not auth_row:
                # Auto-create pending authorization
                cursor.execute("""
                    INSERT INTO share_authorizations (sender_email, recipient_email, status)
                    VALUES (?, ?, 'pending')
                """, (sender_email.lower(), recipient_email.lower()))
                auth_id = cursor.lastrowid
            else:
                auth_id, status = auth_row
                if status == "rejected":
                    return False, "Il destinatario ha rifiutato la tua richiesta di condivisione."
                elif status == "revoked":
                    return False, "Il destinatario ha revocato la tua autorizzazione."

            # Add pending share
            cursor.execute("""
                INSERT INTO pending_shares (authorization_id, intel_context, identifiers)
                VALUES (?, ?, ?)
            """, (auth_id, intel_context, json.dumps(identifiers)))

            conn.commit()
            return True, "Info aggiunta alla coda. Sarà visibile quando il destinatario accetterà."

        except Exception as e:
            logger.error(f"Failed to add pending share: {e}")
            return False, f"Errore: {e}"
        finally:
            conn.close()

    def get_pending_requests(self, recipient_email: str) -> List[Dict[str, Any]]:
        """Get pending share requests for a recipient.

        Args:
            recipient_email: Email of recipient

        Returns:
            List of pending share dicts with sender info and intel
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                ps.id, ps.intel_context, ps.identifiers, ps.created_at,
                sa.sender_email, zu.display_name, zu.owner_id
            FROM pending_shares ps
            JOIN share_authorizations sa ON sa.id = ps.authorization_id
            LEFT JOIN zylch_users zu ON zu.email = sa.sender_email
            WHERE sa.recipient_email = ? AND sa.status = 'pending'
            ORDER BY ps.created_at ASC
        """, (recipient_email.lower(),))

        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "intel_context": row[1],
                "identifiers": json.loads(row[2]),
                "created_at": row[3],
                "sender_email": row[4],
                "sender_display_name": row[5],
                "sender_owner_id": row[6]
            })

        conn.close()
        return results

    def get_pending_shares_for_authorization(self, auth_id: int) -> List[Dict[str, Any]]:
        """Get all pending shares for a specific authorization.

        Args:
            auth_id: Authorization ID

        Returns:
            List of pending share dicts
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, intel_context, identifiers, created_at
            FROM pending_shares
            WHERE authorization_id = ?
            ORDER BY created_at ASC
        """, (auth_id,))

        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "intel_context": row[1],
                "identifiers": json.loads(row[2]),
                "created_at": row[3]
            })

        conn.close()
        return results

    def delete_pending_shares(self, auth_id: int) -> int:
        """Delete all pending shares for an authorization (after acceptance).

        Args:
            auth_id: Authorization ID

        Returns:
            Number of shares deleted
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM pending_shares WHERE authorization_id = ?
        """, (auth_id,))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return deleted

    def get_authorization_id(self, sender_email: str, recipient_email: str) -> Optional[int]:
        """Get authorization ID for a sender-recipient pair.

        Args:
            sender_email: Email of sender
            recipient_email: Email of recipient

        Returns:
            Authorization ID or None
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id FROM share_authorizations
            WHERE sender_email = ? AND recipient_email = ?
        """, (sender_email.lower(), recipient_email.lower()))

        result = cursor.fetchone()
        conn.close()

        return result[0] if result else None
