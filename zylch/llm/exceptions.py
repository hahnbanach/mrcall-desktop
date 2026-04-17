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
