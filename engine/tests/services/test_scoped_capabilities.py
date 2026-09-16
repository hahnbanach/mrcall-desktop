"""Real memory-table reads with synthetic company data, no profile initialization."""

from dataclasses import replace
import hashlib
import unittest
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from zylch.services.capability_contract import (
    ApprovedSentence,
    CapabilityBinding,
    CapabilityRequest,
    ContactGrant,
)
from zylch.services.scoped_capabilities import ScopedCapabilities
from zylch.storage.models import Blob, BlobSentence

KEY = "A" * 22
TEXT = "The customer prefers appointments in the morning."


def binding():
    ref = ApprovedSentence("sentence-1", hashlib.sha256(TEXT.encode()).hexdigest())
    return CapabilityBinding(
        "business",
        "owner",
        "service",
        KEY,
        "rev-1",
        (ContactGrant("contact", "customer@example.com", (ref,)),),
    )


def request(operation="memory.recall"):
    return CapabilityRequest(
        1, "business", "session", "rev-1", "request-1", 1, 0, "contact", operation, 3000
    )


class ScopedCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Blob.__table__.create(self.engine)
        BlobSentence.__table__.create(self.engine)
        self.addCleanup(self.engine.dispose)
        self.scope = ("owner", KEY)
        self.reader = Mock(
            return_value={
                "data": {
                    "customers": {
                        "edges": [
                            {
                                "node": {
                                    "id": "id",
                                    "email": "customer@example.com",
                                    "numberOfOrders": "1",
                                }
                            }
                        ]
                    }
                }
            }
        )
        self.service = ScopedCapabilities(
            binding(), self.reader, lambda: Session(self.engine), lambda: self.scope, lambda: 1000
        )
        with Session(self.engine) as session:
            session.add(
                Blob(
                    id="blob",
                    company_key=KEY,
                    owner_id="other-owner",
                    namespace=f"user:{KEY}",
                    content="Private dossier must not escape",
                )
            )
            session.add(
                BlobSentence(
                    id="sentence-1",
                    blob_id="blob",
                    company_key=KEY,
                    owner_id="other-owner",
                    sentence_text=TEXT,
                    embedding=b"",
                )
            )
            session.commit()

    def test_only_approved_sentence_from_existing_shared_memory(self):
        result = self.service.execute_authorized(request())
        self.assertEqual(
            result,
            {
                "status": "memory_found",
                "sentences": [
                    {"text": TEXT, "revision": binding().contacts[0].sentences[0].digest}
                ],
            },
        )
        self.reader.assert_not_called()

    def test_company_keys_and_namespace_are_all_required(self):
        for model, field, value in (
            (Blob, "company_key", "B" * 22),
            (BlobSentence, "company_key", "B" * 22),
            (Blob, "namespace", "prefs:owner"),
            (Blob, "namespace", "template:owner"),
            (Blob, "namespace", "unknown:namespace"),
        ):
            with self.subTest(field=field, value=value), Session(self.engine) as session:
                row = session.query(model).one()
                old = getattr(row, field)
                setattr(row, field, value)
                session.commit()
                self.assertEqual(
                    self.service.execute_authorized(request()), {"status": "unavailable"}
                )
                setattr(row, field, old)
                session.commit()

    def test_changed_sentence_requires_new_approval(self):
        with Session(self.engine) as session:
            session.query(BlobSentence).one().sentence_text = "Changed private content"
            session.commit()
        self.assertEqual(self.service.execute_authorized(request()), {"status": "unavailable"})

    def test_empty_grant_does_not_fall_back_to_full_entity_search(self):
        self.service.binding = replace(binding(), contacts=(ContactGrant("contact"),))
        self.assertEqual(
            self.service.execute_authorized(request()), {"status": "memory_found", "sentences": []}
        )

    def test_order_read_uses_bound_email_not_request_arguments(self):
        self.assertEqual(
            self.service.execute_authorized(request("order.exists")), {"status": "order_exists"}
        )
        self.reader.assert_called_once_with("customer@example.com")

    def test_scope_rebind_before_or_during_read_is_denied(self):
        self.scope = ("owner", "B" * 22)
        with self.assertRaises(PermissionError):
            self.service.execute_authorized(request("order.exists"))
        self.reader.assert_not_called()
        self.scope = ("owner", KEY)

        def change(_):
            self.scope = ("other", KEY)
            return {"data": {"customers": {"edges": []}}}

        self.reader.side_effect = change
        with self.assertRaises(PermissionError):
            self.service.execute_authorized(request("order.exists"))

    def test_strict_request_and_authority_checks_precede_reads(self):
        invalid = (
            {"version": True},
            {"sequence": False},
            {"generation": -1},
            {"expires_at_ms": 1000},
            {"expires_at_ms": 4001},
            {"operation": "emails.send"},
            {"business_id": "other"},
            {"contact_ref": "other"},
            {"procedure_revision": "rev-2"},
            {"url": "https://invalid"},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises((ValueError, PermissionError)):
                CapabilityRequest.parse(request().public_dict() | changes, binding(), 1000)
        self.reader.assert_not_called()

    def test_binding_does_not_accept_owner_as_service(self):
        with self.assertRaises(ValueError):
            replace(binding(), service_uid="owner")


if __name__ == "__main__":
    unittest.main()
