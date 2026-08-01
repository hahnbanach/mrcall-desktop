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

This script repairs an existing store. Three deterministic passes, in
order; no LLM is involved and none is needed, because every decision is
made on the extractor's own structural markers rather than on prose:

1. RELOCATE — an entity-shaped blob is MOVED to ``user:<owner>``. It is
   never deleted: it is real extracted memory, just filed in the wrong
   drawer. This is the pass that recovers ~99% of the space.
2. DEDUPE — blobs whose content is identical after whitespace/case
   normalisation collapse to the oldest one; the newer copies are
   deleted (with their sentence rows, via ON DELETE CASCADE).
3. SUPERSEDE — when one rule strictly contains another (both ≥ 40
   normalised chars), the shorter one is deleted and the longer kept.

Optional fourth pass, ``--llm``: the three passes above are structural,
and they leave behind a residue they cannot judge — on support@, two
blobs of the memory extractor's own NARRATION ("There is no external
person, company, or concrete interaction to extract") sitting in the
rule store as if they were instructions. Telling narration from an
operating rule is free-text classification, which is an LLM's job with
structured output and never a regex. ``--llm`` sends the surviving
blobs to the profile's configured provider in ONE batched tool call and
drops the ones it judges not to be rules. Off by default: the
deterministic passes must be reproducible without a provider.

Idempotent: a second run finds nothing to do.

Usage:
    # dry run against a profile (default — prints what it would do)
    python scripts/compact_learned_prefs.py --profile <UID>

    # dry run against an explicit database file (e.g. a copy)
    python scripts/compact_learned_prefs.py --db /path/zylch.db

    # actually write
    python scripts/compact_learned_prefs.py --db /path/zylch.db --apply

    # include the LLM residue pass (1 call)
    python scripts/compact_learned_prefs.py --profile <UID> --llm --apply
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROFILE_ROOT = Path.home() / ".zylch" / "profiles"

DEFAULT_CAP = 8000


def _resolve_db(profile: Optional[str], db: Optional[str]) -> Path:
    if db:
        path = Path(db).expanduser()
    elif profile:
        path = PROFILE_ROOT / profile / "zylch.db"
    else:
        raise SystemExit("give --profile <UID> or --db <path>")
    if not path.exists():
        raise SystemExit(f"database not found: {path}")
    return path


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


def _llm_filter(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    """Classify surviving blobs. Returns verdicts; [] when unavailable.

    ONE batched call through the engine's configured provider.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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


def _owners(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT DISTINCT owner_id FROM blobs "
        "WHERE namespace LIKE 'template:%' OR namespace LIKE 'prefs:%'"
    ).fetchall()
    return [r[0] for r in rows]


def run(db_path: Path, apply: bool, cap: int, use_llm: bool = False) -> Dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    stats = {
        "owners": 0,
        "before_blobs": 0,
        "before_chars": 0,
        "relocated": 0,
        "relocated_chars": 0,
        "deduped": 0,
        "deduped_chars": 0,
        "superseded": 0,
        "superseded_chars": 0,
        "llm_kept": 0,
        "llm_dropped": 0,
        "llm_dropped_chars": 0,
        "after_blobs": 0,
        "after_chars": 0,
    }
    try:
        for owner in _owners(conn):
            stats["owners"] += 1
            rows = conn.execute(
                "SELECT id, namespace, content, created_at FROM blobs "
                "WHERE owner_id = ? AND namespace IN (?, ?) "
                "ORDER BY created_at ASC",
                (owner, f"template:{owner}", f"prefs:{owner}"),
            ).fetchall()
            before_chars = sum(len(r["content"] or "") for r in rows)
            stats["before_blobs"] += len(rows)
            stats["before_chars"] += before_chars
            print(f"\nowner={owner}: {len(rows)} blob(s), {before_chars} chars (cap {cap})")

            relocate: List[sqlite3.Row] = []
            keep: List[sqlite3.Row] = []
            for r in rows:
                if is_entity_shaped(r["content"]):
                    relocate.append(r)
                else:
                    keep.append(r)

            for r in relocate:
                name = _entity_name(r["content"])
                print(
                    f"  MOVE  {r['id']} [{len(r['content'])} chars] "
                    f"{r['namespace']} -> user:{owner}  ({name})"
                )
                stats["relocated"] += 1
                stats["relocated_chars"] += len(r["content"] or "")

            # Pass 2 — exact duplicates (oldest wins).
            seen: Dict[str, sqlite3.Row] = {}
            drop: List[sqlite3.Row] = []
            survivors: List[sqlite3.Row] = []
            for r in keep:
                key = normalise(r["content"])
                if key in seen:
                    print(
                        f"  DUP   {r['id']} [{len(r['content'])} chars] "
                        f"identical to {seen[key]['id']}"
                    )
                    drop.append(r)
                    stats["deduped"] += 1
                    stats["deduped_chars"] += len(r["content"] or "")
                else:
                    seen[key] = r
                    survivors.append(r)

            # Pass 3 — strict containment (longer wins).
            final: List[sqlite3.Row] = []
            for r in sorted(survivors, key=lambda x: -len(normalise(x["content"]))):
                key = normalise(r["content"])
                absorbed = None
                for kept_row in final:
                    other = normalise(kept_row["content"])
                    if len(other) < 40 or len(key) < 40:
                        continue
                    if key in other:
                        absorbed = kept_row
                        break
                if absorbed is not None:
                    print(
                        f"  SUPER {r['id']} [{len(r['content'])} chars] "
                        f"contained in {absorbed['id']}"
                    )
                    drop.append(r)
                    stats["superseded"] += 1
                    stats["superseded_chars"] += len(r["content"] or "")
                else:
                    final.append(r)

            # Pass 4 (optional) — LLM residue filter.
            if use_llm and final:
                verdicts = _llm_filter(final)
                by_index = {v.get("index"): v for v in verdicts if isinstance(v, dict)}
                surviving: List[sqlite3.Row] = []
                for i, r in enumerate(final):
                    verdict = by_index.get(i)
                    if verdict is not None and verdict.get("is_operating_rule") is False:
                        print(
                            f"  LLM-  {r['id']} [{len(r['content'])} chars] not an "
                            f"operating rule: {verdict.get('why')}"
                        )
                        drop.append(r)
                        stats["llm_dropped"] += 1
                        stats["llm_dropped_chars"] += len(r["content"] or "")
                    else:
                        why = (verdict or {}).get("why", "no verdict — kept by default")
                        print(f"  LLM+  {r['id']} [{len(r['content'])} chars] kept: {why}")
                        stats["llm_kept"] += 1
                        surviving.append(r)
                final = surviving

            after_chars = sum(len(r["content"] or "") for r in final)
            stats["after_blobs"] += len(final)
            stats["after_chars"] += after_chars
            print(
                f"  => {len(final)} rule blob(s), {after_chars} chars "
                f"({'UNDER' if after_chars <= cap else 'STILL OVER'} the {cap} cap)"
            )

            if apply:
                if relocate:
                    conn.executemany(
                        "UPDATE blobs SET namespace = ? WHERE id = ?",
                        [(f"user:{owner}", r["id"]) for r in relocate],
                    )
                if drop:
                    conn.executemany(
                        "DELETE FROM blobs WHERE id = ?",
                        [(r["id"],) for r in drop],
                    )
                conn.commit()
    finally:
        conn.close()
    return stats


def _entity_name(content: str) -> str:
    for line in (content or "").splitlines()[:6]:
        if line.strip().lower().startswith("name:"):
            return line.strip()
    return "(unnamed entity)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="profile UID under ~/.zylch/profiles")
    parser.add_argument("--db", help="explicit path to a zylch.db (e.g. a copy)")
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
            "also run the LLM residue pass over the surviving blobs "
            "(1 batched call; needs the profile's configured provider)"
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the changes (default: dry run, prints what it would do)",
    )
    args = parser.parse_args()

    db_path = _resolve_db(args.profile, args.db)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] {db_path}")
    stats = run(db_path, apply=args.apply, cap=args.cap, use_llm=args.llm)
    print(
        f"\nowners={stats['owners']} "
        f"before={stats['before_blobs']} blobs / {stats['before_chars']} chars "
        f"-> after={stats['after_blobs']} blobs / {stats['after_chars']} chars\n"
        f"relocated={stats['relocated']} ({stats['relocated_chars']} chars) "
        f"deduped={stats['deduped']} ({stats['deduped_chars']} chars) "
        f"superseded={stats['superseded']} ({stats['superseded_chars']} chars)"
        + (
            f"\nllm_kept={stats['llm_kept']} llm_dropped={stats['llm_dropped']} "
            f"({stats['llm_dropped_chars']} chars)"
            if args.llm
            else ""
        )
    )
    if not args.apply and (
        stats["relocated"] or stats["deduped"] or stats["superseded"] or stats["llm_dropped"]
    ):
        print("(dry run — nothing written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
