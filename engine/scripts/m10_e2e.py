"""Milestone 10's AC 10 end-to-end check of model selection by requirements.

The brief's AC 10: one profile per provider (Anthropic key, OpenRouter key,
MrCall credits) under `economy` and `balanced`, plus a `custom` profile with an
explicit model, across three scenarios — the table downloaded, the download
blocked, a simulated successor — with the expected picks, no pause on the
explicit model, credits on the best served model, and paid legs under USD 2.

Every cell is its own engine process (`scripts/m10_e2e_cell.py`) on a scratch
profile under a scratch HOME inside `--root`; nothing touches `~/.zylch`. The
expected picks come from an oracle that reads the tables as plain JSON and
applies the rule `docs/features/model-selection.md` states, never through the
engine's resolver:

- `downloaded`: the engine downloads `v1/table.json` and `v1/snapshot.json`
  from the data branch; the oracle is a separate download of the same files,
  and the profile's cached copies must be those bytes;
- `blocked`: egress is a closed local port (`HTTPS_PROXY`, honoured by the
  engine's HTTP client), a fresh profile: the build copies are in force;
  `blocked-cached` reuses `downloaded`'s profiles: their last good copy is;
- `successor`: a fake data branch (the fetcher seam) publishes the downloaded
  table and snapshot with Sonnet 5.5 replaced by an unknown "Sonnet 6", priced
  in the new snapshot; then a table ranking an id no snapshot prices, which
  must be refused, and saved explicit models no snapshot prices, whose calls
  must be refused before dispatch.

Credits run against a fake billing server serving (a) every ranked model, (b)
only some ids, (c) only an unranked id. The paid legs (`--paid`) are one call
per preset on OpenRouter and on the Anthropic key, and one on the custom
profile, each journalled against a USD 2 cap before it is sent; each paid
profile's daily budget is USD 0.30, so the engine's own ledger refuses past
it too. Keys come from the environment only; every `.env` written is deleted
at the end and the deletion is checked.

    python scripts/m10_e2e.py --root DIR            # the free matrix
    python scripts/m10_e2e.py --root DIR --paid     # the paid legs only
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
CELL = Path(__file__).resolve().parent / "m10_e2e_cell.py"
ROLES_DIR = ENGINE / "zylch" / "llm" / "roles"
URL = "https://raw.githubusercontent.com/hahnbanach/mrcall-desktop/model-table/v1/{}"
CAP_MICRO_USD = 2_000_000
FILES = ("table.json", "snapshot.json")
PAID_BUDGET = "0.30"
BLOCKED = "http://127.0.0.1:9"  # discard port: nothing listens, every connection is refused
SONNET, SONNET_DIRECT = "anthropic/claude-sonnet-5.5", "claude-sonnet-5-5"
SUCCESSOR, SUCCESSOR_DIRECT = "anthropic/claude-sonnet-6", "claude-sonnet-6"
UNPRICED, UNPRICED_DIRECT = "anthropic/claude-sonnet-7", "claude-sonnet-7"
UNRANKED = "vendor/unranked-model-1"
EXPLICIT = {"anthropic": "claude-sonnet-4-6", "openrouter": "z-ai/glm-5.3-flash"}
EXPLICIT["mrcall"] = "claude-sonnet-4-6"
KEYS = {"anthropic": "MNEMONIC_ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
PAID = {  # (provider, preset) -> the role of the one paid call
    ("openrouter", "economy"): "TASK_DETECTION",
    ("openrouter", "balanced"): "NARRATION",
    ("anthropic", "economy"): "MEMORY_EXTRACT",
    ("anthropic", "balanced"): "NARRATION",
}


def roles() -> list[str]:
    return list(json.loads((ROLES_DIR / "requirements.json").read_text())["roles"])


# ── the oracle ─────────────────────────────────────────────


def expect(doc: dict, provider: str, preset: str, served: list[dict], explicit: str | None):
    """{role: model or "PAUSED"} by the documented rule, from the table as JSON."""
    out = {}
    listed = {m["id"]: m["provider"] for m in served}
    for role in roles():
        if explicit:
            out[role] = explicit
            continue
        rankings = doc["presets"][preset]["roles"][role]
        if provider == "openrouter":
            out[role] = rankings["ranking"][0]["id"]
        elif provider == "anthropic":
            column = rankings["anthropic_ranking"]
            out[role] = column[0]["direct_id"] if column else "PAUSED"
        else:
            out[role] = "PAUSED"
            for entry in rankings["ranking"]:
                if entry["direct_id"] and listed.get(entry["direct_id"]) == "anthropic":
                    out[role] = entry["direct_id"]
                    break
                if listed.get(entry["id"]) == "openrouter":
                    out[role] = entry["id"]
                    break
    return out


def entry(model: str, provider: str) -> dict:
    return {"id": model, "label": model.split("/")[-1], "provider": provider}


def servers(doc: dict, drop: tuple[str, ...] = ()) -> dict[str, list[dict]]:
    """(a) every ranked model, direct ids as Anthropic's; (b) catalogue ids only,
    on OpenRouter, without the most frequent pick and `drop`; (c) an unranked id."""
    ranked = [
        e
        for body in doc["presets"].values()
        for rankings in body["roles"].values()
        for e in rankings["ranking"]
    ]
    direct = dict.fromkeys(e["direct_id"] for e in ranked if e["direct_id"])
    ids = dict.fromkeys(e["id"] for e in ranked)
    picks = Counter(
        rankings["ranking"][0]["id"]
        for body in doc["presets"].values()
        for rankings in body["roles"].values()
    )
    gone = {picks.most_common(1)[0][0], *drop}
    return {
        "all": [entry(m, "anthropic") for m in direct] + [entry(m, "openrouter") for m in ids],
        "some": [entry(m, "openrouter") for m in ids if m not in gone],
        "none": [entry(UNRANKED, "openrouter")],
    }


# ── the scenarios' documents ───────────────────────────────


def download(folder: Path) -> dict[str, dict]:
    import httpx

    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in ("table.json", "snapshot.json"):
        response = httpx.get(URL.format(name), timeout=30)
        response.raise_for_status()
        (folder / name).write_bytes(response.content)
        out[name] = json.loads(response.content)
    return out


def successor(published: dict[str, dict], folder: Path) -> dict[str, dict]:
    """The published copies with Sonnet 5.5 replaced by an unknown Sonnet 6 (same
    metadata and price, so within both ceilings), and, in `folder/next`, a table
    that also ranks Sonnet 7 first for CHAT, which no snapshot prices."""
    sys.path.insert(0, str(ENGINE))
    from zylch.llm.roles import gates

    snap = copy.deepcopy(published["snapshot.json"])
    snap["models"][SUCCESSOR] = copy.deepcopy(snap["models"][SONNET])
    row = copy.deepcopy(snap["direct"][SONNET_DIRECT])
    row["catalogue_id"] = SUCCESSOR
    snap["direct"][SUCCESSOR_DIRECT] = row
    snap = gates.stamped({k: v for k, v in snap.items() if k != "version"})
    text = json.dumps({k: v for k, v in published["table.json"].items() if k != "version"})
    text = text.replace(f'"{SONNET}"', f'"{SUCCESSOR}"')
    text = text.replace(f'"{SONNET_DIRECT}"', f'"{SUCCESSOR_DIRECT}"')
    record = gates.stamped(json.loads(text))
    unpriced = copy.deepcopy(record)
    for preset in unpriced["presets"].values():
        chat = preset["roles"]["CHAT"]
        top = {"id": UNPRICED, "direct_id": UNPRICED_DIRECT}
        chat["ranking"].insert(0, top)
        chat["anthropic_ranking"].insert(0, top)
        del chat["ranking"][5:], chat["anthropic_ranking"][5:]
    unpriced = gates.stamped({k: v for k, v in unpriced.items() if k != "version"})
    for where, doc in ((folder, record), (folder / "next", unpriced)):
        where.mkdir(parents=True, exist_ok=True)
        (where / "table.json").write_text(json.dumps(doc))
        (where / "snapshot.json").write_text(json.dumps(snap))
    return {"table.json": record, "snapshot.json": snap, "unpriced": unpriced}


# ── the matrix ─────────────────────────────────────────────


def cells(scenario: str, doc: dict, paid: bool) -> list[dict]:
    """The profiles of one scenario: OpenRouter and Anthropic per preset, credits per
    preset and server, the custom profiles."""
    drop = (SUCCESSOR,) if scenario == "successor" else ()
    lists = servers(doc, drop)
    out = []
    for preset in ("economy", "balanced"):
        for provider in ("openrouter", "anthropic"):
            out.append({"provider": provider, "preset": preset})
        for server in ("all", "some", "none"):
            out.append({"provider": "mrcall", "preset": preset, "server": server})
    for provider in ("anthropic", "openrouter", "mrcall"):
        out.append({"provider": provider, "preset": "custom", "explicit": EXPLICIT[provider]})
    out[-1]["server"] = "none"  # credits custom: the explicit model, whatever is served
    if scenario == "successor":
        out.append({"provider": "anthropic", "preset": "custom", "explicit": SUCCESSOR_DIRECT})
        for provider, model in (("anthropic", UNPRICED_DIRECT), ("openrouter", UNPRICED)):
            out.append(
                {"provider": provider, "preset": "custom", "explicit": model, "refuse_call": True}
            )
    for spec in out:
        spec["served"] = lists[spec["server"]] if spec["provider"] == "mrcall" else []
        name = "-".join(
            str(spec[k]) for k in ("provider", "preset", "server", "explicit") if spec.get(k)
        )
        spec["profile"] = f"ac10-{scenario}-" + name.replace("/", "_")
        spec["expected"] = expect(
            doc,
            spec["provider"],
            spec["preset"] if spec["preset"] != "custom" else "economy",
            spec["served"],
            spec.get("explicit"),
        )
    if paid:
        out = [s for s in out if (s["provider"], s["preset"]) in PAID or s["preset"] == "custom"]
        out = [s for s in out if s["provider"] != "mrcall"]
    return out


def run_cell(spec: dict, env: dict, logs: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(CELL), json.dumps(spec)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    (logs / f"{spec['cell']}.log").write_text(proc.stderr)
    lines = [x for x in proc.stdout.splitlines() if x.startswith("{")]
    if proc.returncode != 0 or not lines:
        return {"cell": spec["cell"], "crashed": proc.returncode, "tail": proc.stderr[-4000:]}
    return json.loads(lines[-1])


def compare(spec: dict, result: dict) -> dict:
    """Each role: expected, actual, and whether they agree (a pause names its role)."""
    rows, bad = {}, []
    for role, want in spec["expected"].items():
        got = result.get("resolved", {}).get(role)
        if want == "PAUSED":
            ok = isinstance(got, dict) and got.get("role") == role and "paused" in got
        else:
            ok = got == want
        rows[role] = {"expected": want, "actual": got, "ok": ok}
        if not ok:
            bad.append(role)
    return {"roles": rows, "mismatched": bad, "failed_checks": checks(spec, result)}


def checks(spec: dict, result: dict) -> list[str]:
    """The cell's other assertions; each failure as a sentence (empty: all held)."""
    if "state" not in result:
        return ["no result"]
    want, state, fail = spec["oracle"], result["state"], []
    if state["sources"] != want["sources"]:
        fail.append(f"sources {state['sources']} != {want['sources']}")
    if state["table_version"] != want["table"]:
        fail.append(f"table in force {state['table_version']} != {want['table']}")
    if state["snapshot_version"] != want["snapshot"]:
        fail.append(f"snapshot in force {state['snapshot_version']} != {want['snapshot']}")
    for name, digest in (want.get("cached") or {}).items():
        if state["cached"].get(name) != digest:
            fail.append(f"cached {name} is not the published bytes")
    warnings = " | ".join(result.get("model_table_warnings", []))
    if spec["scenario"].startswith("blocked") and "download failed" not in warnings:
        fail.append("no failed download logged")
    paused = {k.removeprefix("MODEL_") for k in result["settings"]["paused"]}
    expected = {r for r, m in spec["expected"].items() if m == "PAUSED"}
    if paused != expected:
        fail.append(f"Settings pauses {sorted(paused)} != {sorted(expected)}")
    for role, model in result["resolved"].items():
        if isinstance(model, str) and result["settings"]["roles"].get("MODEL_" + role) != model:
            fail.append(f"Settings reads {role} differently")
    unpriced = sorted(m for m, v in result["priced"].items() if not v["rate"] or not v["metadata"])
    if unpriced != ([spec["explicit"]] if spec.get("refuse_call") else []):
        fail.append(f"unpriced picks {unpriced}")
    if spec.get("branch_next"):
        after = result.get("after_unpriced") or {}
        if (after.get("state") or {}).get("table_version") != want["table"]:
            fail.append("a table ranking an unpriced id replaced the table in force")
        if after.get("resolved") != result["resolved"]:
            fail.append("picks moved after the unpriced table was refused")
        if "anthropic/claude-sonnet-7 is not in the snapshot" not in warnings:
            fail.append("the unpriced table's refusal was not logged")
    if spec.get("refuse_call"):
        refusal = result.get("refusal") or {}
        reason = {"anthropic": "model pricing is not configured"}.get(spec["provider"])
        reason = reason or "OpenRouter model has no verified price ceiling"
        if reason not in str(refusal.get("refused")):
            fail.append(f"the unpriced explicit call was not refused: {refusal.get('refused')}")
        ledger = refusal.get("ledger") or {}
        if ledger.get("reservations") or ledger.get("usage"):
            fail.append("the refused call reserved or recorded something")
    return fail


def cell_env(home: Path, blocked: bool) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in (*KEYS.values(), "ANTHROPIC_API_KEY")}
    env.pop("ZYLCH_HOME", None)
    env.pop("ZYLCH_PROFILE_DIR", None)
    env.update(HOME=str(home), PYTHONPATH=str(ENGINE), NO_PROXY="127.0.0.1,localhost")
    env["no_proxy"] = env["NO_PROXY"]
    if blocked:
        env.update(HTTPS_PROXY=BLOCKED, https_proxy=BLOCKED, HTTP_PROXY=BLOCKED)
        env["http_proxy"] = BLOCKED
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--paid", action="store_true", help="the paid legs only")
    parser.add_argument("--out", type=Path, help="write the condensed record here")
    parser.add_argument("--raw", type=Path, help="write every cell's whole result here")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if str(root).startswith(str(Path.home() / ".zylch")):
        parser.error("the root must be a scratch directory")
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    published = download(root / "oracle" / "published")
    build = {name: json.loads((ROLES_DIR / name).read_text()) for name in FILES}
    digests = {
        name: hashlib.sha256((root / "oracle" / "published" / name).read_bytes()).hexdigest()
        for name in FILES
    }

    def oracle(docs: dict, sources: str, cached: dict | None = None) -> dict:
        return {
            "sources": {"snapshot": sources, "table": sources},
            "table": docs["table.json"]["version"],
            "snapshot": docs["snapshot.json"]["version"],
            "cached": cached,
        }

    plan = [("downloaded", published, False, None, oracle(published, "downloaded", digests))]
    if not args.paid:
        made = successor(published, root / "oracle" / "successor")
        plan += [
            ("blocked", build, True, None, oracle(build, "build")),
            ("blocked-cached", published, True, "downloaded", oracle(published, "cached", digests)),
            ("successor", made, True, None, oracle(made, "downloaded")),
        ]
    results, anthropic_refused, served_by = [], False, {}
    for scenario, docs, blocked, home_of, expected_state in plan:
        home = root / f"home-{home_of or scenario}"
        doc = docs["table.json"]
        specs = cells("downloaded" if home_of else scenario, doc, args.paid)
        drop = (SUCCESSOR,) if scenario == "successor" else ()
        served_by[scenario] = {
            name: [f"{m['id']} ({m['provider']})" for m in models]
            for name, models in servers(doc, drop).items()
        }
        if home_of:  # the downloaded profiles, now with egress blocked
            specs = [s for s in specs if s["preset"] != "custom"]
        for spec in specs:
            spec.update(home=str(home), roles=roles(), scenario=scenario, oracle=expected_state)
            spec["cell"] = f"{scenario}:{spec['profile']}"
            spec["budget_usd"] = "0"
            if scenario == "successor":
                spec["branch"] = str(root / "oracle" / "successor")
                if spec["provider"] != "mrcall" and spec["preset"] != "custom":
                    spec["branch_next"] = str(root / "oracle" / "successor" / "next")
                spec["placeholder_key"] = bool(spec.get("refuse_call"))
            env = cell_env(home, blocked)
            paid_role = PAID.get((spec["provider"], spec["preset"]))
            if args.paid and spec["preset"] == "custom":
                paid_role = "NARRATION"  # a role an Anthropic key pauses on under economy
                if spec["provider"] == "anthropic" and anthropic_refused:
                    paid_role = None
                elif spec["provider"] == "openrouter" and not anthropic_refused:
                    paid_role = None  # one custom call: on the Anthropic key when it works
            if args.paid and spec["provider"] == "anthropic" and anthropic_refused:
                paid_role = None
            if args.paid and paid_role:
                spec.update(
                    paid_role=paid_role,
                    budget_usd=PAID_BUDGET,
                    journal=str(root / "paid-journal.jsonl"),
                    cap_micro_usd=CAP_MICRO_USD,
                )
                env["AC10_KEY"] = os.environ[KEYS[spec["provider"]]]
            elif args.paid:
                continue
            result = run_cell(spec, env, logs)
            env.pop("AC10_KEY", None)
            result["scenario"], result["spec"] = scenario, {
                k: v for k, v in spec.items() if k not in ("roles", "home", "expected", "served")
            }
            result["comparison"] = compare(spec, result)
            error = (result.get("paid") or {}).get("error") or {}
            if spec["provider"] == "anthropic" and error.get("status") in (401, 403):
                anthropic_refused = True
            results.append(result)
            print(
                json.dumps(
                    {
                        "cell": spec["cell"],
                        "sources": result.get("state", {}).get("sources"),
                        "mismatched": result["comparison"]["mismatched"],
                        "failed_checks": result["comparison"]["failed_checks"],
                        "crashed": result.get("crashed"),
                        "paid": (
                            {
                                k: (result.get("paid") or {}).get(k)
                                for k in ("model", "answer", "error")
                            }
                            if spec.get("paid_role")
                            else None
                        ),
                    }
                ),
                flush=True,
            )
    leaks = check_logs(logs)
    envs = cleanup(root)
    summary = {"cells": len(results), "leaked_key_in_logs": leaks, "env_files_left": envs}
    summary["mismatched_cells"] = [r["cell"] for r in results if r["comparison"]["mismatched"]]
    summary["crashed"] = [r["cell"] for r in results if r.get("crashed") is not None]
    summary["failed_checks"] = {
        r["cell"]: r["comparison"]["failed_checks"]
        for r in results
        if r["comparison"]["failed_checks"]
    }
    print(json.dumps(summary), flush=True)
    versions = {f"published_{n}": published[n]["version"] for n in FILES}
    versions.update({f"build_{n}": build[n]["version"] for n in FILES})
    if not args.paid:
        versions.update({f"successor_{n}": made[n]["version"] for n in FILES})
        versions["successor_unpriced_table.json"] = made["unpriced"]["version"]
    record = {"summary": summary, "versions": versions, "servers": served_by}
    if args.raw:
        args.raw.write_text(json.dumps({**record, "cells": results}, indent=1) + "\n")
    if args.out:
        record["cells"] = [condensed(r) for r in results]
        args.out.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    failed = summary["mismatched_cells"] or summary["crashed"] or summary["failed_checks"]
    return 0 if not (failed or leaks or envs) else 1


def condensed(result: dict) -> dict:
    """One cell of the committed record: what was asked, what the engine did."""
    spec = result["spec"]
    out = {k: spec.get(k) for k in ("scenario", "profile", "provider", "preset", "server")}
    out["explicit"] = spec.get("explicit")
    state = result.get("state") or {}
    out["in_force"] = {
        "sources": state.get("sources"),
        "table": state.get("table_version"),
        "snapshot": state.get("snapshot_version"),
    }
    out["roles"] = {}
    for role, row in result["comparison"]["roles"].items():
        actual = row["actual"]
        if isinstance(actual, dict):
            actual = "PAUSED: " + actual.get("paused", actual.get("error", ""))
        out["roles"][role] = {"expected": row["expected"], "actual": actual, "ok": row["ok"]}
    out["settings_paused"] = sorted((result.get("settings") or {}).get("paused", {}))
    out["failed_checks"] = result["comparison"]["failed_checks"]
    if "after_unpriced" in result:
        after = result["after_unpriced"]
        out["after_unpriced_table"] = {
            "sources": after["state"]["sources"],
            "table": after["state"]["table_version"],
            "picks_unchanged": after["resolved"] == result["resolved"],
        }
    if "refusal" in result:
        out["refusal"] = {k: result["refusal"][k] for k in ("model", "refused")}
    if "paid" in result:
        out["paid"] = result["paid"]
    return out


def check_logs(logs: Path) -> bool:
    """True when any log holds a key value (checked, never printed)."""
    keys = [os.environ.get(k, "") for k in KEYS.values()]
    keys = [k for k in keys if len(k) >= 16]
    for path in logs.iterdir():
        text = path.read_text(errors="replace")
        if any(k in text or k[-12:] in text for k in keys):
            return True
    return False


def cleanup(root: Path) -> list[str]:
    """Delete every `.env` under `root`; the ones that could not be deleted."""
    for path in root.rglob(".env"):
        path.unlink()
    return [str(p) for p in root.rglob(".env")]


if __name__ == "__main__":
    sys.exit(main())
