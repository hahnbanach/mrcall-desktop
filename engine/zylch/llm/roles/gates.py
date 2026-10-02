"""The static gates of the published model table and snapshot (contract schema 1).

The daily job publishes two documents on the `model-table` data branch, and
every consumer checks them with the same rules before using one: the job
before it publishes, `release.yml` before it embeds the build copies, the
engine after each download, the billing server after each load
(`contract/README.md` states the rules in prose for the server):

- `check_snapshot(snapshot)`: `contract/snapshot.schema.json` validates,
  `version` matches the content, and every `direct` entry names a catalogue
  entry of the snapshot under the direct id the rule (`direct_id`) gives it;
- `check_table(table, requirements, snapshot)`: `contract/table.schema.json`
  validates, `version` matches the content, every preset × role of the
  requirements in force has a non-empty `ranking` (an empty
  `anthropic_ranking` is allowed: no measured Anthropic model passes that
  role, and the job's report names it), no preset's ceiling is above the
  requirements' (the job never publishes a raised ceiling), and every ranked
  entry is no alias, no excluded family and has no announced expiry, is
  priced in `snapshot` with positive input and output prices and an output
  price within its preset's ceiling, and carries the direct id the rule
  gives it — priced under the snapshot's `direct` when it is not null, and
  never null in an `anthropic_ranking`, whose entries are all `anthropic/*`;
- `check_table_standalone(table, snapshot)`: the same gates for a consumer
  without `requirements.json` (the billing server mirrors this one): the
  roster is every role the table's presets rank and each preset must rank
  each of them, the ceilings are the table's own (so a raised ceiling cannot
  be told; the job and the engines catch it with `check_table`), and the
  excluded families come from the snapshot's `policy.excluded_families`.

A failed gate raises `GateError`; its `violations` name every rule broken.
The schema is checked first and alone, since the other rules read a
well-formed document. `requirements` is `requirements.json` as the consumer
holds it: only its `presets` (ceilings), `roles` and `excluded_families` are
read, so a consumer holding those three keys can pass them; one holding
none of them takes the roster and ceilings from the table and the families
from the snapshot (`check_table_standalone`).

The schemas are read from `contract/` and applied by `_conform`, a small
interpreter of the JSON Schema keywords they use (`KEYWORDS`); any other
keyword is a programming error, so a schema edit cannot widen what passes
without this module knowing. A `pattern` must be anchored at both ends, and
is matched whole, as JSON Schema's ECMA-262 search of an anchored pattern
does. Standard library only; no network, no clock.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

SCHEMA = 1
CONTRACT = Path(__file__).resolve().parent / "contract"
# Where engines and the billing server read the published files (`<name>`
# is `table.json` or `snapshot.json`).
URL = "https://raw.githubusercontent.com/hahnbanach/mrcall-desktop/model-table/v1/{name}"
ANTHROPIC = "anthropic/"
ALIAS = "~"
KEYWORDS = frozenset(
    "$schema $id $defs $comment title description $ref type const enum pattern minimum"
    " properties required additionalProperties propertyNames items minItems maxItems"
    " uniqueItems".split()
)


class GateError(ValueError):
    """A document failed one or more static gates; `violations` names each."""

    def __init__(self, what: str, violations: list[str]):
        self.violations = list(violations)
        super().__init__(f"{what} fails the static gates: " + "; ".join(self.violations))


def canonical(doc: dict) -> bytes:
    """The bytes `version` is the SHA-256 of: the document without its
    `version`, as JSON with sorted keys, no whitespace (separators `,` and
    `:`), non-ASCII characters kept, encoded as UTF-8."""
    body = {key: value for key, value in doc.items() if key != "version"}
    text = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8")


def version_of(doc: dict) -> str:
    """The `version` a document must carry: SHA-256 hex of `canonical(doc)`."""
    return hashlib.sha256(canonical(doc)).hexdigest()


def stamped(doc: dict) -> dict:
    """`doc` with its `version` set from its content."""
    return {**doc, "version": version_of(doc)}


def dump(value: object, expand: int, indent: int = 0) -> str:
    """The file layout of a published document: JSON with sorted keys, objects
    expanded one key per line down to `expand` levels, anything deeper on one
    line (the snapshot uses 2: a line per model; the table 4: a line per
    role), so a refresh diffs by model or role. The layout is not part of
    `version`, which is taken over `canonical`."""
    if expand <= 0 or not isinstance(value, dict) or not value:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(", ", ": "))
    pad = " " * (indent + 1)
    rows = [
        f"{pad}{json.dumps(key, ensure_ascii=False)}: {dump(value[key], expand - 1, indent + 1)}"
        for key in sorted(value)
    ]
    return "{\n" + ",\n".join(rows) + "\n" + " " * indent + "}"


def direct_id(catalogue_id: str) -> str | None:
    """Anthropic's own id for an `anthropic/*` catalogue entry — the part after
    the vendor, every `.` written `-` (the rule 10a ported from the kit's
    `model_id`) — or None for any other vendor."""
    if not catalogue_id.startswith(ANTHROPIC):
        return None
    return catalogue_id.split("/", 1)[1].replace(".", "-")


def excluded_family(name: object, families: list) -> dict | None:
    """The first `{vendor, token}` of `families` that `name` belongs to, or None.

    `name` is a catalogue id, a `canonical_slug` or an alias's target: its
    vendor is the part before the first `/` (an alias's leading `~` dropped),
    and the token must occur in the part after it, case-insensitively. A name
    without a vendor belongs to no family."""
    if not isinstance(name, str) or "/" not in name:
        return None
    vendor, _, model = name.removeprefix(ALIAS).partition("/")
    for family in families:
        if vendor.lower() == family["vendor"].lower() and family["token"].lower() in model.lower():
            return family
    return None


@lru_cache(maxsize=None)
def schema(name: str) -> dict:
    """A contract schema (`table` or `snapshot`), read once."""
    return json.loads((CONTRACT / f"{name}.schema.json").read_text(encoding="utf-8"))


def _is(value: object, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    kinds = {"object": dict, "array": list, "string": str}
    return isinstance(value, kinds[kind])


def _same(a: object, b: object) -> bool:
    """JSON equality: `true` is not `1`."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _conform(value: object, rule: dict, root: dict, where: str, errors: list[str]) -> None:
    """Append to `errors` what `value` breaks of the schema `rule`."""
    unknown = set(rule) - KEYWORDS
    if unknown:
        raise ValueError(f"schema keyword(s) {sorted(unknown)} at {where} are not interpreted")
    if "$ref" in rule:
        ref = rule["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"schema reference {ref!r} at {where} is not interpreted")
        _conform(value, root["$defs"][ref.removeprefix("#/$defs/")], root, where, errors)
    if "type" in rule:
        kinds = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
        if not any(_is(value, kind) for kind in kinds):
            errors.append(f"{where} must be {' or '.join(kinds)}")
            return
    if "const" in rule and not _same(value, rule["const"]):
        errors.append(f"{where} must be {json.dumps(rule['const'])}")
    if "enum" in rule and not any(_same(value, option) for option in rule["enum"]):
        errors.append(f"{where} must be one of {json.dumps(rule['enum'])}")
    if isinstance(value, str) and "pattern" in rule:
        pattern = rule["pattern"]
        if not (pattern.startswith("^") and pattern.endswith("$")):
            raise ValueError(f"schema pattern {pattern!r} at {where} is not anchored")
        if not re.fullmatch(pattern, value):
            errors.append(
                f"{where} {json.dumps(value, ensure_ascii=False)} does not match {pattern}"
            )
    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if number and "minimum" in rule and value < rule["minimum"]:
        errors.append(f"{where} must be at least {rule['minimum']}")
    if isinstance(value, dict):
        _conform_object(value, rule, root, where, errors)
    if isinstance(value, list):
        _conform_array(value, rule, root, where, errors)


def _conform_object(value: dict, rule: dict, root: dict, where: str, errors: list[str]) -> None:
    for key in rule.get("required", ()):
        if key not in value:
            errors.append(f"{where}.{key} is missing")
    declared = rule.get("properties", {})
    extra = rule.get("additionalProperties", True)
    for key, item in value.items():
        if "propertyNames" in rule:
            _conform(key, rule["propertyNames"], root, f"{where} key", errors)
        if key in declared:
            _conform(item, declared[key], root, f"{where}.{key}", errors)
        elif extra is False:
            errors.append(f"{where}.{key} is not allowed")
        elif isinstance(extra, dict):
            _conform(item, extra, root, f"{where}[{json.dumps(key)}]", errors)


def _conform_array(value: list, rule: dict, root: dict, where: str, errors: list[str]) -> None:
    if len(value) < rule.get("minItems", 0):
        errors.append(f"{where} must hold at least {rule['minItems']} items")
    if "maxItems" in rule and len(value) > rule["maxItems"]:
        errors.append(f"{where} must hold at most {rule['maxItems']} items")
    if rule.get("uniqueItems") and any(
        _same(a, b) for i, a in enumerate(value) for b in value[i + 1 :]
    ):
        errors.append(f"{where} holds a duplicate item")
    for index, item in enumerate(value):
        if "items" in rule:
            _conform(item, rule["items"], root, f"{where}[{index}]", errors)


def schema_errors(doc: object, name: str) -> list[str]:
    """What `doc` breaks of the contract schema `name` (`table` or `snapshot`)."""
    errors: list[str] = []
    _conform(doc, schema(name), schema(name), "$", errors)
    return errors


def _well_formed(doc: object, name: str) -> None:
    errors = schema_errors(doc, name)
    if errors:
        raise GateError(f"{name}.json", [f"schema: {e}" for e in errors])
    if doc["version"] != version_of(doc):
        raise GateError(f"{name}.json", [f"version: {doc['version']} is not the content's"])


def check_snapshot(snapshot: object) -> None:
    """Raise GateError unless `snapshot` passes every snapshot gate."""
    _well_formed(snapshot, "snapshot")
    violations = []
    for model, row in snapshot["direct"].items():
        catalogue_id = row["catalogue_id"]
        if catalogue_id not in snapshot["models"]:
            violations.append(f"direct: {model} names {catalogue_id}, which the snapshot lacks")
        elif direct_id(catalogue_id) != model:
            violations.append(f"direct: {model} is not the direct id of {catalogue_id}")
    if violations:
        raise GateError("snapshot.json", violations)


def _priced(pricing: dict, ceiling: Decimal) -> str | None:
    """Why a pricing fails the price gate, or None."""
    prices = [pricing.get(side) for side in ("input", "output")]
    if any(price is None or Decimal(price) <= 0 for price in prices):
        return "has no positive input and output price"
    if Decimal(prices[1]) > ceiling:
        return f"costs {prices[1]} per million output tokens, above the ceiling of {ceiling}"
    return None


def _entry_violations(entry: dict, ceiling: Decimal, families: list, snap: dict, anthropic: bool):
    model, direct = entry["id"], entry["direct_id"]
    if model.startswith(ALIAS):
        yield "is an alias"
    family = excluded_family(model, families)
    if family:
        yield f"is of the excluded family {family['vendor']} + {family['token']}"
    row = snap["models"].get(model)
    if row is None:
        yield "is not in the snapshot"
        return
    if row["metadata"]["expiration_date"] is not None:
        yield f"expires on {row['metadata']['expiration_date']}"
    problem = _priced(row["pricing"], ceiling)
    if problem:
        yield problem
    if direct is None:
        if anthropic:
            yield "has no direct id in the Anthropic ranking"
    elif direct != direct_id(model):
        yield f"carries the direct id {direct}, not {direct_id(model)}"
    elif direct not in snap["direct"]:
        yield f"has the direct id {direct}, which the snapshot does not price"
    else:
        problem = _priced(snap["direct"][direct]["pricing"], ceiling)
        if problem:
            yield f"(direct {direct}) {problem}"
    if anthropic and not model.startswith(ANTHROPIC):
        yield "is not an Anthropic model, in the Anthropic ranking"


def _ranked_violations(presets: dict, families: list, snapshot: dict) -> list[str]:
    """The rules every ranked entry of every preset and role must meet."""
    violations = []
    for preset, body in presets.items():
        ceiling = Decimal(body["ceiling"])
        for role, rankings in body["roles"].items():
            for column in ("ranking", "anthropic_ranking"):
                ids = [entry["id"] for entry in rankings[column]]
                if len(set(ids)) != len(ids):
                    violations.append(f"{preset} / {role} / {column}: an id is ranked twice")
                for entry in rankings[column]:
                    anthropic = column == "anthropic_ranking"
                    for problem in _entry_violations(entry, ceiling, families, snapshot, anthropic):
                        violations.append(f"{preset} / {role} / {column}: {entry['id']} {problem}")
    return violations


def check_table(table: object, requirements: dict, snapshot: dict) -> None:
    """Raise GateError unless `table` passes every table gate, against the
    requirements in force and a snapshot that passed `check_snapshot`."""
    _well_formed(table, "table")
    violations = []
    presets = table["presets"]
    for preset, spec in requirements["presets"].items():
        if preset not in presets:
            violations.append(f"coverage: preset {preset} is missing")
            continue
        ceiling, in_force = presets[preset]["ceiling"], spec.get("ceiling")
        if in_force is not None and Decimal(ceiling) > Decimal(str(in_force)):
            violations.append(f"ceiling: {preset} is {ceiling}, above the {in_force} in force")
        for role in requirements["roles"]:
            if not presets[preset]["roles"].get(role, {}).get("ranking"):
                violations.append(f"coverage: {preset} / {role} has no ranking")
    families = requirements.get("excluded_families") or []
    violations += _ranked_violations(presets, families, snapshot)
    if violations:
        raise GateError("table.json", violations)


def check_table_standalone(table: object, snapshot: dict) -> None:
    """Raise GateError unless `table` passes every table gate a consumer
    without `requirements.json` can apply (the billing server mirrors this
    one), against a snapshot that passed `check_snapshot`: the roster is every
    role the table's presets rank, and each preset must rank each of them; the
    ceilings are the table's own, so a raised one cannot be told from them;
    the excluded families are the snapshot's `policy.excluded_families`."""
    _well_formed(table, "table")
    presets = table["presets"]
    roster = list(dict.fromkeys(role for body in presets.values() for role in body["roles"]))
    violations = [] if roster else ["coverage: the table ranks no role"]
    for preset, body in presets.items():
        for role in roster:
            if not body["roles"].get(role, {}).get("ranking"):
                violations.append(f"coverage: {preset} / {role} has no ranking")
    families = snapshot["policy"]["excluded_families"]
    violations += _ranked_violations(presets, families, snapshot)
    if violations:
        raise GateError("table.json", violations)
