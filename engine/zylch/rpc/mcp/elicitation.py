import asyncio
import secrets
import time
from typing import Any

from zylch.workflows import admission, service
from zylch.workflows.errors import WorkflowError
from zylch.workflows.identity import current_identity

from .sessions import Session


async def start_legal(
    arguments: dict[str, Any], session: Session, queue: asyncio.Queue, config: dict[str, Any]
) -> dict[str, Any]:
    identity = current_identity()
    if session.uid != identity.uid or session.expires_at <= time.time():
        raise WorkflowError("interactive_admission_required")
    grant = admission.authenticated(identity, session.id, secrets.token_urlsafe(24))
    try:
        return await service.start(
            "cs-legal-research",
            arguments["message"],
            arguments.get("document_ids"),
            origin=admission.Origin.MCP_INTERACTIVE,
            admission=grant,
            legal_public_queries=arguments.get("public_queries", {}),
            legal_approved_urls=arguments.get("approved_urls", []),
        )
    except asyncio.CancelledError:
        try:
            await service.cancel(grant.run_id)
        except Exception:
            pass
        raise
    finally:
        admission._pending.pop(grant.token, None)
        admission._granted.discard(grant.token)
