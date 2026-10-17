"""The last gate before a transport dispatches: no sampling, and the direct binding.

The 1.x SDK removed ``temperature``, ``top_p`` and ``top_k`` from
``messages.create`` — passing one is a ``TypeError`` raised before any
request is made. Milestone 10's one request shape (``request_shape.py``,
brief D3) removes them from every request before admission; this module
repeats the removal on every transport, at the top level and in
``extra_body``, for the requests the shape leaves to their adapter (K3,
whose adapter sends its own default) and for the voice notes, which still
pass ``temperature=`` through ``**kwargs``. A sampling value no longer
reaches any provider: Opus 4.7 and later refuse any sampling field, the
default included, and the one shape is the same for every model.

On the direct transport, a request with adaptive reasoning also gets
Anthropic's ``block_binding`` with ``prefix_mismatch_behavior: drop_block``
and its beta header: a reasoning block replayed after an edit of the
conversation before it is then dropped (and reported in
``input_transformations``) instead of failing the request. Only the SDK call
gets these; the dict that was priced and reserved stays intact.

Found by milestone 9's paid corpus run: a fresh install resolves
``anthropic>=0.39.0`` to 1.x, and every real Anthropic call then failed
client-side with ``Messages.create() got an unexpected keyword argument
'temperature'`` (zero spend, the reservation left open).
"""

from __future__ import annotations

from typing import Any, Dict

SAMPLING_KEYS = ("temperature", "top_p", "top_k")
BINDING_BETA = "thinking-binding-controls-2026-08-01"
DROP_BLOCK = {"prefix_mismatch_behavior": "drop_block"}


def without_sampling(request: Dict[str, Any]) -> Dict[str, Any]:
    """``request`` without sampling fields; the same object when it carries none."""
    extra = request.get("extra_body")
    in_extra = isinstance(extra, dict) and any(key in extra for key in SAMPLING_KEYS)
    if not in_extra and not any(key in request for key in SAMPLING_KEYS):
        return request
    out = {key: value for key, value in request.items() if key not in SAMPLING_KEYS}
    if in_extra:
        kept = {key: value for key, value in extra.items() if key not in SAMPLING_KEYS}
        if kept:
            out["extra_body"] = kept
        else:
            out.pop("extra_body")
    return out


def sdk_request(request_kwargs: Dict[str, Any], transport: str) -> Dict[str, Any]:
    """Return what ``messages.create`` may receive on ``transport``.

    Every transport gets the request without sampling: ``proxy`` before its
    quote, whose body the credits server quotes and runs, so the quote, the
    reservation and the executed body are the same request; ``openrouter``
    and ``openai_voice``, which build their own HTTP body from the dict.
    Only ``direct`` talks to the official SDK, and only there does adaptive
    reasoning gain the ``drop_block`` binding and its beta header, after the
    reservation, which priced the dict the caller still holds.
    """
    kwargs = without_sampling(request_kwargs)
    thinking = kwargs.get("thinking")
    if transport != "direct" or not (
        isinstance(thinking, dict) and thinking.get("type") == "adaptive"
    ):
        return kwargs
    kwargs = dict(kwargs)
    kwargs["thinking"] = {**thinking, "block_binding": dict(DROP_BLOCK)}
    headers = dict(kwargs.get("extra_headers") or {})
    betas = [beta.strip() for beta in str(headers.get("anthropic-beta") or "").split(",")]
    betas = [beta for beta in betas if beta]
    if BINDING_BETA not in betas:
        betas.append(BINDING_BETA)
    headers["anthropic-beta"] = ",".join(betas)
    kwargs["extra_headers"] = headers
    return kwargs
