# Credits protocol v2: `mrcall-bounded-v2`

Scope: what the engine and the MrCall billing server exchange on the bounded
credits routes (`/api/desktop/llm/bounded/...`) when the engine marks a
request as v2, with one example per call. v1, `mrcall-bounded-v1`, is the
contract of every released engine (`engine/zylch/llm/bounded_proxy.py` on
`main`): a request without the marker is v1, and the server keeps today's
semantics for it. Only what changes is written here; everything else —
authentication (`auth: <Firebase ID token>`), the business id, the quote
and receipt arithmetic, `payload_hash` and `quote_hash` (SHA-256 of the
canonical JSON, as `bounded_proxy.digest` computes them), the status route,
the HTTP error codes — is v1's.

## The marker and the answer

- `GET /capabilities?protocol=mrcall-bounded-v2`.
- `POST /quote` and `POST /execute`: `"protocol": "mrcall-bounded-v2"`
  beside `request` in the body. In execute it is part of the binding hash
  the server checks a replay against. It is not inside `request`, so
  `payload_hash` (the digest of `request`) is computed as in v1.
- The server answers v2 with `"protocol": "mrcall-bounded-v2"` in the
  capabilities, the quote and the receipt, and the quote names the snapshot
  it priced with (`snapshot_version`, the snapshot's `version`); execute
  prices with that same snapshot.
- A marked call answered as v1 (or with any other protocol) makes the
  engine pause with "update the billing server". It never falls back to v1.

## What a v2 request and response carry

- Requests have the one shape of the engine (brief D3): no `temperature`,
  `top_p` or `top_k`; `tool_choice` never forced (`auto`); `strict: true`
  on a tool whose schema allows it; reasoning from the model's snapshot
  metadata — `thinking: {"type": "adaptive"}` with `output_config:
  {"effort": <lowest published>}` for a model that publishes efforts, the
  efforts counted being only the request vocabulary `low`, `medium`,
  `high`, `xhigh`, `max` (a published `minimal` or `none` is not a value
  the Messages API accepts, so a model publishing `minimal` and `low` gets
  `low`), or `thinking: {"type": "disabled"}` for one that publishes none
  and whose reasoning is optional and on by default; and, in assistant
  turns of the history, reasoning blocks returned earlier (`thinking` with
  its `signature`, `redacted_thinking` with its `data`), unchanged. A
  `thinking` block that came back without a `signature` (OpenRouter may
  omit it for a non-Anthropic model) is not replayed: the engine drops it
  from the history it sends, because the Messages API requires a
  signature on every replayed `thinking` block and no provider verifies an
  unsigned one. The server accepts an unsigned `thinking` block in
  history from a client that sends one and strips it before forwarding.
- Responses return reasoning blocks: `message.content` holds `thinking`
  and `redacted_thinking` blocks beside `text` and `tool_use`, in the
  order the model produced them.
- K3 is routed to its adapter by its id, not by the presence of
  `thinking`; the adapter is unchanged (adaptive reasoning at `max` effort,
  its pinned provider) and its responses carry no reasoning blocks.
- On OpenRouter the server applies the snapshot's provider policy (no
  fallbacks, parameters required, price sorting, `policy.quantizations`,
  the excluded service tiers) and `max_price` = the model-level price ×
  `policy.margin`; K3's cap is its pinned endpoint's price × the margin,
  or, on a day that endpoint is not admitted (absent from the snapshot's
  `endpoints`), its model-level price × the margin (README, "Prices in
  use").
- Quote and execute accept any model the snapshot prices, excluded
  families included (an explicit choice keeps running); an unpriced id is a
  400 with its reason. Pre-authorisation prices from the snapshot × the
  margin; settlement stays the actual cost × the tariff. The response-model
  check accepts the requested id or `<requested>-YYYYMMDD`.

## Capabilities

`GET /api/desktop/llm/bounded/capabilities?protocol=mrcall-bounded-v2`

```json
{
  "protocol": "mrcall-bounded-v2",
  "currency": "USD",
  "streaming": false,
  "features": ["text", "function_tools"],
  "max_tokens": 8192,
  "models": [
    {
      "id": "claude-sonnet-5-5",
      "label": "Claude Sonnet 5.5",
      "provider": "anthropic",
      "price": "15",
      "as_of": "2026-10-02T13:36:42Z",
      "table_version": "cd6f17cd6c8262a59a3528b169a26f1aa8d1c5f0dad2021aa29465b71aadaafb",
      "roles": [
        {"preset": "economy", "role": "CHAT", "rank": 1},
        {"preset": "balanced", "role": "CHAT", "rank": 2}
      ]
    },
    {
      "id": "moonshotai/kimi-k3",
      "label": "Kimi K3",
      "provider": "openrouter",
      "price": "20.25",
      "as_of": "2026-10-02T13:36:42Z",
      "table_version": "cd6f17cd6c8262a59a3528b169a26f1aa8d1c5f0dad2021aa29465b71aadaafb",
      "roles": [
        {"preset": "balanced", "role": "CHAT", "rank": 4},
        {"preset": "balanced", "role": "MNEMONIC", "rank": 2}
      ]
    }
  ]
}
```

Every model keeps v1's `{id, label, provider}` (`provider` is `anthropic`
for a direct id, `openrouter` for a catalogue id) and adds `price` (USD per
million output tokens with the markup included: the snapshot's output
price × `markup_factor`), `as_of` (the snapshot's `read_at`),
`table_version` (the table's `version`) and `roles`: every preset and role
whose `ranking` lists it, with its 1-based `rank`. To a marked client the
list is the union of the published rankings plus K3 (whose `roles` may be
empty); an unmarked client gets v1's schema and drivable list, and ignores
the added fields.

## Quote

`POST /api/desktop/llm/bounded/quote`

```json
{
  "protocol": "mrcall-bounded-v2",
  "business_id": "biz-123",
  "request": {
    "model": "claude-sonnet-5-5",
    "max_tokens": 3072,
    "system": "You file the user's tasks.",
    "messages": [
      {"role": "user", "content": "Remind me to call the plumber on Friday."}
    ],
    "tools": [
      {
        "name": "create_task",
        "description": "Create one task.",
        "input_schema": {
          "type": "object",
          "properties": {"title": {"type": "string"}, "due": {"type": "string"}},
          "required": ["title", "due"],
          "additionalProperties": false
        },
        "strict": true
      }
    ],
    "tool_choice": {"type": "auto"},
    "thinking": {"type": "adaptive"},
    "output_config": {"effort": "low"}
  }
}
```

```json
{
  "protocol": "mrcall-bounded-v2",
  "currency": "USD",
  "account_id": "firebase-uid-123",
  "business_id": "biz-123",
  "payload_hash": "<SHA-256 of the canonical request>",
  "tariff_version": "<SHA-256 of the tariff>",
  "model": "claude-sonnet-5-5",
  "credit_value_micro_usd": 11000,
  "markup_factor": "1.5",
  "max_credits": 6,
  "max_debit_micro_usd": 66000,
  "snapshot_version": "f04f27349de6020e09f5bc28745af01981b3ff3935c1d594fedf094f211d7fa7",
  "quote_hash": "<SHA-256 of this quote without quote_hash>"
}
```

## Execute

`POST /api/desktop/llm/bounded/execute`

```json
{
  "protocol": "mrcall-bounded-v2",
  "business_id": "biz-123",
  "request": {"model": "claude-sonnet-5-5", "...": "the quoted request, unchanged"},
  "quote": {"protocol": "mrcall-bounded-v2", "...": "the quote, unchanged"},
  "request_id": "0b9d6c1e-7c1a-4bd0-9a51-2f3f0e7d9a11",
  "max_debit_micro_usd": 66000
}
```

```json
{
  "state": "settled",
  "receipt": {"protocol": "mrcall-bounded-v2", "...": "as below"},
  "message": {
    "model": "claude-sonnet-5-5-20260928",
    "content": [
      {"type": "thinking", "thinking": "The user wants a task due Friday.", "signature": "EqQBCkYIARgCKkA..."},
      {"type": "tool_use", "id": "toolu_01", "name": "create_task", "input": {"title": "Call the plumber", "due": "Friday"}}
    ],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 412, "output_tokens": 96}
  }
}
```

The response model may be the requested id or a dated snapshot of it
(`<requested>-YYYYMMDD`). The next turn of the loop sends this assistant
content back unchanged, thinking block first.

## Receipt

In the execute response and from `GET /api/desktop/llm/bounded/status/<request_id>`
(`{"state": "settled", "receipt": ...}`): every field of the quote,
unchanged — `protocol` and `snapshot_version` included — plus the
settlement.

```json
{
  "protocol": "mrcall-bounded-v2",
  "currency": "USD",
  "account_id": "firebase-uid-123",
  "business_id": "biz-123",
  "payload_hash": "<as in the quote>",
  "tariff_version": "<as in the quote>",
  "model": "claude-sonnet-5-5",
  "credit_value_micro_usd": 11000,
  "markup_factor": "1.5",
  "max_credits": 6,
  "max_debit_micro_usd": 66000,
  "snapshot_version": "f04f27349de6020e09f5bc28745af01981b3ff3935c1d594fedf094f211d7fa7",
  "quote_hash": "<as in the quote>",
  "request_id": "0b9d6c1e-7c1a-4bd0-9a51-2f3f0e7d9a11",
  "authorized_max_debit_micro_usd": 66000,
  "credits": 1,
  "debit_micro_usd": 11000
}
```

The engine checks, beyond v1's checks: `protocol` is `mrcall-bounded-v2`
in the capabilities, the quote and the receipt; the quote carries a
`snapshot_version` (64 lowercase hex characters) that the receipt repeats;
reasoning blocks in the message are kept, never refused.
