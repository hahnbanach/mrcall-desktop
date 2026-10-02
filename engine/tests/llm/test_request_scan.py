"""No caller sends sampling or a forced tool choice (brief D10, AC 2): an AST scan.

The one request shape (``zylch/llm/request_shape.py``) removes sampling and
relaxes a forced ``tool_choice`` for every request at the client, so a caller
that still writes them is a caller expecting something it will not get. This
scan walks every module under ``engine/zylch/`` and ``engine/scripts/`` —
voice excluded by the brief (``zylch/services/voice/``,
``zylch/llm/openai_voice.py``) — and fails on an LLM request that passes
``temperature``, ``top_p`` or ``top_k``, or a ``tool_choice`` written as a
dict literal of type ``any`` or ``tool``.

An LLM request is a call of ``create_message`` / ``create_message_sync``, a
call of ``create`` on a ``messages`` attribute (``client.messages.create``),
or a call handed one of those as an argument
(``asyncio.to_thread(client.create_message_sync, ...)``,
``functools.partial(...)``), whose keywords are the request's.

Known limits — this guards against accidents, not deliberate evasion:
keywords splatted from a dict (``**request``), a tool choice held in a
variable, and a method reached under another name are not seen.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[2]
ROOTS = ("zylch", "scripts")
EXCLUDED = ("zylch/services/voice/", "zylch/llm/openai_voice.py")
SAMPLING = frozenset({"temperature", "top_p", "top_k"})
FORCED = frozenset({"any", "tool"})
REQUESTS = frozenset({"create_message", "create_message_sync"})


def _is_request(node: ast.AST) -> bool:
    """``x.create_message`` / ``x.create_message_sync`` / ``x.messages.create``."""
    if not isinstance(node, ast.Attribute):
        return False
    if node.attr in REQUESTS:
        return True
    return (
        node.attr == "create"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "messages"
    )


def _forced(value: ast.AST) -> bool:
    if not isinstance(value, ast.Dict):
        return False
    for key, item in zip(value.keys, value.values):
        if isinstance(key, ast.Constant) and key.value == "type":
            return isinstance(item, ast.Constant) and item.value in FORCED
    return False


def violations(source: str, rel: str) -> list[str]:
    """Every sampling keyword and forced tool choice an LLM request in ``source`` sends."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if not (_is_request(node.func) or any(_is_request(arg) for arg in node.args)):
            continue
        for keyword in node.keywords:
            if keyword.arg in SAMPLING:
                found.append(f"{rel}:{node.lineno}: {keyword.arg}=")
            elif keyword.arg == "tool_choice" and _forced(keyword.value):
                found.append(f"{rel}:{node.lineno}: forced tool_choice")
    return found


def scanned() -> list[tuple[str, Path]]:
    files = []
    for root in ROOTS:
        for path in sorted((ENGINE / root).rglob("*.py")):
            rel = path.relative_to(ENGINE).as_posix()
            if not rel.startswith(EXCLUDED):
                files.append((rel, path))
    return files


def test_no_llm_request_sends_sampling_or_a_forced_tool_choice():
    found = [v for rel, path in scanned() for v in violations(path.read_text(), rel)]
    assert not found, (
        "an LLM request sends sampling or a forced tool_choice; the one request shape "
        "(zylch/llm/request_shape.py) sends neither — name the tool in the prompt and keep "
        "tool_choice auto:\n  " + "\n  ".join(found)
    )


def test_the_scan_covers_engine_and_scripts_and_skips_voice():
    files = {rel for rel, _ in scanned()}
    assert {"zylch/utils/reply_need.py", "scripts/compact_learned_prefs.py"} <= files
    assert "zylch/llm/client.py" in files and "zylch/rpc/methods.py" in files
    assert not {rel for rel in files if rel.startswith(EXCLUDED)}
    requests = sum(
        isinstance(node, ast.Call) and _is_request(node.func)
        for _, path in scanned()
        for node in ast.walk(ast.parse(path.read_text()))
    )
    assert requests >= 30, f"the scan stopped seeing the engine's LLM requests ({requests})"


@pytest.mark.parametrize(
    "line",
    [
        "client.create_message(messages=m, temperature=0)",
        "self.client.create_message_sync(messages=m, top_p=0.9)",
        "self._client.messages.create(model=x, top_k=5)",
        "await asyncio.to_thread(client.create_message_sync, messages=m, temperature=0)",
        "functools.partial(llm.create_message, tool_choice={'type': 'any'})",
        "client.create_message(tool_choice={'type': 'tool', 'name': 'decide'})",
    ],
)
def test_the_scan_sees_each_form(line):
    assert violations(line + "\n", "probe.py") == [f"probe.py:1: {_expected(line)}"]


def _expected(line: str) -> str:
    for key in ("temperature", "top_p", "top_k"):
        if f"{key}=" in line:
            return f"{key}="
    return "forced tool_choice"


@pytest.mark.parametrize(
    "line",
    [
        "client.create_message(messages=m, tool_choice={'type': 'auto'})",
        "client.create_message(messages=m, tool_choice={'type': 'none'})",
        "client.create_message(**request)",
        "other.create(temperature=0)",
        "render(temperature=0)",
        "{'temperature': 1.0, 'tool_choice': {'type': 'tool', 'name': 'x'}}",
    ],
)
def test_the_scan_passes_the_one_shape_and_unrelated_calls(line):
    assert violations(line + "\n", "probe.py") == []
