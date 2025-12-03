"""Sandbox module with mock data for safe tutorial demonstrations."""

from .mock_data import (
    MOCK_CONTACTS,
    MOCK_EMAILS,
    MOCK_EVENTS,
    MOCK_TASKS,
    get_mock_contact,
    get_mock_email_thread,
)

__all__ = [
    "MOCK_CONTACTS",
    "MOCK_EMAILS",
    "MOCK_EVENTS",
    "MOCK_TASKS",
    "get_mock_contact",
    "get_mock_email_thread",
]
