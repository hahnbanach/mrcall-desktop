"""Company memory key RPCs — mint and validate.

The key is a capability: a fresh one starts a new company memory, an
existing one joins it. The engine mints (the app has no generator
surface, and a sidecar exists only once account creation is finalized);
the app collects a pasted key at the onboarding form and acts on it here
after ``finalize``.

At this milestone ``memory.key_validate`` checks SHAPE only. Existence —
"is there a company store this key names?" — is a question the store
answers once memory lives in one file per company; until then the only
key a profile can know is its own.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


async def memory_key_mint(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """memory.key_mint() -> {key, minted}.

    Ensure this profile has a company memory key and return it in clear:
    the show-once moment right after account creation. ``minted`` says
    whether this call created it or the profile already had one (the
    engine also mints on first boot, so a profile that booted before the
    app asked already holds a key — this returns that one). The caller is
    the profile's own owner over an authenticated channel, the same trust
    ``settings.get_secret`` extends.
    """
    from zylch.memory.company_key import current_company_key, ensure_company_key

    had = current_company_key() is not None
    key = ensure_company_key()
    logger.info(f"[rpc] memory.key_mint -> minted={not had}")
    return {"key": key, "minted": not had}


async def memory_key_validate(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """memory.key_validate(key?) -> {well_formed, reason}.

    Shape check: 22 URL-safe base64 characters decoding to 16 bytes — the
    128 bits a minted key carries. Never raises for a bad or missing key —
    a refusal is an answer about the key, not a transport error, which is
    why ``key`` is declared optional (the engine's rule: a param is
    required only where the handler cannot answer without it). ``reason``
    is empty when ``well_formed``.
    """
    from zylch.memory.company_key import well_formed

    key = params.get("key")
    ok, reason = well_formed(key if isinstance(key, str) else None)
    logger.debug(f"[rpc] memory.key_validate -> well_formed={ok}")
    return {"well_formed": ok, "reason": reason}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "memory.key_mint": memory_key_mint,
    "memory.key_validate": memory_key_validate,
}
