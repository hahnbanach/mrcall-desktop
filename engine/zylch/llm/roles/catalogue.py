"""Run-time reader of the model snapshot: request metadata and prices for any model id.

The snapshot (`snapshot.json`, contract schema 1: `contract/README.md`)
describes every catalogue model — picked, ranked or saved by hand — so a
model a profile names explicitly is shaped and priced whatever the picks
are. This module answers from it at call time:

- `metadata(model_id)` — `{reasoning: {mandatory, efforts, default_enabled},
  parameters, forced_tool, structured_outputs, context_length,
  expiration_date}` (a copy) for a catalogue id, a direct id, or a dated
  direct id (`<alias>-YYYYMMDD` resolves to its alias); None for an id no
  snapshot holds. The request shape reads it.
- `rates(model_id, transport)` — `(input, output)` in USD per million tokens
  as Decimals: on `openrouter` the catalogue entry's snapshot price (its
  reference price: the model-level price whenever an eligible endpoint is
  priced within it × the margin, else the lower-median eligible endpoint's;
  the model-level price too when its endpoints were not read, none is
  eligible or that price is not fixed, a variable one staying unpriced), on
  `direct` the direct id's (a dated id as its alias); None when the id is
  not priced there. `pricing` returns all four prices (cache read and write
  too); `endpoint_rates(model_id, tag)` an admitted endpoint's pair (K3's
  pinned provider caps K3); `endpoint_tags(model_id)` the tags of the
  admitted endpoints, the only ones an OpenRouter request may be routed to
  (`provider.only`; a `flex` service tier is never admitted, so never
  named); `policy()` the provider policy with the margin.

**Layers.** The build copy beside this module is always the last layer.
`set_layers(*snapshots)` puts other snapshots in front of it, newest first —
the run-time distribution (slice S6) passes the downloaded copy and the
last good copy, each already through `gates.check_snapshot` — and an id is
answered by the first layer that holds it, so an id only an older copy
still knows keeps its price (brief D5: refuse only an id in none of them).
`set_layers()` alone goes back to the build copy; `build=False` leaves the
build copy out (tests that pin a price on a fixture snapshot). Every call
reads the layers in force at that moment: nothing is frozen at import.
"""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

BUILD = Path(__file__).resolve().parent / "snapshot.json"
TRANSPORTS = ("direct", "openrouter")
DATED = re.compile(r"^(?P<alias>.+)-(?P<date>[0-9]{8})$")

# (front layers, whether the build copy is the last layer); replaced whole.
_state: tuple[tuple[dict, ...], bool] = ((), True)


@lru_cache(maxsize=1)
def _build() -> dict:
    return json.loads(BUILD.read_text(encoding="utf-8"))


def set_layers(*snapshots: dict, build: bool = True) -> None:
    """Put `snapshots` in front of the build copy, newest first."""
    global _state
    _state = (tuple(snapshots), build)


def layers() -> tuple[dict, ...]:
    """The snapshots an id is looked up in, in order."""
    front, build = _state
    return front + ((_build(),) if build else ())


def _find(model_id: object, section: str) -> dict | None:
    if not isinstance(model_id, str) or not model_id:
        return None
    for doc in layers():
        row = doc.get(section, {}).get(model_id)
        if row is not None:
            return row
    return None


def _direct(model_id: object) -> dict | None:
    row = _find(model_id, "direct")
    if row is None and isinstance(model_id, str):
        dated = DATED.match(model_id)
        if dated:
            row = _find(dated["alias"], "direct")
    return row


def metadata(model_id: object) -> dict | None:
    """The request metadata of a catalogue id, a direct id or a dated direct
    id (as its alias), or None."""
    row = _find(model_id, "models") or _direct(model_id)
    return copy.deepcopy(row["metadata"]) if row else None


def _decimal(price: str | None) -> Decimal | None:
    return None if price is None else Decimal(price)


def pricing(model_id: object, transport: str) -> dict | None:
    """`{input, output, cache_read, cache_write}` as Decimals (None where the
    catalogue has no price) for `model_id` on `transport`, or None."""
    if transport not in TRANSPORTS:
        raise ValueError(f"Unknown priced transport {transport!r}")
    row = _direct(model_id) if transport == "direct" else _find(model_id, "models")
    if row is None:
        return None
    return {side: _decimal(price) for side, price in row["pricing"].items()}


def rates(model_id: object, transport: str) -> tuple[Decimal, Decimal] | None:
    """`(input, output)` per million tokens for `model_id` on `transport`, or
    None when it has no input or no output price there."""
    prices = pricing(model_id, transport)
    if prices is None or prices["input"] is None or prices["output"] is None:
        return None
    return prices["input"], prices["output"]


def endpoint_rates(model_id: object, tag: str) -> tuple[Decimal, Decimal] | None:
    """`(input, output)` of the admitted endpoint `tag` of a catalogue id, as
    the first layer holding the model lists it, or None."""
    row = _find(model_id, "models")
    for endpoint in (row or {}).get("endpoints") or []:
        if endpoint["tag"] == tag:
            return Decimal(endpoint["pricing"]["input"]), Decimal(endpoint["pricing"]["output"])
    return None


def endpoint_tags(model_id: object) -> list[str] | None:
    """The sorted tags of a catalogue id's admitted endpoints, as the first
    layer holding the model lists them (an empty list when none is admitted),
    or None when that layer did not read its endpoints or no layer holds it."""
    row = _find(model_id, "models")
    if row is None or row.get("endpoints") is None:
        return None
    return sorted(endpoint["tag"] for endpoint in row["endpoints"])


def policy() -> dict:
    """The provider policy of the newest layer, the margin as a Decimal."""
    rules = layers()[0]["policy"]
    return {
        "margin": Decimal(rules["margin"]),
        "quantizations": list(rules["quantizations"]),
        "excluded_endpoint_variants": list(rules["excluded_endpoint_variants"]),
    }
