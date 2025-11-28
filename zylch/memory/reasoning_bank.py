"""ReasoningBank-inspired memory system for user behavioral learning.

Based on Google's ReasoningBank paper (2024):
- Strategy-level memory (not raw traces)
- Learn from both successes and failures
- Bayesian confidence updates
- Retrieval-augmented generation

Uses JSON file storage (like threads.json, tasks.json) for simplicity and consistency.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Channel types taxonomy
CHANNEL_TYPES = {
    'email': 'Email drafting and replies',
    'calendar': 'Calendar events and scheduling',
    'whatsapp': 'WhatsApp messaging',
    'mrcall': 'Phone call scripts and notes',
    'task': 'Zylch AI task management (descriptions, priorities)',
    # Future: 'slack', 'teams', 'sms', etc.
}


class ReasoningBankMemory:
    """User-scoped memory system for behavioral learning.

    Stores corrections from user feedback and applies them to future tasks.
    Uses Bayesian confidence updates to learn which corrections are reliable.

    Storage: JSON file (cache/memory_{user_id}.json)

    Architecture:
    - User-scoped: Each user has their own memory file
    - Contact-specific: Rules can apply to specific contacts or be general
    - Confidence-based: Rules gain/lose confidence based on outcomes
    - Strategy-level: Stores reasoning (why wrong, what to do), not raw text
    """

    def __init__(self, user_id: str, cache_dir: str = "cache"):
        """Initialize memory system for a user.

        Args:
            user_id: User identifier (e.g., 'mario', 'team_member_x')
            cache_dir: Cache directory path
        """
        self.user_id = user_id
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Personal memory file
        self.memory_file = self.cache_dir / f"memory_{user_id}.json"
        self._memory = self._load_memory(self.memory_file)

        # Global memory file (shared across all users)
        self.global_memory_file = self.cache_dir / "memory_global.json"
        self._global_memory = self._load_memory(self.global_memory_file)

        logger.info(
            f"Initialized ReasoningBankMemory for user '{user_id}' "
            f"({len(self._memory['corrections'])} personal, "
            f"{len(self._global_memory['corrections'])} global corrections)"
        )

    def _load_memory(self, file_path: Path) -> Dict:
        """Load memory from JSON file.

        Args:
            file_path: Path to memory file

        Returns:
            Memory dict
        """
        if file_path.exists():
            try:
                with open(file_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading memory file {file_path}: {e}")
                return self._empty_memory()
        return self._empty_memory()

    def _empty_memory(self) -> Dict:
        """Create empty memory structure."""
        return {
            "user_id": self.user_id,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "corrections": [],
            "applications": []
        }

    def _save_memory(self, is_global: bool = False):
        """Save memory to JSON file.

        Args:
            is_global: Save to global memory file instead of personal
        """
        if is_global:
            self._global_memory["last_updated"] = datetime.now().isoformat()
            file_path = self.global_memory_file
            memory_data = self._global_memory
            scope = "global"
        else:
            self._memory["last_updated"] = datetime.now().isoformat()
            file_path = self.memory_file
            memory_data = self._memory
            scope = f"user '{self.user_id}'"

        try:
            with open(file_path, 'w') as f:
                json.dump(memory_data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Memory saved for {scope}")
        except Exception as e:
            logger.error(f"Error saving memory file {file_path}: {e}")

    def _next_correction_id(self, is_global: bool = False) -> int:
        """Generate next correction ID.

        Args:
            is_global: Get ID from global memory instead of personal

        Returns:
            Next available ID
        """
        memory = self._global_memory if is_global else self._memory
        if not memory['corrections']:
            return 1
        return max(c['id'] for c in memory['corrections']) + 1

    def add_correction(
        self,
        what_went_wrong: str,
        correct_behavior: str,
        channel: str,
        attempted_text: Optional[str] = None,
        correct_text: Optional[str] = None,
        is_global: bool = False
    ) -> int:
        """Store a new correction from user feedback.

        Args:
            what_went_wrong: Description of the mistake (strategy-level)
            correct_behavior: What should have been done (strategy-level)
            channel: Channel type (required - see CHANNEL_TYPES)
            attempted_text: Optional - what AI wrote (example)
            correct_text: Optional - what it should have written (example)
            is_global: Store in global memory (shared across all users)

        Returns:
            Correction ID

        Example:
            # Personal correction for email channel
            memory.add_correction(
                what_went_wrong="Used 'tu' instead of 'lei'",
                correct_behavior="Always use 'lei' for formal communication",
                channel="email"
            )

            # Global correction for email channel (admin only)
            memory.add_correction(
                what_went_wrong="Did not check past communication style",
                correct_behavior="Always check past emails to detect tu/lei, formality",
                channel="email",
                is_global=True
            )
        """
        if channel not in CHANNEL_TYPES:
            raise ValueError(
                f"Invalid channel '{channel}'. Must be one of: {', '.join(CHANNEL_TYPES.keys())}"
            )

        correction_id = self._next_correction_id(is_global=is_global)

        correction = {
            "id": correction_id,
            "channel": channel,
            "what_went_wrong": what_went_wrong,
            "correct_behavior": correct_behavior,
            "attempted_text": attempted_text,
            "correct_text": correct_text,
            "confidence": 0.5,
            "times_applied": 0,
            "times_successful": 0,
            "created_at": datetime.now().isoformat(),
            "last_applied": None,
            "last_updated": datetime.now().isoformat()
        }

        if is_global:
            self._global_memory['corrections'].append(correction)
        else:
            self._memory['corrections'].append(correction)

        self._save_memory(is_global=is_global)

        scope = "global" if is_global else f"user '{self.user_id}'"
        logger.info(
            f"Added correction #{correction_id} ({scope}, channel={channel}): "
            f"{what_went_wrong[:50]}..."
        )

        return correction_id

    def get_relevant_memories(
        self,
        channel: str,
        min_confidence: float = 0.3,
        limit: int = 5,
        include_global: bool = True
    ) -> List[Dict]:
        """Retrieve relevant memories for current task.

        Retrieval strategy:
        - Only memories for the specified channel
        - Global rules (from memory_global.json) are always included if include_global=True
        - Personal rules for this user are included
        - Sorted by confidence (highest first)
        - Only rules above min_confidence threshold

        Args:
            channel: Channel type (required - see CHANNEL_TYPES)
            min_confidence: Minimum confidence threshold (0.0-1.0)
            limit: Max number of memories to return
            include_global: Include global memories (default True)

        Returns:
            List of correction dicts, sorted by confidence descending

        Example:
            memories = memory.get_relevant_memories(
                channel="email",
                min_confidence=0.4
            )
        """
        if channel not in CHANNEL_TYPES:
            raise ValueError(
                f"Invalid channel '{channel}'. Must be one of: {', '.join(CHANNEL_TYPES.keys())}"
            )

        results = []

        # Helper function to filter corrections
        def filter_correction(correction):
            # Channel filter (required!)
            if correction.get('channel') != channel:
                return False

            # Confidence filter
            if correction['confidence'] < min_confidence:
                return False

            return True

        # Add global memories
        if include_global:
            for correction in self._global_memory['corrections']:
                if filter_correction(correction):
                    # Add scope marker for debugging
                    correction_with_scope = correction.copy()
                    correction_with_scope['_scope'] = 'global'
                    results.append(correction_with_scope)

        # Add personal memories
        for correction in self._memory['corrections']:
            if filter_correction(correction):
                correction_with_scope = correction.copy()
                correction_with_scope['_scope'] = 'personal'
                results.append(correction_with_scope)

        # Sort by confidence (highest first), then by created_at (newest first)
        results.sort(key=lambda c: (-c['confidence'], c['created_at']), reverse=False)

        logger.debug(
            f"Retrieved {len(results[:limit])} memories for user '{self.user_id}' "
            f"(channel={channel}, "
            f"global={sum(1 for r in results[:limit] if r.get('_scope')=='global')}, "
            f"personal={sum(1 for r in results[:limit] if r.get('_scope')=='personal')})"
        )

        return results[:limit]

    def record_application(
        self,
        correction_id: int,
        was_successful: bool,
        task_type: str = "email_draft",
        feedback: Optional[str] = None,
        is_global: bool = False
    ):
        """Record that a memory was applied and update confidence.

        Bayesian confidence update:
        - Success: confidence += 0.15 * (1 - confidence)
        - Failure: confidence -= 0.10 * confidence

        This ensures:
        - Confidence converges toward 1.0 for reliable rules
        - Confidence converges toward 0.0 for unreliable rules
        - Updates are proportional to uncertainty

        Args:
            correction_id: ID of the correction that was applied
            was_successful: Did user accept the result?
            task_type: Type of task (e.g., 'email_draft', 'calendar_event', 'mrcall_script')
            feedback: Optional - user's feedback text
            is_global: Whether this is a global correction

        Example:
            memory.record_application(
                correction_id=5,
                was_successful=True,
                task_type="email_draft"
            )
        """
        # Determine which memory store to use
        memory_store = self._global_memory if is_global else self._memory

        # Log application
        application = {
            "correction_id": correction_id,
            "task_type": task_type,
            "was_successful": was_successful,
            "user_feedback": feedback,
            "applied_at": datetime.now().isoformat(),
            "scope": "global" if is_global else "personal"
        }
        memory_store['applications'].append(application)

        # Find and update correction
        correction = None
        for c in memory_store['corrections']:
            if c['id'] == correction_id:
                correction = c
                break

        if not correction:
            scope = "global" if is_global else f"user '{self.user_id}'"
            logger.warning(f"Correction #{correction_id} not found in {scope} memory")
            self._save_memory(is_global=is_global)
            return

        old_confidence = correction['confidence']
        correction['times_applied'] += 1

        if was_successful:
            correction['times_successful'] += 1
            # Increase confidence proportional to uncertainty
            delta = 0.15 * (1.0 - old_confidence)
            correction['confidence'] = old_confidence + delta
            action = "increased"
        else:
            # Decrease confidence proportional to current confidence
            delta = 0.10 * old_confidence
            correction['confidence'] = old_confidence - delta
            action = "decreased"

        # Clamp to [0, 1]
        correction['confidence'] = max(0.0, min(1.0, correction['confidence']))
        correction['last_applied'] = datetime.now().isoformat()
        correction['last_updated'] = datetime.now().isoformat()

        self._save_memory(is_global=is_global)

        scope = "global" if is_global else f"user '{self.user_id}'"
        logger.info(
            f"Correction #{correction_id} ({scope}) applied ({'success' if was_successful else 'failure'}): "
            f"confidence {old_confidence:.2f} → {correction['confidence']:.2f} ({action})"
        )

    def build_memory_prompt(
        self,
        channel: str,
        task_description: Optional[str] = None,
        min_confidence: float = 0.3
    ) -> str:
        """Build prompt section with relevant memories to inject into LLM.

        Returns formatted string that highlights learned behavioral rules.
        Uses emojis and formatting to make rules clear to the LLM.

        Args:
            channel: Channel type (required - see CHANNEL_TYPES)
            task_description: Optional description of current task (auto-generated if None)
            min_confidence: Minimum confidence to include

        Returns:
            String to inject into LLM prompt (empty if no memories)

        Example:
            prompt = memory.build_memory_prompt(
                channel="email",
                task_description="writing a follow-up email"
            )
        """
        memories = self.get_relevant_memories(
            channel=channel,
            min_confidence=min_confidence
        )

        if not memories:
            return ""

        # Auto-generate task description if not provided
        if not task_description:
            task_description = f"using {channel} channel"

        prompt = f"\n## IMPORTANT: Learned Behavioral Rules for User {self.user_id}\n\n"
        prompt += f"When {task_description}, apply these corrections from past feedback:\n\n"

        for i, mem in enumerate(memories, 1):
            # Confidence emoji indicator
            conf = mem['confidence']
            if conf > 0.7:
                confidence_emoji = "🟢"  # High confidence
            elif conf > 0.4:
                confidence_emoji = "🟡"  # Medium confidence
            else:
                confidence_emoji = "🔴"  # Low confidence

            # Scope indicator (global vs personal)
            scope = mem.get('_scope', 'personal')
            scope_indicator = "🌍" if scope == 'global' else "👤"

            # Channel indicator
            channel_label = mem.get('channel', 'unknown').upper()

            # Scope description
            if scope == 'global':
                scope_note = " (global - applies to all users)"
            else:
                scope_note = f" (personal for {self.user_id})"

            prompt += f"{i}. {scope_indicator} [{channel_label}]{scope_note} {confidence_emoji}\n"
            prompt += f"   - ❌ Problem: {mem['what_went_wrong']}\n"
            prompt += f"   - ✅ Correct: {mem['correct_behavior']}\n"

            # Add examples if available
            if mem.get('attempted_text') and mem.get('correct_text'):
                prompt += f"   - Example:\n"
                prompt += f"     - Wrong: \"{mem['attempted_text'][:100]}...\"\n"
                prompt += f"     - Right: \"{mem['correct_text'][:100]}...\"\n"

            # Confidence stats
            success_rate = (mem['times_successful'] / mem['times_applied']) if mem['times_applied'] > 0 else 0.0
            prompt += f"   - Confidence: {mem['confidence']:.0%} "
            prompt += f"({mem['times_successful']}/{mem['times_applied']} successes)\n\n"

        prompt += "⚠️ CRITICAL: Apply these rules STRICTLY. They come from explicit user corrections.\n\n"

        return prompt

    def get_stats(self, scope: str = "all") -> Dict:
        """Get memory bank statistics.

        Args:
            scope: 'all', 'personal', or 'global'

        Returns:
            Dict with statistics about corrections and learning

        Example:
            stats = memory.get_stats(scope="all")
            # {
            #   'user_id': 'mario',
            #   'scope': 'all',
            #   'total_corrections': 12,
            #   'personal_corrections': 9,
            #   'global_corrections': 3,
            #   'avg_confidence': 0.73,
            #   'total_applications': 47,
            #   'total_successes': 38,
            #   'success_rate': 0.81,
            #   'by_channel': {'email': 5, 'calendar': 3, 'whatsapp': 4},
            #   'by_scope': {'personal': 9, 'global': 3}
            # }
        """
        def compute_stats(corrections, label):
            if not corrections:
                return {
                    "total_corrections": 0,
                    "avg_confidence": 0.0,
                    "total_applications": 0,
                    "total_successes": 0,
                    "success_rate": 0.0,
                    "by_channel": {},
                    "high_confidence_rules": 0
                }

            total_applications = sum(c['times_applied'] for c in corrections)
            total_successes = sum(c['times_successful'] for c in corrections)

            # Count by channel
            by_channel = {}
            for c in corrections:
                ch = c.get('channel', 'unknown')
                by_channel[ch] = by_channel.get(ch, 0) + 1

            # High confidence count
            high_confidence = sum(1 for c in corrections if c['confidence'] >= 0.7)

            return {
                "total_corrections": len(corrections),
                "avg_confidence": sum(c['confidence'] for c in corrections) / len(corrections),
                "total_applications": total_applications,
                "total_successes": total_successes,
                "success_rate": (total_successes / total_applications) if total_applications > 0 else 0.0,
                "by_channel": by_channel,
                "high_confidence_rules": high_confidence
            }

        # Gather corrections based on scope
        all_corrections = []
        if scope in ["all", "personal"]:
            all_corrections.extend(self._memory['corrections'])
        if scope in ["all", "global"]:
            all_corrections.extend(self._global_memory['corrections'])

        overall_stats = compute_stats(all_corrections, scope)
        overall_stats['user_id'] = self.user_id
        overall_stats['scope'] = scope

        # Add breakdown by scope if "all"
        if scope == "all":
            overall_stats['personal_corrections'] = len(self._memory['corrections'])
            overall_stats['global_corrections'] = len(self._global_memory['corrections'])
            overall_stats['by_scope'] = {
                'personal': len(self._memory['corrections']),
                'global': len(self._global_memory['corrections'])
            }

        return overall_stats

    def delete_correction(self, correction_id: int, is_global: bool = False) -> bool:
        """Delete a correction from memory.

        Args:
            correction_id: ID of correction to delete
            is_global: Delete from global memory instead of personal

        Returns:
            True if deleted, False if not found
        """
        memory_store = self._global_memory if is_global else self._memory
        scope = "global" if is_global else f"user '{self.user_id}'"

        original_count = len(memory_store['corrections'])
        memory_store['corrections'] = [
            c for c in memory_store['corrections'] if c['id'] != correction_id
        ]

        if len(memory_store['corrections']) < original_count:
            # Also remove applications
            memory_store['applications'] = [
                a for a in memory_store['applications'] if a['correction_id'] != correction_id
            ]
            self._save_memory(is_global=is_global)
            logger.info(f"Deleted correction #{correction_id} from {scope} memory")
            return True

        logger.warning(f"Correction #{correction_id} not found in {scope} memory")
        return False

    def export_memories(self, scope: str = "all") -> List[Dict]:
        """Export memories for backup or analysis.

        Args:
            scope: 'all', 'personal', or 'global'

        Returns:
            List of corrections with full details
        """
        results = []

        if scope in ["all", "global"]:
            global_corrections = [
                {**c, '_scope': 'global'} for c in self._global_memory['corrections']
            ]
            results.extend(global_corrections)

        if scope in ["all", "personal"]:
            personal_corrections = [
                {**c, '_scope': 'personal'} for c in self._memory['corrections']
            ]
            results.extend(personal_corrections)

        logger.info(
            f"Exported {len(results)} memories "
            f"(scope={scope}, user='{self.user_id}')"
        )
        return results

    def get_correction_by_id(self, correction_id: int, is_global: Optional[bool] = None) -> Optional[Dict]:
        """Get a specific correction by ID.

        Args:
            correction_id: Correction ID
            is_global: If None, search both; if True, search only global; if False, search only personal

        Returns:
            Correction dict or None if not found (includes '_scope' marker)
        """
        # Search personal memory
        if is_global is None or is_global is False:
            for c in self._memory['corrections']:
                if c['id'] == correction_id:
                    return {**c, '_scope': 'personal'}

        # Search global memory
        if is_global is None or is_global is True:
            for c in self._global_memory['corrections']:
                if c['id'] == correction_id:
                    return {**c, '_scope': 'global'}

        return None
