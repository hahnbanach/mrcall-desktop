"""Separate exact public definitions from dynamic retained-evidence candidates."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path

from zylch.qonto.public_tool_schemas import PUBLIC_TOOL_SCHEMA_FINGERPRINTS


def _public_tool(schema, *, workflows=True):
    if workflows:
        from zylch.workflows.public_definitions import public_tool

        if public_tool(schema):
            return True
    if not isinstance(schema, dict) or not isinstance(schema.get("name"), str):
        return False
    allowed = PUBLIC_TOOL_SCHEMA_FINGERPRINTS.get(schema["name"], ())
    if not allowed:
        return False
    try:
        canonical = json.dumps(
            schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (ValueError, TypeError):
        return False
    return hashlib.sha256(canonical.encode()).hexdigest() in allowed


def _system_text(text):
    from zylch.assistant.prompts import SYSTEM_PROMPT_BASE

    if isinstance(text, str) and text.startswith(SYSTEM_PROMPT_BASE):
        return text[len(SYSTEM_PROMPT_BASE):]
    return text


def evidence_scan_request(request):
    """Return a scanner-only copy; all dynamic fields keep their original shape."""
    return _evidence_scan_request(request)[0]


def _evidence_scan_request(request):
    from zylch.workflows.public_definitions import project

    scanned = copy.deepcopy(request)
    system = scanned.get("system")
    original_text = system if isinstance(system, str) else None
    if isinstance(system, list) and system and isinstance(system[0], dict):
        first = system[0]
        if first.get("type") == "text":
            original_text = first.get("text")
    workflow_recheck = project(scanned, request)
    tools = scanned.get("tools")
    if isinstance(tools, list):
        scanned["tools"] = [schema for schema in tools if not _public_tool(schema, workflows=False)]
    remainder = _system_text(original_text)
    if remainder != original_text:
        if isinstance(system, str):
            scanned["system"] = remainder
        else:
            system[0]["text"] = remainder
    return scanned, workflow_recheck


POLICY_DIRECTORY = Path("/etc/mrcalld/finance-receipts")


def _instruction_source():
    from zylch.qonto.identity import current_authority, require_same
    from zylch.services import operator_instructions as instructions, project_store

    authority = current_authority(create_host=False)
    paths = [instructions.mail_path(instructions.own_mailbox()), instructions.PROCEDURES]
    docs = []
    with project_store.connection() as (conn, space):
        for path in paths:
            row = project_store.current(conn, instructions.PROJECT, path)
            if row is not None:
                raw = bytes(row["content"])
                if len(raw) > project_store.MAX_BYTES:
                    raise ValueError
                text = raw.decode("utf-8")
                sha = hashlib.sha256(raw).hexdigest()
                if sha != row["sha256"] or type(row["revision"]) is not int:
                    raise ValueError
                docs.append((path, row["revision"], sha, text))
    require_same(authority)
    return authority, space, tuple(docs)


def _policy(source):
    from zylch.services.task_assignment_trust import protected_read

    if os.name != "posix" or sys.platform == "win32":
        return None
    authority, space, docs = source
    path = POLICY_DIRECTORY / (authority.uid + ".json")
    if path == authority.profile_dir or authority.profile_dir in path.parents:
        raise ValueError
    raw = protected_read(path, missing_ok=True)
    if raw is None:
        return None

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    policy = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(policy, dict)
            or set(policy) != {"schema", "status", "profile_uid", "company_space_id", "documents"}
            or type(policy["schema"]) is not int or policy["schema"] != 1
            or policy["status"] != "APPROVED" or policy["profile_uid"] != authority.uid
            or policy["company_space_id"] != space
            or not isinstance(policy["documents"], list)
            or len(policy["documents"]) != len(docs) or not docs):
        raise ValueError
    for entry, (path, revision, sha, text) in zip(policy["documents"], docs):
        if (not isinstance(entry, dict)
                or set(entry) != {"path", "revision", "sha256", "occurrences"}
                or entry["path"] != path or type(entry["revision"]) is not int
                or entry["revision"] != revision or entry["sha256"] != sha
                or not isinstance(entry["occurrences"], list)
                or len(entry["occurrences"]) > 128):
            raise ValueError
        seen = set()
        for match in entry["occurrences"]:
            if (not isinstance(match, dict) or set(match) != {"start", "end", "digest"}
                    or type(match["start"]) is not int or type(match["end"]) is not int
                    or not 0 <= match["start"] < match["end"] <= len(text)
                    or not isinstance(match["digest"], str)):
                raise ValueError
            core = text[match["start"]:match["end"]]
            key = hashlib.sha256(("text:" + core.strip()).encode()).hexdigest()
            item = (match["start"], match["end"], match["digest"])
            if core != core.strip() or key != match["digest"] or item in seen:
                raise ValueError
            seen.add(item)
    return policy


def _qualified_matches(scanned, source, policy):
    from zylch.services.operator_instructions import assemble, FRAMING, SEPARATOR

    system = scanned.get("system")
    if not isinstance(system, list) or not system or not isinstance(system[0], dict):
        return set()
    first = system[0]
    text = first.get("text")
    if (first.get("type") != "text" or not isinstance(text, str)
            or not text.startswith("\n\n**USER CONTEXT:**\n")):
        return set()
    docs = source[2]
    block = assemble([doc[3] for doc in docs])
    if not block or text.count(block) != 1 or text.count(FRAMING) != 1:
        return set()
    start = text.index(block) + len(FRAMING)
    qualified = set()
    for entry, doc in zip(policy["documents"], docs):
        for match in entry["occurrences"]:
            qualified.add((("system", 0, "text"), match["digest"],
                           start + match["start"], start + match["end"]))
        if doc[3]:
            start += len(doc[3]) + len(SEPARATOR)
    return qualified


def reject_request_evidence(request):
    """Allow owner content reuse; otherwise apply the retained-evidence policy."""
    from zylch.qonto.history_receipts import retained_matches
    from zylch.qonto.history_errors import HistoryAuthorizationError
    from zylch.qonto.logging import private_scope
    from zylch.qonto.owner_content import content_recheck

    owner_recheck = content_recheck()
    if owner_recheck is not None:
        owner_recheck()
        return owner_recheck

    try:
        scanned, workflow_recheck = _evidence_scan_request(request)
    except Exception:
        raise HistoryAuthorizationError("history_invalid") from None
    source = None
    qualified = set()
    with private_scope():
        try:
            source = _instruction_source()
            policy = _policy(source)
            if policy is not None:
                qualified = _qualified_matches(scanned, source, policy)
        except Exception:
            qualified = set()
        used = False
        for match in retained_matches(scanned):
            if (match.path, match.digest, match.start, match.end) not in qualified:
                raise HistoryAuthorizationError("history_invalid")
            used = True

    def recheck():
        if workflow_recheck is not None:
            workflow_recheck()
        if used:
            try:
                if _instruction_source() != source or _policy(source) != policy:
                    raise ValueError
            except Exception:
                raise HistoryAuthorizationError("history_invalid") from None

    recheck()
    return recheck
