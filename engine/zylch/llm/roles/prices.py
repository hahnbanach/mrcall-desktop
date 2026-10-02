"""The one price source: USD per million tokens for a model on a transport.

Since milestone 10 (slice S3, brief D5) every price comes from the model
snapshot, read at each call through `catalogue.py` — the snapshots the
run-time distribution puts in front, newest first, then the build copy
`snapshot.json` beside this module — never frozen at import:

- on `openrouter` a catalogue id is priced at its snapshot price
  (`models[id].pricing`), its reference price: its model-level catalogue
  price whenever an eligible endpoint is priced within it × the margin,
  else its reference endpoint's — the lower median of its eligible
  endpoints by Artificial Analysis's blended price — and the model-level
  price too when its endpoints were not read, none is eligible or that
  price is not fixed (a variable one stays unpriced); what
  the preset ceilings compare and the margin multiplies into
  OpenRouter's `max_price` and the reservation (`openrouter_pricing.py`);
- on `direct` Anthropic's id is priced at its `anthropic` endpoint's price
  (`direct[id].pricing`, Anthropic's list price), and a dated id
  `<alias>-YYYYMMDD` at its alias's. The direct transport reserves at the
  list price; there is no provider cap to protect, so no margin.

Milestone 10a's two other price inputs are gone since the switch-over to the
measured table (slice S6): `requirements.json`'s `allowlist`, the billed rows
that answered, on their own transport, for an id no snapshot layer priced,
and the resolved table (`resolved.json`). The snapshot prices every catalogue
model, 10a's picks and every model its allowlist billed included, so 10a's
billed rates that were not catalogue prices have given way to the
snapshot's, and a model a profile saved stays priced as long as one
snapshot layer lists it.

An id in none of them has no price; callers refuse it with their own message.
Prices are `Decimal`, read from the JSON text, never from a float.
`priced(transport)` is a read-only mapping view over the same lookup, so
`model in priced(...)` and `priced(...)[model]` see a snapshot layer
installed after import. `margin()` and `quantizations()` are the spending
parameter and the provider policy of `requirements.json` that OpenRouter's
caps and routing use.
"""

import json
from collections.abc import Iterator, Mapping
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from . import catalogue

HERE = Path(__file__).resolve().parent
TRANSPORTS = ("direct", "openrouter")
# The snapshot section each transport's ids are listed in.
SECTIONS = {"direct": "direct", "openrouter": "models"}
Rate = tuple[Decimal, Decimal]


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"), parse_float=Decimal)


def price(model: object, transport: str) -> Rate | None:
    """``(input, output)`` per million tokens for `model` on `transport`, or None."""
    if transport not in TRANSPORTS:
        raise ValueError(f"Unknown priced transport {transport!r}")
    if not isinstance(model, str) or not model:
        return None
    return catalogue.rates(model, transport)


class Priced(Mapping):
    """Read-only ``{id: (input, output)}`` of every priced id on a transport.

    Nothing is copied: each lookup asks `price`, and iteration lists the ids
    of the layers in force, newest layer first, each id once however many
    layers list it."""

    def __init__(self, transport: str):
        if transport not in TRANSPORTS:
            raise ValueError(f"Unknown priced transport {transport!r}")
        self.transport = transport

    def __getitem__(self, model: object) -> Rate:
        rate = price(model, self.transport)
        if rate is None:
            raise KeyError(model)
        return rate

    def __contains__(self, model: object) -> bool:
        return price(model, self.transport) is not None

    def __iter__(self) -> Iterator[str]:
        section = SECTIONS[self.transport]
        listed = [model for doc in catalogue.layers() for model in doc.get(section, {})]
        for model in dict.fromkeys(listed):
            if model in self:
                yield model

    def __len__(self) -> int:
        return sum(1 for _ in self)


def priced(transport: str) -> Priced:
    """Read-only ``{id: (input, output)}`` of every priced id on `transport`:
    a view (`Priced`) that reads the layers in force at each lookup, never a copy."""
    return Priced(transport)


def margin() -> Decimal:
    """The factor (`requirements.json`, a spending parameter) on the snapshot's
    (reference) price that caps an OpenRouter request (`max_price`) and its
    reservation."""
    return Decimal(str(_load("requirements.json")["margin"]))


def quantizations() -> list[str]:
    """The endpoint quantizations an OpenRouter request may be routed to
    (`requirements.json`'s provider policy; an endpoint declaring none is
    `unknown`)."""
    return list(_load("requirements.json")["provider_policy"]["quantizations"])
