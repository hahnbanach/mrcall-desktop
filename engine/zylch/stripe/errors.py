"""Constant safe Stripe failures."""


class StripeError(RuntimeError):
    code = -32045

    def __init__(self, outcome: str):
        allowed = {
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
        super().__init__(
            f"{self.outcome}: Stripe operation unavailable; review the connection and try again."
        )
