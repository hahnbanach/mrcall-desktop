"""Load HTTP transport only when a listener is requested."""

__all__ = ["create_app", "listener"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    from . import transport

    return getattr(transport, name)
