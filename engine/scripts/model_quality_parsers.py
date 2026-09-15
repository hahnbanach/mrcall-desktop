"""Run the repository's response validation offline, without creating a worker.

The task parser is the unchanged post-inference AST of TaskWorker._analyze_event.
An explicit signature/shape/hash pin fails closed when that contract changes.
Review the diff and update the pin deliberately after a production parser change.
"""

import ast
import hashlib
import inspect
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parents[1]
TASK_SOURCE = ENGINE_ROOT / "zylch/workers/task_creation.py"
TASK_VALIDATION_AST_SHA256 = "e8d99991a8241f319787fc97f1a845c0bcd905e20448a62378fe78df6ab89c06"
EXPECTED_ARGUMENTS = [
    "self",
    "event_type",
    "event_data",
    "blob_context",
    "existing_task_context",
    "calendar_context",
]


class ParserSourceDrift(ValueError):
    """The reviewed offline extraction no longer matches the production method."""


def extract_task_validation(source: str) -> tuple[list[ast.stmt], str]:
    """Identify and verify the exact response-only portion of the real method."""
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TaskWorker"]
    if len(classes) != 1:
        raise ParserSourceDrift("Expected exactly one TaskWorker class")
    methods = [
        n
        for n in classes[0].body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_analyze_event"
    ]
    if len(methods) != 1:
        raise ParserSourceDrift("Expected async TaskWorker._analyze_event")
    method = methods[0]
    if (
        [a.arg for a in method.args.args] != EXPECTED_ARGUMENTS
        or method.args.posonlyargs
        or method.args.kwonlyargs
        or method.args.vararg
        or method.args.kwarg
        or [ast.literal_eval(d) for d in method.args.defaults] != ["", ""]
    ):
        raise ParserSourceDrift("Task method signature changed")
    candidates = [
        n
        for n in method.body
        if isinstance(n, ast.Try) and n.body and isinstance(n.body[0], ast.With)
    ]
    if len(candidates) != 1:
        raise ParserSourceDrift("Expected exactly one inference/response try block")
    dispatch = candidates[0].body[0]
    if (
        len(dispatch.items) != 1
        or len(dispatch.body) != 1
        or not isinstance(dispatch.items[0].context_expr, ast.Call)
        or ast.unparse(dispatch.items[0].context_expr) != "call_site('task.detect')"
    ):
        raise ParserSourceDrift("Inference boundary changed")
    assignment = dispatch.body[0]
    if (
        not isinstance(assignment, ast.Assign)
        or len(assignment.targets) != 1
        or ast.unparse(assignment.targets[0]) != "response"
        or not isinstance(assignment.value, ast.Await)
        or not isinstance(assignment.value.value, ast.Call)
        or ast.unparse(assignment.value.value.func) != "self.client.create_message"
    ):
        raise ParserSourceDrift("Response assignment changed")
    body = candidates[0].body[1:]
    if [type(n).__name__ for n in body] != ["If", "For", "Expr", "Return"]:
        raise ParserSourceDrift("Response validation shape changed")
    if any(
        isinstance(n, (ast.Await, ast.AsyncWith)) or isinstance(n, ast.Name) and n.id == "self"
        for stmt in body
        for n in ast.walk(stmt)
    ):
        raise ParserSourceDrift("Response validation now depends on a worker or async operation")
    fingerprint = hashlib.sha256(
        ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False).encode()
    ).hexdigest()
    if fingerprint != TASK_VALIDATION_AST_SHA256:
        raise ParserSourceDrift("Response validation changed; review and update the AST hash")
    return body, fingerprint


@lru_cache(maxsize=1)
def _components() -> tuple[Any, Any, Any, Any, dict[str, str]]:
    # Resolve from this script, never from the caller's cwd or a private checkout.
    sys.path.insert(0, str(ENGINE_ROOT))
    from zylch.llm.client import LLMResponse
    from zylch.memory.response_validation import complete_memory_text
    from zylch.workers import task_creation
    from zylch.workers.memory import MemoryWorker

    imported_sources = [
        (Path(inspect.getfile(LLMResponse)), ENGINE_ROOT / "zylch/llm/client.py"),
        (Path(task_creation.__file__), TASK_SOURCE),
        (Path(inspect.getfile(MemoryWorker)), ENGINE_ROOT / "zylch/workers/memory.py"),
        (
            Path(inspect.getfile(complete_memory_text)),
            ENGINE_ROOT / "zylch/memory/response_validation.py",
        ),
    ]
    if any(actual.resolve() != expected.resolve() for actual, expected in imported_sources):
        raise ParserSourceDrift("Imported parser component belongs to a different checkout")
    text = TASK_SOURCE.read_text()
    body, fingerprint = extract_task_validation(text)
    function = ast.FunctionDef(
        name="_parse_task",
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg=n) for n in ["response", "thread_history_section", "event_type"]],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[ast.Constant(value=""), ast.Constant(value="email")],
        ),
        body=body,
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = dict(vars(task_creation))
    # Only the signature/shape/hash-verified repository AST is executed, never input data.
    exec(compile(module, str(TASK_SOURCE) + "::<offline response validation>", "exec"), namespace)  # noqa: S102
    provenance = {
        "task_source": str(TASK_SOURCE.relative_to(ENGINE_ROOT)),
        "task_source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "task_validation_ast_sha256": fingerprint,
    }
    for name, path in {
        "memory_worker": ENGINE_ROOT / "zylch/workers/memory.py",
        "memory_completion": ENGINE_ROOT / "zylch/memory/response_validation.py",
    }.items():
        provenance[name + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return LLMResponse, complete_memory_text, MemoryWorker, namespace["_parse_task"], provenance


def parser_provenance() -> dict[str, str]:
    """Return exact code hashes used by the offline parser."""
    return {
        **_components()[4],
        "default_completion_mode": "frozen_raw_completion_v1",
        "response_adapter_sha256": hashlib.sha256(
            (ENGINE_ROOT / "zylch/llm/client.py").read_bytes()
        ).hexdigest(),
    }


def parse(
    stage: str,
    raw: Any,
    thread_history: str = "",
    *,
    completion_mode: str = "frozen_raw_completion_v1",
) -> dict[str, Any]:
    """Validate a response with the production code; never infer, persist or dispatch."""
    if completion_mode not in ("frozen_raw_completion_v1", "counterfactual_tool_completion_v1"):
        raise ValueError("Unknown completion mode")
    response_type, complete_memory_text, worker_type, task_parser, _ = _components()
    try:
        if isinstance(raw, dict):
            raw = SimpleNamespace(
                **{**raw, "content": [SimpleNamespace(**block) for block in raw.get("content", [])]}
            )
        # Re-wrap even an existing adapter: historical mode must never inherit
        # a stop reason normalized by a caller. Raw transport data is immutable.
        if isinstance(raw, response_type):
            raw = raw._raw
        response = response_type(
            raw, normalize_tool_completion=completion_mode == "counterfactual_tool_completion_v1"
        )
        if stage == "memory.extract":
            text = complete_memory_text(response)
            parsed = [] if text.upper() == "SKIP" else worker_type._parse_entities(None, text)
        elif stage == "task.detect":
            parsed = task_parser(response, thread_history)
            if parsed is None:
                return {"accepted": False, "error": "Actual task parser returned None"}
        else:
            raise ValueError("Unknown evaluation stage")
        return {"accepted": True, "parsed": parsed}
    except Exception as exc:  # noqa: BLE001 -- provider payload failures are graded, not raised
        # A malformed provider response is a grading result. Source drift above
        # deliberately propagates instead of being disguised as a model failure.
        return {"accepted": False, "error": type(exc).__name__ + ": " + str(exc)}
