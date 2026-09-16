"""Offline contract parity; no providers, models, grants or credentials required."""

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from tests.assistant.installation_fixture import installation_bytes
from tests.assistant.procedure_fixture import artifact_bytes
from zylch.assistant.installation import InstallationSpec
from zylch.assistant.procedure import ProcedureArtifact


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(raw):
    return InstallationSpec.parse(raw, digest(raw), digest(artifact_bytes()))


def changed(key, value):
    content = json.loads(installation_bytes())
    content[key] = value
    return json.dumps(content).encode()


def denied(raw):
    with pytest.raises(ValueError, match="^invalid installation specification$"):
        load(raw)


def test_canonical_snapshot_and_secret_free_summary():
    raw = installation_bytes()
    spec = load(raw)
    artifact = ProcedureArtifact.parse(artifact_bytes(), digest(artifact_bytes()))
    assert spec.procedure_revision == artifact.revision
    assert spec.summary() == {
        "id": "synthetic-installation",
        "revision": digest(raw),
        "business_id": "synthetic-business",
        "procedure_revision": artifact.revision,
        "connection_ref": "synthetic-connection",
        "authority_ref": "synthetic-authority",
    }
    with pytest.raises(FrozenInstanceError):
        spec.id = "changed"
    spec.summary()["id"] = "changed"
    assert spec.id == "synthetic-installation"


def test_exact_pins_and_revision_drift():
    raw = installation_bytes()
    for expected in ("A" * 64, "a" * 63, None, 1):
        with pytest.raises(ValueError):
            InstallationSpec.parse(raw, expected, digest(artifact_bytes()))
        with pytest.raises(ValueError):
            InstallationSpec.parse(raw, digest(raw), expected)
    with pytest.raises(ValueError):
        InstallationSpec.parse(raw + b"\n", digest(raw), digest(artifact_bytes()))
    with pytest.raises(ValueError):
        InstallationSpec.parse(raw, digest(raw), "0" * 64)
    for revision in ("0" * 64, "A" * 64, [], None):
        denied(changed("procedure_revision", revision))


@pytest.mark.parametrize("version", [True, False, 1.0, 1.5, "1", 2, None, [], {}])
def test_only_lexical_integer_one(version):
    denied(changed("version", version))


@pytest.mark.parametrize("token", [b"1e0", b"1.00", b"+1", b"01", b"NaN", b"Infinity"])
def test_reject_non_integer_lexemes(token):
    denied(installation_bytes().replace(b'"version": 1', b'"version": ' + token))


def test_exact_fields_and_duplicate_escaped_aliases():
    raw = installation_bytes()
    for duplicate in (b'"version": 1, ', b'"\\u0076ersion": 1, '):
        denied(raw.replace(b'"version": 1', duplicate + b'"version": 1'))
    denied(changed("extra", "must-not-be-accepted"))
    content = json.loads(raw)
    for field in content:
        denied(json.dumps({k: v for k, v in content.items() if k != field}).encode())
    # Escaping an otherwise valid key is legal, only aliases/duplicates are not.
    assert load(raw.replace(b'"id"', b'"\\u0069d"')).id == "synthetic-installation"


@pytest.mark.parametrize("field", ["id", "business_id", "connection_ref", "authority_ref"])
def test_references_are_names_not_paths_addresses_or_commands(field):
    for value in (
        "",
        "x" * 129,
        "../secret",
        "https://provider",
        "a@b.test",
        "a b",
        "a\nb",
        "a\tb",
        "\ud800",
        "é",
        "$(command)",
        None,
        [],
        1,
    ):
        denied(changed(field, value))
    for value in ("a", "A-Z_0.9:ref", "x" * 128):
        assert getattr(load(changed(field, value)), field) == value


@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b"{}", b"\xc3\x28", b"\xff", b" " * 4097])
def test_malformed_or_oversized_bytes(raw):
    denied(raw)


def test_size_boundary_trailing_content_and_sanitized_errors():
    raw = installation_bytes()
    assert load(raw + b" " * (4096 - len(raw))).id == "synthetic-installation"
    denied(raw + b" " * (4097 - len(raw)))
    denied(raw + b" {}")
    denied(b"\xef\xbb\xbf" + raw)
    denied(b'{"secret-from-broken-operator-input": bad}')
    denied(b"[" * 1500 + b"]" * 1500)
    with pytest.raises(ValueError):
        InstallationSpec.parse(bytearray(raw), digest(raw), digest(artifact_bytes()))
