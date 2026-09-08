"""LLM client exceptions — provider-agnostic."""


class LLMError(Exception):
    """Base exception for LLM client errors."""

    pass


class LLMAuthenticationError(LLMError):
    """Invalid or missing API key."""

    pass


class LLMRateLimitError(LLMError):
    """Rate limit exceeded."""

    pass


class LLMConnectionError(LLMError):
    """Could not connect to provider API."""

    pass


class LLMPromptTooLargeError(LLMError):
    """The assembled prompt exceeds the token budget; nothing was sent.

    Raised before dispatch by `zylch.assistant.budget.check_prompt_budget`,
    so a caller can tell a refused turn from an upstream rejection.
    """

    def __init__(self, estimated_tokens: int, budget_tokens: int):
        self.estimated_tokens = estimated_tokens
        self.budget_tokens = budget_tokens
        super().__init__(
            f"prompt estimated at {estimated_tokens:,} tokens exceeds the "
            f"{budget_tokens:,}-token budget; nothing was sent"
        )
