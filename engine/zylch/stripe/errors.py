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
            "price_write_permission",
            "payment_link_write_permission",
            "operation_pending",
            "request_conflict",
            "operation_stale",
            "operation_binding_changed",
        }
        self.outcome = outcome if outcome in allowed else "operation_failed"
        messages = {
            "price_write_permission": "Enable Write for Prices and Products on the restricted Stripe key, then retry the same request_id.",
            "payment_link_write_permission": "Enable Write for Payment Links on the restricted Stripe key, then retry the same request_id.",
            "operation_binding_changed": "Connection authority changed during creation; Stripe may already have created an object. Inspect Stripe and retain the same request_id; do not create a replacement automatically.",
            "operation_pending": "Creation outcome is uncertain. Retry with the same request_id and identical inputs; never start a replacement request.",
            "request_conflict": "This request_id belongs to different inputs or connection binding; do not recreate it automatically.",
            "operation_stale": "Pending creation is outside the safe retry window. Inspect Stripe before any new creation.",
        }
        if self.outcome in messages:
            super().__init__(f"{self.outcome}: {messages[self.outcome]}")
            return
        super().__init__(
            f"{self.outcome}: Stripe operation unavailable; review the connection and try again."
        )
