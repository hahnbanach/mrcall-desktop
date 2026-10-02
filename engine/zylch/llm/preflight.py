"""The pipeline's free preflight: can the selected transport bill a request? No inference.

The update pipeline used to find out whether AI was reachable by sending a
paid one-token ping before its LLM-bound stages (brief D3: a probe that
dispatches a paid call only to test the transport becomes a free check). The
check is now free:

- the model is admitted locally, as its first request would be at
  reservation — an unpriced model stops here, with the same ``BudgetError``;
- the credential is checked by a read that runs no model: Anthropic's
  ``GET /v1/models``, OpenRouter's ``GET /api/v1/key``, MrCall's bounded
  ``GET /capabilities`` plus the credit balance ``rpc/account.py`` reads.

A refused key (401) or an exhausted balance (402) raises what the ping raised
— the SDK's ``AuthenticationError`` on the direct transport, a ``BudgetError``
naming the status on the others — so the pipeline records it and
``humanize_error`` reports it exactly as before.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def check_transport(client: Any) -> None:
    """Raise when ``client``'s transport could not run a paid request; send nothing paid."""
    transport = client.transport
    if transport in ("direct", "openrouter"):
        from .budget_pricing import request_bound
        from .client import _with_datetime
        from .request_shape import shaped

        request = {
            "model": client.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "service_tier": "standard_only",
            "system": _with_datetime(None),
        }
        request_bound(shaped(request), transport)
    if transport == "direct":
        client._client.models.list(limit=1)
    elif transport in ("openrouter", "proxy"):
        client._client.check_account()
    logger.debug(f"[preflight] check_transport(transport={transport}, model={client.model}) -> ok")
