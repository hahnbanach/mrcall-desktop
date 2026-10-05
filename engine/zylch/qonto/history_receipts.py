"""Retained exact evidence digests without semantic classification of user facts."""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata

from sqlalchemy import inspect

from zylch.qonto.history_errors import HistoryAuthorizationError
from zylch.qonto.models import QontoEvidenceReceipt
from zylch.qonto.repository import profile_transaction
from zylch.storage.database import get_engine

ACKNOWLEDGEMENTS = frozenset(
    {
        "ok",
        "okay",
        "thanks",
        "thank you",
        "done",
        "finished",
        "sure",
        "yes",
        "no",
        "understood",
        "got it",
        "va bene",
        "fatto",
        "grazie",
        "d'accord",
        "merci",
        "vale",
        "gracias",
        "danke",
        "verstanden",
        "alright",
        "all right",
        "certainly",
        "noted",
        "received",
        "thank you very much",
        "thanks very much",
        "you're welcome",
        "you are welcome",
        "capito",
        "ricevuto",
        "d'accordo",
        "merci beaucoup",
        "compris",
        "bien reçu",
        "de acuerdo",
        "entendido",
        "muchas gracias",
        "in ordnung",
        "vielen dank",
    }
)
ACK_CONJUNCTIONS = frozenset({"and", "or", "also", "e", "et", "y", "und"})
MAX_ACK_CHARACTERS = 256
MAX_ACK_PHRASES = 16
_ACK_PHRASE = re.compile(
    "(?:"
    + "|".join(
        re.escape(p).replace(r"\ ", r"\s+") for p in sorted(ACKNOWLEDGEMENTS, key=len, reverse=True)
    )
    + r")(?!\w)"
)
_ACK_CONJUNCTION = re.compile("(?:" + "|".join(sorted(ACK_CONJUNCTIONS)) + r")(?!\w)")


def _ack_separator(value, position):
    while position < len(value) and (
        value[position].isspace()
        or unicodedata.category(value[position]).startswith("P")
        or value[position] == "&"
    ):
        position += 1
    return position


def acknowledgement_only(value):
    """Recognize only a bounded full composition of finite generic acknowledgements."""
    value = value.strip().casefold().replace("’", "'")
    if not value or len(value) > MAX_ACK_CHARACTERS:
        return False
    position = _ack_separator(value, 0)
    for _ in range(MAX_ACK_PHRASES):
        match = _ACK_PHRASE.match(value, position)
        if match is None:
            return False
        end = match.end()
        position = _ack_separator(value, end)
        if position == len(value):
            return True
        if position == end:
            return False
        for _ in range(2):
            conjunction = _ACK_CONJUNCTION.match(value, position)
            if conjunction is None:
                break
            position = _ack_separator(value, conjunction.end())
            if position == conjunction.end():
                return False
    return False


def retain_assistant_text(session, binding, value):
    if not isinstance(value, str):
        return
    if acknowledgement_only(value):
        return
    retain(session, binding, value, text=True)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value, *, text=False):
    payload = value.strip() if text else canonical(value)
    return hashlib.sha256(("text:" if text else "json:").encode() + payload.encode()).hexdigest()


def retain(session, binding, value, *, text=False):
    if text and (not isinstance(value, str) or not value.strip()):
        return
    key = digest(value, text=text)
    if session.get(QontoEvidenceReceipt, (binding.uid, key)) is None:
        session.add(
            QontoEvidenceReceipt(
                uid=binding.uid,
                digest=key,
                host_id=binding.host_id,
                company_scope=binding.company_scope,
                generation=binding.generation,
                text_length=len(value.strip()) if text else None,
                created_at=time.time(),
            )
        )
        session.flush()


def retain_result(session, binding, result, rendered=None):
    retain(session, binding, result)
    transaction = result.get("transaction")
    if isinstance(transaction, dict) and transaction:
        retain(session, binding, transaction)
    for field in ("accounts", "transactions", "tasks", "groups", "signed_net_flow"):
        rows = result.get(field)
        if isinstance(rows, list) and rows:
            retain(session, binding, rows)
            for row in rows:
                if isinstance(row, dict) and row:
                    retain(session, binding, row)
    if rendered is not None:
        retain(session, binding, rendered, text=True)


def retain_outputs(session, binding, history, result=None):
    for message in history:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if message.get("role") == "assistant" and isinstance(content, str):
            retain_assistant_text(session, binding, content)
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if message.get("role") == "assistant" and block.get("type") == "text":
                    retain_assistant_text(session, binding, block.get("text"))
                if block.get("type") == "tool_result":
                    value = block.get("content")
                    if isinstance(value, str):
                        retain(session, binding, value, text=True)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict) and item.get("type") == "text":
                                retain(session, binding, item.get("text"), text=True)
    if isinstance(result, dict):
        retain_assistant_text(session, binding, result.get("response"))


def _candidates(value):
    if isinstance(value, (dict, list)):
        if value:
            yield digest(value)
        children = value.values() if isinstance(value, dict) else value
        for child in children:
            yield from _candidates(child)
    elif isinstance(value, str):
        yield digest(value, text=True)
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return
        if isinstance(parsed, (list, dict)):
            yield from _candidates(parsed)


def _strings(value):
    if isinstance(value, str):
        yield value.strip()
    elif isinstance(value, (dict, list)):
        for child in value.values() if isinstance(value, dict) else value:
            yield from _strings(child)


def reject_known_evidence(value):
    from zylch.qonto.logging import private_scope

    with private_scope():
        _reject_known_evidence(value)


def _reject_known_evidence(value):
    engine = get_engine()
    if not inspect(engine).has_table(QontoEvidenceReceipt.__tablename__):
        return
    with profile_transaction() as session:
        rows = session.query(QontoEvidenceReceipt.digest, QontoEvidenceReceipt.text_length).all()
    if not rows:
        return
    known = {row.digest for row in rows}
    if known.intersection(_candidates(value)):
        raise HistoryAuthorizationError("history_invalid")
    lengths = {row.text_length for row in rows if row.text_length}
    for text in _strings(value):
        for length in lengths:
            if length < len(text):
                for offset in range(len(text) - length + 1):
                    if digest(text[offset : offset + length], text=True) in known:
                        raise HistoryAuthorizationError("history_invalid")
