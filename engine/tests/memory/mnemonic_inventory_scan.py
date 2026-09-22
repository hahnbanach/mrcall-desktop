"""AST scanners shared by the Milestone 0 mnemonic inventory tests."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


def import_aliases(tree: ast.AST) -> dict[str, str]:
    """Map local imported names back to their declared symbol names."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
    return aliases


def model_reference(node: ast.AST, aliases: dict[str, str], models: set[str]) -> str | None:
    if isinstance(node, ast.Name):
        candidate = aliases.get(node.id, node.id)
        return candidate if candidate in models else None
    if isinstance(node, ast.Attribute) and node.attr in models:
        return node.attr
    return None


def symbol_calls(path: Path, tracked: set[str], models: set[str]) -> tuple[Counter, Counter]:
    tree = ast.parse(path.read_text(), filename=str(path))
    aliases = import_aliases(tree)
    calls: Counter = Counter()
    constructors: Counter = Counter()
    stack: list[str] = []
    function_modes: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            stack.append(node.name)
            function_modes.append("async" if isinstance(node, ast.AsyncFunctionDef) else "sync")
            self.generic_visit(node)
            function_modes.pop()
            stack.pop()

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

        def visit_Call(self, node: ast.Call) -> None:
            raw_name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else (node.func.id if isinstance(node.func, ast.Name) else "")
            )
            name = aliases.get(raw_name, raw_name)
            symbol = ".".join(stack) or "<module>"
            if name in tracked:
                calls[(symbol, name, function_modes[-1] if function_modes else "module")] += 1
            model = model_reference(node.func, aliases, models)
            if model:
                constructors[(symbol, f"construct:{model}")] += 1
            self.generic_visit(node)

    Visitor().visit(tree)
    return calls, constructors


def orm_query_mutations(path: Path, models: set[str]) -> Counter:
    """Find query(Model)...update/delete sinks without mistaking reads for writes."""
    tree = ast.parse(path.read_text(), filename=str(path))
    aliases = import_aliases(tree)
    mutations: Counter = Counter()
    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"delete", "update"}:
                referenced: set[str] = set()
                for child in ast.walk(node.func.value):
                    if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                        continue
                    if child.func.attr != "query":
                        continue
                    referenced.update(
                        model
                        for arg in child.args
                        if (model := model_reference(arg, aliases, models)) is not None
                    )
                for model in referenced:
                    mutations[(".".join(stack), f"orm:{node.func.attr}:{model}")] += 1
            self.generic_visit(node)

    Visitor().visit(tree)
    return mutations


def annotated_parameters(node, aliases: dict[str, str], models: set[str]) -> dict[str, str]:
    """Parameters whose annotation names a tracked model.

    A helper that receives an already-loaded row — ``def _rewrite(self, blob:
    Blob, ...)`` — writes to it exactly like one that queried it itself, and a
    scanner that only followed ``session.query(Model)`` would not see it. Since
    a converted writer naturally grows such helpers, the annotation is treated
    as the binding it is.
    """
    bound: dict[str, str] = {}
    args = node.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        annotation = arg.annotation
        if annotation is None:
            continue
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            candidate = aliases.get(annotation.value, annotation.value)
            if candidate in models:
                bound[arg.arg] = candidate
            continue
        model = model_reference(annotation, aliases, models)
        if model:
            bound[arg.arg] = model
    return bound


def orm_assignments(path: Path, models: set[str]) -> Counter:
    """Bind ORM results to local names and freeze direct persistent field writes."""
    tree = ast.parse(path.read_text(), filename=str(path))
    aliases = import_aliases(tree)
    assignments: Counter = Counter()
    stack: list[str] = []
    bindings: list[dict[str, str]] = []

    def lookup_binding(name: str) -> str | None:
        for scope in reversed(bindings):
            if name in scope:
                return scope[name]
        return None

    def referenced_models(node: ast.AST) -> set[str]:
        found: set[str] = set()
        if isinstance(node, ast.Name) and (bound := lookup_binding(node.id)):
            found.add(bound)
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                constructor = model_reference(child.func, aliases, models)
                if constructor:
                    found.add(constructor)
                name = (
                    child.func.attr
                    if isinstance(child.func, ast.Attribute)
                    else (child.func.id if isinstance(child.func, ast.Name) else "")
                )
                if name in {"get", "query", "select"}:
                    found.update(
                        model
                        for arg in child.args
                        if (model := model_reference(arg, aliases, models)) is not None
                    )
        return found

    def bind(target: ast.AST, value: ast.AST) -> None:
        if not bindings or not isinstance(target, ast.Name):
            return
        found = referenced_models(value)
        if len(found) == 1:
            bindings[-1][target.id] = next(iter(found))
        else:
            bindings[-1].pop(target.id, None)

    def record(target: ast.AST) -> None:
        if not bindings:
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                record(item)
            return
        if not isinstance(target, ast.Attribute):
            return
        models_found = referenced_models(target.value)
        if len(models_found) == 1:
            model = next(iter(models_found))
            assignments[(".".join(stack), f"assign:{model}.{target.attr}")] += 1

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            stack.append(node.name)
            bindings.append(annotated_parameters(node, aliases, models))
            self.generic_visit(node)
            bindings.pop()
            stack.pop()

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                bind(target, node.value)
                record(target)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if node.value is not None:
                bind(node.target, node.value)
                record(node.target)
            self.generic_visit(node)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            record(node.target)
            self.generic_visit(node)

        def visit_For(self, node: ast.For) -> None:
            bind(node.target, node.iter)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            if (
                bindings
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                models_found = referenced_models(node.args[0])
                if len(models_found) == 1:
                    model = next(iter(models_found))
                    assignments[(".".join(stack), f"assign:{model}.{node.args[1].value}")] += 1
            self.generic_visit(node)

    Visitor().visit(tree)
    return assignments


def orm_core_mutations(path: Path, models: set[str]) -> Counter:
    """Freeze SQLAlchemy Core insert/update/delete calls on memory models."""
    tree = ast.parse(path.read_text(), filename=str(path))
    aliases = import_aliases(tree)
    operation_aliases = {
        local: declared
        for local, declared in aliases.items()
        if declared in {"insert", "update", "delete"}
    }
    mutations: Counter = Counter()
    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

        def visit_Call(self, node: ast.Call) -> None:
            raw_name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else (node.func.id if isinstance(node.func, ast.Name) else "")
            )
            name = operation_aliases.get(raw_name, raw_name)
            model = model_reference(node.args[0], aliases, models) if node.args else None
            if name in {"insert", "update", "delete"} and model:
                mutations[(".".join(stack), f"orm-core:{name}:{model}")] += 1
            self.generic_visit(node)

    Visitor().visit(tree)
    return mutations
