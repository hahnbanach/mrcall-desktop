"""Constant safe Stripe failures."""


class StripeError(RuntimeError):
    code = -32045

    def __init__(self, outcome: str):
        allowed = {
            "portal_permission",
            "portal_unavailable",
            "submission_unknown",
            "idempotency_conflict",
            "invalid_key",
            "invalid_params",
            "auth",
            "permission",
            "rate_limited",
            "network",
            "invalid_response",
            "not_found",
            "not_connected",
            "binding_changed",
            "challenge_invalid",
            "authority_required",
            "credentials_unreadable",
            "identity_required",
            "operation_failed",
            "session_expired",
            "company_unavailable",
            "company_joining",
            "host_identity_unavailable",
            "encryption_unavailable",
            "busy",
        }
        self.outcome = outcome if outcome in allowed else "operation_failed"
        messages = {
            "portal_permission": "Enable Customer portal Write; existing read access is preserved.",
            "portal_unavailable": "Review the Stripe portal configuration for payment-method updates.",
            "submission_unknown": "Portal submission outcome is unknown; reuse the same request_id.",
            "idempotency_conflict": "Portal request identity conflicts; do not replace an uncertain request.",
        }
        if self.outcome in messages:
            super().__init__(f"{self.outcome}: {messages[self.outcome]}")
            return
        super().__init__(
            f"{self.outcome}: Stripe operation unavailable; review the connection and try again."
        )
