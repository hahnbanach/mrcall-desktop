"""Zylch Agents - User-facing conversational agents.

Agents are user-facing components that process user requests and
provide intelligent responses. They use trained prompts and tools.

For background data processors, see zylch.workers.
For agent trainers, see zylch.agents.trainers.
"""

from .base_agent import SpecializedAgent
from .emailer_agent import EmailerAgent, EmailContext, EmailContextGatherer
from .mrcall_agent import MrCallAgent

__all__ = [
    # Base classes
    "SpecializedAgent",
    # Agents
    "EmailerAgent",
    "EmailContext",
    "EmailContextGatherer",
    "MrCallAgent",
]
