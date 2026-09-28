#!/usr/bin/env python3
"""Compact a profile's learned-rules store back under the prompt cap.

The always-on OPERATING RULES block is built from ``template:<owner>``
and ``prefs:<owner>`` and injected VERBATIM into every detection,
reanalysis, solve, chat and emailer prompt. On support@ it had grown to
82 blobs / 66,842 chars against an 8,000-char soft cap, so every
detection call logged

    [prefs] learned preferences size 67004 chars exceeds soft cap 8000

and ran on a silently truncated view of the user's own rules.

The growth was not "the same rule written twice" — there were ZERO exact
duplicates. It was a misrouted class of writer: 81 of the 82 blobs were
memory ENTITIES (``#IDENTIFIERS`` / ``Entity type: STYLE`` — trained
-voice response patterns), 66,105 of the 66,842 chars. Those belong in
``user:<owner>``, where they are retrieved by relevance search, not
pinned into every prompt at full length.

This script repairs an existing store. It runs against the profile's
company memory through the engine's own boot (``--profile``), never a raw
connection on a database file, and it reads and touches only the booted
profile's own rules — the ``template:`` / ``prefs:`` rows of either identity
the profile states — never another account's. Three deterministic passes,
in order; no LLM is involved and none is needed, because every decision is
made on the extractor's own structural markers rather than on prose:

1. RELOCATE — an entity-shaped blob belongs in ``user:<owner>``. Moving it
   would turn a private rule into company memory every key holder reads:
   a reclassification, which is a semantic judgment the owner makes. So it
   is reported as needing review and never executed; this script moves
   nothing. The entity stays where it is until its owner acts on it.
2. DEDUPE — blobs whose content is identical after whitespace/case
   normalisation collapse to the oldest one; the newer copies are
   dropped.
3. SUPERSEDE — when one rule strictly contains another (both ≥ 40
   normalised chars), the shorter one is dropped and the longer kept.

A drop is the retaining drop consolidation uses for a donor
(``BlobStorage.delete_blob(retain=True)``): the rule's final text is kept
in ``blob_versions`` with reason ``maintenance`` before the row goes, and
every drop of one run happens in one company transaction that bumps the
mutation sequence once.

Optional fourth pass, ``--llm``: the three passes above are structural,
and they leave behind a residue they cannot judge — on support@, two
blobs of the memory extractor's own NARRATION ("There is no external
person, company, or concrete interaction to extract") sitting in the
rule store as if they were instructions. Telling narration from an
operating rule is free-text classification, which is an LLM's job with
structured output and never a regex. ``--llm`` sends the surviving
blobs to the profile's configured provider in ONE batched tool call and
REPORTS the ones it judges not to be rules; it drops nothing, because
that judgment is the owner's to act on (``/memory delete``). Off by
default: the deterministic passes must be reproducible without a provider.

Idempotent: a second run finds nothing to do. Dry run is the default and
writes nothing.

Usage:
    # dry run against a profile (default — prints what it would do)
    python scripts/compact_learned_prefs.py --profile <UID>

    # actually drop the duplicate and superseded rules
    python scripts/compact_learned_prefs.py --profile <UID> --apply

    # include the LLM residue report (1 call)
    python scripts/compact_learned_prefs.py --profile <UID> --llm
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_CAP = 8000


def normalise(content: str) -> str:
    """Same key the runtime uses (``prefs_store.normalise``)."""
    return re.sub(r"\s+", " ", (content or "").strip().lower())


def is_entity_shaped(content: str) -> bool:
    """Same test the runtime uses (``prefs_store.is_entity_shaped``)."""
    if not content:
        return False
    head = content.strip().lower()
    if head.startswith("#identifiers"):
        return True
    for line in head.splitlines()[:4]:
        if line.strip().startswith("entity type:"):
            return True
    return False


_CLASSIFY_TOOL = {
    "name": "classify_rules",
    "description": (
        "Report, for each numbered entry, whether it is a genuine standing "
        "OPERATING RULE for an assistant, or something that was filed in the "
        "rule store by mistake."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "The entry number shown."},
                        "is_operating_rule": {
                            "type": "boolean",
                            "description": (
                                "true when the text instructs the assistant how to "
                                "behave, always, in future messages (tone, policy, "
                                "a standing business constraint). false when it is "
                                "an observation ABOUT one message, the extractor's "
                                "own narration about what it could or could not "
                                "extract, a per-contact fact, or anything else that "
                                "is not a standing instruction."
                            ),
                        },
                        "why": {"type": "string", "description": "One short sentence."},
                    },
                    "required": ["index", "is_operating_rule", "why"],
                },
            }
        },
        "required": ["verdicts"],
    },
}

_CLASSIFY_SYSTEM = (
    "You are auditing the always-on OPERATING RULES store of an email "
    "assistant. Everything in it is injected verbatim into every prompt the "
    "assistant runs, so it must contain ONLY standing instructions about how "
    "to behave. Anything else — a note about one particular email, the "
    "memory extractor's narration about what it did or did not find, a fact "
    "about a single contact — is misfiled and costs the assistant context on "
    "every call. Be conservative in ONE direction only: when a text plausibly "
    "instructs future behaviour, keep it."
)


def _llm_filter(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Classify surviving blobs. Returns verdicts; [] when unavailable.

    ONE batched call through the engine's configured provider.
    """
    from zylch.llm import try_make_llm_client

    client = try_make_llm_client()
    if client is None:
        print("  (--llm: no LLM transport configured for this profile — skipping the pass)")
        return []

    listing = "\n\n".join(
        f"[{i}] ({len(r['content'])} chars)\n{r['content']}" for i, r in enumerate(rows)
    )
    try:
        response = client.create_message_sync(
            system=_CLASSIFY_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (f"{listing}\n\nCall classify_rules with one verdict per entry."),
                }
            ],
            tools=[_CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_rules"},
            max_tokens=1500,
        )
    except Exception as e:
        print(f"  (--llm: classification call failed: {e})")
        return []

    for block in getattr(response, "content", []) or []:
        data = getattr(block, "input", None)
        if isinstance(data, dict) and isinstance(data.get("verdicts"), list):
            return data["verdicts"]
    print("  (--llm: model returned no verdicts — keeping everything)")
    return []


def plan(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """The three structural passes over one owner's rules, oldest first. Pure: writes nothing.

    Answers ``relocate`` (entity-shaped rows, reported for review only),
    ``drop`` (each row with ``why``: ``duplicate`` or ``superseded`` and the
    id it yields to) and ``final`` (the rules that stay).
    """
    relocate = [r for r in rows if is_entity_shaped(r["content"])]
    keep = [r for r in rows if not is_entity_shaped(r["content"])]
    seen: Dict[str, Dict[str, Any]] = {}
    drop: List[Dict[str, Any]] = []
    survivors: List[Dict[str, Any]] = []
    for r in keep:
        key = normalise(r["content"])
        if key in seen:
            drop.append({**r, "why": "duplicate", "of": seen[key]["id"]})
        else:
            seen[key] = r
            survivors.append(r)
    final: List[Dict[str, Any]] = []
    for r in sorted(survivors, key=lambda x: -len(normalise(x["content"]))):
        key = normalise(r["content"])
        absorbed = next(
            (
                kept
                for kept in final
                if len(key) >= 40
                and len(normalise(kept["content"])) >= 40
                and key in normalise(kept["content"])
            ),
            None,
        )
        if absorbed is not None:
            drop.append({**r, "why": "superseded", "of": absorbed["id"]})
        else:
            final.append(r)
    return {"relocate": relocate, "drop": drop, "final": final}


def _rules(owner: str, company_key: str) -> List[Dict[str, Any]]:
    """``owner``'s own ``template:`` / ``prefs:`` rows in the bound company, oldest first."""
    from zylch.memory.mnemonic.session import company_transaction
    from zylch.storage.models import Blob

    with company_transaction() as session:
        rows = (
            session.query(Blob.id, Blob.namespace, Blob.content, Blob.created_at)
            .filter(
                Blob.company_key == company_key,
                Blob.owner_id == owner,
                Blob.namespace.in_((f"template:{owner}", f"prefs:{owner}")),
            )
            .order_by(Blob.created_at, Blob.id)
            .all()
        )
    return [
        {"id": str(i), "namespace": ns, "content": c or "", "created_at": at}
        for i, ns, c, at in rows
    ]


def drop_rules(storage: Any, owner: str, blob_ids: Iterable[str]) -> int:
    """Drop ``owner``'s rules by id in one company transaction, each text retained first.

    The retaining drop (``delete_blob(retain=True, reason="maintenance")``)
    neither opens a session nor bumps the mutation sequence inside a caller's
    transaction, so this bumps it once for the whole run. Returns the rows
    dropped.
    """
    from zylch.memory.blob_versions import MAINTENANCE
    from zylch.memory.mnemonic.session import company_transaction
    from zylch.memory.store import bump_mutation_seq

    dropped = 0
    with company_transaction(write=True) as session:
        for blob_id in blob_ids:
            dropped += int(
                storage.delete_blob(blob_id, owner, retain=True, session=session, reason=MAINTENANCE)
            )
        if dropped:
            bump_mutation_seq(session)
    return dropped


def run(
    owners: Iterable[str],
    *,
    apply: bool,
    cap: int = DEFAULT_CAP,
    use_llm: bool = False,
    storage: Any = None,
) -> Dict[str, int]:
    """Compact each of ``owners``' own rules in the bound company; ``storage`` drops them."""
    from zylch.memory.company_key import require_company_key

    key = require_company_key()
    stats = {
        name: 0
        for name in (
            "owners", "before_blobs", "before_chars", "relocate_review", "relocate_review_chars",
            "deduped", "deduped_chars", "superseded", "superseded_chars", "llm_flagged",
            "dropped", "after_blobs", "after_chars",
        )
    }
    for owner in sorted({str(o) for o in owners if o}):
        rows = _rules(owner, key)
        if not rows:
            continue
        stats["owners"] += 1
        stats["before_blobs"] += len(rows)
        stats["before_chars"] += sum(len(r["content"]) for r in rows)
        print(f"\nowner={owner}: {len(rows)} blob(s), {sum(len(r['content']) for r in rows)} chars (cap {cap})")
        planned = plan(rows)
        for r in planned["relocate"]:
            print(f"  REVIEW {r['id']} [{len(r['content'])} chars] entity-shaped in {r['namespace']}: "
                  f"belongs in user:<company>; a move is the owner's decision, not made here")
            stats["relocate_review"] += 1
            stats["relocate_review_chars"] += len(r["content"])
        for r in planned["drop"]:
            label = "DUP  " if r["why"] == "duplicate" else "SUPER"
            print(f"  {label} {r['id']} [{len(r['content'])} chars] {r['why']}: yields to {r['of']}")
            stats["deduped" if r["why"] == "duplicate" else "superseded"] += 1
            stats[("deduped" if r["why"] == "duplicate" else "superseded") + "_chars"] += len(r["content"])
        final = planned["final"]
        if use_llm and final:
            verdicts = {v.get("index"): v for v in _llm_filter(final) if isinstance(v, dict)}
            for i, r in enumerate(final):
                verdict = verdicts.get(i)
                if verdict is not None and verdict.get("is_operating_rule") is False:
                    print(f"  LLM?  {r['id']} [{len(r['content'])} chars] may not be an operating "
                          f"rule: {verdict.get('why')} (reported only; /memory delete removes it)")
                    stats["llm_flagged"] += 1
        after = len(rows) - len(planned["drop"])
        after_chars = sum(len(r["content"]) for r in rows) - sum(len(r["content"]) for r in planned["drop"])
        stats["after_blobs"] += after
        stats["after_chars"] += after_chars
        print(f"  => {after} rule blob(s), {after_chars} chars "
              f"({'UNDER' if after_chars <= cap else 'STILL OVER'} the {cap} cap)")
        if apply and planned["drop"]:
            stats["dropped"] += drop_rules(storage, owner, [r["id"] for r in planned["drop"]])
    return stats


def _boot(profile: Optional[str]):
    """The profile booted the way every ``zylch`` subcommand boots it; its identities and a store."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from zylch.cli import main as _main
    from zylch.memory import BlobStorage, EmbeddingEngine, MemoryConfig
    from zylch.memory.mnemonic.authorization import _current_owners
    from zylch.storage.database import get_session
    from zylch.storage.storage import Storage

    _main._setup_profile(profile, lock=False)
    Storage.get_instance()
    return sorted(_current_owners()), BlobStorage(get_session, EmbeddingEngine(MemoryConfig()))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="profile under ~/.zylch/profiles")
    parser.add_argument(
        "--cap",
        type=int,
        default=DEFAULT_CAP,
        help=f"soft cap in characters used for the report (default {DEFAULT_CAP})",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help=(
            "also report what the LLM residue pass judges not to be rules "
            "(1 batched call; needs the profile's configured provider; drops nothing)"
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="drop the duplicate and superseded rules (default: dry run, prints what it would do)",
    )
    args = parser.parse_args(argv)

    owners, storage = _boot(args.profile)
    print(f"[{'APPLY' if args.apply else 'DRY RUN'}] profile={args.profile} owners={', '.join(owners)}")
    stats = run(owners, apply=args.apply, cap=args.cap, use_llm=args.llm, storage=storage)
    print(
        f"\nowners={stats['owners']} "
        f"before={stats['before_blobs']} blobs / {stats['before_chars']} chars "
        f"-> after={stats['after_blobs']} blobs / {stats['after_chars']} chars\n"
        f"relocate_review={stats['relocate_review']} ({stats['relocate_review_chars']} chars) "
        f"deduped={stats['deduped']} ({stats['deduped_chars']} chars) "
        f"superseded={stats['superseded']} ({stats['superseded_chars']} chars)"
        + (f"\nllm_flagged={stats['llm_flagged']}" if args.llm else "")
    )
    if not args.apply and (stats["deduped"] or stats["superseded"]):
        print("(dry run — nothing written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
