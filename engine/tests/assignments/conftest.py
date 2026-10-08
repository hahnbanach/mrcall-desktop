"""Disposable SQLite stores; only OS privilege and Firebase issuer are fixtures."""

import base64
import json
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from zylch.auth import clear_session, set_session
from zylch.services import project_store, task_assignment_approval as approval
from zylch.services import task_assignment_trust as trust
from zylch.storage import database as db


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    from zylch.cli import profiles
    from zylch.memory.company_key import mint_key
    from zylch.memory.store import open_memory_engine, prepare_store
    from zylch.rpc import firebase_auth

    db.dispose_engine()
    company = mint_key()
    monkeypatch.setenv("MEMORY_DB_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("MEMORY_KEY", company)
    memory = open_memory_engine(company, create=True)
    prepare_store(memory, company, created_by="fixture")
    db.set_memory_engine(memory, None)
    key = Ed25519PrivateKey.generate()
    with project_store.connection() as (_conn, space):
        pass
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    configuration = {
        "version": 1,
        "issuer": "fixture",
        "space_id": space,
        "public_key": base64.b64encode(public).decode(),
        "members": {"alice": ["alice@example.test"], "bob": ["bob@example.test"]},
    }
    trust_dir, signing_dir = tmp_path / "trust", tmp_path / "signing"
    trust_dir.mkdir()
    signing_dir.mkdir()
    trust_file = trust_dir / f"{space}.json"
    trust_file.write_text(json.dumps(configuration))
    (signing_dir / "fixture.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(trust, "TRUST_DIRECTORY", trust_dir)
    monkeypatch.setattr(trust, "SIGNING_DIRECTORY", signing_dir)
    monkeypatch.setattr(trust, "protected_read", lambda path, **kwargs: path.read_bytes())

    def verify(token):
        if not token.startswith("fixture:"):
            raise firebase_auth.FirebaseAuthError("fixture refusal")
        return {"sub": token.removeprefix("fixture:"), "exp": time.time() + 3600}

    monkeypatch.setattr(firebase_auth, "verify_firebase_id_token", verify)

    def select(uid, mailbox=None):
        if db._engine is not None:
            db._engine.dispose()
        db._engine, db._session_factory = None, None
        path = tmp_path / "profiles" / uid
        path.mkdir(parents=True, exist_ok=True)
        address = mailbox or f"{uid}@example.test"
        (path / ".env").write_text(
            f"OWNER_ID={uid}\nEMAIL_ADDRESS={address}\nMEMORY_KEY={company}\n"
        )
        monkeypatch.setattr(profiles, "_active_profile", uid)
        monkeypatch.setattr(profiles, "_active_profile_dir", str(path))
        monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(path))
        monkeypatch.setenv("ZYLCH_DB_PATH", str(path / "zylch.db"))
        monkeypatch.setenv("OWNER_ID", uid)
        monkeypatch.setenv("EMAIL_ADDRESS", address)
        monkeypatch.setenv("MEMORY_KEY", company)
        db.Base.metadata.create_all(db.get_engine(), tables=db.profile_tables())
        set_session(uid, address, f"fixture:{uid}", int(time.time() * 1000) + 3600000)
        return path

    def sign(intent):
        with monkeypatch.context() as patch:
            patch.setattr(approval.os, "geteuid", lambda: 0)
            return approval.sign(intent)

    select("alice")
    yield SimpleNamespace(
        select=select,
        sign=sign,
        memory=memory,
        space=space,
        trust=configuration,
        trust_file=trust_file,
        key=key,
        company=company,
    )
    clear_session()
    db.dispose_engine()
