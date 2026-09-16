"""Pinned installation metadata, never credentials, grants or executable code.

References only name dependencies supplied by trusted composition. Parsing a
matching name does not resolve it or authorize any contact. A digest detects
drift in exact bytes; it is not proof of authorship or permission to install.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)
_FIELDS = frozenset(
    {"version", "id", "business_id", "procedure_revision", "connection_ref", "authority_ref"}
)
_REF = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_REVISION = re.compile(r"[0-9a-f]{64}")


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        # JSON decoding has already unescaped keys: escaped aliases are duplicates.
        if key in result:
            raise ValueError("invalid installation specification")
        result[key] = value
    return result


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


@dataclass(frozen=True)
class InstallationSpec:
    """Immutable metadata snapshot; composition must recheck the actual artifact.

    Construction is not an authority boundary. The parser checks pinned content;
    the installation separately checks trusted dependencies and live scope.
    No path lookup, provider call or credential refresh occurs here.
    """

    id: str
    business_id: str
    procedure_revision: str
    connection_ref: str
    authority_ref: str
    revision: str

    @classmethod
    def parse(
        cls, raw: bytes, expected_revision: str, expected_procedure_revision: str
    ) -> "InstallationSpec":
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= 4096
            or not _matches(_REVISION, expected_revision)
            or not _matches(_REVISION, expected_procedure_revision)
            or hashlib.sha256(raw).hexdigest() != expected_revision
        ):
            raise ValueError("invalid installation specification")
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_object)
            if (
                not isinstance(value, dict)
                or set(value) != _FIELDS
                or type(value["version"]) is not int
                or value["version"] != 1
                or any(
                    not _matches(_REF, value[key])
                    for key in ("id", "business_id", "connection_ref", "authority_ref")
                )
                or value["procedure_revision"] != expected_procedure_revision
            ):
                raise ValueError("invalid installation specification")
        except (ValueError, RecursionError):
            # Decode exceptions can otherwise contain supplied bytes or JSON text.
            # Never include malformed operator content in production diagnostics.
            raise ValueError("invalid installation specification") from None
        logger.debug("[installation] parse(revision=%s) -> validated", expected_revision)
        return cls(
            value["id"],
            value["business_id"],
            value["procedure_revision"],
            value["connection_ref"],
            value["authority_ref"],
            expected_revision,
        )

    def summary(self) -> dict[str, str]:
        """Return only public metadata; a fresh mapping cannot mutate the snapshot."""
        return {
            "id": self.id,
            "revision": self.revision,
            "business_id": self.business_id,
            "procedure_revision": self.procedure_revision,
            "connection_ref": self.connection_ref,
            "authority_ref": self.authority_ref,
        }
