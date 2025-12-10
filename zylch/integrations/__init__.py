"""
Integration management system for Zylch.

This module provides a unified interface for managing external service connections
(email, CRM, messaging, telephony, etc.).
"""

from .registry import (
    get_available_providers,
    get_user_connections,
    get_connection_status,
    detect_provider_from_email,
    PROVIDER_CATEGORIES
)

__all__ = [
    'get_available_providers',
    'get_user_connections',
    'get_connection_status',
    'detect_provider_from_email',
    'PROVIDER_CATEGORIES'
]
