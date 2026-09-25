"""Socket client for the bridge running inside NIS-Elements."""

from __future__ import annotations

import socket
import threading
from typing import Any

from .protocol import ProtocolError, decode_reply, encode_request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 54470


class NisConnectionError(RuntimeError):
    """The bridge could not be reached, or the connection dropped."""


class NisClient:
    """One connection to the bridge. ``request(op, **args)`` returns the result.

    Errors reported by the bridge are raised as ValueError (bad request) or
    RuntimeError (NIS refused or failed).
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 30.0):
        self.host, self.port, self.timeout = host, int(port), float(timeout)
        self._lock = threading.Lock()
        self._next_id = 0
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise NisConnectionError(
                f"no bridge at {self.host}:{self.port} ({exc}). Is NIS-Elements running, "
                "and is start_bridge.mac running in it?"
            ) from None
        self._reader = self._sock.makefile("r", encoding="utf-8", newline="\n")
        self.info = self.request("ping")

    def request(self, op: str, *, timeout: float | None = None, **args: Any) -> Any:
        """Send one operation and wait for its reply. ``timeout`` overrides the default."""
        if self._sock is None:
            raise NisConnectionError("the connection is closed")
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            try:
                self._sock.settimeout(timeout or self.timeout)
                self._sock.sendall(encode_request(request_id, op, args).encode("utf-8"))
                line = self._reader.readline()
            except OSError as exc:
                self.close()
                raise NisConnectionError(f"connection lost during {op!r}: {exc}") from None
        if not line:
            self.close()
            raise NisConnectionError(f"the bridge closed the connection during {op!r}")
        reply_id, result = decode_reply(line)
        if reply_id != request_id:
            raise ProtocolError(f"reply {reply_id} does not match request {request_id}")
        return result

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            self._reader.close()
            sock.close()

    def __enter__(self) -> NisClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
