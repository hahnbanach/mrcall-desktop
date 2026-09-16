"""Private startup authority and the small public read-request contract.

Bindings/grants are installed by trusted code, never decoded from wire requests.
No production loader installs them yet. In particular, an identifier observed in
a call or email does not grant access to a contact's facts by itself.
"""

from dataclasses import asdict, dataclass, field
import re

OPERATIONS = frozenset({"order.exists", "memory.recall"})
MAX_HORIZON_MS = 3000


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value))


@dataclass(frozen=True)
class ApprovedSentence:
    sentence_id: str
    digest: str

    def __post_init__(self):
        if not _identifier(self.sentence_id) or not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError("invalid approved sentence reference")


@dataclass(frozen=True)
class ContactGrant:
    contact_ref: str
    email: str | None = field(default=None, repr=False)
    sentences: tuple[ApprovedSentence, ...] = ()

    def __post_init__(self):
        if (
            not _identifier(self.contact_ref)
            or type(self.sentences) is not tuple
            or len(self.sentences) > 8
            or any(not isinstance(ref, ApprovedSentence) for ref in self.sentences)
            or len({ref.sentence_id for ref in self.sentences}) != len(self.sentences)
        ):
            raise ValueError("invalid contact grant")


@dataclass(frozen=True)
class CapabilityBinding:
    business_id: str
    profile_uid: str
    service_uid: str
    company_key: str = field(repr=False)
    procedure_revision: str
    contacts: tuple[ContactGrant, ...]

    def __post_init__(self):
        if (
            not all(
                _identifier(v)
                for v in (
                    self.business_id,
                    self.profile_uid,
                    self.service_uid,
                    self.procedure_revision,
                )
            )
            or self.profile_uid == self.service_uid
            or not re.fullmatch(r"[A-Za-z0-9_-]{22}", self.company_key)
            or type(self.contacts) is not tuple
            or not 0 < len(self.contacts) <= 32
            or any(not isinstance(g, ContactGrant) for g in self.contacts)
            or len({g.contact_ref for g in self.contacts}) != len(self.contacts)
        ):
            raise ValueError("invalid capability binding")


@dataclass(frozen=True)
class CapabilityRequest:
    version: int
    business_id: str
    session_id: str
    procedure_revision: str
    request_id: str
    sequence: int
    generation: int
    contact_ref: str
    operation: str
    expires_at_ms: int

    def public_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def parse(cls, payload: object, binding: CapabilityBinding, now_ms: int):
        if not isinstance(payload, dict) or set(payload) != set(cls.__dataclass_fields__):
            raise ValueError("invalid capability request")
        integers = ("version", "sequence", "generation", "expires_at_ms")
        strings = ("business_id", "session_id", "procedure_revision", "request_id", "contact_ref")
        if (
            any(type(payload[k]) is not int for k in integers)
            or any(not _identifier(payload[k]) for k in strings)
            or payload["version"] != 1
            or not 1 <= payload["sequence"] <= 2**53 - 1
            or not 0 <= payload["generation"] <= 2**53 - 1
            or not isinstance(payload["operation"], str)
            or payload["operation"] not in OPERATIONS
            or not 0 < payload["expires_at_ms"] - now_ms <= MAX_HORIZON_MS
        ):
            raise ValueError("invalid capability request")
        if (
            payload["business_id"] != binding.business_id
            or payload["procedure_revision"] != binding.procedure_revision
            or payload["contact_ref"] not in {g.contact_ref for g in binding.contacts}
        ):
            raise PermissionError("capability denied")
        return cls(**payload)
