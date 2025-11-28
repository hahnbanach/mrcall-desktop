"""Zylch Assistant management service.

Manages multiple Zylch assistants per owner, each with completely isolated:
- Business info
- Contacts
- Person memories
- Email style

Example:
    owner_mario can have:
    - "mrcall_assistant" (telecom business)
    - "caffe_assistant" (coffee shop business)

    Both are completely isolated with different business info, contacts, etc.
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


class AssistantManager:
    """Manages Zylch assistants for owners."""

    def __init__(self, storage_path: str = "cache/zylch_assistants.json"):
        """Initialize AssistantManager.

        Args:
            storage_path: Path to JSON storage file
        """
        self.storage_path = Path(storage_path)
        self._load()

    def _load(self):
        """Load assistants from JSON file."""
        if self.storage_path.exists():
            with open(self.storage_path, 'r') as f:
                self.data = json.load(f)
        else:
            self.data = {}
            self._save()

    def _save(self):
        """Save assistants to JSON file."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, 'w') as f:
            json.dump(self.data, f, indent=2)

    def list_assistants(self, owner_id: str) -> List[Dict]:
        """List all assistants for an owner.

        Args:
            owner_id: Owner identifier (Firebase UID)

        Returns:
            List of assistant dictionaries
        """
        if owner_id not in self.data:
            return []
        return self.data[owner_id].get("assistants", [])

    def get_assistant(self, owner_id: str, zylch_assistant_id: str) -> Optional[Dict]:
        """Get specific assistant details.

        Args:
            owner_id: Owner identifier
            zylch_assistant_id: Zylch assistant ID

        Returns:
            Assistant dict or None if not found
        """
        assistants = self.list_assistants(owner_id)
        for assistant in assistants:
            if assistant['id'] == zylch_assistant_id:
                return assistant
        return None

    def create_assistant(
        self,
        owner_id: str,
        zylch_assistant_id: str,
        name: str,
        mrcall_assistant_id: Optional[str] = None,
        business_type: Optional[str] = None
    ) -> Dict:
        """Create new Zylch assistant.

        Args:
            owner_id: Owner identifier
            zylch_assistant_id: Unique assistant ID
            name: Human-readable name (e.g., "MrCall Telecom", "Caffè Rosso")
            mrcall_assistant_id: Optional MrCall/StarChat assistant ID for contacts
            business_type: Optional business type (e.g., "telecom", "retail", "services")

        Returns:
            Created assistant dict

        Raises:
            ValueError: If owner already has an assistant (single-assistant mode)
        """
        # Initialize owner data if needed
        if owner_id not in self.data:
            self.data[owner_id] = {
                "owner_id": owner_id,
                "assistants": []
            }

        # SINGLE-ASSISTANT MODE: Check if owner already has an assistant
        existing_assistants = self.list_assistants(owner_id)
        if len(existing_assistants) >= 1:
            existing_id = existing_assistants[0]['id']
            raise ValueError(
                f"❌ Owner '{owner_id}' already has an assistant: '{existing_id}'\n"
                f"   For now, only ONE assistant per owner is supported.\n"
                f"   Use /assistant to view current assistant or /mrcall --id to link MrCall"
            )

        # Check if assistant already exists (shouldn't happen with single-assistant mode)
        existing = self.get_assistant(owner_id, zylch_assistant_id)
        if existing:
            raise ValueError(f"Assistant {zylch_assistant_id} already exists for owner {owner_id}")

        # Create assistant
        assistant = {
            "id": zylch_assistant_id,
            "name": name,
            "mrcall_assistant_id": mrcall_assistant_id,
            "business_type": business_type,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        self.data[owner_id]["assistants"].append(assistant)
        self._save()

        return assistant

    def update_assistant(
        self,
        owner_id: str,
        zylch_assistant_id: str,
        name: Optional[str] = None,
        mrcall_assistant_id: Optional[str] = None,
        business_type: Optional[str] = None
    ) -> Optional[Dict]:
        """Update assistant details.

        Args:
            owner_id: Owner identifier
            zylch_assistant_id: Assistant ID
            name: New name (optional)
            mrcall_assistant_id: New MrCall assistant ID (optional)
            business_type: New business type (optional)

        Returns:
            Updated assistant dict or None if not found
        """
        assistants = self.list_assistants(owner_id)

        for assistant in assistants:
            if assistant['id'] == zylch_assistant_id:
                # Update fields
                if name is not None:
                    assistant['name'] = name
                if mrcall_assistant_id is not None:
                    assistant['mrcall_assistant_id'] = mrcall_assistant_id
                if business_type is not None:
                    assistant['business_type'] = business_type

                assistant['updated_at'] = datetime.now().isoformat()
                self._save()
                return assistant

        return None

    def delete_assistant(self, owner_id: str, zylch_assistant_id: str) -> bool:
        """Delete an assistant.

        WARNING: This does NOT delete the assistant's data (memories, contacts).
        It only removes the assistant from the registry.

        Args:
            owner_id: Owner identifier
            zylch_assistant_id: Assistant ID

        Returns:
            True if deleted, False if not found
        """
        if owner_id not in self.data:
            return False

        assistants = self.data[owner_id].get("assistants", [])
        original_length = len(assistants)

        self.data[owner_id]["assistants"] = [
            a for a in assistants if a['id'] != zylch_assistant_id
        ]

        if len(self.data[owner_id]["assistants"]) < original_length:
            self._save()
            return True

        return False

    def link_mrcall_assistant(
        self,
        owner_id: str,
        zylch_assistant_id: str,
        mrcall_assistant_id: str
    ) -> Optional[Dict]:
        """Link a Zylch assistant to a MrCall/StarChat assistant.

        This allows the Zylch assistant to save contacts to the specified
        MrCall assistant in StarChat.

        Args:
            owner_id: Owner identifier
            zylch_assistant_id: Zylch assistant ID
            mrcall_assistant_id: MrCall/StarChat assistant ID

        Returns:
            Updated assistant dict or None if not found
        """
        return self.update_assistant(
            owner_id,
            zylch_assistant_id,
            mrcall_assistant_id=mrcall_assistant_id
        )
