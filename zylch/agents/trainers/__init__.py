"""Agent trainers for learning from user data.

Trainers analyze user data (emails, calls, etc.) and generate personalized
prompts that are stored and used by the corresponding agents.
"""

from .base import BaseAgentTrainer
from .emailer import EmailerAgentTrainer
from .memory_email import EmailMemoryAgentTrainer
from .task_email import EmailTaskAgentTrainer

# MrCall trainers loaded lazily (files may not exist yet):
#   from .mrcall import MrCallAgentTrainer
#   from .memory_mrcall import MrCallMemoryTrainer
#   from .mrcall_configurator import MrCallConfiguratorTrainer

__all__ = [
    "BaseAgentTrainer",
    "EmailerAgentTrainer",
    "EmailMemoryAgentTrainer",
    "EmailTaskAgentTrainer",
]
