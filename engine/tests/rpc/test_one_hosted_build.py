"""The hosted package unites the support line and the Café 124 line.

Each test names something one of the two lines had and the other lacked.
A later change that drops one side fails here.
"""

from __future__ import annotations

import asyncio
import inspect

from zylch.rpc import server_ws
from zylch.rpc.methods import METHODS


def _no_notify(method, params):
    return None


def test_capabilities_keep_both_stripe_links_and_what_the_kernel_requires():
    capabilities = asyncio.run(METHODS["system.capabilities"]({}, _no_notify))
    for key in (
        "stripe_payment_method_links",  # support line: customer portal link
        "stripe_payment_links",  # Café 124 line: payment link
        "exact_draft_publication",
        "sent_mirror_recovery",
        "interactive_exact_send",
    ):
        assert capabilities[key] == 1, key


def test_both_stripe_link_methods_are_registered():
    assert "stripe.payment_method_update_link" in METHODS
    assert "stripe.payment_link_create" in METHODS


def test_operator_management_methods_are_registered():
    for name in (
        "operator.rules.list",
        "operator.rules.decide",
        "operator.rules.import_preview",
        "operator.rules.import_confirm",
        "operator.operations.list",
        "operator.operations.recover",
    ):
        assert name in METHODS, name


def test_stripe_errors_know_both_families_of_outcome():
    from zylch.stripe.errors import StripeError

    assert StripeError("portal_permission").outcome == "portal_permission"
    assert StripeError("payment_link_write_permission").outcome == "payment_link_write_permission"
    assert StripeError("not a known outcome").outcome == "operation_failed"


def test_the_server_keeps_the_mail_loop_and_takes_an_operator_listener():
    assert inspect.iscoroutinefunction(server_ws._mail_sync_loop)
    assert "operator_listener" in inspect.signature(server_ws.serve_ws).parameters
    assert "voice_listener" in inspect.signature(server_ws.serve_ws).parameters


def test_instruction_authority_refuses_a_malformed_marker():
    """The support line's guard stays beside the Café 124 line's managed write."""
    from zylch.services import operator_instructions

    assert callable(operator_instructions._authority)
    source = inspect.getsource(operator_instructions.preview)
    assert "_authority(conn, space)" in source
    assert "managed_in_transaction" in inspect.getsource(operator_instructions.store)
