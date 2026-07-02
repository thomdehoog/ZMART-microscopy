"""Connection layer: the TCP client and session lifecycle."""

from .client import DEFAULT_HOST, DEFAULT_PORT, MesospimClient, MesospimError
from .session import close, connect

__all__ = [
    "MesospimClient",
    "MesospimError",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "connect",
    "close",
]
