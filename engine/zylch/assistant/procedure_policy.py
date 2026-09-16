"""Restricted policy for the existing conversational loop, not another runner.

The loop still owns model messages and iteration. This policy owns only the
two permitted tool operations, invocation-local evidence and controlled output.
It never loads owner notes/history or accepts model-authored response bodies.
"""

import contextvars
import hashlib
import json
import logging
import time

from .procedure import ProcedureArtifact

logger = logging.getLogger(__name__)


class ProcedurePolicy:
    def __init__(
        self,
        artifact: ProcedureArtifact,
        read,
        check_authority,
        workers,
        deadline: float,
        *,
        identified: bool,
        now=time.monotonic,
    ):
        self.artifact = artifact
        self._read = read
        self._check_authority = check_authority
        self._workers = workers
        self.deadline = deadline
        self._now = now
        self.identified = identified
        self._model_calls = 0
        self._tool_calls = 0
        self._reads = 0
        self._ids = set()
        self._order = None
        self._memory = None
        self.completed = None
        self.status = None
        self.closed = False

    @property
    def prompt(self):
        return self.artifact.prompt

    def schemas(self):
        grant = frozenset(self.artifact.operations) if self.identified else frozenset()
        return self.artifact.schemas(grant)

    def check(self):
        if self.closed or self._now() >= self.deadline:
            raise TimeoutError("procedure invocation expired")
        self._check_authority()

    async def create_message(self, client, **kwargs):
        self.check()
        if self._model_calls >= 4:
            raise TimeoutError("procedure model budget exhausted")
        self._model_calls += 1
        # Keep the SAME guarded client: create_message_sync owns provider choice,
        # model-specific reasoning budgets, reservations and settlement. Do not
        # override its K3 promotion: reasoning shares the final-output budget.
        # Only scheduling changes: abandoned SDK work
        # retains a bounded slot rather than accumulating on the default executor.
        context = contextvars.copy_context()
        logger.debug(
            "[procedure] model dispatch=%s revision=%s", self._model_calls, self.artifact.revision
        )
        response = await self._workers.run(
            lambda: context.run(lambda: client.create_message_sync(**kwargs)),
            self.deadline - self._now(),
        )
        self.check()
        return response

    async def execute_tools(self, content):
        results = []
        calls = [block for block in content if getattr(block, "type", None) == "tool_use"]
        if len(calls) + self._tool_calls > 6:
            raise TimeoutError("procedure tool budget exhausted")
        for block in calls:
            self.check()
            self._tool_calls += 1
            # Never echo attacker arguments, exception text or provider payloads.
            # A repeated ID is not a retry: it cannot perform another read/write.
            result = {"status": "refused"}
            call_id = getattr(block, "id", None)
            if isinstance(call_id, str) and 0 < len(call_id) <= 128 and call_id not in self._ids:
                self._ids.add(call_id)
                arguments = getattr(block, "input", None)
                if isinstance(arguments, dict):
                    if block.name == "capability_read":
                        result = await self._execute_read(arguments)
                    elif block.name == "procedure_finish":
                        self._finish(arguments)
                        if self.completed is not None:
                            # Stop this batch immediately. A second tool in the
                            # same model response cannot run after completion.
                            return results, self.completed
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call_id or "invalid",
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        return results, None

    async def _execute_read(self, arguments):
        op = arguments.get("operation")
        if (
            set(arguments) != {"operation"}
            or not isinstance(op, str)
            or op not in self.artifact.operations
            or not self.identified
        ):
            return {"status": "refused"}
        # A newer attempt supersedes evidence even if the provider subsequently
        # fails; an old success must never mask a failed refresh.
        if op == "order.exists":
            self._order = None
        else:
            self._memory = None
        if self._reads >= 4:
            return {"status": "unavailable"}
        self._reads += 1
        try:
            result = await self._read(op)
        except Exception as error:  # noqa: BLE001 -- all provider failures are a finite outcome
            logger.debug("[procedure] read failed type=%s", type(error).__name__)
            result = {"status": "unavailable"}
        self.check()
        if not isinstance(result, dict):
            return {"status": "unavailable"}
        status = result.get("status")
        if op == "order.exists":
            if set(result) != {"status"} or status not in (
                "order_exists",
                "no_order",
                "need_identification",
                "unavailable",
            ):
                return {"status": "unavailable"}
            self._order = status
            return {"status": status}
        rows = result.get("sentences")
        if (
            set(result) != {"status", "sentences"}
            or status != "memory_found"
            or not isinstance(rows, list)
            or len(rows) > 8
        ):
            return {"status": "unavailable"}
        approved = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"text", "revision"}:
                return {"status": "unavailable"}
            text = row["text"]
            if (
                not isinstance(text, str)
                or not 0 < len(text) <= 1000
                or hashlib.sha256(text.encode()).hexdigest() != row["revision"]
            ):
                return {"status": "unavailable"}
            approved.append(text)
        if sum(map(len, approved)) > 3500:
            return {"status": "unavailable"}
        self._memory = tuple(approved)
        return result

    def _finish(self, arguments):
        self.check()
        if (
            set(arguments) != {"status", "include_memory"}
            or type(arguments["include_memory"]) is not bool
        ):
            return
        status, include = arguments["status"], arguments["include_memory"]
        safe = status in ("need_identification", "unavailable")
        order = (
            self.artifact.completion == "order"
            and status in ("order_exists", "no_order")
            and status == self._order
        )
        memory = (
            self.artifact.completion == "memory"
            and status == "memory_found"
            and self._memory is not None
            and include
        )
        if not (safe or order or memory) or (include and self._memory is None):
            return
        text = self.artifact.message(status)
        if include:
            text += "\n\n" + "\n".join(self._memory)
        if len(text) > 4000:
            return
        self.status, self.completed = status, text

    def final_text(self):
        """Tool-skipping free text is replaced, never silently saved as a reply."""
        self.check()
        if self.completed is None:
            self._finish({"status": "unavailable", "include_memory": False})
        return self.completed

    def close(self):
        self.closed = True
        self._order = self._memory = None
