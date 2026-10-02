"""Every measurement case of the agent and smoke roles captures one request of its role.

Milestone 10 measures a role by replaying, on several models, the request the
engine builds for it. For CHAT, TASK_SOLVE, COMPACTION, NARRATION, WEB_SEARCH
and TRAIN that request comes from the harness beside the cases
(``tests/fixtures/measurement/<ROLE>/capture.py``), which drives the role's
own code path with a capturing client. This suite runs each harness on every
case — no network, no key, no paid call — and holds what a replay relies on:

- one request per case, from the role's call site and no other, carrying the
  role's tools where it has them and what the case seeded, JSON as sent,
  nothing left at a default, no real model id in it;
- a replayed tool round ends the captured transcript, so the decision the
  label scores is the one the request asks for;
- the labels of the tool-using roles name tools, arguments and scripted
  results the captured request actually carries;
- the same case captures the same bytes twice (the measurement caches on
  it), and the environment the capture runs in never reaches the prompt;
- a turn continued past the capture runs through the scripted tools;
- the chat's own web search, which the cases cannot measure, is still refused
  by the engine's admission.
"""

from __future__ import annotations

import importlib.util
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tests.measurement import conversation_capture as cc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "measurement"
ROLES = ("CHAT", "TASK_SOLVE", "COMPACTION", "NARRATION", "WEB_SEARCH", "TRAIN")
TOOL_ROLES = ("CHAT", "TASK_SOLVE")

# What identifies each role's call site in the request it sends: the opening
# of its system prompt or of its single user turn.
TRAINER_OPENINGS = {
    "build_memory_message_prompt": "create a personalized prompt for their AI assistant",
    "build_task_prompt": "create a personalized prompt for identifying actionable items",
    "build_emailer_prompt": "create a personalized email writing assistant",
}


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """The root suite's storage cleanup does not apply: each capture boots its own profile."""
    yield


@lru_cache(maxsize=None)
def harness(role: str):
    path = FIXTURES / role / "capture.py"
    spec = importlib.util.spec_from_file_location(f"measurement_capture_{role.lower()}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=None)
def document(role: str) -> Dict[str, Any]:
    return cc.load_document(FIXTURES / role)


@lru_cache(maxsize=None)
def captured(role: str):
    calls: Dict[str, int] = {}
    requests = harness(role).build_requests(document(role)["cases"], calls=calls)
    return requests, calls


def by_id(role: str) -> Dict[str, Dict[str, Any]]:
    return {item["case_id"]: item["request"] for item in captured(role)[0]}


def tool_names(request: Dict[str, Any]) -> List[str]:
    return [tool["name"] for tool in request.get("tools") or []]


def label_tools(case: Dict[str, Any]) -> List[str]:
    label = case["label"]
    named = [spec["name"] for spec in (label.get("first_call") or {}).get("any_of", [])]
    named += list(label.get("never_call") or [])
    named += list((case["input"].get("tool_results") or {}).keys())
    named += [step["name"] for step in case["input"].get("replay") or []]
    return named


# ─── The case files ───────────────────────────────────────────────────


@pytest.mark.parametrize("role", ROLES)
def test_case_files_follow_the_shared_schema(role):
    doc = document(role)
    assert doc["schema"] == 1 and doc["role"] == role
    assert isinstance(doc["builder"], str) and doc["builder"].startswith("zylch.")
    prefix = role.lower()
    ids = [case["id"] for case in doc["cases"]]
    assert ids == [f"{prefix}-{n:02d}" for n in range(1, len(ids) + 1)]
    assert {case["lang"] for case in doc["cases"]} == {"it", "en"}
    for case in doc["cases"]:
        assert set(case) == {"id", "lang", "input", "label", "critical", "why"}, case["id"]
        assert isinstance(case["critical"], bool), case["id"]
        assert case["why"].strip(), case["id"]
    assert (FIXTURES / role / "README.md").is_file()


# ─── One request, from the role's call site ───────────────────────────


@pytest.mark.parametrize("role", ROLES)
def test_every_case_captures_exactly_one_request_of_its_role(role):
    requests, calls = captured(role)
    cases = document(role)["cases"]
    assert [item["case_id"] for item in requests] == [case["id"] for case in cases]
    assert calls == {case["id"]: 1 for case in cases}
    for item, case in zip(requests, cases):
        request = item["request"]
        json.dumps(request, allow_nan=False)
        # Only what the call site passed: no parameter left at its default.
        assert None not in request.values(), case["id"]
        assert request["messages"] and isinstance(request["max_tokens"], int), case["id"]
        assert request.get("model", cc.PLACEHOLDER_MODEL) == cc.PLACEHOLDER_MODEL, case["id"]
        _assert_call_site(role, case, request)


def _system_text(request: Dict[str, Any]) -> str:
    system = request.get("system") or ""
    if isinstance(system, list):
        return "".join(block.get("text", "") for block in system)
    return system


def _first_user_text(request: Dict[str, Any]) -> str:
    content = request["messages"][0]["content"]
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if block.get("type") == "text")
    return content


def _assert_call_site(role: str, case: Dict[str, Any], request: Dict[str, Any]) -> None:
    given = case["input"]
    if role == "CHAT":
        from zylch.assistant.prompts import SYSTEM_PROMPT_BASE

        assert _system_text(request).startswith(SYSTEM_PROMPT_BASE)
        assert {"search_local_memory", "get_tasks", "send_draft", "web_search"} <= set(
            tool_names(request)
        )
        sent = json.dumps(request["messages"], ensure_ascii=False)
        # The turn's clock is the capture's, and every channel is set up.
        assert cc.CAPTURE_NOW.strftime("%B %d, %Y") in sent, case["id"]
        for channel in ("- Email: ready", "- WhatsApp: ready", "- SMS: ready"):
            assert channel in sent, case["id"]
    elif role == "TASK_SOLVE":
        from zylch.services.solve_constants import SOLVE_TOOLS

        assert tool_names(request) == [tool["name"] for tool in SOLVE_TOOLS]
        assert "WORKFLOW (mandatory order)" in _system_text(request)
        context = _first_user_text(request)
        assert context.startswith("Solve this task.")
        # What the harness seeded is what the RPC read.
        if given.get("email"):
            assert f"Subject: {given['email']['subject']}" in context, case["id"]
        for blob in given.get("memory") or []:
            assert blob in context, case["id"]
        for rule in given.get("rules") or []:
            assert rule in _system_text(request), case["id"]
        assert f"- Name: {given['profile']['USER_FULL_NAME']}" in _system_text(request)
    else:
        assert not request.get("tools"), case["id"]
    if role == "COMPACTION":
        assert _system_text(request).startswith("You are a conversation summarizer.")
        assert _first_user_text(request).startswith("CHAT HISTORY:")
    elif role == "NARRATION":
        opening = "Riassumi" if given["builder"].endswith("summarize") else "You predict"
        assert _system_text(request).startswith(opening), case["id"]
    elif role == "WEB_SEARCH":
        assert _first_user_text(request) == f"Search the web and answer: {given['query']}"
    elif role == "TRAIN":
        meta_prompt = _first_user_text(request)
        opening = TRAINER_OPENINGS[given["builder"].rsplit(".", 1)[1]]
        assert opening in meta_prompt, case["id"]
        # The seeded mailbox, chats and blobs are what the trainer read.
        assert any(email["subject"] in meta_prompt for email in given["emails"]), case["id"]
        if given.get("whatsapp"):
            assert given["whatsapp"][0]["text"] in meta_prompt, case["id"]
        if given.get("memory"):
            assert "--- Blob for " in meta_prompt, case["id"]


@pytest.mark.parametrize("role", TOOL_ROLES)
def test_the_capture_is_what_was_sent_not_what_the_loop_did_after(role):
    # The solve loop appends the model's answer to the very list it passed; a
    # capture holding that list would end on the scripted closing text. The
    # request as sent ends on the user's turn or on a tool result.
    for item in captured(role)[0]:
        assert item["request"]["messages"][-1]["role"] == "user", item["case_id"]


@pytest.mark.parametrize("role", TOOL_ROLES)
def test_replayed_rounds_end_the_captured_transcript(role):
    requests = by_id(role)
    replayed = [case for case in document(role)["cases"] if case["input"].get("replay")]
    assert replayed, f"{role} needs a case with two tool rounds"
    for case in replayed:
        messages = requests[case["id"]]["messages"]
        steps = case["input"]["replay"]
        tail = messages[-2 * len(steps) :]
        for i, step in enumerate(steps):
            call, result = tail[2 * i], tail[2 * i + 1]
            uses = [b for b in call["content"] if b.get("type") == "tool_use"]
            assert [(u["name"], u["input"]) for u in uses] == [(step["name"], step["input"])]
            results = [b for b in result["content"] if b.get("type") == "tool_result"]
            assert [r["tool_use_id"] for r in results] == [uses[0]["id"]], case["id"]
            spec = case["input"]["tool_results"][step["name"]]
            scripted = cc.scripted_result(spec, step["input"])
            if role == "CHAT":
                # The agent sends a tool's result as its JSON-formatted ToolResult.
                sent = json.loads(results[0]["content"])
                assert sent["status"] == scripted["status"], case["id"]
                assert sent["message"] == scripted["message"], case["id"]
            else:
                # A solve tool answers with the text the script picked for its arguments.
                assert isinstance(results[0]["content"], str), case["id"]
                assert results[0]["content"] == scripted, case["id"]


@pytest.mark.parametrize("role", TOOL_ROLES)
def test_labels_name_tools_and_arguments_the_request_carries(role):
    requests = by_id(role)
    for case in document(role)["cases"]:
        schemas = {tool["name"]: tool["input_schema"] for tool in requests[case["id"]]["tools"]}
        for name in label_tools(case):
            assert name in schemas, f"{case['id']}: {name} is not a tool of this request"
        for spec in (case["label"].get("first_call") or {}).get("any_of", []):
            properties = schemas[spec["name"]].get("properties", {})
            for arg, matcher in (spec.get("args") or {}).items():
                assert arg in properties, f"{case['id']}: {spec['name']} has no argument {arg}"
                assert set(matcher) <= {"contains", "equals", "digits_contain"}, case["id"]
        for step in case["input"].get("replay") or []:
            required = schemas[step["name"]].get("required", [])
            assert set(required) <= set(step["input"]), case["id"]


# ─── Reproducible captures ────────────────────────────────────────────


@pytest.mark.parametrize("role", ROLES)
def test_a_case_captures_the_same_request_twice(role):
    again = harness(role).build_requests(document(role)["cases"])
    assert again == captured(role)[0]


def test_the_shell_environment_never_reaches_a_capture(monkeypatch):
    # The persona is the case's and nothing else: settings exported where the
    # capture runs must not change the prompt a measurement replays.
    monkeypatch.setenv("USER_LANGUAGE", "en")
    monkeypatch.setenv("USER_SECRET_INSTRUCTIONS", "measurement-leak-check")
    case = document("TASK_SOLVE")["cases"][0]
    request = harness("TASK_SOLVE").build_requests([case])[0]["request"]
    assert "measurement-leak-check" not in _system_text(request)
    assert "Match the language of the original email" in _system_text(request)


# ─── A turn continued past the capture ────────────────────────────────


def test_a_continued_chat_turn_runs_the_scripted_tool_after_approval():
    case = next(c for c in document("CHAT")["cases"] if c["id"] == "chat-03")
    call = {"phone_number": "+39 02 0000 0187", "message": "Ciao Laura, confermo domani alle 15."}
    client = cc.CapturingClient(
        answer="Inviato.",
        script=[cc.tool_use_response("send_whatsapp_message", call, "toolu_test_1")],
    )
    outcome = harness("CHAT").run_case(case, client)
    assert outcome["answer"] == "Inviato."
    assert outcome["calls"] == [{"name": "send_whatsapp_message", "input": call}]
    result = client.requests[-1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and "sent to Laura Bassi" in result["content"]


def test_a_continued_solve_runs_the_scripted_tool_after_approval():
    case = next(c for c in document("TASK_SOLVE")["cases"] if c["id"] == "task_solve-01")
    call = {"to": "paolo@rinaldiimpianti.example", "subject": "Ritiro", "body": "Giovedì alle 10."}
    client = cc.CapturingClient(
        answer="Confermato a Paolo.",
        script=[cc.tool_use_response("send_email", call, "toolu_test_2")],
    )
    outcome = harness("TASK_SOLVE").run_case(case, client)
    assert outcome["result"]["ok"] is True
    assert outcome["answer"] == "Confermato a Paolo."
    assert outcome["calls"] == [{"name": "send_email", "input": call}]
    result = client.requests[-1]["messages"][-1]["content"][0]
    assert result == {
        "type": "tool_result",
        "tool_use_id": "toolu_test_2",
        "content": case["input"]["tool_results"]["send_email"],
    }


# ─── What the cases cannot measure ────────────────────────────────────


def test_the_chat_web_search_server_tool_is_refused_by_admission():
    from zylch.llm.budget_pricing import PRICES, BudgetError, request_bound

    request = harness("WEB_SEARCH").capture_chat_tool_request("EORI number application")
    assert [tool.get("type") for tool in request["tools"]] == ["web_search_20250305"]
    priced = {**request, "model": next(iter(PRICES))}
    with pytest.raises(BudgetError, match=re.escape("server-tool costs require an explicit bound")):
        request_bound(priced, "direct")
