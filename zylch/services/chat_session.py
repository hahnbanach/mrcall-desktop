"""Chat session management for multi-user dashboard integration."""

import logging
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
import json

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """Single chat message in a conversation."""

    role: str  # 'user' or 'assistant'
    content: str
    timestamp: str
    session_id: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "session_id": self.session_id
        }


@dataclass
class ChatSession:
    """User chat session with conversation history."""

    user_id: str
    session_id: str
    created_at: str
    messages: List[ChatMessage] = field(default_factory=list)
    last_activity: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def add_message(self, role: str, content: str) -> ChatMessage:
        """Add a message to the conversation.

        Args:
            role: 'user' or 'assistant'
            content: Message content

        Returns:
            ChatMessage object that was added
        """
        timestamp = datetime.utcnow().isoformat()
        message = ChatMessage(
            role=role,
            content=content,
            timestamp=timestamp,
            session_id=self.session_id
        )
        self.messages.append(message)
        self.last_activity = timestamp
        return message

    def get_history(self, limit: Optional[int] = None) -> List[ChatMessage]:
        """Get conversation history.

        Args:
            limit: Optional limit on number of messages to return

        Returns:
            List of messages (most recent last)
        """
        if limit:
            return self.messages[-limit:]
        return self.messages

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "messages": [msg.to_dict() for msg in self.messages]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatSession":
        """Create ChatSession from dictionary."""
        messages = [
            ChatMessage(**msg) for msg in data.get("messages", [])
        ]
        return cls(
            user_id=data["user_id"],
            session_id=data["session_id"],
            created_at=data["created_at"],
            messages=messages,
            last_activity=data.get("last_activity", data["created_at"])
        )


class ChatSessionManager:
    """Manages chat sessions for multiple users.

    Each user can have multiple sessions, but typically only one active session.
    Sessions persist conversation history and context.
    """

    def __init__(self, persistence_dir: Optional[str] = None):
        """Initialize session manager.

        Args:
            persistence_dir: Optional directory to persist sessions to disk
        """
        self._sessions: Dict[str, ChatSession] = {}  # session_id -> ChatSession
        self._user_sessions: Dict[str, List[str]] = {}  # user_id -> [session_ids]
        self.persistence_dir = Path(persistence_dir) if persistence_dir else None

        if self.persistence_dir:
            self.persistence_dir.mkdir(parents=True, exist_ok=True)
            self._load_sessions()

    def create_session(self, user_id: str, session_id: Optional[str] = None) -> ChatSession:
        """Create a new chat session for a user.

        Args:
            user_id: Firebase user ID
            session_id: Optional custom session ID (generated if not provided)

        Returns:
            New ChatSession instance
        """
        if not session_id:
            # Generate session ID: user_id + timestamp
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            session_id = f"{user_id}_{timestamp}"

        # Check if session already exists
        if session_id in self._sessions:
            logger.warning(f"Session {session_id} already exists, returning existing")
            return self._sessions[session_id]

        # Create new session
        session = ChatSession(
            user_id=user_id,
            session_id=session_id,
            created_at=datetime.utcnow().isoformat()
        )

        # Store session
        self._sessions[session_id] = session

        # Track user's sessions
        if user_id not in self._user_sessions:
            self._user_sessions[user_id] = []
        self._user_sessions[user_id].append(session_id)

        logger.info(f"Created session {session_id} for user {user_id}")

        # Persist to disk if configured
        if self.persistence_dir:
            self._save_session(session)

        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Get an existing session by ID.

        Args:
            session_id: Session ID to retrieve

        Returns:
            ChatSession or None if not found
        """
        return self._sessions.get(session_id)

    def get_or_create_session(self, user_id: str, session_id: Optional[str] = None) -> ChatSession:
        """Get existing session or create new one.

        Args:
            user_id: Firebase user ID
            session_id: Optional session ID

        Returns:
            ChatSession (existing or newly created)
        """
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            # SECURITY: Verify session belongs to requesting user
            if session.user_id == user_id:
                return session
            # Session belongs to different user - ignore session_id, create new
            logger.warning(
                f"Session {session_id} belongs to {session.user_id}, not {user_id}. Creating new session."
            )

        # If no session_id provided, try to get user's latest session
        if not session_id:
            latest_session = self.get_latest_session_for_user(user_id)
            if latest_session:
                return latest_session

        # Create new session
        return self.create_session(user_id, session_id)

    def get_user_sessions(self, user_id: str) -> List[ChatSession]:
        """Get all sessions for a user.

        Args:
            user_id: Firebase user ID

        Returns:
            List of ChatSession objects
        """
        session_ids = self._user_sessions.get(user_id, [])
        return [self._sessions[sid] for sid in session_ids if sid in self._sessions]

    def get_latest_session_for_user(self, user_id: str) -> Optional[ChatSession]:
        """Get the most recent session for a user.

        Args:
            user_id: Firebase user ID

        Returns:
            Latest ChatSession or None
        """
        sessions = self.get_user_sessions(user_id)
        if not sessions:
            return None

        # Sort by last activity timestamp
        sessions.sort(key=lambda s: s.last_activity, reverse=True)
        return sessions[0]

    def add_message(self, session_id: str, role: str, content: str) -> Optional[ChatMessage]:
        """Add a message to a session.

        Args:
            session_id: Session to add message to
            role: 'user' or 'assistant'
            content: Message content

        Returns:
            ChatMessage that was added, or None if session not found
        """
        session = self.get_session(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            return None

        message = session.add_message(role, content)

        # Persist updated session
        if self.persistence_dir:
            self._save_session(session)

        return message

    def get_session_history(
        self,
        session_id: str,
        limit: Optional[int] = None
    ) -> List[ChatMessage]:
        """Get conversation history for a session.

        Args:
            session_id: Session ID
            limit: Optional limit on messages

        Returns:
            List of ChatMessage objects
        """
        session = self.get_session(session_id)
        if not session:
            return []

        return session.get_history(limit=limit)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session to delete

        Returns:
            True if deleted, False if not found
        """
        session = self._sessions.get(session_id)
        if not session:
            return False

        # Remove from user's session list
        user_id = session.user_id
        if user_id in self._user_sessions:
            self._user_sessions[user_id] = [
                sid for sid in self._user_sessions[user_id] if sid != session_id
            ]

        # Delete session
        del self._sessions[session_id]

        # Delete from disk
        if self.persistence_dir:
            session_file = self.persistence_dir / f"{session_id}.json"
            if session_file.exists():
                session_file.unlink()

        logger.info(f"Deleted session {session_id}")
        return True

    def _save_session(self, session: ChatSession):
        """Persist session to disk.

        Args:
            session: Session to save
        """
        if not self.persistence_dir:
            return

        session_file = self.persistence_dir / f"{session.session_id}.json"
        try:
            with open(session_file, "w") as f:
                json.dump(session.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save session {session.session_id}: {e}")

    def _load_sessions(self):
        """Load all sessions from disk."""
        if not self.persistence_dir or not self.persistence_dir.exists():
            return

        for session_file in self.persistence_dir.glob("*.json"):
            try:
                with open(session_file, "r") as f:
                    data = json.load(f)
                    session = ChatSession.from_dict(data)

                    # Store in memory
                    self._sessions[session.session_id] = session

                    # Track user's sessions
                    if session.user_id not in self._user_sessions:
                        self._user_sessions[session.user_id] = []
                    if session.session_id not in self._user_sessions[session.user_id]:
                        self._user_sessions[session.user_id].append(session.session_id)

                logger.debug(f"Loaded session {session.session_id}")
            except Exception as e:
                logger.error(f"Failed to load session from {session_file}: {e}")

        logger.info(f"Loaded {len(self._sessions)} sessions from disk")


# Global session manager instance
_session_manager: Optional[ChatSessionManager] = None


def get_session_manager() -> ChatSessionManager:
    """Get global chat session manager instance.

    Creates in-memory session manager (no local persistence per ARCHITECTURE.md).

    Returns:
        ChatSessionManager instance
    """
    global _session_manager

    if _session_manager is None:
        # No local persistence - sessions are ephemeral API sessions
        _session_manager = ChatSessionManager(persistence_dir=None)
        logger.info("Initialized global chat session manager (in-memory)")

    return _session_manager
