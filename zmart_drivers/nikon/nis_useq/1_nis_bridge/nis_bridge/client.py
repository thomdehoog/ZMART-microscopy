"""Socket client for the bridge running inside NIS-Elements.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

from __future__ import annotations

import socket
import threading
from typing import Any

from .protocol import PROTOCOL_VERSION, ProtocolError, decode_reply, encode_request
from .settings import HOST, PORT, REPLY_MARGIN_S, REQUEST_TIMEOUT_S


class NisConnectionError(RuntimeError):
    """The bridge could not be reached, or the connection dropped."""


class NisClient:
    """One connection to the bridge. ``request(op, **args)`` returns the result.

    Errors reported by the bridge are raised as ValueError (bad request) or
    RuntimeError (NIS refused or failed).
    """

    def __init__(self, host: str = HOST, port: int = PORT, timeout: float = REQUEST_TIMEOUT_S):
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
        if self.info.get("protocol") != PROTOCOL_VERSION:
            self.close()
            raise NisConnectionError(
                f"the bridge speaks protocol {self.info.get('protocol')}, this client "
                f"{PROTOCOL_VERSION}. Restart start_bridge.mac so NIS loads the current bridge."
            )

    def request(self, op: str, *, timeout: float | None = None, **args: Any) -> Any:
        """Send one operation and wait for its reply. ``timeout`` overrides the default."""
        if self._sock is None:
            raise NisConnectionError(
                "The connection to NIS-Elements was closed after an earlier error. Check that "
                "start_bridge.mac is running in NIS (restart it if needed), then connect again."
            )
        timeout = timeout or self.timeout
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            try:
                # A little longer than the bridge, so its own explanation arrives first.
                self._sock.settimeout(timeout + REPLY_MARGIN_S)
                self._sock.sendall(encode_request(request_id, op, args, timeout).encode("utf-8"))
                line = self._reader.readline()
            except TimeoutError:
                self.close()
                raise NisConnectionError(
                    f"NIS-Elements did not answer {op!r} within {timeout:g} s. "
                    "Is start_bridge.mac still running?"
                ) from None
            except OSError as exc:
                self.close()
                raise NisConnectionError(f"connection lost during {op!r}: {exc}") from None
        if not line:
            self.close()
            raise NisConnectionError(f"the bridge closed the connection during {op!r}")
        reply_id, result = decode_reply(line)
        if reply_id != request_id:
            self.close()  # the replies are out of step with the requests from here on
            raise ProtocolError(f"reply {reply_id} does not match request {request_id}")
        return result

    @property
    def closed(self) -> bool:
        """True after close(), or after an error that ended the connection."""
        return self._sock is None

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            self._reader.close()
            sock.close()

    def __enter__(self) -> NisClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
