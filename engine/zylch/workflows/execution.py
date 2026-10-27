import time
from functools import wraps
from typing import Any

from zylch.assistant.core import ZylchAIAgent
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.exceptions import LLMPromptTooLargeError
from zylch.workflows.identity import Identity, check_same
from zylch.workflows.errors import WorkflowError
from .admission import Origin, assert_execution
from .lifecycle import assert_version


class InputRequired(Exception):
    def __init__(self, question: str) -> None:
        self.question = question
        super().__init__("workflow needs user input")


class WorkflowAgent(ZylchAIAgent):
    DIRECT_RESPONSE_TOOLS = {"workflow_finish_report"}

    def __init__(
        self, identity: Identity, procedure: str, tools: list[Any], workflow_id: str, version: str
    ) -> None:
        super().__init__(tools=tools, max_tokens=8192)
        self.identity = identity
        self.procedure = procedure
        self.workflow_id, self.version = workflow_id, version
        self.expires_at = time.time() + 1800
        self.origin = Origin.RPC
        self._workflow_step = 0
        self.prepared_legal = False
        self._final_only = False
        self.failure_progress = {"phase": "guard", "kind": "dispatch_refused", "step": 0}
        original_dispatch = self.client.create_message_sync

        @wraps(original_dispatch)
        def guarded_dispatch(*args: Any, **kwargs: Any) -> Any:
            self.check_dispatch()
            if self._final_only and self.client.transport == "direct":
                from .legal_headroom import FINAL_TOOL_CHOICE

                kwargs["tool_choice"] = dict(FINAL_TOOL_CHOICE)
            elif self.prepared_legal and self.client.transport == "direct":
                from .legal_headroom import RESEARCH_MAX_TOKENS

                kwargs["max_tokens"] = RESEARCH_MAX_TOKENS
            return original_dispatch(*args, **kwargs)

        self.client.create_message_sync = guarded_dispatch

    def check_dispatch(self) -> None:
        assert_version(self.workflow_id, self.version)
        assert_execution(self.origin)
        if self.origin == Origin.INTERNAL_INTERACTIVE:
            from zylch.rpc.workflow_interactive import check_dispatch

            check_dispatch()
        check_same(self.identity)
        if self.expires_at <= time.time():
            raise WorkflowError("run_expired")

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        schemas = super()._get_tool_schemas()
        if self._workflow_step == 9 or self._final_only:
            return [schema for schema in schemas if schema["name"] == "workflow_finish_report"]
        return schemas

    async def _create_message_within_budget(
        self, *, system_blocks: list[dict[str, Any]], volatile_suffix: str, turn_id: str, step: int
    ) -> Any:
        self._workflow_step = min(max(step, 0), 10)
        if step == 9:
            self._final_only = True
        self.failure_progress = {
            "phase": "guard",
            "kind": "dispatch_refused",
            "step": self._workflow_step,
        }
        self.check_dispatch()
        if step >= 10:
            self.failure_progress.update(phase="limit", kind="round_limit")
            raise WorkflowError("operation_failed")
        blocks = [{"type": "text", "text": self.procedure, "cache_control": {"type": "ephemeral"}}]
        if step >= 8:
            blocks.append(
                {
                    "type": "text",
                    "text": (
                        "Finalize now using retained evidence. Include useful conditional proposals, "
                        "explicit missing facts and omissions; never invent support. "
                        "The final response must call workflow_finish_report exactly once. "
                        "Only one further research response is available before the final response."
                        if step == 8
                        else "This is the final response. Call workflow_finish_report exactly once using "
                        "retained evidence, conditional proposals and explicit unresolved facts or "
                        "omissions. Do not invent support or request another tool."
                    ),
                }
            )
        if self.prepared_legal:
            from .legal_headroom import FINAL_GUIDANCE, RESEARCH_GUIDANCE, plan

            try:
                planning = plan(self, blocks)
            except BudgetError:
                self.failure_progress.update(phase="admission", kind="admission_refused")
                raise
            if planning is not None:
                self.failure_progress.update(planning)
                self._final_only = self._final_only or (
                    planning["research_bound_micro_usd"] + planning["finish_bound_micro_usd"]
                    > planning["available_micro_usd"]
                )
            blocks.append(
                {"type": "text", "text": FINAL_GUIDANCE if self._final_only else RESEARCH_GUIDANCE}
            )
        self.failure_progress.update(phase="model", kind="dispatch_failed")
        try:
            response = await super()._create_message_within_budget(
                system_blocks=blocks,
                volatile_suffix="",
                turn_id=turn_id,
                step=step,
            )
        except BudgetError:
            self.failure_progress.update(phase="admission", kind="admission_refused")
            raise
        except LLMPromptTooLargeError:
            self.failure_progress.update(phase="admission", kind="prompt_limit")
            raise
        self.failure_progress.update(phase="completion", kind="incomplete_response")
        _validate_completion(response)
        actions = [block for block in response.content if block.type == "tool_use"]
        if self.prepared_legal and len(actions) > 2:
            self.failure_progress.update(kind="research_batch_limit")
            raise WorkflowError("operation_failed")
        if step == 9 or self._final_only:
            if len(actions) != 1 or actions[0].name != "workflow_finish_report":
                self.failure_progress.update(
                    kind="final_action_required",
                    action_count=min(len(actions), 100),
                    finish_action_count=min(
                        sum(block.name == "workflow_finish_report" for block in actions), 100
                    ),
                    known_other_action_count=min(
                        sum(
                            block.name != "workflow_finish_report" and block.name in self.tool_map
                            for block in actions
                        ),
                        100,
                    ),
                    unknown_action_count=min(
                        sum(block.name not in self.tool_map for block in actions), 100
                    ),
                )
                raise WorkflowError("operation_failed")
        return response

    async def _call_tool(self, name: str, input_data: dict[str, Any]) -> Any:
        from zylch.qonto import history
        from zylch.tools.base import ToolResult, ToolStatus

        self.failure_progress.update(phase="tool", kind="tool_failed")
        self.check_dispatch()
        history.check_before_disclosure()
        if name not in self.tool_map:
            return ToolResult(ToolStatus.ERROR, None, error="The workflow tool is unavailable.")
        try:
            result = await self.tool_map[name].execute(**input_data)
            self.check_dispatch()
            history.check_before_disclosure()
            return result
        except InputRequired:
            raise
        except history.HistoryAuthorizationError:
            raise
        except WorkflowError as error:
            if self._workflow_step == 9 or self._final_only:
                self.failure_progress.update(kind="report_rejected")
                raise
            return ToolResult(ToolStatus.ERROR, None, error=str(error))
        except Exception:
            if self._workflow_step == 9 or self._final_only:
                self.failure_progress.update(kind="report_rejected")
                raise WorkflowError("operation_failed") from None
            return ToolResult(ToolStatus.ERROR, None, error="The private workflow tool failed.")


def _validate_completion(response: Any) -> None:
    raw = getattr(response, "_raw", None)
    blocks = getattr(raw, "content", None)
    if (
        response.stop_reason != "tool_use"
        or getattr(raw, "stop_reason", None) not in {"tool_use", "end_turn"}
        or getattr(raw, "refusal", None)
        or not isinstance(blocks, list)
        or not blocks
    ):
        raise WorkflowError("operation_failed")
    has_tool = False
    for block in blocks:
        if getattr(block, "refusal", None):
            raise WorkflowError("operation_failed")
        kind = getattr(block, "type", None)
        if kind == "text":
            if not isinstance(getattr(block, "text", None), str):
                raise WorkflowError("operation_failed")
        elif kind == "tool_use":
            if not all(
                isinstance(getattr(block, field, None), str) and getattr(block, field).strip()
                for field in ("id", "name")
            ) or not isinstance(getattr(block, "input", None), dict):
                raise WorkflowError("operation_failed")
            has_tool = True
        else:
            raise WorkflowError("operation_failed")
    if not has_tool:
        raise WorkflowError("operation_failed")
