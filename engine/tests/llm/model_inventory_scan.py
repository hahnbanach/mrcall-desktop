"""Scanners shared by the milestone 10a model-name boundary and role-inventory tests.

Two questions, asked of the source tree rather than of a running engine:

- where does a model *name* occur (``model_names``): a line-based regular
  expression, so a name in a docstring, a dict, an f-string or a JSON file is
  found as well as one in an assignment; a line whose first non-blank
  character is ``#`` is a comment and is skipped, a trailing comment on a code
  line is not;
- where is an LLM client *built*, and with which model (``client_sites``,
  ``routed_sites``): an AST walk, so comments and docstrings that mention
  ``make_llm_client()`` are never counted, and a probe — a client built only
  to test ``is None`` — is told apart from a caller that keeps the client.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

# A model id as the engine spells one: Anthropic's direct ids, OpenRouter
# catalogue ids under the vendors the engine has used or the resolver may
# pick, OpenAI ids, and any dated snapshot id. Case-sensitive: ids are lower
# case, prose such as "GPT-Live" or "Google/Microsoft" is not an id. The
# look-behind keeps URL paths such as ``/oauth2/google/callback`` out.
MODEL_NAME = re.compile(
    r"(?<![\w/.-])(?:"
    r"claude-[a-z0-9][a-z0-9.\-]*"
    r"|(?:anthropic|z-ai|moonshotai|google|qwen|x-ai|openai)/[a-z0-9][a-z0-9.\-:]*"
    r"|gpt-[a-z0-9][a-z0-9.\-]*"
    r"|[a-z][a-z0-9.]*(?:-[a-z0-9.]+)*-20[2-3]\d{5}"
    r")"
)

CLIENT_FACTORIES = frozenset({"make_llm_client", "try_make_llm_client"})


def text_files(root: Path) -> list[Path]:
    """Every readable text file under ``root``, compiled bytecode excluded, in a stable order."""
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        try:
            path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        files.append(path)
    return files


def model_names(path: Path) -> list[tuple[int, str]]:
    """``(line, literal)`` for every model name on a non-comment line of ``path``."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        found.extend((number, match.group(0)) for match in MODEL_NAME.finditer(line))
    return found


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _called_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _is_probe(node: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    """The client is only tested for availability and then dropped.

    ``f() is None`` / ``f() is not None``, ``not f()``, ``bool(f())`` and a bare
    ``if f():`` / ``while f():`` test all discard the client they build.
    """
    parent = parents.get(node)
    if isinstance(parent, ast.Compare) and parent.left is node:
        return all(isinstance(op, (ast.Is, ast.IsNot)) for op in parent.ops) and all(
            isinstance(c, ast.Constant) and c.value is None for c in parent.comparators
        )
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
        return True
    if isinstance(parent, ast.Call) and _called_name(parent) == "bool":
        return True
    return isinstance(parent, (ast.If, ast.While, ast.IfExp)) and parent.test is node


def client_sites(path: Path) -> list[dict]:
    """Every call of the client factories in ``path``, classified.

    ``kind`` is ``probe`` (availability test, client discarded),
    ``caller_with_model`` (a model passed, by keyword or position; ``model`` is
    the argument's source text) or ``caller`` (no model: the factory's base
    model decides).
    """
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    parents = _parents(tree)
    sites: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _called_name(node) not in CLIENT_FACTORIES:
            continue
        model = next((k.value for k in node.keywords if k.arg == "model"), None)
        if model is None and node.args:
            model = node.args[0]
        if _is_probe(node, parents):
            kind = "probe"
        elif model is not None:
            kind = "caller_with_model"
        else:
            kind = "caller"
        site = {"line": node.lineno, "call": _called_name(node), "kind": kind}
        if model is not None:
            site["model"] = ast.get_source_segment(source, model)
        sites.append(site)
    return sorted(sites, key=lambda s: s["line"])


def routed_sites(path: Path) -> list[tuple[int, str]]:
    """``(line, env key)`` for every ``routed_model("MODEL_…")`` call; a non-literal key reads ``<dynamic>``."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called_name(node) == "routed_model":
            arg = node.args[0] if node.args else None
            key = (
                arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
            )
            found.append((node.lineno, key or "<dynamic>"))
    return sorted(found)


def counted(rows: list[dict], *fields: str) -> Counter:
    """A Counter of ``rows`` keyed by the named fields."""
    return Counter(tuple(row[f] for f in fields) for row in rows)
