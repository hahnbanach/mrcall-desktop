"""Factory: StarChat client wired to the active Firebase session.

The desktop's MrCall integration is signin-driven: the renderer holds
the user's Firebase ID token, pushes it to the engine via
`account.set_firebase_token`, and the engine then uses that token as
the StarChat Bearer credential. This module is the small bridge that
turns the cached `FirebaseSession` into a configured `StarChatClient`.

Why this lives in `zylch.tools` (not `zylch.tools.mrcall`):
  - `zylch/tools/mrcall/__init__.py` currently imports several modules
    that do not exist in this checkout (`variable_utils`, `llm_helper`,
    `config_tools`, `feature_context_tool` — leftovers from a partially
    landed refactor). Anything we add inside that package would chain a
    broken import every time the dispatcher loaded.
  - `tools/starchat.py` is the generic, multi-auth StarChat client this
    module composes; a sibling under `tools/` is the natural home.

This module always picks `auth_type="firebase"` and pulls the JWT from
`zylch.auth.require_session()`, so callers don't have to know about
sessions or thread the token through their own plumbing.

Tokens are NOT refreshed here — refresh is renderer-driven (Firebase JS
SDK in the renderer pushes a new id_token every ~50 minutes). If a call
ever fails with 401 the right answer is "tell the renderer to push a
fresh token", not "refresh on the engine side".
"""

from __future__ import annotations

import logging
from typing import Optional

from zylch.auth import FirebaseSession, require_session
from zylch.config import settings
from zylch.tools.starchat import StarChatClient

logger = logging.getLogger(__name__)


def make_starchat_client_from_firebase_session(
    *,
    realm: Optional[str] = None,
    timeout: int = 30,
) -> StarChatClient:
    """Build a StarChatClient bound to the active Firebase session.

    Raises `NoActiveSession` if no token is cached. Callers should let
    that bubble up — the JSON-RPC dispatcher maps it to error code
    -32010 with a clear "sign in first" message.
    """
    session: FirebaseSession = require_session()
    effective_realm = realm or settings.mrcall_realm

    logger.debug(
        f"[mrcall] making StarChat client uid={session.uid} "
        f"email={session.email!r} realm={effective_realm}"
    )
    return StarChatClient(
        base_url=settings.mrcall_base_url,
        auth_type="firebase",
        jwt_token=session.id_token,
        realm=effective_realm,
        timeout=timeout,
        verify_ssl=settings.starchat_verify_ssl,
        owner_id=session.uid,
    )
