"""Readiness is offline, redacted and distinct from live identity/connectivity."""

# Imported pytest fixtures are deliberately injected by their argument names.
# ruff: noqa: F811

from dataclasses import replace
from unittest.mock import Mock

import pytest

from tests.services.test_procedure_email import setup as base_setup  # noqa: F401
from tests.services.test_procedure_installation import installed  # noqa: F401
from zylch.services.procedure_installation import PilotProcedureInstallation


def test_preflight_and_construction_never_call_io_suppliers(installed):
    state = installed
    fail = Mock(side_effect=AssertionError("must not invoke supplier"))
    options = dict(state.options, read_customers=fail, session_factory=fail, verify_token=fail)
    readiness = PilotProcedureInstallation.preflight(
        state.spec, state.artifact, state.binding, **options
    )
    assert readiness.local_ready
    assert readiness.summary()["live_ready"] is False
    assert "service_identity_and_renewal" in readiness.live_obligations
    with PilotProcedureInstallation(
        state.spec, state.artifact, state.binding, **options
    ) as prepared:
        assert prepared.readiness().local_ready
    fail.assert_not_called()
    assert state.binding.company_key not in repr(readiness)
    assert state.binding.contacts[0].email not in repr(readiness.summary())


@pytest.mark.parametrize(
    "change,code",
    [
        ("binding", "invalid_binding"),
        ("business", "business_mismatch"),
        ("procedure", "procedure_mismatch"),
        ("binding_revision", "procedure_mismatch"),
        ("connection", "reference_mismatch"),
        ("authority", "reference_mismatch"),
        ("dependency", "invalid_dependency"),
        ("scope", "scope_mismatch"),
        ("scope_error", "scope_unavailable"),
        ("operation", "unsupported_operation"),
    ],
)
def test_invalid_inputs_refuse_before_resource_allocation(installed, monkeypatch, change, code):
    state = installed
    spec, artifact, binding = state.spec, state.artifact, state.binding
    options = state.options.copy()
    if change == "binding":
        binding = None
    elif change == "business":
        spec = replace(spec, business_id="other")
    elif change == "procedure":
        spec = replace(spec, procedure_revision="0" * 64)
    elif change == "binding_revision":
        binding = replace(binding, procedure_revision="0" * 64)
    elif change in ("connection", "authority"):
        options[change + "_ref"] = "other"
    elif change == "dependency":
        options["read_customers"] = None
    elif change == "scope":
        options["profile_scope"] = lambda: ("wrong", "SECRET")
    elif change == "scope_error":
        options["profile_scope"] = Mock(side_effect=RuntimeError("SECRET"))
    else:
        artifact = replace(artifact, operations=("owner.send",))
    from zylch.services import procedure_installation

    allocation = Mock(side_effect=AssertionError("must validate first"))
    monkeypatch.setattr(procedure_installation, "BoundedReads", allocation)
    monkeypatch.setattr(procedure_installation, "CapabilityEndpoint", allocation)
    result = PilotProcedureInstallation.preflight(spec, artifact, binding, **options)
    assert result.code == code and not result.local_ready
    assert "SECRET" not in repr(result.summary())
    with pytest.raises(ValueError, match=code):
        PilotProcedureInstallation(spec, artifact, binding, **options)
    allocation.assert_not_called()


def test_partial_constructor_failure_retires_first_resource(installed, monkeypatch):
    from zylch.services import procedure_installation

    pool = Mock()
    monkeypatch.setattr(procedure_installation, "BoundedReads", Mock(return_value=pool))
    monkeypatch.setattr(
        procedure_installation, "CapabilityEndpoint", Mock(side_effect=RuntimeError)
    )
    with pytest.raises(RuntimeError):
        PilotProcedureInstallation(
            installed.spec, installed.artifact, installed.binding, **installed.options
        )
    pool.close.assert_called_once()


def test_handles_never_allocate_or_close_installation_resources(installed, monkeypatch):
    from tests.services.test_procedure_email import OWNER
    from zylch.services import procedure_email, procedure_installation

    state = installed
    fail = Mock(side_effect=AssertionError("preparation must reuse resources"))
    monkeypatch.setattr(procedure_installation, "BoundedReads", fail)
    monkeypatch.setattr(procedure_installation, "CapabilityEndpoint", fail)
    monkeypatch.setattr(procedure_email, "BoundedReads", fail)
    pool_close = Mock(wraps=state.installation._workers.close)
    endpoint_close = Mock(wraps=state.installation.endpoint.close)
    monkeypatch.setattr(state.installation._workers, "close", pool_close)
    monkeypatch.setattr(state.installation.endpoint, "close", endpoint_close)
    for selection in (state.selection, state.second):
        with state.installation.prepare_email(selection, state.storage, OWNER):
            pass
    fail.assert_not_called()
    pool_close.assert_not_called()
    endpoint_close.assert_not_called()
    state.installation.close()
    state.installation.close()
    pool_close.assert_called_once()
    endpoint_close.assert_called_once()
