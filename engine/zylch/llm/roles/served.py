"""What the MrCall billing server serves, and the credits choice (brief D6; `contract/protocol-v2.md`).

For an automatic choice on MrCall credits the engine runs the first id of
the role's ranking (`roles/table.py`, the same ranking a personal OpenRouter
key runs, so paying with credits never moves a choice) that the billing
server publishes on its v2 ``GET /capabilities?protocol=mrcall-bounded-v2``:
the direct id when the server lists that as Anthropic's (``provider:
anthropic``), else the catalogue id when it lists that (``provider:
openrouter``). An explicit choice (a model the profile saved) never comes
here: it is sent as saved, and the server prices any model its snapshot
prices.

- `served(url)` reads the server's model list through `bounded_proxy`
  (5-second timeout) at most once an hour per server (`CACHE_SECONDS`) and
  keeps the last good answer; `cached(url)` returns that answer without any
  network, which is what `model_policy.policy_fingerprint` resolves from.
  The reader is a seam (`_reader`, a `BoundedProxyClient` on the signed-in
  session), so no test reaches a server.
- `choose` is the choice itself, pure; a role none of whose ranked models
  the server serves pauses with `NO_SERVED_MODEL`, naming the role.
- An answer in another protocol than ``mrcall-bounded-v2`` (a v1 server)
  pauses with "update the billing server", and a malformed model list is an
  explicit error (`MALFORMED`): nothing is ever guessed, and a failed read is
  never cached.
"""

from __future__ import annotations

import logging
import threading
import time

from ..bounded_proxy import MALFORMED, PROTOCOL, UPDATE_SERVER
from ..budget_pricing import BudgetError
from . import table

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60 * 60
PROVIDERS = ("anthropic", "openrouter")
NO_SERVED_MODEL = (
    "AI paused: no model served for role {role}: the MrCall billing server serves none "
    "of the models ranked for it under the {preset} preset. {remedy}"
)
UNREAD = "AI paused: the MrCall billing server's model catalogue has not been read yet."

# The monotonic clock the cache ages by (a seam for tests).
_clock = time.monotonic
_lock = threading.Lock()
# billing server URL -> (when read, the validated model list)
_cache: dict[str, tuple[float, tuple[dict, ...]]] = {}


def parse(answer: object) -> tuple[dict, ...]:
    """The ``{id, label, provider}`` entries of a v2 capabilities answer.

    Pauses with "update the billing server" unless the answer speaks
    ``mrcall-bounded-v2``; refuses, with `MALFORMED`, a currency other than
    USD or a model list that is not a list of entries with a non-empty string
    id, label and provider, the provider ``anthropic`` or ``openrouter``. The
    added v2 fields (`price`, `as_of`, `table_version`, `roles`) are not needed
    for the choice and are not read. An empty list is a valid answer: the
    server serves nothing, so every automatic credits choice pauses.
    """
    if not isinstance(answer, dict):
        raise BudgetError(MALFORMED)
    if answer.get("protocol") != PROTOCOL:
        raise BudgetError(UPDATE_SERVER)
    models = answer.get("models")
    if answer.get("currency") != "USD" or not isinstance(models, list):
        raise BudgetError(MALFORMED)
    entries = []
    for model in models:
        if (
            not isinstance(model, dict)
            or not all(isinstance(model.get(k), str) and model[k] for k in ("id", "label"))
            or model.get("provider") not in PROVIDERS
        ):
            raise BudgetError(MALFORMED)
        entries.append({key: model[key] for key in ("id", "label", "provider")})
    return tuple(entries)


def _reader(url: str):
    from zylch.auth import get_session

    from ..bounded_proxy import BoundedProxyClient

    return BoundedProxyClient(url, get_session())


def served(url: str, *, client=None) -> tuple[dict, ...]:
    """The models the billing server at `url` serves: the last answer when it
    is under an hour old, else a fresh read (through `client`, by default a
    `BoundedProxyClient` on the signed-in session) that replaces it."""
    with _lock:
        hit = _cache.get(url)
        if hit is not None and _clock() - hit[0] < CACHE_SECONDS:
            return hit[1]
    models = parse((client or _reader(url)).capabilities())
    with _lock:
        _cache[url] = (_clock(), models)
    logger.debug(f"[served] served(url={url}) -> {len(models)} models")
    return models


def cached(url: str) -> tuple[dict, ...] | None:
    """The last model list read from `url`, whatever its age, or None; no network."""
    with _lock:
        hit = _cache.get(url)
    return hit[1] if hit is not None else None


def choose(preset: str, role: str, ranking: list[dict], models: tuple[dict, ...]) -> str:
    """The first entry of `ranking` the server serves: its direct id when listed
    as Anthropic's, else its catalogue id when listed as OpenRouter's."""
    providers = {model["id"]: model["provider"] for model in models}
    for entry in ranking:
        direct = entry.get("direct_id")
        if direct and providers.get(direct) == "anthropic":
            return direct
        if providers.get(entry["id"]) == "openrouter":
            return entry["id"]
    fix = table.remedy(role, "a model the billing server serves")
    raise table.RolePaused(unserved_pause(role, preset), role, preset, fix)


def unserved_pause(role: str, preset: str) -> str:
    """`NO_SERVED_MODEL` for `role` under `preset`, with its remedy (`table.remedy`)."""
    remedy = table.remedy(role, "a model the billing server serves")
    return NO_SERVED_MODEL.format(role=role, preset=preset, remedy=remedy)


def pick(preset: str, role: str, url: str, *, online: bool = True, client=None) -> str:
    """The credits model of `role` under `preset`: `choose` over the role's
    ranking and the server's list — read (`served`) when `online`, else the
    cached one only (no network; `UNREAD` when nothing was read yet)."""
    ranking = table.ranking(preset, role)
    models = served(url, client=client) if online else cached(url)
    if models is None:
        raise BudgetError(UNREAD)
    return choose(preset, role, ranking, models)
