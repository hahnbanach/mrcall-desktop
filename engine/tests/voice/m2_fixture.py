"""Synthetic M2 history, deliberately separated profile/company SQLite files."""

from sqlalchemy import create_engine

from zylch.memory.company_key import mint_key
from zylch.services.project_store import ensure_space
from zylch.storage import database as db
from zylch.storage.models import Base, Blob, BlobSentence, PersonIdentifier

OWNER = "fixture-owner"
NUMBER = "+390200000001"
KNOWN = "+393330000001"
OTHER = "+393330000002"
SHARED = "+393330000003"
PUBLIC = "The earlier request concerns blue replacement filters."
FOLLOWUP = "The filter delivery was agreed for Thursday in the prior email."
INTERNAL = "INTERNAL: discount margin and confidential staff assessment."
OTHER_FACT = "OTHER CUSTOMER: payment dispute for red cartridges."


def seed(root, monkeypatch, owner=OWNER):
    """Never activate a profile or use a customer's store or credentials."""
    db.dispose_engine()
    root.mkdir(exist_ok=True)
    key = mint_key()
    monkeypatch.setenv("OWNER_ID", owner)
    monkeypatch.setenv("MEMORY_KEY", key)
    monkeypatch.setenv("ZYLCH_DB_PATH", str(root / "profile.db"))
    monkeypatch.setenv("MEMORY_DB_DIR", str(root / "memory"))
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(root))
    Base.metadata.create_all(db.get_engine(), tables=db.profile_tables())
    memory = create_engine(f"sqlite:///{root / 'company.db'}")
    Base.metadata.create_all(memory, tables=db.memory_tables())
    ensure_space(memory)
    db.set_memory_engine(memory, None)
    with db.get_session() as session:
        for bid, company in (("customer-a", key), ("customer-b", key), ("foreign", "foreign-key")):
            session.add(
                Blob(
                    id=bid,
                    owner_id=owner,
                    company_key=company,
                    namespace=f"user:{company}",
                    content="PRIVATE FULL BLOB " + INTERNAL,
                )
            )
        session.flush()
        for sid, bid, text, company in (
            ("a-public", "customer-a", PUBLIC, key),
            ("a-followup", "customer-a", FOLLOWUP, key),
            ("a-internal", "customer-a", INTERNAL, key),
            ("b-public", "customer-b", OTHER_FACT, key),
            ("foreign-public", "foreign", "FOREIGN COMPANY SECRET", "foreign-key"),
        ):
            session.add(
                BlobSentence(
                    id=sid,
                    blob_id=bid,
                    owner_id=owner,
                    company_key=company,
                    sentence_text=text,
                    embedding=b"fixture",
                )
            )
        for bid, phone, company in (
            ("customer-a", KNOWN, key),
            ("customer-b", OTHER, key),
            ("customer-a", SHARED, key),
            ("customer-b", SHARED, key),
            ("foreign", KNOWN, "foreign-key"),
        ):
            session.add(
                PersonIdentifier(
                    blob_id=bid, owner_id=owner, company_key=company, kind="phone", value=phone
                )
            )
    return key


def configuration():
    return {
        "enabled": True,
        "called_number": NUMBER,
        "instructions": "Use only approved stored facts. Ask when information is missing.",
        "tools": ["caller_memory"],
        "customers": [{"blob_id": "customer-a", "sentence_ids": ["a-public", "a-followup"]}],
    }
