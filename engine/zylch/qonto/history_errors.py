"""Safe refusals shared by canonical history and retained receipts."""

from zylch.qonto.errors import QontoError


class HistoryAuthorizationError(QontoError):
    pass
