"""Typed email action failures survive optimistic model summaries."""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zylch.assistant import core
from zylch.services.chat_service import ChatService
from zylch.tools.base import Tool, ToolResult, ToolStatus


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield


class Action(Tool):
    def __init__(self, name, status):
        super().__init__(name, "deterministic local action")
        self.status = status
        self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        await asyncio.sleep(0)
        return ToolResult(self.status, {"body": "SECRET_BODY"}, error="SECRET_ERROR")

    def get_schema(self):
        return {"name": self.name, "description": self.description, "input_schema": {}}


def use(name, identity="SECRET_ID\n" * 100):
    return SimpleNamespace(type="tool_use", name=name, id=identity,
                           input={"body": "SECRET_INPUT"})


@pytest.fixture
def setup_service(monkeypatch):
    monkeypatch.setattr(core, "new_turn_id", lambda: "turn_test")
    monkeypatch.setattr(core, "get_system_prompt_base", lambda: "test")
    monkeypatch.setattr(core, "get_personal_data_section", lambda **kwargs: "")
    monkeypatch.setattr(core, "get_channel_status_block", lambda: "")
    from zylch.tools.factory import ToolFactory
    monkeypatch.setattr(ToolFactory, "_session_state", None)

    def build(actions):
        agent = core.ZylchAIAgent.__new__(core.ZylchAIAgent)
        agent.tools = actions
        agent.tool_map = {tool.name: tool for tool in actions}
        agent.conversation_history = []
        agent.message_count = 0
        agent.last_truncations = []
        agent.triggered_instructions = []
        agent.model_selector = SimpleNamespace(select_model=lambda *a, **k: "test")
        service = ChatService.__new__(ChatService)
        service.agent = agent
        service._initialized = True
        service.storage = SimpleNamespace(get_unread_notifications=lambda user: [])
        service._initialize_agent = AsyncMock()
        service._match_semantic_command = lambda message: None
        service._check_auto_sync = lambda user, banner: banner
        return service
    return build


def script(agent, blocks):
    responses = iter([
        SimpleNamespace(stop_reason="tool_use", content=blocks, usage={}),
        SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Everything sent successfully.")], usage={}),
    ])
    agent._create_message_within_budget = AsyncMock(side_effect=lambda **kwargs: next(responses))


async def approve(*args):
    return True


@pytest.mark.parametrize("name", ["create_draft", "update_draft", "send_draft"])
def test_real_tool_error_survives_optimistic_prose(setup_service, name):
    action = Action(name, ToolStatus.ERROR)
    service = setup_service([action])
    script(service.agent, [use(name)])
    result = asyncio.run(service.process_message("please handle this", "owner", approval_callback=approve))
    assert result["response"] == "Everything sent successfully."
    record = result["metadata"]["action_failures"][0]
    assert record == {"tool": name, "attempt_id": "attempt_" + hashlib.sha256(("turn_test:1:0:" + "SECRET_ID\n" * 100).encode()).hexdigest()[:16],
                      "failure_kind": "tool_error", "delivery_certainty": "unknown"}
    error = result["metadata"]["error"]
    assert name in error and record["attempt_id"] in error
    assert "attempted action failed" in error.lower()
    assert "delivery unknown" in error.lower() and "retry blindly" in error.lower()
    assert "SECRET" not in json.dumps(result["metadata"])
    assert action.calls == 1


def test_success_after_failure_and_bounded_metadata(setup_service):
    bad = Action("create_draft", ToolStatus.ERROR)
    good = Action("update_draft", ToolStatus.SUCCESS)
    service = setup_service([bad, good])
    script(service.agent, [use(bad.name, str(i)) for i in range(25)] + [use(good.name)])
    result = asyncio.run(service.process_message("handle this", "owner", approval_callback=approve))
    assert len(result["metadata"]["action_failures"]) == 16
    assert result["metadata"]["error"]
    assert bad.calls == 25 and good.calls == 1


@pytest.mark.parametrize("name,status", [("create_draft", ToolStatus.SUCCESS), ("read_email", ToolStatus.ERROR)])
def test_success_and_read_error_are_unchanged(setup_service, name, status):
    service = setup_service([Action(name, status)])
    script(service.agent, [use(name)])
    result = asyncio.run(service.process_message("handle this", "owner", approval_callback=approve))
    assert "action_failures" not in result["metadata"]
    assert "error" not in result["metadata"]


def test_approval_decline_is_not_an_attempt(setup_service):
    tool = Action("send_draft", ToolStatus.ERROR)
    service = setup_service([tool])
    script(service.agent, [use(tool.name)])
    result = asyncio.run(service.process_message("handle this", "owner", approval_callback=AsyncMock(return_value=False)))
    assert tool.calls == 0
    assert "error" not in result["metadata"]


def test_sequential_requests_do_not_share_failures(setup_service):
    tool = Action("create_draft", ToolStatus.ERROR)
    service = setup_service([tool])
    script(service.agent, [use(tool.name)])
    first = asyncio.run(service.process_message("handle this", "owner"))
    tool.status = ToolStatus.SUCCESS
    script(service.agent, [use(tool.name)])
    second = asyncio.run(service.process_message("handle this", "owner"))
    assert first["metadata"]["error"]
    assert "error" not in second["metadata"]


def test_concurrent_requests_have_isolated_collectors(setup_service):
    service = setup_service([Action("create_draft", ToolStatus.ERROR), Action("update_draft", ToolStatus.SUCCESS)])
    rounds = {}
    async def response(**kwargs):
        task = asyncio.current_task().get_name()
        count = rounds.get(task, 0)
        rounds[task] = count + 1
        await asyncio.sleep(0)
        return SimpleNamespace(stop_reason="tool_use" if count == 0 else "end_turn", usage={},
            content=[use("create_draft" if task == "bad" else "update_draft")] if count == 0 else [SimpleNamespace(text="Success")])
    service.agent._create_message_within_budget = response
    async def run():
        return await asyncio.gather(asyncio.create_task(service.process_message("handle this", "owner"), name="bad"),
                                    asyncio.create_task(service.process_message("handle this", "owner"), name="good"))
    bad, good = asyncio.run(run())
    assert bad["metadata"]["error"]
    assert "error" not in good["metadata"]


@pytest.mark.parametrize("exception", [RuntimeError("existing failure"), asyncio.CancelledError()])
def test_call_boundary_exceptions_propagate(setup_service, exception):
    service = setup_service([Action("create_draft", ToolStatus.ERROR)])
    service.agent._call_tool = AsyncMock(side_effect=exception)
    failures = []
    with pytest.raises(type(exception)):
        asyncio.run(service.agent._execute_tools([use("create_draft")], action_failures=failures))
    assert failures == []


def test_attempt_identity_includes_turn(setup_service, monkeypatch):
    service = setup_service([Action("create_draft", ToolStatus.ERROR)])
    identities = []
    for turn in ("turn_one", "turn_two"):
        monkeypatch.setattr(core, "new_turn_id", lambda value=turn: value)
        script(service.agent, [use("create_draft", "repeated_provider_id")])
        result = asyncio.run(service.process_message("handle this", "owner"))
        identities.append(result["metadata"]["action_failures"][0]["attempt_id"])
    assert identities[0] != identities[1]


def test_existing_kernel_consumers_accept_actual_metadata(setup_service, tmp_path):
    import os
    import subprocess
    from pathlib import Path
    kernel = os.environ.get("CS_KERNEL_TEST_ROOT")
    if not kernel:
        pytest.skip("CS_KERNEL_TEST_ROOT is required for the kernel consumer check")
    service = setup_service([Action("send_draft", ToolStatus.ERROR)])
    script(service.agent, [use("send_draft")])
    result = asyncio.run(service.process_message("handle this", "owner", approval_callback=approve))
    program = '''import io,json,sys
from contextlib import redirect_stderr
from cs import cli,operator_recovery
result=json.load(sys.stdin)
err=io.StringIO()
with redirect_stderr(err):
    rc=cli._chat_engine_error(result)
assert rc == cli._ENGINE_ERROR_RC and rc != 0
assert result['metadata']['error'] in err.getvalue()
events=[{'type':'assistant','message':{'content':[{'type':'tool_use','id':'chat','name':'Bash','input':{'command':'cs chat'}}]}},
{'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'chat','is_error':True,'content':err.getvalue()}]}},
{'type':'result','is_error':True,'result':'Action failed'}]
attempt=operator_recovery.Attempt(rc,events)
assert not operator_recovery._prework_refusal(attempt)
assert attempt.result['is_error'] is True
print('actual metadata -> CLI nonzero; executed-tool outer failure -> no prework fallback')
'''
    env = dict(os.environ, PYTHONPATH=kernel)
    process = subprocess.run([str(Path(kernel) / ".venv/bin/python"), "-B", "-c", program],
        input=json.dumps(result), text=True, capture_output=True, env=env, cwd=tmp_path)
    assert process.returncode == 0, process.stderr
    assert "CLI nonzero" in process.stdout


@pytest.mark.parametrize("status", [ToolStatus.ERROR, ToolStatus.SUCCESS])
def test_real_scoped_assignment_route(setup_service, monkeypatch, status):
    from zylch.services import task_assignment_draft_policy as policy
    service = setup_service([Action("create_draft", status)])
    script(service.agent, [use("create_draft")])
    monkeypatch.setattr(policy.projection, "project", lambda root: {"complete": True, "hold_auto_reply": False})
    monkeypatch.setattr(policy.evidence, "admission", lambda: (SimpleNamespace(mailbox="owner"), None, None))
    with policy.scope("<scoped@example.test>"):
        result = asyncio.run(service.process_message("draft the reply", "owner", session_id="scoped-session"))
    assert result["response"] == "Everything sent successfully."
    assert result["session_id"] == "scoped-session"
    assert result["metadata"]["assignment_draft_policy"] == policy.VERSION
    if status == ToolStatus.ERROR:
        assert result["metadata"]["action_failures"][0]["tool"] == "create_draft"
        assert "attempted action failed" in result["metadata"]["error"]
        assert "delivery unknown" in result["metadata"]["error"]
    else:
        assert result["metadata"] == {"assignment_draft_policy": policy.VERSION}


@pytest.mark.parametrize("name", ["create_draft", "update_draft", "send_draft"])
def test_m10_read_only_refusal_precedes_collector_and_approval(setup_service, name):
    from zylch.services.request_policy import policy_scope
    action = Action(name, ToolStatus.ERROR)
    service = setup_service([action])
    script(service.agent, [use(name)])
    approval = AsyncMock(return_value=True)
    with policy_scope("read_only"):
        result = asyncio.run(service.process_message("handle this", "owner", approval_callback=approval))
    approval.assert_not_awaited()
    assert action.calls == 0
    assert "action_failures" not in result["metadata"]
    assert "error" not in result["metadata"]
