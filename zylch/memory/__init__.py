"""Memory system for behavioral learning."""

import sys
from pathlib import Path

# Add zylch_memory to path
_zylch_memory_path = Path(__file__).parent.parent.parent / "zylch_memory"
if _zylch_memory_path.exists():
    sys.path.insert(0, str(_zylch_memory_path))

from zylch_memory.core import ZylchMemory
from zylch_memory.config import ZylchMemoryConfig

# Legacy imports for backward compatibility (deprecated)
from .reasoning_bank import ReasoningBankMemory

__all__ = ['ZylchMemory', 'ZylchMemoryConfig', 'ReasoningBankMemory']
