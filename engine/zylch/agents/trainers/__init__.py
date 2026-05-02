"""Agent trainers for learning from user data.

Trainers analyze user data (emails, calls, etc.) and generate personalized
prompts that are stored and used by the corresponding agents.

MrCall configurator/agent trainers belong to the platform
(`mrcall-agent` repo), not the desktop. The desktop is a consumer of
MrCall via StarChat — see `zylch.tools.starchat_firebase` and
`zylch.rpc.mrcall_actions`.
"""

from .base import BaseAgentTrainer
from .emailer import EmailerAgentTrainer
from .memory_email import EmailMemoryAgentTrainer
from .task_email import EmailTaskAgentTrainer

__all__ = [
    "BaseAgentTrainer",
    "EmailerAgentTrainer",
    "EmailMemoryAgentTrainer",
    "EmailTaskAgentTrainer",
]
