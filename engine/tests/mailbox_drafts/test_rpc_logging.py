"""Draft-bearing campaign RPC calls never persist an editable text copy in logs."""
import asyncio
import json
import logging

import pytest

from zylch.rpc import dispatch


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Dispatcher-only checks use no retired SaaS storage fixture."""
    yield


@pytest.mark.parametrize("method,identity", [
    ("campaign.add_contact", {"campaign_id": "synthetic-campaign", "email": "recipient@example.test"}),
    ("campaign.update_contact", {"contact_id": "synthetic-contact"}),
])
def test_campaign_dispatch_redacts_text_before_debug_log(method, identity, monkeypatch, caplog):
    async def accepted(params, notify):
        return {"ok": True}
    monkeypatch.setitem(dispatch.METHODS, method, accepted)
    caplog.set_level(logging.DEBUG, logger="zylch.rpc.dispatch")
    private = {"draft_subject": "synthetic-private-subject", "draft_body": "synthetic-private-body",
               "dossier": {"research": "synthetic-private-research"}, "draft_request_key": "synthetic-key"}
    result = asyncio.run(dispatch.dispatch_raw(json.dumps({"jsonrpc": "2.0", "id": 1,
        "method": method, "params": {**identity, **private}}), lambda *args: None))
    assert result["result"]["ok"]
    records = [record.getMessage() for record in caplog.records if record.name == "zylch.rpc.dispatch"]
    assert records and any(method in record for record in records)
    logs = " ".join(records)
    for text in (private["draft_subject"], private["draft_body"], private["dossier"]["research"], private["draft_request_key"]):
        assert text not in logs
