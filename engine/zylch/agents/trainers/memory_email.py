"""Deprecated module — kept for backward compatibility only.

The trainer was renamed to ``zylch.agents.trainers.memory_message`` on
2026-05-08 (whatsapp-pipeline-parity Phase 2b). All public symbols are
re-exported here so existing imports keep working through one release;
new code should import from ``memory_message`` directly.
"""

from zylch.agents.trainers.memory_message import (  # noqa: F401
    EMAIL_AGENT_META_PROMPT,
    EmailMemoryAgentTrainer,
    MESSAGE_AGENT_META_PROMPT,
    MessageMemoryAgentTrainer,
)
