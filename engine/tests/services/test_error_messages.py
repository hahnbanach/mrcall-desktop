"""Tests for humanize_error — classify failures into decent messages."""

import errno
import imaplib
import socket
import ssl

from zylch.services.error_messages import humanize_error


def test_dns_gaierror():
    r = humanize_error(socket.gaierror(8, "nodename nor servname provided"), "email_sync")
    assert r["kind"] == "dns"
    assert r["severity"] == "error"
    assert r["action"]


def test_imap_auth_failed():
    r = humanize_error(
        imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials"), "email_sync"
    )
    assert r["kind"] == "auth"


def test_imap_generic_error():
    r = humanize_error(imaplib.IMAP4.error("server busy, try later"), "email_sync")
    assert r["kind"] == "imap"


def test_connection_refused_is_network():
    r = humanize_error(ConnectionRefusedError(errno.ECONNREFUSED, "refused"), "email_sync")
    assert r["kind"] == "network"


def test_timeout():
    r = humanize_error(TimeoutError("timed out"), "email_sync")
    assert r["kind"] == "timeout"


def test_tls():
    r = humanize_error(ssl.SSLError("handshake failure"), "email_sync")
    assert r["kind"] == "tls"


def test_no_llm():
    r = humanize_error(RuntimeError("No LLM configured: set ANTHROPIC_API_KEY or sign in"), "tasks")
    assert r["kind"] == "no_llm"
    assert r["severity"] == "error"


def test_insufficient_credits():
    from zylch.llm.proxy_client import MrCallInsufficientCredits

    r = humanize_error(MrCallInsufficientCredits(0, "https://dashboard.mrcall.ai/plan"), "memory")
    assert r["kind"] == "credits"
    assert "dashboard.mrcall.ai" in r["action"]


def test_unknown_fallback():
    r = humanize_error(ValueError("boom"), "tasks")
    assert r["kind"] == "unknown"
    assert r["title"]


def test_whatsapp_failure_is_warning():
    r = humanize_error(socket.gaierror(8, "x"), "whatsapp")
    assert r["severity"] == "warning"


def test_email_failure_is_error():
    r = humanize_error(socket.gaierror(8, "x"), "email_sync")
    assert r["severity"] == "error"


def test_never_raises():
    r = humanize_error(Exception(), None)
    assert "title" in r and "kind" in r and "severity" in r


def test_httpx_connect_error_wrapping_gaierror_classifies_as_dns():
    """The exact account.balance case: httpx.ConnectError wraps a
    socket.gaierror via __cause__. Walking the chain must find it."""
    import httpx

    try:
        raise socket.gaierror(8, "nodename nor servname provided")
    except Exception as inner:
        try:
            raise httpx.ConnectError("connect failed") from inner
        except httpx.ConnectError as e:
            r = humanize_error(e, "llm")
            assert r["kind"] == "dns"
            assert "the server" in r["title"].lower()


def test_dns_for_non_email_stage_uses_generic_server_label():
    r = humanize_error(socket.gaierror(8, "x"), "llm")
    assert r["kind"] == "dns"
    # Email-stage title says "mail server"; other stages say plain "server".
    assert "mail server" not in r["title"].lower()
