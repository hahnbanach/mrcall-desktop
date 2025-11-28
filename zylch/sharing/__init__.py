"""Intelligence Sharing package for Zylch.

Enables users to share contact intelligence with other authorized Zylch users.
"""

from .authorization import SharingAuthorizationManager
from .intel_share import IntelShareManager

__all__ = [
    "SharingAuthorizationManager",
    "IntelShareManager",
]
