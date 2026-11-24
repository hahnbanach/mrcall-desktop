"""Public, content-free failures from the mailbox transport."""


class MailboxProviderError(Exception):
    """A technical mailbox refusal, with explicit non-dispatch evidence."""

    code = -32030

    def __init__(self, reason: str, *, non_dispatch: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.non_dispatch = non_dispatch
