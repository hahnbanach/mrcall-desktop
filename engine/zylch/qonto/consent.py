"""Bounded non-secret company label for the engine-issued consent context."""

from zylch.memory.company_key import current_company_key
from zylch.memory.mnemonic.session import company_transaction
from zylch.qonto.identity import require_same
from zylch.storage.models import MemoryMeta


def company_name(authority):
    require_same(authority)
    with company_transaction() as session:
        notion = session.query(MemoryMeta.self_notion).filter(MemoryMeta.id == 1).scalar()
    require_same(authority)
    if not isinstance(notion, str) or not notion.strip():
        return None
    capability = current_company_key()
    if capability:
        notion = notion.replace(capability, "[redacted]")
    label = " ".join(notion.split())
    return "".join(character for character in label if character.isprintable())[:200] or None
