"""Inactive, trusted source-email binding into the existing ChatService path.

Normal ChatService construction installs no route. A future owner-controlled
pilot loader must supply the selected source/contact and exact artifact revision;
chat context can only match that selection, never create or widen it.
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass

from zylch.assistant.procedure import ProcedureArtifact
from zylch.assistant.procedure_policy import ProcedurePolicy
from zylch.rpc.capability_ws import BoundedReads
from zylch.services.capability_contract import CapabilityRequest
from zylch.services.order_existence import _mailbox
from zylch.services.scoped_capabilities import ScopedCapabilities

logger = logging.getLogger(__name__)
_SOURCE_FIELDS = (
    "id",
    "owner_id",
    "from_email",
    "to_email",
    "subject",
    "body_plain",
    "thread_id",
    "message_id_header",
    "references",
)


def source_revision(source: dict) -> str:
    """Pin content and addressing, not unrelated read/pin/sync timestamps."""
    data = {key: source.get(key) for key in _SOURCE_FIELDS}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class EmailSelection:
    source_id: str
    source_revision: str
    recipient: str
    contact_ref: str | None


class PilotEmailRoute:
    def __init__(
        self, artifact: ProcedureArtifact, service: ScopedCapabilities, selection: EmailSelection
    ):
        if (
            artifact.revision != service.binding.procedure_revision
            or _mailbox(selection.recipient) != selection.recipient
            or not selection.source_id
            or len(selection.source_revision) != 64
        ):
            raise ValueError("invalid pilot email binding")
        if selection.contact_ref is not None:
            grant = next(
                (g for g in service.binding.contacts if g.contact_ref == selection.contact_ref),
                None,
            )
            if grant is None or _mailbox(grant.email) != selection.recipient:
                raise ValueError("pilot email contact is not granted")
        self.artifact, self.service, self.selection = artifact, service, selection
        self._binding = service.binding
        # Owned by this route, not one executor per request. A timed-out model or
        # provider call keeps its slot until the underlying thread really exits.
        self._workers = BoundedReads()
        self._busy = False
        self._closed = False

    def close(self):
        self._closed = True
        self._workers.close()

    def _source(self, storage, owner):
        if self.service.binding != self._binding:
            raise PermissionError("pilot email binding changed")
        self.service.check_scope()
        if self._closed or owner != self.service.binding.profile_uid:
            raise PermissionError("pilot email scope denied")
        source = storage.get_email_by_supabase_id(owner, self.selection.source_id)
        if (
            not source
            or source.get("owner_id") != owner
            or _mailbox(source.get("from_email")) != self.selection.recipient
            or source_revision(source) != self.selection.source_revision
        ):
            raise PermissionError("pilot email source changed")
        return source

    async def process(self, storage, user_id, context):
        # Admission occurs before any await. Inactive/incorrect selection never
        # falls through to commands, owner tools, notification handling or sync.
        if self._busy or self._closed:
            return self._refused()
        self._busy = True
        policy = None
        try:
            if not isinstance(context, dict) or context.get("email_id") != self.selection.source_id:
                raise PermissionError("pilot email selection required")
            source = self._source(storage, user_id)
            body, subject = source.get("body_plain"), source.get("subject") or ""
            if (
                not isinstance(body, str)
                or not 0 < len(body) <= 8000
                or not isinstance(subject, str)
                or len(subject) > 500
                or "\r" in subject
                or "\n" in subject
            ):
                raise ValueError("pilot email source exceeds bounds")
            deadline = time.monotonic() + 15
            invocation = uuid.uuid4().hex
            sequence = 0

            def check_authority():
                self._source(storage, user_id)

            async def read(operation):
                nonlocal sequence
                sequence += 1
                remaining = min(3.0, deadline - time.monotonic())
                request = CapabilityRequest(
                    1,
                    self.service.binding.business_id,
                    invocation,
                    self.artifact.revision,
                    uuid.uuid4().hex,
                    sequence,
                    0,
                    self.selection.contact_ref,
                    operation,
                    time.time_ns() // 1_000_000 + int(remaining * 1000),
                )
                return await self._workers.run(
                    lambda: self.service.execute_authorized(request), remaining
                )

            policy = ProcedurePolicy(
                self.artifact,
                read,
                check_authority,
                self._workers,
                deadline,
                identified=self.selection.contact_ref is not None,
            )
            from zylch.assistant.core import ZylchAIAgent
            from zylch.tools.base import ToolStatus
            from zylch.tools.gmail_tools import CreateDraftTool

            agent = ZylchAIAgent(tools=[], max_tokens=1024, procedure_policy=policy)
            # This IS the existing engine conversation loop and guarded client.
            # User chat text/history and private owner context are deliberately
            # absent: only the selected incoming message enters this invocation.
            async with asyncio.timeout_at(deadline):
                await agent.process_message(body)
                text = policy.final_text()
                await asyncio.sleep(0)  # Deliver pending cancellation BEFORE the write.
                policy.check()
                current = self._source(storage, user_id)
                references = current.get("references") or ""
                message_id = current.get("message_id_header") or ""
                if (
                    not isinstance(references, str)
                    or len(references) > 4096
                    or not isinstance(message_id, str)
                    or len(message_id) > 998
                    or any(c in references + message_id for c in ("\r", "\n"))
                ):
                    raise ValueError("invalid pilot email threading headers")
                references = " ".join(part for part in (references, message_id) if part)
                # No asynchronous work separates the last scope/source/deadline
                # checks and CreateDraftTool's synchronous persistence section.
                result = await CreateDraftTool(storage, user_id).execute(
                    to=self.selection.recipient,
                    subject=subject,
                    body=text,
                    in_reply_to=current.get("message_id_header"),
                    references=references,
                    thread_id=current.get("thread_id"),
                )
                if result.status != ToolStatus.SUCCESS:
                    raise RuntimeError("pilot draft persistence failed")
            logger.debug(
                "[procedure email] completed revision=%s status=%s",
                self.artifact.revision,
                policy.status,
            )
            return {
                "response": text,
                "tool_calls": [],
                "metadata": {
                    "procedure_revision": self.artifact.revision,
                    "procedure_execution": invocation,
                    "procedure_status": policy.status,
                    "draft_id": result.data["draft_id"],
                },
            }
        except Exception as error:  # noqa: BLE001 -- never expose SDK/storage details to the reply
            # Cancellation is BaseException and deliberately propagates. Ordinary
            # SDK failures have many types; none may escape into a caller-facing
            # reply or reopen the unrestricted owner route.
            logger.debug(
                "[procedure email] refused type=%s without owner-route fallback",
                type(error).__name__,
            )
            return self._refused()
        finally:
            if policy is not None:
                policy.close()
            self._busy = False

    def _refused(self):
        return {
            "response": self.artifact.message("unavailable"),
            "tool_calls": [],
            "metadata": {
                "error": "pilot_procedure_unavailable",
                "procedure_revision": self.artifact.revision,
            },
        }
