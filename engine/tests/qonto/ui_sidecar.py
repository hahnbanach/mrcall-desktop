import asyncio
import contextlib
import json
import logging
from pathlib import Path
import socket
import sys
from datetime import datetime, timezone

import pytest
from dotenv import dotenv_values

from tests.qonto.conftest import Environment, UID, http_api
from tests.qonto.chat_fixture import install_client
from tests.qonto.test_session_admission import signer
from tests.qonto.test_sync import raw
from tests.memory.mnemonic_env import BagOfWordsEmbedder, stub_embedder, clear_process_state
from zylch.auth import clear_session
from zylch.storage import database as dbm


def boot(root):
    from zylch import runtime
    from zylch.cli import profiles
    from zylch.qonto import sync
    from zylch.memory.mnemonic import agent
    from zylch.services import preparation
    import zylch.llm as llm

    patch = pytest.MonkeyPatch()
    home = root / "engine-home"
    home.mkdir(exist_ok=True, mode=0o700)
    directory = home / "profiles" / UID
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    saved = directory / ".env"
    initial = not saved.exists()
    if initial:
        saved.write_text(
            f"OWNER_ID={UID}\nEMAIL_ADDRESS=display@example.test\nLLM_DAILY_BUDGET_USD=5\nPREPARATION_BATCH_SIZE=25\n"
        )
        saved.chmod(0o600)
    for key, value in {
        "ZYLCH_HOME": str(home),
        "ZYLCH_PROFILE_DIR": str(directory),
        "ZYLCH_DB_PATH": str(directory / "zylch.db"),
        "OWNER_ID": UID,
        "EMAIL_ADDRESS": "display@example.test",
        "MEMORY_KEY": dotenv_values(saved).get("MEMORY_KEY", ""),
        "MEMORY_DB_DIR": str(home / "memory"),
    }.items():
        patch.setenv(key, value)
    patch.delenv("QONTO_BOOTSTRAP_ENV_FILE", raising=False)
    patch.delenv("QONTO_HOST_ID_FILE", raising=False)
    patch.setattr(runtime, "_serving", False)
    patch.setattr(profiles, "_active_profile", UID)
    patch.setattr(profiles, "_active_profile_dir", str(directory))
    patch.setattr(profiles, "PROFILES_DIR", str(home / "profiles"))
    dbm.init_db()
    env = Environment(directory, home, None)
    api = http_api.__wrapped__(env, patch)
    api.rows = [raw("native-declined", status="declined", amount="10.00")]
    api.rows[0]["label"] = "Synthetic native fixture evidence"
    patch.setattr(sync, "now", lambda: datetime(2026, 10, 4, 12, tzinfo=timezone.utc))
    stub_embedder(patch, BagOfWordsEmbedder())
    clear_process_state()
    wire = install_client(env, patch)
    patch.setattr(agent, "_default_client", lambda: llm.make_llm_client())
    clear_session()
    signed_token = signer.__wrapped__(env, patch)()
    admitted = env.rpc(
        "account.set_firebase_token", uid=UID, id_token=signed_token, expires_at_ms=2**53
    )
    assert admitted["result"]["ok"]
    if initial:
        preparation.pause(UID)
    real_connect = socket.socket.connect

    def offline(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Native fixture attempted an external connection")
        return real_connect(self, address)

    patch.setattr(socket.socket, "connect", offline)
    return env, api, wire, patch


def inspect(wire, api):
    from zylch.memory.mnemonic import journal
    from zylch.storage.models import Blob, MemoryOperation, TaskItem
    from zylch.qonto.models import QontoTransaction, QontoCheckpoint
    from zylch.qonto import repository
    from zylch.services import preparation

    with repository.profile_transaction() as session:
        private = {
            "transactions": session.query(QontoTransaction).count(),
            "checkpoints": session.query(QontoCheckpoint).count(),
            "tasks": session.query(TaskItem).filter_by(event_type="qonto").count(),
        }
    with journal.company_transaction() as session:
        blobs = session.query(Blob).all()
        operations = session.query(MemoryOperation).all()
        company = {
            "facts": len(blobs),
            "minimal_only": all(
                "The company uses Qonto." in row.content
                and "10.00" not in row.content
                and "Synthetic" not in row.content
                for row in blobs
            ),
            "receipts": len(operations),
            "committed": all(
                row.state == "committed"
                and row.payload is None
                and row.source_ref.startswith("qonto:")
                and row.result.get("committed_ids")
                for row in operations
            ),
        }
    with dbm.get_engine().connect() as connection:
        ledger = [
            dict(row)
            for row in connection.exec_driver_sql(
                "SELECT settled_at FROM llm_reservations"
            ).mappings()
        ]
    return {
        **private,
        **company,
        "reservations": len(ledger),
        "settled": sum(row["settled_at"] is not None for row in ledger),
        "wire_calls": len(wire.calls),
        "paused": preparation.status(UID)["paused"],
        "get_only": all(
            request.method == "GET" and request.url.host == "thirdparty.qonto.com"
            for request in api.requests
        ),
    }


async def run(env, api, wire, patch):
    previews = {}
    print(json.dumps({"ready": True}), flush=True)
    try:
        for line in sys.stdin:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if request.get("control") == "inspect":
                    result = {"id": request["id"], "result": inspect(wire, api)}
                else:
                    if (
                        request["method"] == "qonto.publish"
                        and request.get("params", {}).get("preview_id") in previews
                    ):
                        wire.answer(
                            json.dumps(
                                dict(
                                    action="CREATE",
                                    entity_type="FACT",
                                    scope="company",
                                    content=previews[request["params"]["preview_id"]],
                                    reason="Confirmed minimal company projection.",
                                )
                            )
                        )
                    result = await env.arpc(request["method"], **request.get("params", {}))
                    result["id"] = request["id"]
                    if request["method"] == "qonto.publication_preview" and "result" in result:
                        previews[result["result"]["preview_id"]] = result["result"]["fact_text"]
            print(json.dumps(result), flush=True)
    finally:
        clear_session()
        dbm.dispose_engine()
        patch.undo()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(sys.stderr):
        state = boot(Path(sys.argv[1]))
    asyncio.run(run(*state))
