# The model table contract, schema 1

Scope: the two documents the engine's resolver produces and every consumer
reads — the decision record `table.json` and the price and metadata
`snapshot.json` — their encoding, their `version`, the static gates every
consumer applies, and where they are published. The credits protocol that
names them is in [`protocol-v2.md`](protocol-v2.md). Design:
`docs/briefs/2026-10-01-model-selection-by-requirements.md` (hb, D1–D9) and
its plan `docs/execution-plans/2026-10-02-model-selection-m10.md` ("The
published contract").

| File | What |
|---|---|
| `table.schema.json` | JSON Schema (draft 2020-12) of `table.json` |
| `snapshot.schema.json` | JSON Schema (draft 2020-12) of `snapshot.json` |
| `table.example.json`, `snapshot.example.json` | small valid documents; they pass every gate below against the requirements `{presets: economy 10, balanced 20; roles: CHAT, MNEMONIC; excluded_families: anthropic + haiku}`, and the standalone table gate (the snapshot example is cut from the 2026-10-02 read, its endpoint lists trimmed) |
| `protocol-v2.md` | the credits protocol `mrcall-bounded-v2` |
| `../gates.py` | the static gates as one pure function per document, plus the standalone table gate for a consumer without `requirements.json`: the reference implementation of the rules below |

## Who writes, who reads, where

- `engine/scripts/resolve_models.py --apply` writes the build copies
  `engine/zylch/llm/roles/snapshot.json` (always) and `table.json` (only
  when `roles/measured.json` covers every role).
- The daily job publishes on the orphan branch `model-table` of
  `hahnbanach/mrcall-desktop`, under `v1/`: `table.json`, `snapshot.json`,
  `measured.json` and `ledger.json`.
- Run-time URL, engine and billing server alike:
  `https://raw.githubusercontent.com/hahnbanach/mrcall-desktop/model-table/v1/<file>`.
- The engine downloads `table.json` and `snapshot.json` at start and every
  24 hours (ETag), applies the gates, caches them in the profile directory,
  and falls back to the last good copy, then to the build copy. The billing
  server loads them daily, keeps the current and the previous snapshot, and
  falls back to the copy taken at image build. `release.yml` refuses a copy
  older than 14 days or failing the gates.

## Encoding

- UTF-8 JSON. Timestamps are UTC, `YYYY-MM-DDTHH:MM:SSZ`.
- **Prices** are decimal strings in US dollars per million tokens, in
  canonical form: digits with at most one `.`, no sign, no exponent, no
  leading zero (`0.25`, not `.25` or `00.25`), no trailing fractional zero
  (`20`, not `20.0`; `0.02625`). `null` where the source has none (absent, or
  a variable price, which the catalogue writes as `-1`). Never read a price
  through a binary float.
- **`version`** is the lowercase hex SHA-256 of the canonical JSON of the
  document without its `version`: keys sorted by code point, separators `,`
  and `:` with no whitespace, non-ASCII characters written as themselves
  (no `\u` escapes), encoded as UTF-8. In Python:
  `sha256(json.dumps({k: v for k, v in doc.items() if k != "version"},
  sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()`
  (`gates.version_of`). The file's own line layout (`gates.dump`: sorted
  keys, a line per model in the snapshot, a line per role in the table) is
  not part of it.
- `v1/` holds `schema: 1` documents only; a document with another `schema`
  fails the gates.

## `table.json`: the decision record

`schema`, `version`, `resolved_at`, `catalogue_read_at`,
`requirements_sha256` and `measured_sha256` (SHA-256 of the bytes of the
`requirements.json` and `measured.json` it was resolved from), and
`presets`: per preset its `ceiling` (the highest catalogue output price a
ranked model may have) and per role two lists of at most five entries
`{id, direct_id}`, best first:

- `ranking` — over every vendor. Its first entry is the pick. A
  `maximise` role ranks the models that passed its measurement by its
  Artificial Analysis index (imputed where the index is missing); a
  `satisfice` role ranks, cheapest first, the models at or above its
  measured threshold (or, where the role accepts measured models only,
  those that passed).
- `anthropic_ranking` — the same rule over the `anthropic/*` models with a
  direct id: what a personal Anthropic key runs. It may be empty (no
  measured Anthropic model passes that role); a profile on a personal
  Anthropic key then pauses on that role with an explicit message.

`id` is the OpenRouter catalogue id; `direct_id` is Anthropic's own id
(the part after `anthropic/`, every `.` written `-`) when the snapshot
prices the model under `direct`, else `null`. No price, score or metadata:
those are the snapshot's, so a refresh of prices moves no record.

## `snapshot.json`: prices and request metadata

`schema`, `version`, `read_at` (when the catalogue was read), and:

- `policy` — the provider policy the endpoints were admitted under:
  `margin`, `quantizations`, `excluded_endpoint_variants`; and
  `excluded_families` (`[{vendor, token}]`, as `requirements.json` holds
  them), which a consumer without `requirements.json` applies to a table.
- `models` — every catalogue entry (aliases, `:free`/`:batch` variants and
  excluded families included, so a model a profile saved explicitly keeps a
  price), keyed by catalogue id:
  - `pricing`: the model-level catalogue price, `input`, `output`,
    `cache_read`, `cache_write`.
  - `metadata`: `reasoning` (`mandatory`; `efforts`, the published
    `supported_efforts` in the catalogue's order, highest first;
    `default_enabled`, `null` when unpublished), `parameters` (sorted: the
    intersection of the admitted endpoints' `supported_parameters` when the
    endpoints were read and one is admitted, the model-level list
    otherwise), `forced_tool` (true only when an admitted endpoint accepts a
    forced named tool choice), `structured_outputs` (`structured_outputs` is
    one of the parameters), `context_length`, `expiration_date`.
  - `endpoints`: for the models whose endpoints were read (tools, the
    minimum context, no variant, no alias), the admitted ones as `{tag,
    quantization, pricing}` sorted by tag; `null` for the others.
- `direct` — keyed by Anthropic's direct id: `{catalogue_id, pricing,
  metadata}` from the endpoint tagged `anthropic` (Anthropic's list price,
  that endpoint's parameters, forced tool choice and context; reasoning and
  expiry from the catalogue entry).

An endpoint is **admitted** when it is up (status 0), its declared
quantization is in `policy.quantizations` (an endpoint that declares none is
`unknown`), it supports tools, no segment of its tag after the provider is
in `policy.excluded_endpoint_variants` (`<provider>/flex`,
`<provider>/<region>/flex`), and its input and output prices are at or
under the model-level prices × `policy.margin`.

**Prices in use.** Ceilings compare `models[id].pricing.output`. On
OpenRouter, `max_price` and the reservation (engine) and the
pre-authorisation (billing server) use the model-level price × the margin;
K3's cap is its pinned `digitalocean` endpoint's price × the margin, read
from its `endpoints`. A direct id is priced from `direct`. A dated direct
id `<alias>-YYYYMMDD` is priced and shaped as its alias, and a response
naming a dated snapshot of the requested alias settles as the alias.

## The static gates

Every consumer applies them after each read, and uses a document only if it
passes all of them (`gates.check_snapshot`, then `gates.check_table` or,
without `requirements.json`, `gates.check_table_standalone`). A failure
names every rule broken; the schema is checked first and alone.

Snapshot:

1. `snapshot.schema.json` validates.
2. `version` equals the SHA-256 of the canonical JSON above.
3. Every `direct` entry's `catalogue_id` is a key of `models`, and the
   entry's key is that id's direct id.

Table, against the requirements in force and a snapshot that passed:

1. `table.schema.json` validates.
2. `version` equals the SHA-256 of the canonical JSON above.
3. Coverage: every preset × role of the requirements in force has a
   non-empty `ranking`. An empty `anthropic_ranking` is allowed. Presets or
   roles beyond the requirements are checked by the rules below but not
   required (a newer roster stays readable).
4. No preset's `ceiling` is above the requirements' ceiling for it (a raised
   ceiling is never published).
5. No ranked entry, in either ranking, is an alias (an id starting with
   `~`), of an excluded family (`{vendor, token}`: the id's part before the
   first `/` is the vendor and the token occurs in the part after it,
   case-insensitively) or has an announced expiry (its snapshot
   `metadata.expiration_date` is not `null`).
6. Every ranked `id` is a key of the snapshot's `models` with positive
   `input` and `output` prices and an `output` price at or under its
   preset's ceiling.
7. A ranked entry's `direct_id` is `null` or the direct id of its `id`; when
   not `null` it is a key of the snapshot's `direct`, whose price passes
   rule 6. Every `anthropic_ranking` entry is an `anthropic/*` id with a
   non-null `direct_id`.
8. No id appears twice in one ranking.

"The requirements in force" are three keys of the engine's
`zylch/llm/roles/requirements.json`: `presets` (each `ceiling`), `roles`
(the roster) and `excluded_families`. The job and the engines hold them
(`gates.check_table`). The resolver also matches the excluded families on
an entry's `canonical_slug` and an alias's target, which the snapshot does
not carry; the gate checks the published ids.

**A consumer without `requirements.json`** (the billing server) takes the
roster and the ceilings from the table, and the excluded families, the
margin, the quantizations and the excluded endpoint variants from the
snapshot's `policy`; it applies `gates.check_table_standalone(table,
snapshot)`, which is the table rules above with these changes:

- rule 3 reads: the table ranks at least one role, and every preset of the
  table has a non-empty `ranking` for every role any preset of the table
  ranks (the roster is the union of the presets' roles);
- rule 4 does not apply (the table's own ceilings are the only ones known,
  so a raised ceiling cannot be told; the job's and the engines'
  `check_table` refuse it before and after publication);
- rule 5 matches the families of `policy.excluded_families`, and rules 6
  and 7 compare with each preset's own `ceiling`.
