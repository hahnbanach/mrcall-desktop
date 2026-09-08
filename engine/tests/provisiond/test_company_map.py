"""M2.10 — provisiond injects the company key from the host's map (brief C18).

A MEMORY_KEY in the request body is refused; a mapped uid gets the host's
key injected with MEMORY_KEY_SOURCE=provision; an unmapped uid is refused
rather than given a default — a host-wide fallback is how two tenants end
up in one memory store, and this host is multi-tenant.
"""

from __future__ import annotations

import json
import os

import pytest

from zylch.provisiond import handler

KEY = "AbCdEfGhIjKlMnOpQrStUv"


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setenv("MRCALL_PROFILES_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: False)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)
    cmap = tmp_path / "company-map.json"
    cmap.write_text(json.dumps({"uid-mapped": KEY}))
    monkeypatch.setenv("PROVISIOND_COMPANY_MAP", str(cmap))
    return tmp_path


def _claims(sub):
    return {"sub": sub, "email": f"{sub}@example.test"}


def _env(tmp_path, uid):
    return (tmp_path / "profiles" / uid / ".env").read_text()


def test_memory_key_in_the_body_is_refused(host):
    with pytest.raises(handler.ProvisionError) as e:
        handler.handle_provision(_claims("uid-mapped"), {"MEMORY_KEY": KEY})
    assert e.value.status_code == 400 and "injected by the host" in e.value.public_message
    with pytest.raises(handler.ProvisionError):
        handler.handle_provision(_claims("uid-mapped"), {"MEMORY_KEY_SOURCE": "mint"})


def test_mapped_uid_gets_the_hosts_key_injected(host):
    status, payload = handler.handle_provision(_claims("uid-mapped"), {"EMAIL_ADDRESS": "a@b.test"})
    assert status == 200
    env = _env(host, "uid-mapped")
    assert f"MEMORY_KEY={KEY}" in env and "MEMORY_KEY_SOURCE=provision" in env
    assert "OWNER_ID=uid-mapped" in env
    assert "/" not in json.dumps(payload)  # no path reaches the client


def test_unmapped_uid_is_refused_never_defaulted(host):
    with pytest.raises(handler.ProvisionError) as e:
        handler.handle_provision(_claims("uid-stranger"), {"EMAIL_ADDRESS": "s@b.test"})
    assert e.value.status_code == 403
    assert not os.path.exists(host / "profiles" / "uid-stranger")


def test_missing_map_file_fails_closed(host, monkeypatch):
    monkeypatch.setenv("PROVISIOND_COMPANY_MAP", str(host / "absent.json"))
    with pytest.raises(handler.ProvisionError) as e:
        handler.handle_provision(_claims("uid-mapped"), {})
    assert e.value.status_code == 403
