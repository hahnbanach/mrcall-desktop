from __future__ import annotations

import os
import base64
import hashlib
import re
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
    instructions_enabled: bool = False


_SUMMARY_FIELDS = frozenset({"thread_id", "subject", "from_email", "from_name", "to_email", "date", "snippet", "unread", "has_attachments", "pinned", "message_count", "mailbox_ids", "last_email_id"})
_EMAIL_FIELDS = frozenset({"id", "message_id_header", "from_email", "from_name", "to_email", "cc_email", "date", "subject", "body_plain", "body_html", "is_auto_reply", "is_user_sent", "has_attachments", "attachment_filenames", "mailbox_id", "mailbox_address", "original_message_id", "pec_markers"})
_DRAFT_FIELDS = frozenset({"id", "to_addresses", "cc_addresses", "bcc_addresses", "subject", "body", "body_format", "in_reply_to", "references", "thread_id", "status", "created_at", "updated_at", "reply_binding"})
_HANDLERS = frozenset({"emails.search", "emails.list_by_thread", "drafts.list"})


class NativeReadPort:
    def __init__(self, binding_snapshot: Callable[[], ProfileBinding], handlers: Mapping[str, Callable] | None = None, *, instruction_reader: Callable[[str], list[dict]] | None = None):
        if handlers is not None and set(handlers) != _HANDLERS:
            raise ReadError("Invalid native read handlers")
        if instruction_reader is not None and not callable(instruction_reader):
            raise ReadError("Invalid instruction reader")
        self._instruction_reader = instruction_reader
        self._snapshot = binding_snapshot
        self._handlers = dict(handlers) if handlers is not None else None

    def _check(self, grant: ReadGrant, kind: str | None = None) -> ProfileBinding:
        try:
            binding = self._snapshot()
        except Exception:
            raise ReadError("Profile binding unavailable") from None
        if (not isinstance(binding, ProfileBinding) or not binding.profile_uid or not binding.email
                or not binding.company_ref or not isinstance(binding.mailbox_ids, frozenset)
                or grant.subject != grant.profile_uid or grant.profile_uid != binding.profile_uid
                or grant.company_ref != binding.company_ref or grant.expires_at <= time.time()
                or "operator.read" not in grant.scopes or not grant.client_id or not grant.resource
                or not grant.grant_id or not isinstance(grant.mailbox_ids, frozenset)
                or (kind is not None and len(grant.mailbox_ids) != 1)
                or not grant.mailbox_ids <= binding.mailbox_ids
                or any(not isinstance(value, str) or not value for value in grant.mailbox_ids)):
            raise ReadError("Profile read permission denied")
        if kind is not None and ("mail" not in grant.source_classes or "email.read" not in grant.scopes):
            raise ReadError("Mail read permission denied")
        if kind == "drafts" and ("drafts" not in grant.source_classes or "draft.read" not in grant.scopes):
            raise ReadError("Draft read permission denied")
        return binding

    async def _call(self, grant: ReadGrant, name: str, params: dict, kind: str) -> Any:
        before = self._check(grant, kind)
        try:
            if self._handlers is None:
                from zylch.cli.utils import get_owner_id
                if get_owner_id() != before.email or os.environ.get("OWNER_ID") != before.profile_uid:
                    raise ReadError("Native profile owner mismatch")
                from zylch.rpc.methods import emails_search, emails_list_by_thread
                from zylch.rpc.draft_queries import drafts_list
                handler = {"emails.search": emails_search, "emails.list_by_thread": emails_list_by_thread, "drafts.list": drafts_list}[name]
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
        if not isinstance(row, dict) or not isinstance(row.get("mailbox_id"), str) or not row["mailbox_id"]:
            raise ReadError("Mail provenance unavailable")
        if row.get("source_class", "mail") != "mail" or "pec_markers" not in row:
            raise ReadError("Mail provenance unavailable")
        if row.get("pec_markers") or row.get("original_message_id"):
            raise ReadError("Excluded mail source")
        return row["mailbox_id"] in grant.mailbox_ids

    async def instructions(self, grant: ReadGrant) -> dict:
        before = self._check(grant, "mail")
        if (before.instructions_enabled is not True or "instructions.read" not in grant.scopes
                or "instructions" not in grant.source_classes):
            raise ReadError("Instruction read permission denied")
        from zylch.services.operator_instructions import PROCEDURES, PROJECT, mail_path
        try:
            paths = frozenset({PROCEDURES, mail_path(before.email)})
        except Exception:
            raise ReadError("Instruction binding unavailable") from None
        if not isinstance(grant.instruction_paths, frozenset) or grant.instruction_paths != paths:
            raise ReadError("Instruction path permission denied")
        try:
            if self._instruction_reader is None:
                from zylch.cli.utils import get_owner_id
                if get_owner_id() != before.email or os.environ.get("OWNER_ID") != before.profile_uid:
                    raise ReadError("Native profile owner mismatch")
                from zylch.services.operator_instructions import documents
                rows = documents(before.email)
            else:
                rows = self._instruction_reader(before.email)
        except Exception:
            raise ReadError("Native instructions unavailable") from None
        if self._check(grant, "mail") != before:
            raise ReadError("Profile binding changed")
        if not isinstance(rows, list) or len(rows) > 2:
            raise ReadError("Invalid instruction documents")
        out, seen = [], set()
        for row in rows:
            if (not isinstance(row, dict) or row.get("space_id") != grant.company_ref
                    or row.get("project") != PROJECT or not isinstance(row.get("path"), str)
                    or row["path"] not in paths or row["path"] in seen
                    or type(row.get("revision")) is not int or row["revision"] < 1
                    or type(row.get("size")) is not int or not 0 <= row["size"] <= 65536
                    or not isinstance(row.get("content_base64"), str) or len(row["content_base64"]) > 87384
                    or not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                raise ReadError("Invalid instruction document")
            try:
                raw = base64.b64decode(row["content_base64"], validate=True)
                if len(raw) != row["size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                    raise ValueError()
                content = raw.decode("utf-8", errors="strict")
            except (ValueError, UnicodeError):
                raise ReadError("Instruction integrity unavailable") from None
            document = {"path": row["path"], "revision": row["revision"], "sha256": row["sha256"], "text": content}
            author = row.get("author_uid")
            if author is not None:
                if not isinstance(author, str) or len(author) > 254 or any(ord(c) < 32 for c in author):
                    raise ReadError("Invalid publication author")
                document["publication_author"] = author
            seen.add(row["path"])
            out.append(document)
        missing = sorted(paths - seen)
        return {"status": "not_configured" if not out else "partial" if missing else "available",
                "documents": out, "missing_paths": missing}

    async def identity(self, grant: ReadGrant) -> dict:
        binding = self._check(grant)
        capabilities = ["operator_identity", "cs_bootstrap", "cs_bootstrap_hook"]
        if "mail" in grant.source_classes and "email.read" in grant.scopes:
            capabilities.extend(["search_email", "read_email", "customer_context"])
            if "drafts" in grant.source_classes and "draft.read" in grant.scopes:
                capabilities.append("list_drafts")
        if 'draft.prepare' in grant.scopes:
            capabilities.extend(['prepare_reply', 'recover_reply'])
        if 'instructions.propose' in grant.scopes:
            capabilities.extend(['propose_rule', 'rule_status'])
        if 'pricing.use' in grant.scopes:
            capabilities.extend(['pricing_context', 'pricing_document', 'pricing_calculate'])
        if 'instructions.write' in grant.scopes:
            capabilities.extend(['read_rules', 'save_rule', 'rule_history', 'restore_rule', 'rule_change_status'])
        if 'projects.read' in grant.scopes:
            capabilities.extend(['list_projects', 'list_project_files', 'read_project', 'project_history'])
        if 'projects.write' in grant.scopes:
            capabilities.extend(['create_project', 'write_project'])
        if "operator.use" in grant.scopes:
            capabilities.extend(["search_memory", "read_memory"])
        return {"subject": grant.subject, "profile_uid": binding.profile_uid, "email": binding.email, "company_ref": binding.company_ref, "client_id": grant.client_id, "grant_id": grant.grant_id, "capabilities": capabilities}

    async def search(self, grant: ReadGrant, query: str, limit: int) -> dict:
        self._check(grant, "mail")
        self._limit(limit)
        if not isinstance(query, str) or len(query) > 1000:
            raise ReadError("Invalid mail query")
        result = await self._call(grant, "emails.search", {"query": query, "folder": "all", "limit": limit, "offset": 0, "mailbox_id": next(iter(grant.mailbox_ids))}, "mail")
        rows = result.get("threads") if isinstance(result, dict) else None
        if not isinstance(rows, list) or len(rows) > limit:
            raise ReadError("Mail search unavailable")
        out = []
        for row in rows:
            ids = row.get("mailbox_ids") if isinstance(row, dict) else None
            if (not isinstance(ids, list) or not ids or any(not isinstance(value, str) or not value for value in ids)
                    or set(ids) != set(grant.mailbox_ids) or row.get("source_class", "mail") != "mail"
                    or row.get("pec_markers") or row.get("original_message_id")):
                raise ReadError("Mail search provenance unavailable")
            root, source_id = row.get("thread_id"), row.get("last_email_id")
            if not isinstance(root, str) or not root or not isinstance(source_id, str) or not source_id:
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

    async def customer_thread(self, grant: ReadGrant, thread_key: str, customer_email: str, source_email_id: str | None = None) -> dict:
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
        """Retain the strict list-only interface for older internal callers."""
        result = await self.draft_listing(grant, limit)
        if result['coverage']['unverified_count'] and not result['drafts']:
            raise ReadError("Draft provenance unavailable")
        return result['drafts']

    async def draft_listing(self, grant: ReadGrant, limit: int, thread_key: str | None = None) -> dict:
        before = self._check(grant, "drafts")
        self._limit(limit)
        threads = {}
        if thread_key is not None:
            if not isinstance(thread_key, str) or not thread_key or len(thread_key) > 512:
                raise ReadError("Invalid thread key")
            threads[thread_key] = (await self.thread(grant, thread_key))["emails"]
            if not threads[thread_key]:
                raise ReadError("Selected thread unavailable")
        result = await self._call(grant, "drafts.list", {"status": "draft"}, "drafts")
        if not isinstance(result, list):
            raise ReadError("Draft read unavailable")
        out = []
        unverified = unlinked = verified = 0
        for row in result:
            self._check(grant, "drafts")
            if not isinstance(row, dict):
                unverified += 1
                continue
            if not isinstance(row.get('owner_id'), str) or not row['owner_id']:
                unverified += 1
                continue
            if row.get("owner_id") != before.email:
                continue
            binding = row.get("reply_binding")
            source = binding.get("source") if isinstance(binding, dict) else None
            root = binding.get("root") if isinstance(binding, dict) else row.get("thread_id")
            if isinstance(source, dict) and isinstance(source.get("mailbox_id"), str) and source["mailbox_id"] and source["mailbox_id"] not in grant.mailbox_ids:
                continue
            if thread_key is not None and root and root != thread_key and row.get('thread_id') != thread_key:
                continue
            if (row.get('status') != 'draft' or not isinstance(row.get('id'), str) or not row['id']
                    or not isinstance(root, str) or not root
                    or len(root) > 512 or row.get("thread_id") != root):
                unverified += 1
                unlinked += int(not row.get('thread_id'))
                continue
            try:
                if root not in threads:
                    threads[root] = (await self.thread(grant, root))["emails"]
                emails = threads[root]
            except ReadError:
                self._check(grant, "drafts")
                unverified += 1
                continue
            if binding is None:
                # Older native drafts have no reply_binding field. Only an
                # exact, unique RFC source inside this granted thread proves it.
                header = row.get('in_reply_to')
                matches = [email for email in emails if isinstance(header, str) and header
                           and email.get('message_id_header') == header]
                if len(matches) == 1:
                    source = {'id': matches[0]['id'], 'mailbox_id': matches[0]['mailbox_id']}
                    binding = {'root': root, 'source': source}
            elif (not isinstance(binding, dict) or not isinstance(source, dict)
                    or not isinstance(source.get('id'), str) or not source['id']
                    or not isinstance(source.get('mailbox_id'), str)
                    or source.get('mailbox_id') not in grant.mailbox_ids):
                unverified += 1
                continue
            else:
                matches = [email for email in emails if email.get("id") == source["id"] and email.get("mailbox_id") == source["mailbox_id"]]
            if len(matches) != 1:
                unverified += 1
                continue
            if (not isinstance(matches[0].get('id'), str) or not matches[0]['id']
                    or row.get('in_reply_to') and row['in_reply_to'] != matches[0].get('message_id_header')):
                unverified += 1
                continue
            projected = {key: value for key, value in row.items() if key in _DRAFT_FIELDS}
            target = binding.get("target")
            if target is not None and not isinstance(target, str):
                unverified += 1
                continue
            projected["reply_binding"] = {"root": root, "target": target, "source": {"id": source["id"], "mailbox_id": source["mailbox_id"]}}
            verified += 1
            if len(out) < limit:
                out.append(projected)
        if self._check(grant, "drafts") != before:
            raise ReadError("Profile binding changed")
        return {'drafts': out, 'coverage': {
            'complete': unverified == 0 and verified <= limit,
            'scope': 'recorded_thread' if thread_key is not None else 'granted_mailbox',
            'thread_key': thread_key, 'verified_count': verified, 'returned_count': len(out),
            'limit_reached': verified > limit, 'unverified_count': unverified,
            'unlinked_count': unlinked,
            'absence_confirmed': unverified == 0 and verified == 0,
            'note': 'Partial or limited results do not prove absence. Unlinked legacy drafts remain unverified.'}}
