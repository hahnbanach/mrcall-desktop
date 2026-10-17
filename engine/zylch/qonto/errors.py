"""Safe error outcomes without provider or credential text."""

MESSAGES = {
    "history_invalid": "The finance conversation binding is missing or invalid. Start a new conversation.",
    "history_unavailable": "This finance conversation is no longer authorized. Start a new conversation after connecting Qonto.",
    "identity_required": "Sign in with this profile's Firebase account.",
    "session_expired": "Refresh the Firebase session before accessing Qonto.",
    "company_unavailable": "Company memory must be available before connecting Qonto.",
    "company_joining": "Finish the company join and explicitly test Qonto again.",
    "binding_changed": "The account, engine or company changed. Test and confirm Qonto again.",
    "not_connected": "Qonto is disconnected or suspended. Test and confirm it again.",
    "generation_changed": "The Qonto operation was cancelled by a connection change.",
    "credentials_required": "Enter the organization login and API key.",
    "login_required": "The Qonto organization API login is required.",
    "invalid_credentials": "The Qonto credential format is invalid or ambiguous.",
    "bootstrap_unavailable": "No Qonto bootstrap credential is available.",
    "bootstrap_override_disabled": "Development bootstrap overrides are disabled on hosted engines.",
    "encryption_unavailable": "The private encryption key is missing, invalid or unsafe.",
    "credentials_unreadable": "Stored Qonto credentials could not be decrypted.",
    "host_identity_unavailable": "The private engine identity is missing, invalid or unsafe.",
    "busy": "Another Qonto state change is in progress. Try again.",
    "challenge_invalid": "Test Qonto again before saving this connection.",
    "accounts_invalid": "Select only accounts returned by the successful Qonto test.",
    "authority_required": "Confirm your authority to connect the displayed company.",
    "confirmation_required": "Confirm deletion of imported Qonto data.",
    "transport_unavailable": "This engine does not yet have a Qonto provider transport.",
    "auth": "Qonto rejected the credential. Test a valid credential again.",
    "network": "Qonto could not be reached. Try again.",
    "tls": "Qonto TLS verification failed.",
    "rate_limited": "Qonto rate limited the request. Try again later.",
    "invalid_response": "Qonto returned an invalid response.",
    "pagination_changed": "Qonto pagination changed during the scan. Coverage remains partial.",
    "sync_limit": "The bounded Qonto scan stopped. Resume the remaining windows manually.",
    "operation_failed": "The Qonto operation failed.",
}


class QontoError(RuntimeError):
    code = -32040

    def __init__(self, outcome: str):
        self.outcome = outcome if outcome in MESSAGES else "operation_failed"
        super().__init__(f"{self.outcome}: {MESSAGES[self.outcome]}")
