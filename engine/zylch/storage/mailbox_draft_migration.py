from __future__ import annotations

import email
import hashlib
import json
import re
import time
from email.policy import default
from email.utils import getaddresses
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import MetaData, Table, inspect, select

from .mailbox_operations import MailboxOperations, RECEIPTS

LEGACY_TABLES = ("drafts", "draft_provider_operations", "operator_reply_operations", "campaigns", "campaign_contacts")
REQUIRED = {
    "drafts": {"id", "owner_id", "status", "in_reply_to", "sent_message_id"},
    "draft_provider_operations": {"owner_uid", "operation_id", "operation_type", "draft_id", "binding", "stage"},
    "operator_reply_operations": {"id", "result", "state"},
    "campaigns": {"id", "owner_id", "status"},
    "campaign_contacts": {"id", "owner_id", "campaign_id", "dossier", "draft_subject", "draft_body"},
}


class MigrationRefusal(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            raise MigrationRefusal("legacy_json_unreadable") from None
    if not isinstance(value, dict):
        raise MigrationRefusal("legacy_json_unreadable")
    return value


def _identifier(value):
    if not value:
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", value):
        raise MigrationRefusal("legacy_message_identity_invalid")
    return value


def _escaped_source_header(source):
    if isinstance(source, str) and source.startswith("&lt;") and source.endswith("&gt;"):
        return "<" + source[4:-4] + ">"
    return None


def _fenced(assertion):
    if not callable(assertion):
        raise MigrationRefusal("writer_fence_required")
    result = assertion()
    if not isinstance(result, dict) or result.get("writers_stopped") is not True or result.get("schedules_paused") is not True:
        raise MigrationRefusal("writers_not_fenced")


def _sent_proof(lookup, message_id, owner):
    if not message_id:
        return None, "message_identity_unavailable"
    try:
        rows = lookup(message_id)
    except Exception:
        return None, "sent_lookup_failed"
    if not isinstance(rows, list):
        return None, "sent_lookup_incomplete"
    if len(rows) != 1:
        return None, "sent_absent" if not rows else "sent_ambiguous"
    row = rows[0]
    if not isinstance(row, dict) or "SENT" not in row.get("labels", []) or not isinstance(row.get("raw"), bytes):
        return None, "sent_identity_unverified"
    message = email.message_from_bytes(row["raw"], policy=default)
    ids = message.get_all("Message-ID", [])
    senders = [address.lower() for _, address in getaddresses(message.get_all("From", []))]
    if len(ids) != 1 or str(ids[0]).strip() != message_id or senders != [owner]:
        return None, "sent_identity_unverified"
    native = row.get("message_id") or row.get("id")
    if not isinstance(native, str) or not native:
        return None, "sent_identity_unverified"
    return {"id": native, "message_id": message_id, "raw_sha256": hashlib.sha256(row["raw"]).hexdigest()}, "sent_verified"


class MailboxDraftMigration:
    def __init__(self, engine, *, owner, profile_uid):
        self.engine = engine
        self.owner = owner.strip().lower()
        self.profile_uid = profile_uid
        if "@" not in self.owner or not isinstance(profile_uid, str) or not profile_uid:
            raise MigrationRefusal("profile_binding_required")

    def _snapshot(self, conn):
        schema = inspect(conn)
        present = set(schema.get_table_names())
        data = {}
        for name in (*LEGACY_TABLES, RECEIPTS.name):
            if name not in present:
                data[name] = {"columns": None, "rows": []}
                continue
            table = Table(name, MetaData(), autoload_with=conn)
            columns = set(table.c.keys())
            if name in REQUIRED and not REQUIRED[name] <= columns:
                raise MigrationRefusal("legacy_schema_unknown:" + name)
            if name == RECEIPTS.name and set(RECEIPTS.c.keys()) != columns:
                raise MigrationRefusal("receipt_schema_unknown")
            rows = [dict(row) for row in conn.execute(select(table)).mappings().all()]
            data[name] = {"columns": sorted(columns), "rows": sorted(rows, key=_json)}
        headers = {_escaped_source_header(draft["in_reply_to"]) for draft in data["drafts"]["rows"]
                   if draft["sent_message_id"] or draft["status"] in {"sending", "sent", "failed"}}
        headers.discard(None)
        if headers:
            data["escaped_source_archive"] = self._source_archive(conn, schema, present, headers)
        return data

    def _source_archive(self, conn, schema, present, headers):
        for table, fields in (("mailboxes", {"id", "owner_id", "address", "is_primary", "removed_at"}),
                              ("emails", {"id", "owner_id", "mailbox_id", "message_id_header"})):
            if table not in present or not fields <= {c["name"] for c in schema.get_columns(table)}:
                raise MigrationRefusal("legacy_source_archive_unavailable")
        primary = conn.exec_driver_sql(
            "SELECT id, address FROM mailboxes WHERE owner_id COLLATE BINARY = ? "
            "AND is_primary = 1 AND removed_at IS NULL AND lower(address) = ? ORDER BY id COLLATE BINARY",
            (self.owner, self.owner),
        ).all()
        matches = {}
        if len(primary) == 1:
            for header in headers:
                rows = conn.exec_driver_sql(
                    "SELECT id, message_id_header FROM emails WHERE owner_id COLLATE BINARY = ? "
                    "AND mailbox_id COLLATE BINARY = ? AND message_id_header COLLATE BINARY = ? "
                    "ORDER BY id COLLATE BINARY",
                    (self.owner, primary[0].id, header),
                ).all()
                matches[header] = [tuple(row) for row in rows]
        return {"primary": [tuple(row) for row in primary], "matches": matches}

    @staticmethod
    def _snapshot_digest(data):
        return _digest({name: value for name, value in data.items() if name != RECEIPTS.name or value["rows"]})

    def preview(self):
        with self.engine.connect() as conn:
            data = self._snapshot(conn)
        counts = {}
        for row in data["drafts"]["rows"]:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {"owner": self.owner, "profile_uid": self.profile_uid,
                "snapshot_digest": self._snapshot_digest(data), "legacy_drafts": counts,
                "legacy_journal_rows": len(data["draft_provider_operations"]["rows"]),
                "reply_operations": len(data["operator_reply_operations"]["rows"]),
                "legacy_campaign_drafts": sum(row.get("draft_subject") is not None or row.get("draft_body") is not None
                    for row in data["campaign_contacts"]["rows"]),
                "provider_mutations": 0}

    def _candidate(self, operation_id, draft_id, source, message_id, old_stage, identity_digest):
        request_key = "legacy-send:" + operation_id
        if len(request_key) > 256:
            raise MigrationRefusal("legacy_operation_identity_invalid")
        return {"request_key": request_key, "target": "legacy-internal:" + draft_id,
                "source": _identifier(source), "message_id": _identifier(message_id),
                "payload_digest": identity_digest, "legacy_stage": old_stage}

    def _candidates(self, data):
        # Campaign content belongs to the same explicitly selected profile.
        # Validate every owner before importing receipts or clearing any text.
        for name in ("campaigns", "campaign_contacts"):
            if any(str(row["owner_id"]).lower() != self.owner for row in data[name]["rows"]):
                raise MigrationRefusal("legacy_campaign_mailbox_mismatch")
        drafts = {row["id"]: row for row in data["drafts"]["rows"]}
        if any(str(row["owner_id"]).lower() != self.owner for row in drafts.values()):
            raise MigrationRefusal("legacy_mailbox_mismatch")
        if any(row["status"] not in {"draft", "sending", "sent", "failed"} for row in drafts.values()):
            raise MigrationRefusal("legacy_draft_status_unknown")
        existing = {row["request_key"]: row for row in data[RECEIPTS.name]["rows"] if row["owner"] == self.owner}
        candidates = []
        represented = set()
        for operation in data["draft_provider_operations"]["rows"]:
            if operation["owner_uid"] != self.profile_uid:
                raise MigrationRefusal("legacy_profile_mismatch")
            if operation["operation_type"] != "send":
                continue
            if operation["stage"] not in {"reserved", "inventoried", "dispatch_possible", "acknowledged", "completed", "not_dispatched"}:
                raise MigrationRefusal("legacy_send_stage_unknown")
            binding = _object(operation["binding"])
            transport = binding.get("transport") or {}
            if not isinstance(transport, dict):
                raise MigrationRefusal("legacy_transport_unreadable")
            draft = drafts.get(operation["draft_id"], {})
            prior = existing.get("legacy-send:" + operation["operation_id"], {})
            source = draft.get("in_reply_to") or binding.get("target") or prior.get("source") or ""
            if draft.get("in_reply_to") and binding.get("target") and draft["in_reply_to"] != binding["target"]:
                raise MigrationRefusal("legacy_source_identity_conflict")
            message_id = transport.get("message_id") or draft.get("sent_message_id") or prior.get("message_id") or ""
            old_stage = operation["stage"]
            if old_stage in {"reserved", "inventoried"} and draft.get("status") in {"sending", "sent", "failed"}:
                old_stage = "dispatch_possible"
            candidate = self._candidate(operation["operation_id"], operation["draft_id"], source,
                                        message_id, old_stage, _digest({
                                            "operation_id": operation["operation_id"], "draft_id": operation["draft_id"],
                                            "source": source, "message_id": message_id,
                                            "mime_digest": transport.get("mime_digest"),
                                        }))
            candidates.append(candidate)
            represented.add((operation["draft_id"], message_id))
        for draft in drafts.values():
            mid = draft.get("sent_message_id") or ""
            covered = any(candidate["target"] == "legacy-internal:" + draft["id"]
                          and candidate["legacy_stage"] != "not_dispatched" for candidate in candidates)
            if (draft["id"], mid) in represented or (not mid and covered):
                continue
            if not mid and draft["status"] not in {"sending", "sent", "failed"}:
                continue
            source = draft.get("in_reply_to") or ""
            header = _escaped_source_header(source)
            if header is not None:
                _identifier(header)
                try:
                    parsed = default.header_factory("Message-ID", header)
                except (email.errors.MessageError, ValueError, IndexError, AttributeError):
                    raise MigrationRefusal("legacy_message_identity_invalid") from None
                if parsed.defects or str(parsed) != header:
                    raise MigrationRefusal("legacy_message_identity_invalid")
                if len(data["escaped_source_archive"]["matches"].get(header, [])) != 1:
                    raise MigrationRefusal("legacy_source_archive_not_unique")
            candidates.append(self._candidate("draft:" + draft["id"], draft["id"], header or source, mid,
                              "dispatch_possible", _digest({"draft_id": draft["id"], "source": source, "message_id": mid})))
        return candidates

    def apply(self, expected_digest, *, writer_fence, sent_lookup):
        _fenced(writer_fence)
        if not callable(sent_lookup):
            raise MigrationRefusal("read_only_sent_lookup_required")
        operations = MailboxOperations(self.engine)
        counts = {"discarded_internal_drafts": 0, "scrubbed_reply_snapshots": 0,
                  "cleared_campaign_draft_contacts": 0, "cleared_campaign_draft_fields": 0,
                  "imported_send_receipts": 0, "confirmed_sends": 0, "unconfirmed_sends": 0,
                  "not_dispatched_sends": 0, "provider_mutations": 0, "sent_lookup_failures": 0}
        with operations.writer() as conn:
            data = self._snapshot(conn)
            if self._snapshot_digest(data) != expected_digest:
                raise MigrationRefusal("migration_snapshot_changed")
            candidates = self._candidates(data)
            _fenced(writer_fence)
            for candidate in candidates:
                proof, lookup_status = _sent_proof(sent_lookup, candidate["message_id"], self.owner)
                stage = "completed" if proof else (
                    "not_dispatched" if candidate["legacy_stage"] in {"reserved", "inventoried", "not_dispatched"}
                    else "unconfirmed")
                if lookup_status in {"sent_lookup_failed", "sent_lookup_incomplete"}:
                    counts["sent_lookup_failures"] += 1
                result = {"ok": bool(proof), "state": "sent" if proof else stage,
                          "message_id": candidate["message_id"], "cause": "legacy_" + lookup_status,
                          "legacy_internal_draft_discarded": True}
                if proof:
                    result["sent"] = proof
                existing = conn.execute(select(RECEIPTS).where(
                    RECEIPTS.c.owner == self.owner, RECEIPTS.c.request_key == candidate["request_key"],
                )).mappings().one_or_none()
                binding = {key: candidate[key] for key in ("target", "source", "message_id", "payload_digest")}
                if existing is not None:
                    if existing["kind"] != "send" or any(existing[k] != v for k, v in binding.items()):
                        raise MigrationRefusal("legacy_receipt_identity_conflict")
                    if existing["stage"] not in {"completed", "dispatch_possible", "unconfirmed", "not_dispatched"}:
                        raise MigrationRefusal("legacy_receipt_stage_unknown")
                    if existing["stage"] == "completed" or (proof is None and existing["stage"] in {"dispatch_possible", "unconfirmed"}):
                        stage = existing["stage"]
                    else:
                        conn.execute(RECEIPTS.update().where(RECEIPTS.c.id == existing["id"]).values(
                            stage=stage, result=_json(result), updated_at=time.time()))
                else:
                    now = time.time()
                    conn.execute(RECEIPTS.insert().values(
                        id=str(uuid5(NAMESPACE_URL, "mrcall-mailbox-legacy-send:" + self.profile_uid + ":" + candidate["request_key"])),
                        owner=self.owner, kind="send", **binding, request_key=candidate["request_key"],
                        draft_id=None, stage=stage, executor="", result=_json(result), created_at=now, updated_at=now))
                    counts["imported_send_receipts"] += 1
                counts[{"completed": "confirmed_sends", "dispatch_possible": "unconfirmed_sends",
                        "unconfirmed": "unconfirmed_sends", "not_dispatched": "not_dispatched_sends"}[stage]] += 1
            for row in data["operator_reply_operations"]["rows"]:
                if row["result"] is None:
                    continue
                result = _object(row["result"])
                if "snapshot" not in result:
                    continue
                snapshot = result.get("snapshot")
                if not isinstance(snapshot, dict):
                    raise MigrationRefusal("legacy_reply_snapshot_unreadable")
                minimal = {"status": "discarded", "legacy_draft_id": result.get("draft_id") or snapshot.get("id"),
                           "snapshot_hash": result.get("snapshot_hash") or _digest(snapshot),
                           "body_sha256": result.get("body_sha256") or hashlib.sha256(str(snapshot.get("body") or "").encode()).hexdigest()}
                conn.exec_driver_sql("UPDATE operator_reply_operations SET result = ? WHERE id = ?", (_json(minimal), row["id"]))
                counts["scrubbed_reply_snapshots"] += 1
            _fenced(writer_fence)
            if data["drafts"]["columns"] is not None:
                counts["discarded_internal_drafts"] = conn.exec_driver_sql("DELETE FROM drafts").rowcount
            if data["campaign_contacts"]["columns"] is not None:
                affected = [row for row in data["campaign_contacts"]["rows"]
                            if row.get("draft_subject") is not None or row.get("draft_body") is not None]
                counts["cleared_campaign_draft_contacts"] = len(affected)
                counts["cleared_campaign_draft_fields"] = sum(
                    row.get(field) is not None for row in affected for field in ("draft_subject", "draft_body"))
                conn.exec_driver_sql("UPDATE campaign_contacts SET draft_subject = NULL, draft_body = NULL "
                                     "WHERE draft_subject IS NOT NULL OR draft_body IS NOT NULL")
            counts["legacy_journal_rows_preserved"] = len(data["draft_provider_operations"]["rows"])
        return counts

    def rollback_check(self, *, writer_fence):
        _fenced(writer_fence)
        with self.engine.connect() as conn:
            data = self._snapshot(conn)
        journal = data["draft_provider_operations"]
        if journal["columns"] is None:
            raise MigrationRefusal("legacy_journal_unavailable")
        if journal["rows"]:
            raise MigrationRefusal("old_writer_rollback_requires_empty_journal")
        if data[RECEIPTS.name]["rows"]:
            raise MigrationRefusal("old_writer_rollback_cannot_read_mailbox_receipts")
        if data["drafts"]["rows"]:
            raise MigrationRefusal("old_writer_rollback_has_legacy_drafts")
        if any(row.get("draft_subject") is not None or row.get("draft_body") is not None
               for row in data["campaign_contacts"]["rows"]):
            raise MigrationRefusal("old_writer_rollback_has_legacy_campaign_drafts")
        return {"old_writer_restart_allowed": True, "restored_internal_drafts": 0}
