"""Exact, short-lived operator approval without a signing entry in the engine."""

import base64
import os
import uuid
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import task_assignment_trust as trust
from .task_assignment_types import AssignmentError, canonical, digest, validate_intent


def sign(intent: dict[str, Any]) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise AssignmentError("Assignment approval requires the independent host operator")
    validate_intent(intent)
    current = trust.load(intent["space_id"])
    trust.member(current, intent["actor_uid"])
    if intent["assignee_uid"] is not None:
        trust.member(current, intent["assignee_uid"])
    raw = trust.protected_read(trust.SIGNING_DIRECTORY / f"{current['issuer']}.pem", private=True)
    try:
        key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError
        if key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ) != (
            trust.public_key(current).public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise AssignmentError("Assignment signing key refused") from None
    grant = {
        "version": 1,
        "issuer": current["issuer"],
        "space_id": intent["space_id"],
        "operation_id": intent["operation_id"],
        "payload_digest": digest(intent),
        "expires_at": intent["expires_at"],
        "nonce": str(uuid.uuid4()),
    }
    return {
        "approval": grant,
        "signature": base64.b64encode(key.sign(canonical(grant))).decode("ascii"),
    }


def verify(intent: dict[str, Any], grant: Any, current: dict) -> str:
    if not isinstance(grant, dict) or set(grant) != {"approval", "signature"}:
        raise AssignmentError("Independent assignment approval required")
    approval = grant["approval"]
    expected = {
        "version": 1,
        "issuer": current["issuer"],
        "space_id": intent["space_id"],
        "operation_id": intent["operation_id"],
        "payload_digest": digest(intent),
        "expires_at": intent["expires_at"],
        "nonce": approval.get("nonce") if isinstance(approval, dict) else None,
    }
    if approval != expected:
        raise AssignmentError("Assignment approval does not match the operation")
    nonce = approval["nonce"]
    try:
        if not isinstance(nonce, str) or str(uuid.UUID(nonce)) != nonce:
            raise ValueError
        trust.public_key(current).verify(
            base64.b64decode(grant["signature"], validate=True), canonical(approval)
        )
    except (ValueError, TypeError, InvalidSignature):
        raise AssignmentError("Assignment approval signature refused") from None
    return nonce
