"""Authorize content reuse by the authenticated owner of the selected profile."""

import logging
from collections.abc import Callable
from pathlib import Path

from zylch.qonto.errors import QontoError
from zylch.qonto.history_errors import HistoryAuthorizationError

logger = logging.getLogger(__name__)


def _owner() -> tuple[str, Path] | None:
    from zylch.auth import get_session
    from zylch.qonto.identity import profile_identity

    try:
        uid, directory = profile_identity()
        session = get_session()
        if session is None or session.uid != uid or session.is_expired():
            return None
        return uid, directory
    except (QontoError, OSError, ValueError, RuntimeError):
        return None


def content_recheck() -> Callable[[], None] | None:
    """Pin real owner identity; text similarity is not an authorization boundary.

    No bank connection is required to reuse the owner's existing content.
    Resource access and managed-history binding keep their separate guards.
    """
    owner = _owner()
    if owner is None:
        return None
    logger.debug("[finance-content] authenticated profile owner may reuse content")

    def recheck() -> None:
        if _owner() != owner:
            raise HistoryAuthorizationError("history_unavailable")

    return recheck
