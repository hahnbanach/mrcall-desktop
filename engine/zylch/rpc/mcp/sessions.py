import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    uid: str
    elicitation: bool
    id: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    expires_at: float = field(default_factory=lambda: time.time() + 1800)
    initialized: bool = False
    pending: dict = field(default_factory=dict)
    requests: dict = field(default_factory=dict)

    def close(self) -> None:
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        for task in self.requests.values():
            task.cancel()
        self.pending.clear()


def request_key(value: Any) -> tuple[str, int | str]:
    if type(value) not in (int, str) or isinstance(value, str) and len(value) > 128:
        raise ValueError("invalid_request")
    return type(value).__name__, value


def new_future() -> asyncio.Future:
    return asyncio.get_running_loop().create_future()
