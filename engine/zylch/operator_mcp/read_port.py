from __future__ import annotations

import os
import time
from email import policy
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from cs.operator_read import ReadError, ReadGrant, customer_address


@dataclass(frozen=True)
class ProfileBinding:
    profile_uid: str
    email: str
    company_ref: str
    mailbox_ids: frozenset[str]


_SUMMARY_FIELDS = frozenset(
    {
        "thread_id",
        "subject",
        "from_email",
        "from_name",
        "to_email",
        "date",
        "snippet",
        "unread",
        "has_attachments",
        "pinned",
        "message_count",
        "mailbox_ids",
        "last_email_id",
    }
)
_EMAIL_FIELDS = frozenset(
    {
        "id",
        "from_email",
        "from_name",
        "to_email",
        "cc_email",
        "date",
        "subject",
        "body_plain",
        "body_html",
        "is_auto_reply",
        "is_user_sent",
        "has_attachments",
        "attachment_filenames",
        "mailbox_id",
        "mailbox_address",
        "original_message_id",
        "pec_markers",
    }
)
_DRAFT_FIELDS = frozenset(
    {
        "id",
        "to_addresses",
        "cc_addresses",
        "bcc_addresses",
        "subject",
        "body",
        "body_format",
        "in_reply_to",
        "references",
        "thread_id",
        "status",
        "created_at",
        "updated_at",
        "reply_binding",
    }
)
_HANDLERS = frozenset({"emails.search", "emails.list_by_thread", "drafts.list"})


class NativeReadPort:
    def __init__(
        self,
        binding_snapshot: Callable[[], ProfileBinding],
        handlers: Mapping[str, Callable] | None = None,
    ):
        if handlers is not None and set(handlers) != _HANDLERS:
            raise ReadError("Invalid native read handlers")
        self._snapshot = binding_snapshot
        self._handlers = dict(handlers) if handlers is not None else None

    def _check(self, grant: ReadGrant, kind: str | None = None) -> ProfileBinding:
        try:
            binding = self._snapshot()
        except Exception:
            raise ReadError("Profile binding unavailable") from None
        if (
            not isinstance(binding, ProfileBinding)
            or not binding.profile_uid
            or not binding.email
            or not binding.company_ref
            or not isinstance(binding.mailbox_ids, frozenset)
            or grant.subject != grant.profile_uid
            or grant.profile_uid != binding.profile_uid
            or grant.company_ref != binding.company_ref
            or grant.expires_at <= time.time()
            or "operator.read" not in grant.scopes
            or not grant.client_id
            or not grant.resource
            or not grant.grant_id
            or not isinstance(grant.mailbox_ids, frozenset)
            or (kind is not None and len(grant.mailbox_ids) != 1)
            or not grant.mailbox_ids <= binding.mailbox_ids
            or any(not isinstance(value, str) or not value for value in grant.mailbox_ids)
        ):
            raise ReadError("Profile read permission denied")
        if kind is not None and (
            "mail" not in grant.source_classes or "email.read" not in grant.scopes
        ):
            raise ReadError("Mail read permission denied")
        if kind == "drafts" and (
            "drafts" not in grant.source_classes or "draft.read" not in grant.scopes
        ):
            raise ReadError("Draft read permission denied")
        return binding

    async def _call(self, grant: ReadGrant, name: str, params: dict, kind: str) -> Any:
        before = self._check(grant, kind)
        try:
            if self._handlers is None:
                from zylch.cli.utils import get_owner_id

                if (
                    get_owner_id() != before.email
                    or os.environ.get("OWNER_ID") != before.profile_uid
                ):
                    raise ReadError("Native profile owner mismatch")
                from zylch.rpc.methods import emails_search, emails_list_by_thread
                from zylch.rpc.draft_queries import drafts_list

                handler = {
                    "emails.search": emails_search,
                    "emails.list_by_thread": emails_list_by_thread,
                    "drafts.list": drafts_list,
                }[name]
            else:
                handler = self._handlers[name]
            result = await handler(params, lambda method, values: None)
        except Exception:
            raise ReadError("Native read unavailable") from None
        if self._check(grant, kind) != before:
            raise ReadError("Profile binding changed")
        return result

    @staticmethod
    def _limit(limit: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ReadError("Invalid read limit")

    @staticmethod
    def _mail(row: Any, grant: ReadGrant) -> bool:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("mailbox_id"), str)
            or not row["mailbox_id"]
        ):
            raise ReadError("Mail provenance unavailable")
        if row.get("source_class", "mail") != "mail" or "pec_markers" not in row:
            raise ReadError("Mail provenance unavailable")
        if row.get("pec_markers") or row.get("original_message_id"):
            raise ReadError("Excluded mail source")
        return row["mailbox_id"] in grant.mailbox_ids

    async def identity(self, grant: ReadGrant) -> dict:
        binding = self._check(grant)
        capabilities = ["operator_identity"]
        if "mail" in grant.source_classes and "email.read" in grant.scopes:
            capabilities.extend(["search_email", "read_email", "customer_context"])
            if "drafts" in grant.source_classes and "draft.read" in grant.scopes:
                capabilities.append("list_drafts")
        return {
            "subject": grant.subject,
            "profile_uid": binding.profile_uid,
            "email": binding.email,
            "company_ref": binding.company_ref,
            "client_id": grant.client_id,
            "grant_id": grant.grant_id,
            "capabilities": capabilities,
        }

    async def search(self, grant: ReadGrant, query: str, limit: int) -> dict:
        self._check(grant, "mail")
        self._limit(limit)
        if not isinstance(query, str) or len(query) > 1000:
            raise ReadError("Invalid mail query")
        result = await self._call(
            grant,
            "emails.search",
            {
                "query": query,
                "folder": "all",
                "limit": limit,
                "offset": 0,
                "mailbox_id": next(iter(grant.mailbox_ids)),
            },
            "mail",
        )
        rows = result.get("threads") if isinstance(result, dict) else None
        if not isinstance(rows, list) or len(rows) > limit:
            raise ReadError("Mail search unavailable")
        out = []
        for row in rows:
            ids = row.get("mailbox_ids") if isinstance(row, dict) else None
            if (
                not isinstance(ids, list)
                or not ids
                or any(not isinstance(value, str) or not value for value in ids)
                or set(ids) != set(grant.mailbox_ids)
                or row.get("source_class", "mail") != "mail"
                or row.get("pec_markers")
                or row.get("original_message_id")
            ):
                raise ReadError("Mail search provenance unavailable")
            root, source_id = row.get("thread_id"), row.get("last_email_id")
            if (
                not isinstance(root, str)
                or not root
                or not isinstance(source_id, str)
                or not source_id
            ):
                raise ReadError("Mail search provenance unavailable")
            emails = (await self.thread(grant, root))["emails"]
            matches = [email for email in emails if email.get("id") == source_id]
            if len(matches) != 1 or not self._mail(matches[0], grant):
                raise ReadError("Mail search provenance unavailable")
            out.append({key: value for key, value in row.items() if key in _SUMMARY_FIELDS})
        return {"threads": out[:limit]}

    async def thread(self, grant: ReadGrant, thread_key: str) -> dict:
        if not isinstance(thread_key, str) or not thread_key or len(thread_key) > 512:
            raise ReadError("Invalid thread key")
        result = await self._call(grant, "emails.list_by_thread", {"thread_id": thread_key}, "mail")
        rows = result.get("emails") if isinstance(result, dict) else None
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ReadError("Thread unavailable")
        out = []
        for row in rows:
            if self._mail(row, grant):
                out.append({key: value for key, value in row.items() if key in _EMAIL_FIELDS})
        return {"emails": out}

    def context_binding(self, grant: ReadGrant) -> ProfileBinding:
        return self._check(grant, "mail")

    @staticmethod
    def _participants(row: dict) -> set[str]:
        participants = set()
        for field in ("from_email", "to_email", "cc_email"):
            value = row.get(field)
            if value is None or value == "":
                continue
            if not isinstance(value, str) or len(value) > 16384 or "\r" in value or "\n" in value:
                raise ReadError("Invalid participant headers")
            try:
                header = policy.default.header_factory("to", value)
                if header.defects:
                    raise ValueError()
                for address in header.addresses:
                    participants.add(customer_address(address.addr_spec))
            except Exception:
                raise ReadError("Invalid participant headers") from None
        return participants

    async def customer_thread(
        self,
        grant: ReadGrant,
        thread_key: str,
        customer_email: str,
        source_email_id: str | None = None,
    ) -> dict:
        before = self._check(grant, "mail")
        customer = customer_address(customer_email)
        if customer == customer_address(before.email):
            raise ReadError("Customer must differ from profile owner")
        rows = (await self.thread(grant, thread_key))["emails"]
        if source_email_id is not None:
            selected = [row for row in rows if row.get("id") == source_email_id]
            if len(selected) != 1 or customer not in self._participants(selected[0]):
                raise ReadError("Selected source participant mismatch")
        out = []
        for row in rows:
            if not isinstance(row.get("id"), str) or not row["id"]:
                raise ReadError("Mail identity unavailable")
            if customer in self._participants(row):
                out.append(row)
        if self._check(grant, "mail") != before:
            raise ReadError("Profile binding changed")
        return {"emails": out}

    async def drafts(self, grant: ReadGrant, limit: int) -> list[dict]:
        self._limit(limit)
        result = await self._call(grant, "drafts.list", {"status": "draft"}, "drafts")
        if not isinstance(result, list):
            raise ReadError("Draft read unavailable")
        out = []
        unavailable = False
        for row in result:
            if (
                not isinstance(row, dict)
                or row.get("owner_id") != self._check(grant, "drafts").email
            ):
                continue
            binding = row.get("reply_binding")
            source = binding.get("source") if isinstance(binding, dict) else None
            root = binding.get("root") if isinstance(binding, dict) else None
            if (
                isinstance(source, dict)
                and isinstance(source.get("mailbox_id"), str)
                and source["mailbox_id"]
                and source["mailbox_id"] not in grant.mailbox_ids
            ):
                continue
            if (
                not isinstance(source, dict)
                or not isinstance(root, str)
                or not root
                or not isinstance(source.get("id"), str)
                or not source["id"]
                or not isinstance(source.get("mailbox_id"), str)
                or source["mailbox_id"] not in grant.mailbox_ids
                or row.get("thread_id") != root
            ):
                unavailable = True
                continue
            try:
                emails = (await self.thread(grant, root))["emails"]
            except ReadError:
                self._check(grant, "drafts")
                unavailable = True
                continue
            matches = [
                email
                for email in emails
                if email.get("id") == source["id"]
                and email.get("mailbox_id") == source["mailbox_id"]
            ]
            if len(matches) != 1:
                unavailable = True
                continue
            projected = {key: value for key, value in row.items() if key in _DRAFT_FIELDS}
            target = binding.get("target")
            if target is not None and not isinstance(target, str):
                unavailable = True
                continue
            projected["reply_binding"] = {
                "root": root,
                "target": target,
                "source": {"id": source["id"], "mailbox_id": source["mailbox_id"]},
            }
            out.append(projected)
            if len(out) == limit:
                break
        self._check(grant, "drafts")
        if unavailable and not out:
            raise ReadError("Draft provenance unavailable")
        return out
