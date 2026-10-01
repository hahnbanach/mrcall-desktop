"""PEC (posta elettronica certificata) envelopes: markers and the wrapped original.

A PEC provider never delivers the sender's message as is. What lands in
the mailbox is a transport envelope — a message from the provider whose
body is a notice and whose ``message/rfc822`` part, named
``postacert.eml``, is the original — plus receipts (acceptance, delivery,
non-delivery and the like) that carry no human message at all, and the
anomaly wrapper (``busta di anomalia``): the same shape as the transport
envelope, with ``X-Trasporto: errore`` and an ``ANOMALIA MESSAGGIO``
subject, which is how every ordinary, non-certified message reaches a
PEC mailbox that accepts ordinary mail. The archive wants the original's
sender, subject, body, attachments and threading, while keeping the
envelope's Message-ID as the row's identity, because that is what the
server holds; ``pec_markers.kind`` keeps ``anomaly`` for the wrapper, so a
later delivery can derive that the message was not certified.

Markers (D4). Standard-derived from the PEC technical rules (DPCM
2 November 2005, AgID): ``X-Trasporto: posta-certificata`` on a transport
envelope, ``X-Trasporto: errore`` on an anomaly wrapper, ``X-Ricevuta``
on a receipt with its type as the value, and
``X-Riferimento-Message-ID`` naming the message a receipt refers to. This
list awaits the M7 live sample from the supervised PEC.net account; until
then it is the standard's. Detection fires only on these headers, never
on the mere presence of an attached message, so a forward-as-attachment
is untouched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.message import Message
from typing import Any

logger = logging.getLogger(__name__)

TRANSPORT_HEADER = "X-Trasporto"
RECEIPT_HEADER = "X-Ricevuta"
REFERENCE_HEADER = "X-Riferimento-Message-ID"
# Every marker header the row keeps verbatim when present.
MARKER_HEADERS = (
    TRANSPORT_HEADER,
    RECEIPT_HEADER,
    REFERENCE_HEADER,
    "X-TipoRicevuta",
    "X-VerificaSicurezza",
    "X-Mittente",
)
TRANSPORT_VALUE = "posta-certificata"
ANOMALY_VALUE = "errore"
# The receipt types the standard names. Detection keeps the raw value
# whatever it is (an unknown value is still a receipt); the set only says
# whether the value is one the standard defines.
RECEIPT_TYPES = frozenset(
    {
        "accettazione",
        "non-accettazione",
        "presa-in-carico",
        "avvenuta-consegna",
        "errore-consegna",
        "preavviso-errore-consegna",
        "rilevazione-virus",
    }
)
ORIGINAL_PART_NAME = "postacert.eml"
# The provider's own parts: the wrapped original, the certification data
# and the provider's S/MIME signature. Never user attachments.
PROVIDER_PART_NAMES = frozenset({ORIGINAL_PART_NAME, "daticert.xml", "smime.p7s"})

KIND_TRANSPORT = "transport"
KIND_RECEIPT = "receipt"
KIND_ANOMALY = "anomaly"


@dataclass(frozen=True)
class PecEnvelope:
    """What the provider's headers say about a message."""

    kind: str  # transport | receipt | anomaly
    receipt_type: str | None
    reference_message_id: str | None
    headers: dict[str, str]  # the raw marker headers present, by canonical name

    def to_markers(self) -> dict[str, Any]:
        """The JSON the ``emails.pec_markers`` column stores."""
        return {
            "kind": self.kind,
            "receipt_type": self.receipt_type,
            "reference_message_id": self.reference_message_id,
            "headers": dict(self.headers),
        }


@dataclass(frozen=True)
class PecUnwrap:
    """The result of :func:`pec_original`.

    ``original`` is the wrapped human message of a transport envelope;
    ``None`` for a receipt, an anomaly wrapper, or a transport envelope
    that carries no ``message/rfc822`` part (stored as is, markers kept).
    """

    envelope: PecEnvelope
    original: Message | None


def _header(msg: Message, name: str) -> str:
    value = msg.get(name)
    return " ".join(str(value).split()) if value else ""


def detect_envelope(msg: Message) -> PecEnvelope | None:
    """The envelope the marker headers describe, or ``None`` for ordinary mail."""
    present = {name: _header(msg, name) for name in MARKER_HEADERS if msg.get(name) is not None}
    transport = present.get(TRANSPORT_HEADER, "").lower()
    receipt = present.get(RECEIPT_HEADER, "").lower()
    if not transport and not receipt:
        return None
    reference = present.get(REFERENCE_HEADER) or None
    if receipt:
        kind, receipt_type = KIND_RECEIPT, receipt
        if receipt not in RECEIPT_TYPES:
            logger.debug(f"[pec] receipt type {receipt!r} is not one the standard names; kept")
    elif transport == TRANSPORT_VALUE:
        kind, receipt_type = KIND_TRANSPORT, None
    else:
        kind, receipt_type = KIND_ANOMALY, None
    return PecEnvelope(
        kind=kind, receipt_type=receipt_type, reference_message_id=reference, headers=present
    )


def is_provider_part(filename: str | None) -> bool:
    """Whether a part name is one of the provider's (never a user attachment)."""
    return (filename or "").strip().lower() in PROVIDER_PART_NAMES


def envelope_parts(msg: Message):
    """The envelope's own leaf parts, through its ``multipart/*`` containers.

    Real envelopes are S/MIME-signed by the provider: ``multipart/signed``
    holding a ``multipart/mixed`` (notice, ``postacert.eml``,
    ``daticert.xml``) and ``smime.p7s``. Descends through every
    ``multipart/*`` container (signed, mixed, alternative, ...) but never
    into a ``message/rfc822`` payload: the original's own parts are the
    original's, not the envelope's.
    """
    if not msg.is_multipart():
        yield msg
        return
    for part in msg.get_payload():
        if not isinstance(part, Message):
            continue
        if part.get_content_maintype() == "multipart":
            yield from envelope_parts(part)
        else:
            yield part


def find_original(msg: Message) -> Message | None:
    """The ``message/rfc822`` part carrying the original: ``postacert.eml`` first.

    Looks through the envelope's containers (see :func:`envelope_parts`)
    without entering nested messages. A part named ``postacert.eml``
    wins; otherwise the first ``message/rfc822`` part; ``None`` when
    there is none.
    """
    fallback: Message | None = None
    for part in envelope_parts(msg):
        if part.get_content_type() != "message/rfc822":
            continue
        inner = _inner_message(part)
        if inner is None:
            continue
        if (part.get_filename() or "").strip().lower() == ORIGINAL_PART_NAME:
            return inner
        if fallback is None:
            fallback = inner
    return fallback


def _inner_message(part: Message) -> Message | None:
    """The message inside an ``rfc822`` part, decoding a base64/QP-encoded one.

    The parser nests the inner message as the part's payload when the part
    is sent verbatim; a provider that transfer-encodes the part leaves a
    string payload, decoded here into a message of its own.
    """
    import base64
    import quopri
    from email import message_from_bytes

    def _looks_like_mail(candidate: Message) -> bool:
        return bool(
            candidate.get("From") or candidate.get("Message-ID") or candidate.get("Subject")
        )

    payload = part.get_payload()
    nested = payload[0] if isinstance(payload, list) and payload else None
    if isinstance(nested, Message) and _looks_like_mail(nested):
        return nested
    # A transfer-encoded part: the parser nested a header-less pseudo-message
    # whose body is the encoded text. Decode it into the message it is.
    encoding = (part.get("Content-Transfer-Encoding") or "").strip().lower()
    text = nested.get_payload() if isinstance(nested, Message) else payload
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        if encoding == "base64":
            raw = base64.b64decode("".join(text.split()))
        elif encoding == "quoted-printable":
            raw = quopri.decodestring(text.encode("utf-8", errors="replace"))
        else:
            raw = text.encode("utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"[pec] rfc822 part could not be decoded ({encoding}): {e}")
        return None
    inner = message_from_bytes(raw)
    return inner if _looks_like_mail(inner) else None


def pec_original(msg: Message) -> PecUnwrap | None:
    """Unwrap a PEC message: ``None`` for ordinary mail (forwards included).

    A transport envelope and an anomaly wrapper yield their original (the
    wrapper carries the ordinary message it delivers); a receipt yields
    the envelope alone; an envelope or wrapper without an ``rfc822``
    part yields the envelope alone too, logged, never raised.
    """
    envelope = detect_envelope(msg)
    if envelope is None:
        return None
    wraps = envelope.kind in (KIND_TRANSPORT, KIND_ANOMALY)
    original = find_original(msg) if wraps else None
    if wraps and original is None:
        logger.warning(
            f"[pec] {envelope.kind} envelope {_header(msg, 'Message-ID')} carries no "
            f"message/rfc822 part; stored as is"
        )
    return PecUnwrap(envelope=envelope, original=original)
