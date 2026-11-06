"""Stable, permission-filtered entry points to registered operator business tools."""
from __future__ import annotations

import json
from typing import Annotated

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field
from cs.operator_read import ReadError

_ROUTES = frozenset({'operator_capabilities', 'operator_read', 'operator_action'})
_MAX_BYTES = 262144


def install_routes(server, verifier, port):
    async def admitted():
        access = get_access_token()
        if access is None:
            raise ReadError('grant_required')
        current = await verifier.verify_token(access.token)
        if current is None:
            raise ReadError('grant_refused')
        return access.token, verifier.grant(current.claims)

    async def recheck(token, grant, write=False):
        current = await verifier.verify_token(token)
        if current is None or verifier.grant(current.claims) != grant:
            raise ReadError('operation_outcome_unavailable: inspect the saved result before retrying' if write else 'grant_changed_before_result')

    async def available(grant):
        identity = await port.identity(grant)
        names = set(identity['capabilities']) - _ROUTES
        return {tool.name: tool for tool in await server.list_tools() if tool.name in names}

    def bounded(value):
        if len(json.dumps(value, ensure_ascii=True).encode()) > _MAX_BYTES:
            raise ReadError('operator_result_exceeds_budget: use the selected tool pagination')
        return value

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    async def operator_capabilities(limit: Annotated[int, Field(ge=1, le=10)] = 10,
                                    offset: Annotated[int, Field(ge=0)] = 0) -> dict[str, object]:
        """Discover this account's currently permitted business actions and exact argument schemas. Follow next_offset. Use stable operator_read/operator_action; new server features do not require a new connection."""
        token, grant = await admitted()
        tools = sorted((await available(grant)).values(), key=lambda tool: tool.name)
        selected = tools[offset:offset+limit]
        def result(items):
            end = offset + len(items)
            return {'items': [{'name': tool.name, 'description': tool.description,
                               'input_schema': tool.inputSchema,
                               'read_only': bool(tool.annotations and tool.annotations.readOnlyHint)} for tool in items],
                    'total': len(tools), 'offset': offset,
                    'next_offset': end if end < len(tools) else None}
        while selected and len(json.dumps(result(selected), ensure_ascii=True).encode()) > _MAX_BYTES:
            selected.pop()
        if offset < len(tools) and not selected:
            raise ReadError('operator_action_schema_exceeds_budget')
        await recheck(token, grant)
        return bounded(result(selected))

    async def dispatch(name, arguments, read_only):
        if not isinstance(name, str) or not name or len(name) > 100 or name in _ROUTES or not isinstance(arguments, dict):
            raise ReadError('invalid_operator_action')
        token, grant = await admitted()
        tool = (await available(grant)).get(name)
        if tool is None:
            raise ReadError('operator_action_unavailable')
        is_read = bool(tool.annotations and tool.annotations.readOnlyHint)
        if read_only and not is_read:
            raise ReadError('operator_read_refuses_changes')
        # StrictReadMCP validates the registered input schema and the original
        # handler rechecks its own native permission/effect/recovery contract.
        value = await server.call_tool(name, arguments)
        await recheck(token, grant, write=not is_read)
        if isinstance(value, CallToolResult):
            if value.isError:
                raise ReadError('operator_action_failed: inspect original action status before retrying')
            result = value.structuredContent or {'content': [block.model_dump(mode='json') for block in value.content]}
        elif isinstance(value, tuple) and len(value) == 2:
            content, structured = value
            result = structured if structured is not None else {'content': [block.model_dump(mode='json') for block in content]}
        elif isinstance(value, dict):
            result = value
        else:
            result = {'content': [block.model_dump(mode='json') for block in value]}
        return bounded({'action': name, 'result': result})

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    async def operator_read(name: str, arguments: dict[str, object]) -> dict[str, object]:
        """Run one currently permitted read action from operator_capabilities using its exact schema and pagination. Refuses writes, unknown actions and routing recursion."""
        return await dispatch(name, arguments, True)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))
    async def operator_action(name: str, arguments: dict[str, object]) -> dict[str, object]:
        """Run one currently permitted registered business action from operator_capabilities. Native permissions, revision checks, budgets and approval rules still apply. Use the selected action's stable request key and recovery instructions; never blindly retry an uncertain change."""
        return await dispatch(name, arguments, False)
