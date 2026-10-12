"""One cell of milestone 10's AC 10 end-to-end check: one engine process, one profile.

Run by `scripts/m10_e2e.py`, never by hand. The cell is a real engine process
on a scratch profile under a scratch HOME (`spec["home"]`):

1. writes the profile's `.env` (the provider, the preset, the explicit model,
   the daily budget; the API key only for a paid cell, taken from the
   process environment and removed from it before the profile is activated);
2. for a credits profile, serves a fake billing server's
   ``GET /capabilities?protocol=mrcall-bounded-v2`` on 127.0.0.1 and puts a
   synthetic Firebase session in memory (`zylch.auth.set_session`, what
   `account.set_firebase_token` does);
3. activates the profile (`profiles.activate_profile`: the last good copy,
   then the background download) and runs one download round itself
   (`distribution.refresh`): the production fetcher, or, for the simulated
   successor, a fake data branch through the fetcher seam (`refresh(fetch=)`);
4. resolves all sixteen roles as call sites do (`routed_model`), reads the
   Settings snapshot (`policy_snapshot`), and checks every pick is priced on
   its transport;
5. optionally sends one paid call through `make_llm_client`, admitted first by
   the harness journal (USD 2 for the whole check), then by the profile's own
   durable reservation ledger, and reports the settled ledger rows.

It prints one JSON line. It never prints a key: the paid cell's key is written
to the scratch `.env` only, which the driver deletes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
MESSAGE = [{"role": "user", "content": "Reply with the single word: ready"}]
MAX_TOKENS = 48
UNKNOWN_KEY = "ac10-placeholder-not-a-key"  # never valid; a refused call must not need one


class Captured(logging.Handler):
    """Every `[model-table]` warning, so a refused download is visible in the record."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record):
        if record.name.startswith("zylch.llm.roles"):
            self.lines.append(record.getMessage())


def _server(models: list[dict]) -> tuple[HTTPServer, str]:
    answer = json.dumps(
        {
            "protocol": "mrcall-bounded-v2",
            "currency": "USD",
            "streaming": False,
            "features": ["text", "function_tools"],
            "max_tokens": 8192,
            "models": models,
        }
    ).encode()
    reads: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            reads.append(self.path)
            if self.path != "/api/desktop/llm/bounded/capabilities?protocol=mrcall-bounded-v2":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    httpd.reads = reads  # type: ignore[attr-defined]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


class Branch:
    """A fake data branch (the fetcher seam): serves the files of `folder`, ETag = sha256."""

    def __init__(self, folder: Path):
        self.folder, self.calls = folder, []

    def __call__(self, url, etag):
        name = url.rsplit("/", 1)[1]
        body = (self.folder / name).read_bytes()
        tag = '"' + hashlib.sha256(body).hexdigest() + '"'
        self.calls.append(name)
        return (304, None, tag) if etag == tag else (200, body, tag)


def _env(spec: dict, profile: Path, proxy: str | None) -> None:
    profile.mkdir(parents=True, exist_ok=True)
    lines = {
        "OWNER_ID": spec["profile"],
        "LLM_PROVIDER": spec["provider"],
        "LLM_DAILY_BUDGET_USD": spec["budget_usd"],
    }
    if spec.get("preset"):
        lines["LLM_MODEL_PRESET"] = spec["preset"]
    base = {"anthropic": "ANTHROPIC_MODEL", "openrouter": "OPENROUTER_MODEL"}
    base["mrcall"] = "MRCALL_CREDITS_MODEL"
    if spec.get("explicit"):
        lines[base[spec["provider"]]] = spec["explicit"]
    if proxy:
        lines["MRCALL_PROXY_URL"] = proxy
    key = os.environ.pop("AC10_KEY", "") or (UNKNOWN_KEY if spec.get("placeholder_key") else "")
    if key and spec["provider"] != "mrcall":
        lines["ANTHROPIC_API_KEY" if spec["provider"] == "anthropic" else "OPENROUTER_API_KEY"] = (
            key
        )
    text = "".join(f"{k}={v}\n" for k, v in lines.items())
    path = profile / ".env"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def _resolve(roles: list[str]) -> dict:
    from zylch.llm import routed_model
    from zylch.llm.budget_pricing import BudgetError
    from zylch.llm.roles.table import RolePaused

    out = {}
    for role in roles:
        try:
            out[role] = routed_model("MODEL_" + role)
        except RolePaused as pause:
            out[role] = {"paused": str(pause), "role": pause.role, "preset": pause.preset}
        except BudgetError as exc:
            out[role] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def _transport(provider: str, model: str) -> str:
    if provider == "anthropic":
        return "direct"
    if provider == "openrouter":
        return "openrouter"
    return "openrouter" if "/" in model else "direct"


def _priced(provider: str, resolved: dict) -> dict:
    from zylch.llm.roles import catalogue, prices

    out = {}
    for model in {m for m in resolved.values() if isinstance(m, str)}:
        rate = prices.price(model, _transport(provider, model))
        out[model] = {
            "transport": _transport(provider, model),
            "rate": None if rate is None else [str(rate[0]), str(rate[1])],
            "metadata": catalogue.metadata(model) is not None,
        }
    return out


def _state(profile: Path) -> dict:
    from zylch.llm.roles import catalogue, distribution, table

    folder = profile / "model-table"
    files = {}
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "sources": distribution.sources(),
        "table_version": (table.document() or {}).get("version"),
        "snapshot_version": catalogue.layers()[0]["version"],
        "cached": files,
    }


def _ledger(owner: str) -> dict:
    from sqlalchemy import select

    from zylch.llm.budget import budget_snapshot
    from zylch.storage.database import get_session
    from zylch.storage.models import LlmReservation, LlmUsage

    with get_session() as session:
        usage = session.execute(select(LlmUsage)).scalars().all()
        held = session.execute(select(LlmReservation)).scalars().all()
        rows = [
            {
                "model": u.model,
                "transport": u.transport,
                "call_site": u.call_site,
                "est_cost_usd": u.est_cost_usd,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
            }
            for u in usage
        ]
        holds = [
            {
                "model": r.model,
                "reserved_usd": r.reserved_micro_usd / 1e6,
                "settled": r.settled_at is not None,
            }
            for r in held
        ]
    return {"usage": rows, "reservations": holds, "budget": budget_snapshot(owner)}


def _bound(client) -> int:
    from zylch.llm.budget_pricing import request_bound
    from zylch.llm.client import _with_datetime
    from zylch.llm.request_shape import shaped
    from zylch.llm.response import _coerce_messages

    sent = {
        "model": client.model,
        "messages": _coerce_messages(MESSAGE),
        "max_tokens": MAX_TOKENS,
        "service_tier": "standard_only",
        "system": _with_datetime(None, None),
    }
    return request_bound(shaped(sent), client.transport)


def _admit(journal: Path, cap: int, name: str, model: str, bound: int) -> None:
    rows = [json.loads(x) for x in journal.read_text().splitlines()] if journal.exists() else []
    settled = {r["call"]: r["spent_micro_usd"] for r in rows if r["event"] == "result"}
    used = sum(settled.get(r["call"], r["bound_micro_usd"]) for r in rows if r["event"] == "intent")
    if used + bound > cap:
        raise RuntimeError(f"not sent: bound {bound} + used {used} > cap {cap} micro-USD")
    _journal(journal, {"event": "intent", "call": name, "model": model, "bound_micro_usd": bound})


def _journal(journal: Path, row: dict) -> None:
    row["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with journal.open("a") as out:
        out.write(json.dumps(row) + "\n")
        out.flush()
        os.fsync(out.fileno())


def _paid(spec: dict, owner: str) -> dict:
    """One real call through the engine's client; never retried."""
    from zylch.llm import routed_model
    from zylch.llm.client import make_llm_client
    from zylch.llm.usage import call_site

    role = spec["paid_role"]
    model = routed_model("MODEL_" + role)
    client = make_llm_client(model)
    bound = _bound(client)
    journal, name = Path(spec["journal"]), f"{spec['profile']}:{role}"
    out = {"role": role, "model": client.model, "transport": client.transport}
    out["bound_usd"] = bound / 1e6
    _admit(journal, int(spec["cap_micro_usd"]), name, client.model, bound)
    try:
        with call_site(f"ac10.{role.lower()}"):
            response = client.create_message_sync(messages=MESSAGE, max_tokens=MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 - recorded, never retried
        status = getattr(exc, "status_code", None)
        out["error"] = {"type": type(exc).__name__, "status": status, "message": str(exc)}
        out["ledger"] = _ledger(owner)
        spent = round(out["ledger"]["budget"]["spent_usd"] * 1e6)
        held = round(out["ledger"]["budget"]["reserved_usd"] * 1e6)
        _journal(journal, {"event": "result", "call": name, "spent_micro_usd": spent + held})
        return out
    out["answer"] = "".join(getattr(b, "text", "") or "" for b in response.content)
    out["answered_by"] = getattr(response._raw, "model", None)
    out["stop_reason"] = response.stop_reason
    out["ledger"] = _ledger(owner)
    spent = round(out["ledger"]["budget"]["spent_usd"] * 1e6)
    _journal(journal, {"event": "result", "call": name, "spent_micro_usd": spent})
    return out


def _refused(spec: dict) -> dict:
    """A saved model no snapshot layer prices: sent as saved, refused before dispatch."""
    from zylch.llm.client import make_llm_client

    client = make_llm_client()
    try:
        client.create_message_sync(messages=MESSAGE, max_tokens=MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 - the refusal is the result
        return {"model": client.model, "refused": f"{type(exc).__name__}: {exc}"}
    return {"model": client.model, "refused": None}


def main() -> int:
    spec = json.loads(sys.argv[1])
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    captured = Captured()
    logging.getLogger().addHandler(captured)
    import zylch

    out: dict = {"cell": spec["cell"], "engine": str(Path(zylch.__file__).resolve().parent)}
    assert out["engine"] == str(ENGINE / "zylch"), out["engine"]
    profile = Path(spec["home"]) / ".zylch" / "profiles" / spec["profile"]
    httpd, proxy = _server(spec["served"]) if spec["provider"] == "mrcall" else (None, None)
    _env(spec, profile, proxy)
    if httpd is not None:
        from zylch.auth import set_session

        expiry = int(time.time() * 1000) + 3_600_000
        set_session(spec["profile"], None, "ac10-synthetic-session", expiry)
    from zylch.cli import profiles
    from zylch.llm.roles import distribution
    from zylch.storage.database import init_db

    assert profiles.PROFILES_DIR == str(profile.parent), profiles.PROFILES_DIR
    profiles.activate_profile(spec["profile"])
    init_db()
    roles = spec["roles"]
    branch = Branch(Path(spec["branch"])) if spec.get("branch") else None
    distribution.refresh(str(profile), fetch=branch)
    out["state"] = _state(profile)
    out["resolved"] = _resolve(roles)
    from zylch.llm.model_policy import policy_snapshot

    snapshot = policy_snapshot()
    out["settings"] = {"roles": snapshot["roles"], "paused": snapshot["paused"]}
    out["priced"] = _priced(spec["provider"], out["resolved"])
    if spec.get("branch_next"):
        branch.folder = Path(spec["branch_next"])
        distribution.refresh(str(profile), fetch=branch)
        out["after_unpriced"] = {"state": _state(profile), "resolved": _resolve(roles)}
    if spec.get("refuse_call"):
        out["refusal"] = _refused(spec)
        out["refusal"]["ledger"] = _ledger(spec["profile"])
    if spec.get("paid_role"):
        out["paid"] = _paid(spec, spec["profile"])
    if httpd is not None:
        out["capabilities_reads"] = len(httpd.reads)
        httpd.shutdown()
    out["model_table_warnings"] = captured.lines
    print(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
