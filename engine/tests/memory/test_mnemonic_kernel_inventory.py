"""Milestone 0 freeze for cs-kernel callers and headless permission effects."""

from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import re

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
KERNEL_ROOT = ENGINE_ROOT.parent.parent / "cs-kernel"
FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "mnemonic" / "legacy_writer_inventory.json"


def _manifest() -> dict:
    return json.loads(FIXTURE.read_text())


def _kernel_root() -> Path:
    if not KERNEL_ROOT.is_dir():
        pytest.skip("cs-kernel sibling checkout is required for the cross-repository audit")
    return KERNEL_ROOT


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert len(matches) == 1, name
    return matches[0]


def _allow_descriptor(node: ast.AST | None) -> str:
    if node is None:
        return "missing"
    if isinstance(node, ast.Name):
        return f"variable:{node.id}"
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "set"
        and not node.args
    ):
        return "empty_set"
    if isinstance(node, ast.Set):
        values = sorted(str(item.value) for item in node.elts if isinstance(item, ast.Constant))
        return "set:" + ",".join(values)
    return ast.dump(node, include_attributes=False)


def _exact_bash_effect_count(source: str, command: str) -> int:
    pattern = re.compile(r'"Bash\([^"\n]*' + re.escape(command) + r':\*\)"')
    return len(pattern.findall(source))


def test_kernel_rpc_chat_callers_and_transport_match_the_frozen_audit():
    manifest = _manifest()
    kernel_root = _kernel_root()
    actual_callers: Counter = Counter()

    for path in sorted((kernel_root / "cs").rglob("*.py")):
        rel = path.relative_to(kernel_root).as_posix()
        tree = ast.parse(path.read_text(), filename=str(path))
        stack: list[str] = []
        rpc_modules = {"rpc"}
        rpc_chat_functions: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if (node.module or "").endswith("rpc"):
                    rpc_chat_functions.update(
                        item.asname or item.name for item in node.names if item.name == "chat"
                    )
                rpc_modules.update(
                    item.asname or item.name for item in node.names if item.name == "rpc"
                )
            elif isinstance(node, ast.Import):
                rpc_modules.update(
                    item.asname or item.name.rsplit(".", 1)[-1]
                    for item in node.names
                    if item.name.endswith(".rpc")
                )

        class ChatVisitor(ast.NodeVisitor):
            def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_FunctionDef = _visit_function
            visit_AsyncFunctionDef = _visit_function

            def visit_Call(self, node: ast.Call) -> None:
                is_rpc_attribute = (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in rpc_modules
                    and node.func.attr == "chat"
                )
                is_imported_chat = (
                    isinstance(node.func, ast.Name) and node.func.id in rpc_chat_functions
                )
                if is_rpc_attribute or is_imported_chat:
                    keywords = {item.arg: item.value for item in node.keywords}
                    predicate = keywords.get("approval_predicate")
                    predicate_name = predicate.id if isinstance(predicate, ast.Name) else None
                    actual_callers[
                        (
                            rel,
                            ".".join(stack),
                            _allow_descriptor(keywords.get("allow_tools")),
                            predicate_name,
                        )
                    ] += 1
                self.generic_visit(node)

        ChatVisitor().visit(tree)

    expected_callers = Counter(
        {
            (row["path"], row["symbol"], row["allow_tools"], row["approval_predicate"]): row[
                "count"
            ]
            for row in manifest["kernel_chat_callers"]
        }
    )
    assert actual_callers == expected_callers
    assert all(1 <= row["milestone"] <= 8 for row in manifest["kernel_chat_callers"])

    transport = manifest["kernel_chat_transport"]
    assert 1 <= transport["milestone"] <= 8
    path = kernel_root / transport["path"]
    tree = ast.parse(path.read_text(), filename=str(path))
    chat = _function(tree, transport["symbol"])
    allow_values = [
        ast.unparse(node.value)
        for node in ast.walk(chat)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "allow" for target in node.targets)
    ]
    assert allow_values == [transport["allow_normalization"]]
    assert (
        sum(
            isinstance(node, ast.Constant) and node.value == transport["pending_notification"]
            for node in ast.walk(chat)
        )
        == 1
    )

    actual_rpc_calls: Counter = Counter()
    for node in ast.walk(chat):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "call"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            continue
        payload_keys: tuple[str, ...] = ()
        if len(node.args) > 1 and isinstance(node.args[1], ast.Dict):
            payload_keys = tuple(
                sorted(
                    key.value
                    for key in node.args[1].keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
            )
        actual_rpc_calls[(node.args[0].value, payload_keys)] += 1
    expected_rpc_calls = Counter(
        {
            (row["method"], tuple(row["payload_keys"])): row["count"]
            for row in transport["rpc_calls"]
        }
    )
    assert actual_rpc_calls == expected_rpc_calls
    assert all(1 <= row["milestone"] <= 8 for row in transport["rpc_calls"])


def test_scheduled_rpc_and_permission_templates_match_the_frozen_audit():
    manifest = _manifest()
    kernel_root = _kernel_root()
    cli_path = kernel_root / "cs/cli.py"
    cli_tree = ast.parse(cli_path.read_text(), filename=str(cli_path))
    catchup = _function(cli_tree, "cmd_catchup")
    actual_scheduled: Counter = Counter()
    for node in ast.walk(catchup):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "rpc"
            and node.func.attr == "call_sync"
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Constant)
        ):
            actual_scheduled[("cs/cli.py", "cmd_catchup", node.args[1].value)] += 1
    expected_scheduled = Counter(
        {
            (row["path"], row["symbol"], row["method"]): row["count"]
            for row in manifest["kernel_scheduled_rpc_callers"]
        }
    )
    assert actual_scheduled == expected_scheduled
    assert all(1 <= row["milestone"] <= 8 for row in manifest["kernel_scheduled_rpc_callers"])

    for row in manifest["kernel_template_effects"]:
        source = (kernel_root / row["path"]).read_text()
        assert row["section"] in {"allow", "deny"}
        if row["path"].endswith("settings.json.j2"):
            template = json.loads(source)
            section_source = json.dumps(template["permissions"][row["section"]])
        else:
            assert row["section"] == "deny"
            section_source = source.split("--disallowed-tools", 1)[1]
        assert _exact_bash_effect_count(section_source, row["command"]) == row["count"], row
        assert 1 <= row["milestone"] <= 8

    cron = (kernel_root / "cs/templates/project/bin/cs_operator_cron.sh.j2").read_text()
    for row in manifest["kernel_raw_rpc_effects"]:
        engine_path = ENGINE_ROOT / row["engine_path"]
        engine_tree = ast.parse(engine_path.read_text(), filename=str(engine_path))
        assert (
            sum(
                isinstance(node, ast.Dict)
                and any(
                    isinstance(key, ast.Constant) and key.value == row["method"]
                    for key in node.keys
                )
                for node in ast.walk(engine_tree)
            )
            == 1
        )
        command = f"cs rpc {row['method']}"
        assert _exact_bash_effect_count(cron, command) == row["cron_explicit_deny_count"]
        assert 1 <= row["milestone"] <= 8


def test_chat_slash_effects_are_routed_and_owned_by_a_later_milestone():
    manifest = _manifest()
    handlers_path = ENGINE_ROOT / "zylch/services/command_handlers.py"
    handlers_tree = ast.parse(handlers_path.read_text(), filename=str(handlers_path))
    routes: dict[str, str | None] = {}
    for node in ast.walk(handlers_tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "COMMAND_HANDLERS"
                and isinstance(node.value, ast.Dict)
            ):
                for key, value in zip(node.value.keys, node.value.values):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        routes[key.value] = value.id if isinstance(value, ast.Name) else None
            elif (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "COMMAND_HANDLERS"
                and isinstance(target.slice, ast.Constant)
                and isinstance(node.value, ast.Name)
            ):
                routes[target.slice.value] = node.value.id

    for row in manifest["kernel_chat_command_effects"]:
        path = ENGINE_ROOT / row["engine_path"]
        tree = ast.parse(path.read_text(), filename=str(path))
        handler = _function(tree, row["symbol"])
        constants = {
            node.value
            for node in ast.walk(handler)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert routes[row["route"]] == row["symbol"]
        for selector in row["selectors"]:
            assert selector in constants, row
        assert row["commands"]
        assert 1 <= row["milestone"] <= 8
