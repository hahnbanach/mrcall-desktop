"""Plan M2.6: hosted encryption refuses fallbacks and the rekey is safe."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from zylch import runtime
from zylch.storage import database as dbm
from zylch.storage import rekey as rk
from zylch.storage.models import OAuthToken
from zylch.utils import encryption as enc

OLD = Fernet.generate_key().decode()
NEW = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    enc.reset_for_tests()
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    yield
    enc.reset_for_tests()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "zylch.db"))
    monkeypatch.setattr(dbm, "_engine", None)
    monkeypatch.setattr(dbm, "_session_factory", None)
    from zylch.storage.database import Base, get_engine

    Base.metadata.create_all(get_engine(), tables=[OAuthToken.__table__])
    yield
    dbm.get_engine().dispose()


def _row(provider: str, credentials):
    with dbm.get_session() as s:
        s.add(OAuthToken(owner_id="o", provider=provider, email="", credentials=credentials))


def _read(provider: str) -> str:
    with dbm.get_session() as s:
        return s.query(OAuthToken).filter_by(provider=provider).one().credentials


# ─── hosted refusals ─────────────────────────────────────


def test_hosted_without_key_refuses_instead_of_plaintext(monkeypatch):
    monkeypatch.setattr(runtime, "_serving", True)
    with pytest.raises(enc.EncryptionUnavailable):
        enc.encrypt("x")


def test_hosted_ignores_the_profile_env_fallback(monkeypatch):
    monkeypatch.setattr(runtime, "_serving", True)
    import zylch.config as cfg

    monkeypatch.setattr(cfg.settings, "encryption_key", OLD, raising=False)
    with pytest.raises(enc.EncryptionUnavailable):
        enc.is_encryption_enabled()


def test_local_without_key_still_passes_through():
    assert enc.encrypt("x") == "x" and enc.decrypt("x") == "x"


def test_hosted_wrong_key_raises_instead_of_returning_ciphertext(monkeypatch):
    token = Fernet(OLD.encode()).encrypt(b"secret").decode()
    monkeypatch.setenv("ENCRYPTION_KEY", NEW)
    monkeypatch.setattr(runtime, "_serving", True)
    with pytest.raises(enc.DecryptionError):
        enc.decrypt(token)
    # plaintext (never encrypted) is still returned as is, for the rekey to find
    assert enc.decrypt('{"refresh_token": "plain"}') == '{"refresh_token": "plain"}'


def test_start_time_self_check(monkeypatch):
    good = Fernet(OLD.encode()).encrypt(b"s").decode()
    bad = Fernet(NEW.encode()).encrypt(b"s").decode()
    monkeypatch.setenv("ENCRYPTION_KEY", OLD)
    assert enc.assert_encryption_ready([good, "", None, "plain"]) == 1
    with pytest.raises(enc.DecryptionError):
        enc.assert_encryption_ready([good, bad])


# ─── rekey ───────────────────────────────────────────────


def _nested_under(key: str) -> str:
    f = Fernet(key.encode())
    inner = "encrypted:" + f.encrypt(b"api-key-123").decode()
    outer = {"pipedrive": {"api_token": inner, "domain": "x"}, "metadata": {"pipedrive": {"a": 1}}}
    return f.encrypt(json.dumps(outer).encode()).decode()


def test_rekey_rewrites_outer_and_inner_then_verifies(db):
    _row("firebase", Fernet(OLD.encode()).encrypt(b'{"refresh_token": "rt"}').decode())
    _row("pipedrive", _nested_under(OLD))
    report = rk.rekey(OLD, NEW)
    assert report.ok and report.rewritten == 2
    new = Fernet(NEW.encode())
    assert json.loads(new.decrypt(_read("firebase").encode())) == {"refresh_token": "rt"}
    outer = json.loads(new.decrypt(_read("pipedrive").encode()))
    assert new.decrypt(outer["pipedrive"]["api_token"][len("encrypted:") :].encode()) == b"api-key-123"
    assert outer["metadata"] == {"pipedrive": {"a": 1}}
    check = rk.verify(NEW)
    assert check.ok and check.rewritten == 2


def test_rekey_is_idempotent_no_double_encryption(db):
    _row("firebase", Fernet(OLD.encode()).encrypt(b'{"refresh_token": "rt"}').decode())
    rk.rekey(OLD, NEW)
    once = _read("firebase")
    second = rk.rekey(OLD, NEW)
    assert second.ok and second.rewritten == 0 and second.already == 1
    new = Fernet(NEW.encode())
    assert json.loads(new.decrypt(_read("firebase").encode())) == {"refresh_token": "rt"}
    # the ciphertext may differ (Fernet nonces) but never nests
    assert new.decrypt(once.encode()) == b'{"refresh_token": "rt"}'


def test_rekey_encrypts_plaintext_rows(db):
    _row("firebase", '{"refresh_token": "was-plain"}')
    report = rk.rekey(OLD, NEW)
    assert report.ok and report.plaintext == 1
    assert json.loads(Fernet(NEW.encode()).decrypt(_read("firebase").encode())) == {
        "refresh_token": "was-plain"
    }


def test_rekey_legacy_tagged_plaintext_round_trip(db):
    legacy = {
        "google_calendar": {
            "refresh_token": "encrypted:legacy-refresh",
            "expires_in": "encrypted:3600",
        },
        "metadata": {"google_calendar": {"label": "calendar"}},
    }
    _row("google_calendar", json.dumps(legacy))
    report = rk.rekey(OLD, NEW)
    assert report.ok and report.rewritten == 1 and report.plaintext == 1
    assert rk.verify(NEW).ok

    new = Fernet(NEW.encode())
    migrated = _read("google_calendar")
    outer = json.loads(new.decrypt(migrated.encode()))
    for field, expected in {"refresh_token": "legacy-refresh", "expires_in": "3600"}.items():
        assert new.decrypt(outer["google_calendar"][field][10:].encode()).decode() == expected
    assert outer["metadata"] == legacy["metadata"]

    second = rk.rekey(OLD, NEW)
    assert second.ok and second.already == 1
    assert _read("google_calendar") == migrated
    assert rk.rekey(NEW, OLD).ok and rk.verify(OLD).ok
    old = Fernet(OLD.encode())
    restored = json.loads(old.decrypt(_read("google_calendar").encode()))
    assert old.decrypt(restored["google_calendar"]["refresh_token"][10:].encode()) == b"legacy-refresh"


@pytest.mark.parametrize("truncated", [False, True])
def test_rekey_refuses_foreign_or_truncated_inner_ciphertext(db, truncated):
    token = Fernet(Fernet.generate_key()).encrypt(b"unavailable-secret").decode()
    if truncated:
        token = token[:20]
    _row("google_calendar", json.dumps({"google_calendar": {"refresh_token": "encrypted:" + token}}))
    report = rk.rekey(OLD, NEW)
    assert not report.ok
    assert report.failed == ["google_calendar: inner field refresh_token"]
    assert not rk.verify(NEW).ok


def test_rekey_reports_a_row_under_neither_key(db):
    other = Fernet.generate_key().decode()
    _row("google_calendar", Fernet(other.encode()).encrypt(b"{}").decode())
    report = rk.rekey(OLD, NEW)
    assert not report.ok and "google_calendar" in report.failed[0]
    assert not rk.verify(NEW).ok


def test_rekey_reverse_is_the_rollback(db):
    _row("pipedrive", _nested_under(OLD))
    assert rk.rekey(OLD, NEW).ok
    assert rk.rekey(NEW, OLD).ok
    assert rk.verify(OLD).ok
    outer = json.loads(Fernet(OLD.encode()).decrypt(_read("pipedrive").encode()))
    assert outer["pipedrive"]["api_token"].startswith("encrypted:")


def test_rekey_keeps_a_bare_string_outer_unquoted(db):
    _row("legacy", Fernet(OLD.encode()).encrypt(b"not-json-token").decode())
    assert rk.rekey(OLD, NEW).ok
    assert Fernet(NEW.encode()).decrypt(_read("legacy").encode()) == b"not-json-token"


def test_serve_pins_the_unit_key_over_a_profile_env_key(monkeypatch):
    from zylch.cli.main import _pin_hosted_encryption_key

    monkeypatch.setenv("ENCRYPTION_KEY", OLD)  # what load_env() left behind
    _pin_hosted_encryption_key(NEW)
    import os

    assert os.environ["ENCRYPTION_KEY"] == NEW
    monkeypatch.setenv("ENCRYPTION_KEY", OLD)
    _pin_hosted_encryption_key(None)
    assert "ENCRYPTION_KEY" not in os.environ
