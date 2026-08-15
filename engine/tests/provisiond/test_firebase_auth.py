"""First tests for `zylch.rpc.firebase_auth.verify_firebase_id_token`.

That function has shipped since the cross-machine transport landed
(2026-06) with no direct test coverage of its own — provisiond is the
second caller (after the WebSocket handshake), and this plan's test
deliverable is where it finally gets exercised: signature/claims
acceptance, expiry, wrong audience, wrong issuer, missing `sub`. All
against a LOCALLY generated RSA keypair via the `fake_google_certs` +
`rsa_keypair` fixtures in conftest.py — no network, no real Google cert
endpoint touched.
"""

from __future__ import annotations

import pytest

from zylch.rpc.firebase_auth import FirebaseAuthError, verify_firebase_id_token

from .conftest import PROJECT_ID, make_id_token


def test_accepts_valid_token(fake_google_certs, rsa_keypair):
    private_key, _ = rsa_keypair
    token = make_id_token(private_key, sub="uid-abc")
    claims = verify_firebase_id_token(token, project_id=PROJECT_ID)
    assert claims["sub"] == "uid-abc"
    assert claims["aud"] == PROJECT_ID


def test_rejects_expired_token(fake_google_certs, rsa_keypair):
    private_key, _ = rsa_keypair
    token = make_id_token(private_key, exp_delta=-60, iat_delta=-120)
    with pytest.raises(FirebaseAuthError):
        verify_firebase_id_token(token, project_id=PROJECT_ID)


def test_rejects_wrong_audience(fake_google_certs, rsa_keypair):
    private_key, _ = rsa_keypair
    token = make_id_token(private_key, audience="some-other-project")
    with pytest.raises(FirebaseAuthError):
        verify_firebase_id_token(token, project_id=PROJECT_ID)


def test_rejects_wrong_issuer(fake_google_certs, rsa_keypair):
    private_key, _ = rsa_keypair
    token = make_id_token(private_key, issuer="https://evil.example.com/not-google")
    with pytest.raises(FirebaseAuthError):
        verify_firebase_id_token(token, project_id=PROJECT_ID)


def test_rejects_missing_sub(fake_google_certs, rsa_keypair):
    private_key, _ = rsa_keypair
    token = make_id_token(private_key, include_sub=False)
    with pytest.raises(FirebaseAuthError):
        verify_firebase_id_token(token, project_id=PROJECT_ID)


def test_rejects_unknown_kid(fake_google_certs, rsa_keypair):
    # A kid our fake cert set never served — mirrors a rotated/unknown
    # Google signing key, after the one forced refresh gives up.
    private_key, _ = rsa_keypair
    token = make_id_token(private_key, kid="some-other-kid")
    with pytest.raises(FirebaseAuthError):
        verify_firebase_id_token(token, project_id=PROJECT_ID)


def test_rejects_garbage_token(fake_google_certs):
    with pytest.raises(FirebaseAuthError):
        verify_firebase_id_token("not-a-real-jwt", project_id=PROJECT_ID)


def test_rejects_empty_token(fake_google_certs):
    with pytest.raises(FirebaseAuthError):
        verify_firebase_id_token("", project_id=PROJECT_ID)
