"""Trusted, inactive composition of a pinned procedure and scoped capabilities.

This is not a loader or an identity verifier. Startup must supply already trusted
dependencies, and every email selection requires its own explicit authorization.
Nothing here changes ordinary chat routing, joins company memory or fetches tokens.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

from zylch.assistant.installation import InstallationSpec
from zylch.assistant.procedure import ProcedureArtifact
from zylch.rpc.capability_ws import BoundedReads, CapabilityEndpoint
from zylch.services.capability_contract import OPERATIONS, CapabilityBinding
from zylch.services.procedure_email import EmailSelection, PilotEmailRoute
from zylch.services.scoped_capabilities import ScopedCapabilities

logger = logging.getLogger(__name__)
_LIVE_OBLIGATIONS = (
    "startup_wiring",
    "service_identity_and_renewal",
    "provider_connectivity",
    "model_billing",
    "per_invocation_authorization",
    "live_pilot_rehearsal",
)


@dataclass(frozen=True)
class InstallationReadiness:
    """Offline construction checks never imply operational readiness."""

    code: str
    live_obligations: tuple[str, ...] = _LIVE_OBLIGATIONS

    @property
    def local_ready(self) -> bool:
        return self.code == "ready_for_local_construction"

    def summary(self) -> dict:
        return {
            "code": self.code,
            "local_ready": self.local_ready,
            "live_ready": False,
            "live_obligations": list(self.live_obligations),
        }


class PreparedEmail:
    """One selected source, owned by its caller until close/finalization.

    The route may only be handed to the existing restricted ChatService path.
    Closing this handle retires that route permanently, not the installation's
    executor or endpoint. Callers must close even on cancellation and exceptions.
    """

    def __init__(self, installation: "PilotProcedureInstallation", route: PilotEmailRoute):
        self.route = route
        self._installation = installation
        self._closed = False

    def close(self) -> None:
        self._installation._release(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class PilotProcedureInstallation:
    """One bounded service/endpoint and email executor, no global selected route.

    Reference equality identifies the supplied trusted dependencies; matching a
    name alone never obtains authority. Profile scope is checked both before and
    after reads, including remote reads that were pending when close was called.
    """

    @staticmethod
    def preflight(
        spec: InstallationSpec,
        artifact: ProcedureArtifact,
        binding: CapabilityBinding,
        *,
        connection_ref: str,
        authority_ref: str,
        read_customers: Callable,
        session_factory: Callable,
        profile_scope: Callable,
        verify_token: Callable | None = None,
    ) -> InstallationReadiness:
        """Inspect local dependencies only; never invoke IO/token/model suppliers."""
        code = "ready_for_local_construction"
        if not isinstance(spec, InstallationSpec) or not isinstance(artifact, ProcedureArtifact):
            code = "invalid_artifact_or_spec"
        elif not isinstance(binding, CapabilityBinding):
            code = "invalid_binding"
        elif spec.business_id != binding.business_id:
            code = "business_mismatch"
        elif (
            spec.procedure_revision != artifact.revision
            or binding.procedure_revision != artifact.revision
        ):
            code = "procedure_mismatch"
        elif connection_ref != spec.connection_ref or authority_ref != spec.authority_ref:
            code = "reference_mismatch"
        elif not artifact.operations or not set(artifact.operations).issubset(OPERATIONS):
            code = "unsupported_operation"
        elif not all(callable(f) for f in (read_customers, session_factory, profile_scope)) or (
            verify_token is not None and not callable(verify_token)
        ):
            code = "invalid_dependency"
        else:
            try:
                if profile_scope() != (binding.profile_uid, binding.company_key):
                    code = "scope_mismatch"
            except Exception:  # noqa: BLE001 -- callbacks must not leak secret diagnostics
                code = "scope_unavailable"
        logger.debug("[procedure installation] preflight -> %s", code)
        return InstallationReadiness(code)

    def __init__(
        self,
        spec: InstallationSpec,
        artifact: ProcedureArtifact,
        binding: CapabilityBinding,
        *,
        connection_ref: str,
        authority_ref: str,
        read_customers: Callable,
        session_factory: Callable,
        profile_scope: Callable,
        verify_token: Callable | None = None,
    ):
        readiness = self.preflight(
            spec,
            artifact,
            binding,
            connection_ref=connection_ref,
            authority_ref=authority_ref,
            read_customers=read_customers,
            session_factory=session_factory,
            profile_scope=profile_scope,
            verify_token=verify_token,
        )
        if not readiness.local_ready:
            raise ValueError(readiness.code)
        self.spec, self.artifact, self._binding = spec, artifact, binding
        self._profile_scope = profile_scope
        self._lock = threading.RLock()
        self._closed = False
        self._active: PreparedEmail | None = None
        self._preparing = False
        self.service = ScopedCapabilities(binding, read_customers, session_factory, self._scope)
        # Validation precedes resource allocation. A failed second allocation
        # cannot leave the first pool alive. Constructors perform no paid work.
        self._workers = BoundedReads()
        try:
            self.endpoint = CapabilityEndpoint(self.service, verify_token=verify_token)
        except BaseException:
            self._workers.close()
            raise

    def _scope(self) -> tuple[str, str]:
        # Called from provider threads too. Never hold this lock across provider
        # IO, SDK shutdown, or any callback that can enter the channel host.
        with self._lock:
            if self._closed or self.service.binding != self._binding:
                raise PermissionError("installation retired")
        scope = self._profile_scope()
        with self._lock:
            if self._closed or self.service.binding != self._binding:
                raise PermissionError("installation retired")
        return scope

    def readiness(self) -> InstallationReadiness:
        with self._lock:
            if self._closed:
                return InstallationReadiness("installation_closed")
        try:
            self.service.check_scope()
        except Exception:  # noqa: BLE001 -- callback failures are a finite readiness code
            return InstallationReadiness("scope_unavailable")
        return InstallationReadiness("ready_for_local_construction")

    def prepare_email(self, selection: EmailSelection, storage, owner_id: str) -> PreparedEmail:
        """Freeze an explicitly selected source; no mailbox search or recognition.

        The owner-scoped source digest and granted recipient are validated before
        admission. Missing contact remains the existing clarification-only path;
        it never inherits a prior handle's authorized contact or evidence.
        """
        with self._lock:
            if self._closed:
                raise PermissionError("installation_closed")
            if self._active is not None or self._preparing:
                raise PermissionError("email_preparation_busy")
            self._preparing = True
        route = None
        try:
            # Storage/scope callbacks run outside admission locks. A pending
            # preparation reserves the single slot but close can still revoke it.
            route = PilotEmailRoute(self.artifact, self.service, selection, workers=self._workers)
            route._source(storage, owner_id)
            with self._lock:
                if self._closed:
                    raise PermissionError("installation_closed")
                handle = PreparedEmail(self, route)
                self._active = handle
        except Exception:  # noqa: BLE001 -- source/provider details cannot reach the caller
            if route is not None:
                route.close()
            raise PermissionError("email_selection_denied") from None
        finally:
            with self._lock:
                self._preparing = False
        logger.debug("[procedure installation] prepare_email -> prepared")
        return handle

    def _release(self, handle: PreparedEmail) -> None:
        with self._lock:
            if handle._closed:
                return
            handle._closed = True
            handle.route.close()
            if self._active is handle:
                self._active = None
        logger.debug("[procedure installation] email handle -> closed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active = self._active
        # No callback/resource cleanup under the admission lock. Running threads
        # retain slots until they finish; scope revocation denies their results.
        if active is not None:
            active.close()
        self.endpoint.close()
        self._workers.close()
        logger.debug("[procedure installation] installation -> closed")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
