"""The direct transport's keyword arguments for the ``anthropic`` 1.x SDK.

The 1.x SDK removed ``temperature``, ``top_p`` and ``top_k`` from
``messages.create`` — passing one is a ``TypeError`` raised before any
request is made — while the pricing quote, the MrCall proxy and the
OpenRouter client still read those keys from the same request dict. So the
dict that was priced and reserved stays intact and only the SDK call gets a
copy without them.

A non-default value (the intent classifier's ``temperature=0``) still
reaches the API through ``extra_body``, where the models that honour
sampling (the Claude 4.6 / 4.5 line, Haiku 4.5 included) apply it. A default
value is dropped: it is what the API assumes anyway, and Opus 4.7 and later
refuse any sampling field, the default included, so sending it would turn
every request on those models into a 400.

Found by milestone 9's paid corpus run: a fresh install resolves
``anthropic>=0.39.0`` to 1.x, and every real Anthropic call then failed
client-side with ``Messages.create() got an unexpected keyword argument
'temperature'`` (zero spend, the reservation left open).
"""

from __future__ import annotations

from typing import Any, Dict

from .roles.request_rules import apply as apply_request_rules

SAMPLING_KEYS = ("temperature", "top_p", "top_k")
SAMPLING_DEFAULTS: Dict[str, Any] = {"temperature": 1.0}


def sdk_request(request_kwargs: Dict[str, Any], transport: str) -> Dict[str, Any]:
    """Return what ``messages.create`` may receive on ``transport``.

    Only the ``direct`` transport talks to the official SDK; every other
    transport builds its own HTTP body from the full dict and is returned
    the dict unchanged, except ``proxy``, whose body the credits server
    quotes: there the model's request rules apply before the quote, so the
    quote, the reservation and the executed body are the same request. On
    ``direct`` the model's request rules (``roles/request_rules.py``) apply
    last.
    """
    if transport == "proxy":
        # The credits server quotes and runs this body: sampling and a forced
        # tool_choice the model refuses go before the quote, thinking is left.
        return apply_request_rules(request_kwargs, thinking=False)
    if transport != "direct":
        return request_kwargs
    kwargs = dict(request_kwargs)
    extra = dict(kwargs.get("extra_body") or {})
    for key in SAMPLING_KEYS:
        if key not in kwargs:
            continue
        value = kwargs.pop(key)
        if value is not None and value != SAMPLING_DEFAULTS.get(key):
            extra[key] = value
    if extra:
        kwargs["extra_body"] = extra
    # Then the fields this model refuses (roles/request_rules.py): after the
    # reservation, which priced the dict the caller still holds.
    return apply_request_rules(kwargs)
